"""Finding panoramas around a stop, to photograph it from different distances.

The metadata endpoint only returns the single panorama nearest to a point, so
we query points on rings around the stop and keep the distinct panoramas found.
This needs no knowledge of the road layout, and metadata requests are free.
"""

import logging
from collections.abc import Sequence

from .streetview import ImageSource
from .errors import NoImageryError, ServerError
from .geo import bearing_deg, distance_m, offset
from .models import Shot, Stop, View

logger = logging.getLogger(__name__)

MAX_DISTANCE_M = 60.0
RING_RADII_M = (20.0, 40.0)
POINTS_PER_RING = 8
RING_SEARCH_RADIUS_M = 15.0


def _sample_points(stop: Stop) -> list[tuple[float, float, float]]:
    """(lat, lon, search radius) for the stop itself plus each point on the rings."""
    points = [(stop.lat, stop.lon, MAX_DISTANCE_M)]
    for ring_radius in RING_RADII_M:
        for i in range(POINTS_PER_RING):
            lat, lon = offset(stop.lat, stop.lon, 360 * i / POINTS_PER_RING, ring_radius)
            points.append((lat, lon, RING_SEARCH_RADIUS_M))
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


def choose_shots(candidates: Sequence[Shot], views: Sequence[View]) -> list[Shot]:
    """Pick one shot per view, closest to the view's distance, preferring unused panoramas."""
    used: set[str] = set()
    chosen = []
    for view in views:
        pool = [c for c in candidates if c.pano.pano_id not in used] or candidates
        best = min(pool, key=lambda c: abs(c.distance_m - view.distance_m))
        used.add(best.pano.pano_id)
        chosen.append(best)
    return chosen
