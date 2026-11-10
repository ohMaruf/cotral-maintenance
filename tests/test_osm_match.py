from cotral_maintenance.osm_match import NEAREST_M, match_osm
from cotral_maintenance.osm_store import StopFeature
from cotral_maintenance.roadpath import LocalFrame
from cotral_maintenance.stops import Stop

FRAME = LocalFrame(41.9, 12.5)


def at(x: float, y: float) -> tuple[float, float]:
    return FRAME.to_latlon(x, y)


def feature(osm_id: str, x: float, y: float, ref: str = "", kind: str = "bus_stop") -> StopFeature:
    return StopFeature(osm_id, kind, *at(x, y), ref=ref, name="", operator="", tags={})


class FakeStore:
    def __init__(self, features):
        self.features = features

    def stops_with_ref(self, ref):
        return [f for f in self.features if ref.lower() in f.ref.lower().split(";")]

    def stops_in(self, bbox):
        south, west, north, east = bbox
        return [f for f in self.features if south <= f.lat <= north and west <= f.lon <= east]


STOP = Stop("f1", "Here", *at(0, 0))


def test_an_object_with_the_stop_id_wins_however_far_it_is():
    store = FakeStore([feature("n1", 5, 0), feature("n2", 230, 10, ref="F2;f1")])
    m = match_osm(STOP, store, [STOP])
    assert m.how == "ref" and m.feature.osm_id == "n2" and 230 < m.from_gtfs_m < 231


def test_else_the_nearest_object_that_belongs_to_no_other_stop():
    other = Stop("f2", "There", *at(20, 0))
    store = FakeStore([feature("n1", 15, 0), feature("n2", -30, 5, kind="shelter")])
    m = match_osm(STOP, store, [STOP, other])
    assert m.how == "nearest" and m.feature.osm_id == "n2"  # n1 is closer to f2


def test_nothing_within_reach_is_no_match():
    store = FakeStore([feature("n1", NEAREST_M + 20, 0)])
    assert match_osm(STOP, store, [STOP]) is None
