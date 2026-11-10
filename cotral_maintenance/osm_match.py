"""The OpenStreetMap object that is a given Cotral stop, when there is one.

OSM is the most accurate position source we have, when an object can be tied to the
stop. Measured on the 504 verified stops (experiments/explore, 2026-11-09), error to the
verified position:

  - by ref: an object whose `ref` lists the stop id (anywhere, no distance limit):
    135 stops, median 6.9 m (their GTFS: 17.0 m)
  - nearest: the closest stop-like object within NEAREST_M of the GTFS position, provided
    it is closer to this stop than to any other Cotral stop: 132 stops, median 9.9 m
    (their GTFS: 16.7 m)
  - by name alone: 12 more stops, median 33 m, worse than GTFS: not used.

Together: OSM for 267 of 504 stops; with GTFS for the rest, median 17.5 m against 23.7 m.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .osm_store import OsmStore, StopFeature, bbox_around
from .roadpath import LocalFrame
from .stops import Stop

NEAREST_M = 100.0
OTHERS_REACH_M = 400.0  # how far to look for a Cotral stop that an object could belong to instead


@dataclass(frozen=True)
class OsmMatch:
    feature: StopFeature
    how: str  # "ref" or "nearest"
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
