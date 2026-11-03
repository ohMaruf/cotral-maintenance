import pytest

from cotral_maintenance.errors import StopNotFoundError
from cotral_maintenance.models import Stop
from cotral_maintenance.stops import find_pairs, is_cotral_stop, load_stops, sample_order, select_stops

CSV = '''stop_id,stop_name,stop_lat,stop_lon,location_type
"1019","GAETA Lungomare","41.2152937","13.57178992","0"
"bad","Broken row","not-a-number","13.0","0"
"1021","ARTENA # 1021","41.74654018","12.91509521","0"
"f1168","BAGNOREGIO | Ist. "F.lli AGosti" # f1168","42.6","12.1","0"
'''


@pytest.fixture
def stops(tmp_path):
    path = tmp_path / "stops.txt"
    path.write_text(CSV, encoding="utf-8")
    return load_stops(path)


def test_load_skips_malformed_rows(stops):
    assert [s.stop_id for s in stops] == ["1019", "1021", "f1168"]
    assert (stops[0].lat, stops[0].lon) == (41.2152937, 13.57178992)


def test_load_strips_the_id_from_the_name(stops):
    assert stops[1].name == "ARTENA"
    assert stops[2].name == 'BAGNOREGIO | Ist. F.lli AGosti"'


def test_select_keeps_requested_order(stops):
    assert [s.stop_id for s in select_stops(stops, ["1021", "1019"])] == ["1021", "1019"]


def test_select_unknown_id_raises(stops):
    with pytest.raises(StopNotFoundError, match="nope"):
        select_stops(stops, ["1019", "nope"])


def test_cotral_stop_ids():
    ids = {"f3583": True, "f12": True, "1019": False, "fCAGIP": False, "AQUINOBV": False, "f8270A": True, "F34502": False}

    assert {i: is_cotral_stop(Stop(i, "", 0.0, 0.0)) for i in ids} == ids


def test_sample_order_is_reproducible_and_seed_dependent():
    stops = [Stop(f"f{i}", "", 0.0, 0.0) for i in range(50)]

    assert sample_order(stops, seed=0) == sample_order(list(reversed(stops)), seed=0)
    assert sample_order(stops, seed=0) != sample_order(stops, seed=1)


def test_sample_order_is_stable_when_stops_are_added():
    stops = [Stop(f"f{i}", "", 0.0, 0.0) for i in range(50)]
    extended = stops + [Stop(f"f{i}", "", 0.0, 0.0) for i in range(50, 60)]

    original = sample_order(stops, seed=0)
    assert [s for s in sample_order(extended, seed=0) if s in stops] == original


def test_pair_is_the_nearest_same_name_stop_within_range():
    a = Stop("f1", "ROMA | Piazza", 41.9000, 12.5000)
    across = Stop("f2", "ROMA | Piazza", 41.9002, 12.5000)  # ~22 m
    far = Stop("f3", "ROMA | Piazza", 41.9100, 12.5000)  # ~1.1 km
    other_name = Stop("f4", "ROMA | Via", 41.90005, 12.5000)
    lonely = Stop("f5", "TIVOLI | Centro", 41.9600, 12.8000)

    pairs = find_pairs([a, far, lonely], [a, across, far, other_name, lonely])

    assert pairs == {"f1": across}
