import csv

import pytest

from cotral_maintenance.errors import TransportError
from cotral_maintenance.geo import offset
from cotral_maintenance.models import Stop
from cotral_maintenance.verification import (
    RawPlacesStore,
    build_dataset,
    fetch_stop,
    fetch_stops,
    verify_record,
    write_dataset,
)

STOP = Stop(stop_id="f3583", name="ROMA | Anagnina (Metro A)", lat=41.84, lon=12.58)


def place(name: str, bearing: float = 0.0, distance: float = 0.0, **extra) -> dict:
    lat, lon = offset(STOP.lat, STOP.lon, bearing, distance)
    return {
        "id": f"id-{name}",
        "displayName": {"text": name},
        "location": {"latitude": lat, "longitude": lon},
        **extra,
    }


class FakePlaces:
    def __init__(self, places: list[dict] | None = None, error: Exception | None = None) -> None:
        self.places = places or []
        self.error = error
        self.requests: list[dict] = []

    def search_nearby(self, request: dict) -> list[dict]:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.places


@pytest.fixture
def store(tmp_path):
    return RawPlacesStore(tmp_path / "raw")


def record_for(places: list[dict], store: RawPlacesStore) -> dict:
    fetch_stop(STOP, FakePlaces(places), store)
    return next(store.records())


def test_matching_id_in_name_verifies_the_stop(store):
    google = place("ROMA | Anagnina (Metro A) # f3583", bearing=90, distance=12,
                   primaryType="bus_stop", types=["bus_stop", "transit_station"],
                   accessibilityOptions={"wheelchairAccessibleEntrance": True}, photos=[{}, {}])

    row = verify_record(record_for([place("Anagnina Metro A"), google], store))

    assert row.verified
    assert row.coord_source == "places"
    assert (row.lat, row.lon) == (google["location"]["latitude"], google["location"]["longitude"])
    assert row.offset_m == pytest.approx(12, abs=0.1)
    assert row.place_id == "id-ROMA | Anagnina (Metro A) # f3583"
    assert row.types == "bus_stop;transit_station"
    assert row.wheelchair_accessible_entrance is True
    assert row.photo_count == 2


def test_no_match_falls_back_to_gtfs_and_lists_nearby_cotral_stops(store):
    places = [place("GAETA | Piazza Libertà # f4207", distance=31), place("Other operator stop")]

    row = verify_record(record_for(places, store))

    assert not row.verified
    assert row.coord_source == "gtfs"
    assert (row.lat, row.lon) == (STOP.lat, STOP.lon)
    assert row.place_id is None
    assert row.nearby_cotral_ids == "f4207"


def test_similar_id_is_not_a_match(store):
    row = verify_record(record_for([place("Somewhere # f35830")], store))

    assert not row.verified


def test_duplicate_matches_pick_nearest_and_are_counted(store):
    places = [place("A # f3583", distance=40), place("B # f3583", distance=8)]

    row = verify_record(record_for(places, store))

    assert row.match_count == 2
    assert row.place_name == "B # f3583"


def test_fetch_is_skipped_when_raw_record_exists(store):
    fetch_stop(STOP, FakePlaces(), store)
    client = FakePlaces()

    assert fetch_stop(STOP, client, store) is False
    assert client.requests == []


def test_force_refetches(store):
    fetch_stop(STOP, FakePlaces(), store)
    client = FakePlaces()

    assert fetch_stop(STOP, client, store, force=True) is True
    assert len(client.requests) == 1


def test_raw_record_keeps_request_for_reproducibility(store):
    record = record_for([], store)

    assert record["stop"]["stop_id"] == STOP.stop_id
    assert record["request"]["body"]["locationRestriction"]["circle"]["center"] == {
        "latitude": STOP.lat, "longitude": STOP.lon,
    }
    assert "places.location" in record["request"]["field_mask"]


def test_transport_error_skips_stop_without_saving(store):
    fetched = fetch_stops([STOP], FakePlaces(error=TransportError("down")), store)

    assert fetched == 0
    assert not store.has(STOP.stop_id)


def test_dataset_csv_roundtrip(store, tmp_path):
    record_for([place("X # f3583", distance=5)], store)
    out = tmp_path / "stops_verified.csv"

    write_dataset(build_dataset(store), out)

    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["stop_id"], r["verified"], r["coord_source"]) for r in rows] == [
        ("f3583", "True", "places")
    ]
