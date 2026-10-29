import pytest

from cotral_maintenance.geo import bearing_deg, distance_m, offset

ORIGIN = (41.2152937, 13.57178992)


@pytest.mark.parametrize("bearing", [0, 45, 90, 180, 270])
def test_offset_then_measure_roundtrips(bearing):
    lat, lon = offset(*ORIGIN, bearing, 30)

    assert distance_m(*ORIGIN, lat, lon) == pytest.approx(30, abs=0.01)
    assert bearing_deg(*ORIGIN, lat, lon) == pytest.approx(bearing, abs=0.01)


def test_bearing_east():
    assert bearing_deg(41.0, 13.0, 41.0, 13.001) == pytest.approx(90, abs=0.01)
