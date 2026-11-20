import math
from collections.abc import Iterable
from dataclasses import dataclass

from .osm_store import OsmStore, StopFeature, bbox_around
from .roadpath import LocalFrame
from .stops import Stop

NEAREST_M = 100.0
OTHERS_REACH_M = 400.0


@dataclass(frozen=True)
class OsmMatch:
    feature: StopFeature
    how: str
    from_gtfs_m: float


def match_osm(stop: Stop, store: OsmStore, cotral_stops: Iterable[Stop]) -> OsmMatch | None:
    frame = LocalFrame(stop.lat, stop.lon)

    def from_gtfs(f: StopFeature) -> float:
        return math.hypot(*frame.to_xy(f.lat, f.lon))

    by_ref = store.stops_with_ref(stop.stop_id)
    if by_ref:
        best = min(by_ref, key=from_gtfs)
        return OsmMatch(best, "ref", from_gtfs(best))
    near = sorted((f for f in store.stops_in(bbox_around(stop.lat, stop.lon, NEAREST_M))
                   if from_gtfs(f) <= NEAREST_M), key=from_gtfs)
    if not near:
        return None
    south, west, north, east = bbox_around(stop.lat, stop.lon, OTHERS_REACH_M)
    others = [s for s in cotral_stops
              if s.stop_id != stop.stop_id and south <= s.lat <= north and west <= s.lon <= east]
    for f in near:
        mine = from_gtfs(f)
        if all(math.hypot(*LocalFrame(o.lat, o.lon).to_xy(f.lat, f.lon)) > mine for o in others):
            return OsmMatch(f, "nearest", mine)
    return None
