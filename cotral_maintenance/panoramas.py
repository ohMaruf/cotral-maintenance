"""Finding panoramas around a stop and planning the shots that photograph it.

The metadata endpoint only returns the single panorama nearest to a point, so
we query points on rings around the stop and keep the distinct panoramas found.
This needs no knowledge of the road layout, and metadata requests are free.

Shot plan, per stop: a sidewalk sweep. Stop coordinates can be tens of metres off
along the road, and Static API images are capped at 640x640, so rather than aim a
few images at the coordinates, we photograph as much of the stop's sidewalk as
possible, each image from close by:
  1. The road is the line through the most panoramas around the stop (panoramas
     lie along roads; at a junction, along several).
  2. The stop's sidewalk is the side of that line its coordinates are on; if they
     are on the line, the side away from the opposite-direction stop.
  3. sweep_1..sweep_4: panoramas at SWEEP_OFFSETS_M along the road from the stop,
     each looking straight across at that one sidewalk.
All images come from the drive of the panorama nearest the stop, so they show one
moment and the stop has a single imagery date.
"""

import logging
import math
from dataclasses import dataclass
from collections.abc import Sequence
from itertools import combinations

from .streetview import ImageSource
from .errors import NoImageryError, ServerError
from .geo import bearing_deg, distance_m, offset
from .models import Shot, Stop, View

logger = logging.getLogger(__name__)

MAX_DISTANCE_M = 60.0
# (ring radius, metadata search radius, points on the ring)
RINGS = ((7.5, 5.0, 12), (20.0, 15.0, 8))

# Panoramas within this distance are used to fit the road's line.
ROAD_FIT_RADIUS_M = 30.0
# A panorama this close to a line counts as lying on it; lines are fitted through
# pairs at least MIN_ROAD_FIT_SPAN_M apart, so their direction is well defined.
ROAD_INLIER_M = 2.0
MIN_ROAD_FIT_SPAN_M = 5.0
# The stop must be at least this far off the road line for its coordinates to
# decide its side; otherwise its opposite-direction stop must be this much further
# to one side than the stop.
MIN_SIDE_OFFSET_M = 2.0
MIN_PAIR_SIDE_GAP_M = 1.0
# Where to look up sweep panoramas, along the road from the stop, and how far
# from that point a panorama may be. With a 110 degree view, a sidewalk 6 m away
# is covered for about 8.5 m either side of each panorama: 16 m apart leaves no gaps.
# Only one sidewalk is swept: the other may have the opposite direction's stop.
SWEEP_OFFSETS_M = (-24.0, -8.0, 8.0, 24.0)
SWEEP_SEARCH_RADIUS_M = 6.0

# One billed Static API request per view (the Static API caps images at 640x640).
# 110 degrees is about 6 px per degree: a stop sign 0.4 m wide is about 15 px
# from 9 m away. Pitch 5 keeps the pavement and lamp heads in frame.
VIEWS = tuple(View(f"sweep_{i}", pitch=5.0, fov=110.0) for i in range(1, 5))


def _sample_points(stop: Stop) -> list[tuple[float, float, float]]:
    """(lat, lon, search radius) for the stop itself plus each point on the rings."""
    points = [(stop.lat, stop.lon, MAX_DISTANCE_M)]
    for ring_radius, search_radius, n_points in RINGS:
        for i in range(n_points):
            lat, lon = offset(stop.lat, stop.lon, 360 * i / n_points, ring_radius)
            points.append((lat, lon, search_radius))
    return points


def find_nearby_shots(client: ImageSource, stop: Stop) -> list[Shot]:
    """Distinct Google panoramas within MAX_DISTANCE_M of the stop, nearest first, aimed at it."""
    return _lookup(client, stop, _sample_points(stop))


def _lookup(client: ImageSource, stop: Stop, points: Sequence[tuple[float, float, float]]) -> list[Shot]:
    """Distinct Google panoramas nearest to each (lat, lon, search radius), aimed at the stop."""
    panos = {}
    for lat, lon, radius in points:
        try:
            pano = client.get_metadata(lat, lon, radius)
        except NoImageryError:
            continue
        except ServerError as exc:
            logger.debug("Stop %s: skipping sample point: %s", stop.stop_id, exc)
            continue
        if not pano.is_google:
            logger.debug("Stop %s: skipping user photosphere %s", stop.stop_id, pano.pano_id)
            continue
        panos.setdefault(pano.pano_id, pano)

    shots = [
        Shot(
            pano=pano,
            distance_m=distance_m(pano.lat, pano.lon, stop.lat, stop.lon),
            heading=bearing_deg(pano.lat, pano.lon, stop.lat, stop.lon),
        )
        for pano in panos.values()
    ]
    shots = sorted((s for s in shots if s.distance_m <= MAX_DISTANCE_M), key=lambda s: s.distance_m)
    logger.debug(
        "Stop %s: %d panoramas at %s m",
        stop.stop_id, len(shots), [round(s.distance_m) for s in shots],
    )
    return shots


def _local(stop: Stop, lat: float, lon: float) -> tuple[float, float]:
    """(east, north) metres from the stop."""
    d = distance_m(stop.lat, stop.lon, lat, lon)
    b = math.radians(bearing_deg(stop.lat, stop.lon, lat, lon))
    return d * math.sin(b), d * math.cos(b)


@dataclass(frozen=True)
class Road:
    """A straight road line near a stop, in metres east/north of the stop."""

    bearing: float
    east: float  # a point on the line
    north: float

    def right_of(self, east: float, north: float) -> float:
        """Signed distance of a point from the line, positive to the right of `bearing`."""
        b = math.radians(self.bearing)
        return (east - self.east) * math.cos(b) - (north - self.north) * math.sin(b)


def fit_road(stop: Stop, candidates: Sequence[Shot]) -> Road | None:
    """The straight line through the most nearby panoramas (within ROAD_INLIER_M of it),
    ties going to the line nearest the stop.

    A least-squares fit through all of them would average crossing streets at a
    junction into a direction no street has. None if no two panoramas are far
    enough apart to fit a line through.
    """
    points = [_local(stop, c.pano.lat, c.pano.lon) for c in candidates if c.distance_m <= ROAD_FIT_RADIUS_M]
    best: tuple[tuple[int, float], Road] | None = None
    for (ax, ay), (bx, by) in combinations(points, 2):
        if math.hypot(bx - ax, by - ay) < MIN_ROAD_FIT_SPAN_M:
            continue
        road = Road(math.degrees(math.atan2(bx - ax, by - ay)) % 360, ax, ay)
        inliers = sum(abs(road.right_of(px, py)) <= ROAD_INLIER_M for px, py in points)
        key = (inliers, -abs(road.right_of(0, 0)))
        if best is None or key > best[0]:
            best = key, road
    return best[1] if best else None


def choose_side(stop: Stop, road: Road, pair: Stop | None) -> tuple[int, str]:
    """Which sidewalk the stop is on: +1 right of the road's bearing, -1 left; and why.

    Coordinates are usually wrong along the road, rarely across it, so a stop clearly
    off the road line is on that side. Otherwise its opposite-direction stop decides:
    the two stand on opposite sidewalks, so the stop is on the side away from it.
    """
    right = road.right_of(0, 0)
    if abs(right) >= MIN_SIDE_OFFSET_M:
        return (1 if right > 0 else -1), "coordinates"
    if pair is not None:
        pair_right = road.right_of(*_local(stop, pair.lat, pair.lon))
        if abs(right - pair_right) >= MIN_PAIR_SIDE_GAP_M:
            return (1 if right > pair_right else -1), f"opposite stop {pair.stop_id}"
    return (1 if right >= 0 else -1), "coordinates, uncertain"


def plan_shots(client: ImageSource, stop: Stop, pair: Stop | None = None) -> dict[str, Shot]:
    """Panorama and heading for each view in VIEWS (fewer if there are too few panoramas).

    `pair` is the stop for the opposite direction, if any (stops.find_pairs); it
    decides the stop's side of the road when the coordinates are on the road line.
    """
    candidates = find_nearby_shots(client, stop)
    if not candidates:
        return {}
    road = fit_road(stop, candidates)
    if road is None:
        # A single panorama: nothing to sweep along, so look at the stop.
        return {VIEWS[0].name: candidates[0]}
    side, basis = choose_side(stop, road, pair)
    across = (road.bearing + 90 * side) % 360
    # The stop's position projected onto the road line.
    right = road.right_of(0, 0)
    foot = offset(stop.lat, stop.lon, (road.bearing + (90 if right < 0 else -90)) % 360, abs(right))
    date = candidates[0].pano.date

    shots: list[Shot] = []
    used: set[str] = set()
    for along_m in SWEEP_OFFSETS_M:
        point = offset(*foot, road.bearing if along_m >= 0 else (road.bearing + 180) % 360, abs(along_m))
        found = _lookup(client, stop, [(*point, SWEEP_SEARCH_RADIUS_M)])
        if not found or found[0].pano.pano_id in used or found[0].pano.date != date:
            continue
        used.add(found[0].pano.pano_id)
        shots.append(Shot(pano=found[0].pano, distance_m=found[0].distance_m, heading=across))
    logger.info(
        "Stop %s: road %.0f°, sweeping the %s sidewalk (side from %s), %d shots",
        stop.stop_id, road.bearing, "right" if side > 0 else "left", basis, len(shots),
    )
    return {view.name: shot for view, shot in zip(VIEWS, shots)}
