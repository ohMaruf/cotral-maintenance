import math

import pytest

from cotral_maintenance.osm_store import OsmStore, Road, StopFeature, bbox_around, bus_road, stop_kind
from cotral_maintenance.roadpath import LocalFrame, RoadGraph, locate, match

FRAME = LocalFrame(41.9, 12.5)
_next_node = iter(range(1, 1_000_000))


def road(way_id, points, oneway=0, nodes=None):
    """A road through local (x, y) points; shared node ids connect roads."""
    nodes = nodes or [next(_next_node) for _ in points]
    return Road(way_id=way_id, highway="residential", name="", oneway=oneway, node_ids=tuple(nodes),
                coords=tuple(FRAME.to_latlon(x, y) for x, y in points))


def graph(*roads):
    return RoadGraph(list(roads), FRAME)


def near(points, target, tolerance=1.0):
    return any(math.dist(p, target) <= tolerance for p in points)


def test_frame_round_trip():
    lat, lon = FRAME.to_latlon(123.0, -456.0)
    x, y = FRAME.to_xy(lat, lon)
    assert x == pytest.approx(123.0, abs=1e-6) and y == pytest.approx(-456.0, abs=1e-6)


def test_prefers_the_road_the_shape_runs_along_over_a_parallel_one():
    main = road(1, [(0, 0), (500, 0)])
    parallel = road(2, [(0, 40), (500, 40)])
    path = match([(0, 8), (250, 8), (500, 8)], graph(main, parallel))
    assert len(path.pieces) == 1
    assert all(abs(y) < 1e-6 for _, y in path.pieces[0])
    assert path.length == pytest.approx(500, abs=1)


def test_follows_the_corner_a_coarse_chord_cuts():
    a, corner, b = next(_next_node), next(_next_node), next(_next_node)
    leg1 = road(1, [(0, 0), (300, 0)], nodes=[a, corner])
    leg2 = road(2, [(300, 0), (300, 300)], nodes=[corner, b])
    # The shape has a point near each end and one on the chord, 60 m inside the corner... too far;
    # only the ends and points near the legs are on roads, like a sparse GTFS shape.
    path = match([(0, 5), (150, 10), (290, 150), (305, 300)], graph(leg1, leg2))
    assert path.length == pytest.approx(600, abs=5)
    assert near(path.pieces[0], (300, 0))


def test_takes_the_loop_when_a_shape_point_is_in_it():
    j1, j2, l1, l2 = (next(_next_node) for _ in range(4))
    west = road(1, [(0, 0), (200, 0)], nodes=[next(_next_node), j1])
    middle = road(2, [(200, 0), (300, 0)], nodes=[j1, j2])
    east = road(3, [(300, 0), (500, 0)], nodes=[j2, next(_next_node)])
    loop = road(4, [(200, 0), (200, 120), (300, 120), (300, 0)], nodes=[j1, l1, l2, j2])
    path = match([(0, 2), (250, 118), (500, 2)], graph(west, middle, east, loop))
    assert len(path.pieces) == 1
    assert near(path.pieces[0], (200, 120)) and near(path.pieces[0], (300, 120))
    assert path.length == pytest.approx(200 + 340 + 200, abs=5)


def test_respects_one_way_for_a_bus():
    # Dual carriageway: eastbound on y = 0, westbound on y = 20. The shape travels east, nearer to y = 20.
    eastbound = road(1, [(0, 0), (500, 0)], oneway=1)
    westbound = road(2, [(500, 20), (0, 20)], oneway=1)
    path = match([(0, 14), (100, 14), (200, 14), (300, 14), (400, 14), (500, 14)], graph(eastbound, westbound))
    assert all(abs(y) < 1e-6 for _, y in path.pieces[0])


def test_splits_into_pieces_when_no_road_connects():
    a = road(1, [(0, 0), (200, 0)])
    b = road(2, [(2000, 0), (2200, 0)])  # far apart, not connected
    path = match([(0, 2), (200, 2), (2000, 2), (2200, 2)], graph(a, b))
    assert len(path.pieces) == 2


def test_counts_points_without_a_road_nearby():
    path = match([(0, 2), (100, 500), (200, 2)], graph(road(1, [(0, 0), (200, 0)])))
    assert path.unmatched == 1 and path.matched == 2


def test_locate_gives_along_and_signed_offset_right_of_travel():
    line = [(0, 0), (100, 0), (100, 100)]  # east, then north
    along, offset, distance = locate(line, (50, -10))  # south of an eastbound leg: right
    assert along == pytest.approx(50) and offset == pytest.approx(10) and distance == pytest.approx(10)
    along, offset, _ = locate(line, (90, 50))  # west of a northbound leg: left
    assert along == pytest.approx(150) and offset == pytest.approx(-10)


@pytest.mark.parametrize(("tags", "expected"), [
    ({"highway": "residential"}, ("residential", 0)),
    ({"highway": "primary", "oneway": "yes"}, ("primary", 1)),
    ({"highway": "primary", "oneway": "-1"}, ("primary", -1)),
    ({"highway": "primary", "oneway": "yes", "oneway:bus": "no"}, ("primary", 0)),
    ({"highway": "secondary", "junction": "roundabout"}, ("secondary", 1)),
    ({"highway": "service", "access": "no", "bus": "yes"}, ("service", 0)),
    ({"highway": "service", "access": "private"}, None),
    ({"highway": "footway"}, None),
    ({"highway": "busway"}, ("busway", 0)),
])
def test_bus_road(tags, expected):
    assert bus_road(tags) == expected


@pytest.mark.parametrize(("tags", "expected"), [
    ({"highway": "bus_stop", "public_transport": "platform"}, "bus_stop"),
    ({"public_transport": "platform"}, "platform"),
    ({"public_transport": "stop_position", "bus": "yes"}, "stop_position"),
    ({"amenity": "shelter", "shelter_type": "public_transport"}, "shelter"),
    ({"amenity": "shelter", "shelter_type": "picnic_shelter"}, None),
    ({"amenity": "bus_station"}, "bus_station"),
    ({"highway": "residential"}, None),
])
def test_stop_kind(tags, expected):
    assert stop_kind(tags) == expected


def test_store_round_trip_and_bbox_queries(tmp_path):
    store = OsmStore(tmp_path / "osm.sqlite3")
    store.create()
    near_road = road(10, [(0, 0), (100, 0)], oneway=1)
    far_road = road(11, [(5000, 5000), (5100, 5000)])
    assert store.add_roads([near_road, far_road]) == 2
    lat, lon = FRAME.to_latlon(50, 5)
    store.add_stops([
        StopFeature("n1", "shelter", lat, lon, "", "", "", {"amenity": "shelter", "shelter_type": "public_transport"}),
        StopFeature("w1", "platform", *FRAME.to_latlon(5000, 5000), "f123", "X", "Cotral", {}),
        StopFeature("r1", "platform", *FRAME.to_latlon(5000, 5000), "", "", "", {}),
    ])
    store.set_meta({"built_at": "now"})

    box = bbox_around(FRAME.lat0, FRAME.lon0, 300)
    roads = store.roads_in(box)
    assert [r.way_id for r in roads] == [10]
    assert roads[0].oneway == 1 and roads[0].node_ids == near_road.node_ids
    assert roads[0].coords[1] == pytest.approx(near_road.coords[1])
    stops = store.stops_in(box)
    assert [(s.osm_id, s.kind) for s in stops] == [("n1", "shelter")]
    assert stops[0].tags["shelter_type"] == "public_transport"
    assert {s.osm_id for s in store.all_stops()} == {"n1", "w1", "r1"}  # same number, different elements
    assert store.meta() == {"built_at": "now"}


def test_never_turns_round_mid_road_but_uses_a_real_turnaround():
    # A two-way road east, with a one-way loop at x = 300..340 (in at the bottom, out at the top). The shape
    # goes east to x = 300 and comes back west: the bus must use the loop, not reverse on the road.
    j, l1, l2 = next(_next_node), next(_next_node), next(_next_node)
    main = road(1, [(0, 0), (300, 0)], nodes=[next(_next_node), j])
    loop = road(2, [(300, 0), (340, -20), (340, 20), (300, 0)], oneway=1, nodes=[j, l1, l2, j])
    path = match([(0, 2), (150, 2), (290, 2), (150, -2), (0, -2)], graph(main, loop))
    assert len(path.pieces) == 1
    assert near(path.pieces[0], (340, -20)) and near(path.pieces[0], (340, 20))
    loop_m = 2 * math.hypot(40, 20) + 40
    assert path.length == pytest.approx(300 + loop_m + 300, abs=10)


def test_turns_round_at_a_dead_end():
    dead_end = road(1, [(0, 0), (200, 0)])
    path = match([(0, 2), (100, 2), (195, 2), (100, -2), (0, -2)], graph(dead_end))
    assert len(path.pieces) == 1
    assert path.length == pytest.approx(400, abs=5)


def test_a_mid_road_reversal_is_not_a_route():
    through = road(1, [(0, 0), (400, 0)], nodes=[next(_next_node), next(_next_node)])
    beyond = road(2, [(400, 0), (900, 0)], nodes=[through.node_ids[1], next(_next_node)])
    g = graph(through, beyond)
    east = next(c for c in g.candidates((100, 0)) if c.direction == 1 and c.segment == 0)
    west_behind = next(c for c in g.candidates((50, 0)) if c.direction == -1 and c.segment == 0)
    assert g.routes_from(east, [west_behind], max_length=500)[0] is None
