"""Finding panoramas around a stop and planning the shots that photograph it.

The metadata endpoint only returns the single panorama nearest to a point, so
we query points on rings around the stop and keep the distinct panoramas found.
This needs no knowledge of the road layout, and metadata requests are free.

Shot plan, per stop:
  converge_a, converge_b: two panoramas CONVERGE_DISTANCE_M from the stop, on
      opposite sides of it, both aimed at the stop and tilted up to include lamps.
  sky_a, sky_b: from the panorama nearest the stop, looking up and outwards
      towards each converging panorama, to find street lamps around the stop.
"""

import logging
from collections.abc import Sequence
from itertools import combinations

from .streetview import ImageSource
from .errors import NoImageryError, ServerError
from .geo import angle_between, bearing_deg, distance_m, offset
from .models import Shot, Stop, View

logger = logging.getLogger(__name__)

MAX_DISTANCE_M = 60.0
# (ring radius, metadata search radius, points on the ring)
RINGS = ((7.5, 5.0, 12), (20.0, 15.0, 8), (40.0, 15.0, 8))

CONVERGE_DISTANCE_M = (5.0, 10.0)
# Tried in order when no opposite pair is found at CONVERGE_DISTANCE_M. Further away,
# the stop is too small to judge, so a closer pair that is not quite opposite wins.
FALLBACK_DISTANCES_M = ((3.0, 20.0), (0.0, 30.0))
# Bearings from the stop at least this far apart count as opposite sides.
MIN_SEPARATION_DEG = 120.0

VIEWS = (
    View("converge_a", pitch=10.0, fov=100.0),
    View("converge_b", pitch=10.0, fov=100.0),
    View("sky_a", pitch=25.0, fov=100.0),
    View("sky_b", pitch=25.0, fov=100.0),
)


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
    panos = {}
    for lat, lon, radius in _sample_points(stop):
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


def choose_converging(candidates: Sequence[Shot]) -> list[Shot]:
    """Two shots from opposite sides of the stop, as close to CONVERGE_DISTANCE_M as possible.

    Returns the most opposite pair found if none is MIN_SEPARATION_DEG apart, and
    a single shot if there is only one panorama.
    """
    best_pair: tuple[Shot, Shot] | None = None
    for low, high in (CONVERGE_DISTANCE_M, *FALLBACK_DISTANCES_M):
        pool = [c for c in candidates if low <= c.distance_m <= high]
        pairs = list(combinations(pool, 2))
        if not pairs:
            continue
        pair = max(pairs, key=lambda p: angle_between(p[0].heading, p[1].heading))
        if angle_between(pair[0].heading, pair[1].heading) >= MIN_SEPARATION_DEG:
            return list(pair)
        best_pair = best_pair or pair
    if best_pair:
        return list(best_pair)
    return list(candidates[:1])


def plan_shots(candidates: Sequence[Shot]) -> dict[str, Shot]:
    """Panorama and heading for each view in VIEWS (fewer if there are too few panoramas)."""
    if not candidates:
        return {}
    converging = choose_converging(candidates)
    nearest = candidates[0]
    # Looking out from the stop towards each converging panorama, i.e. away from the stop.
    outward = [(shot.heading + 180) % 360 for shot in converging]
    if len(outward) == 1:
        outward.append((outward[0] + 180) % 360)

    plan = dict(zip(("converge_a", "converge_b"), converging))
    for name, heading in zip(("sky_a", "sky_b"), outward):
        plan[name] = Shot(pano=nearest.pano, distance_m=nearest.distance_m, heading=heading)
    return plan
