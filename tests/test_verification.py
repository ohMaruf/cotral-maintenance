import csv

import pytest

from cotral_maintenance.errors import TransportError
from cotral_maintenance.fileutils import RawStore, write_dataset
from cotral_maintenance.geo import offset
from cotral_maintenance.models import Stop
from cotral_maintenance.verification import (
    CorrectedStop,
    Status,
    build_dataset,
    fetch_stop,
    fetch_stops,
    load_corrected_stops,
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
    return RawStore(tmp_path / "raw")


def row_for(places: list[dict], store: RawStore):
    fetch_stop(STOP, FakePlaces(places), store)
    return build_dataset([STOP], store)[0]


def test_matching_id_in_name_verifies_the_stop(store):
    google = place("ROMA | Anagnina (Metro A) # f3583", bearing=90, distance=12,
                   primaryType="bus_stop", types=["bus_stop", "transit_station"],
                   accessibilityOptions={"wheelchairAccessibleEntrance": True}, photos=[{}, {}])

    row = row_for([place("Anagnina Metro A"), google], store)

    assert row.status == Status.VERIFIED
    assert row.coord_source == "places"
    assert (row.stop_lat, row.stop_lon) == (google["location"]["latitude"], google["location"]["longitude"])
    assert (row.gtfs_lat, row.gtfs_lon) == (STOP.lat, STOP.lon)
    assert row.offset_m == pytest.approx(12, abs=0.1)
    assert row.google_stop_id == "f3583"
    assert row.place_id == "id-ROMA | Anagnina (Metro A) # f3583"
    assert row.types == "bus_stop;transit_station"
    assert row.wheelchair_accessible_entrance is True
    assert row.photo_count == 2


def test_no_match_is_missing_and_lists_nearby_cotral_stops(store):
    places = [place("GAETA | Piazza Libertà # f4207", distance=31), place("Other operator stop")]

    row = row_for(places, store)

    assert row.status == Status.MISSING
    assert row.coord_source == "gtfs"
    assert (row.stop_lat, row.stop_lon) == (STOP.lat, STOP.lon)
    assert row.place_id is None
    assert row.nearby_cotral_ids == "f4207"


def test_similar_id_is_not_a_match(store):
    assert row_for([place("Somewhere # f35830")], store).status == Status.MISSING


def test_duplicate_matches_pick_nearest_and_are_counted(store):
    places = [place("A # f3583", distance=40), place("B # f3583", distance=8)]

    row = row_for(places, store)

    assert row.match_count == 2
    assert row.place_name == "B # f3583"


def test_id_followed_by_a_stray_quote_still_matches(store):
    assert row_for([place('ROMA | Ist. Agosti" # f3583"')], store).status == Status.VERIFIED


def test_stop_is_verified_through_a_neighbours_search(store):
    # Our own search misses the stop: Google has it beyond the search radius.
    neighbour = Stop("f4207", "GAETA | Libertà", *offset(STOP.lat, STOP.lon, 90, 400))
    fetch_stop(STOP, FakePlaces([]), store)
    fetch_stop(neighbour, FakePlaces([place("X # f3583", bearing=90, distance=300)]), store)

    row = build_dataset([STOP, neighbour], store)[0]

    assert row.status == Status.VERIFIED
    assert row.offset_m == pytest.approx(300, abs=0.1)


def test_retired_id_with_the_same_name_gives_the_stop_its_position(store):
    # f99994 in the GTFS is on Google as f99933, which is no longer in the GTFS.
    google = place("roma| anagnina (METRO A) # f99933", distance=120)

    row = row_for([google], store)

    assert row.status == Status.REIDENTIFIED
    assert row.coord_source == "places"
    assert row.google_stop_id == "f99933"
    assert row.stop_lat == google["location"]["latitude"]
    assert row.offset_m == pytest.approx(120, abs=0.1)
    assert "f99933" in row.reason


def test_same_name_id_that_is_in_the_gtfs_is_a_different_stop(store):
    other = Stop("f99933", STOP.name, *offset(STOP.lat, STOP.lon, 0, 120))
    fetch_stop(STOP, FakePlaces([place(f"{STOP.name} # f99933", distance=120)]), store)

    row = build_dataset([STOP, other], store)[0]

    assert row.status == Status.MISSING
    assert row.coord_source == "gtfs"


def test_retired_id_too_far_away_is_a_different_stop(store):
    google = place(f"{STOP.name} # f99933", distance=2500)

    assert row_for([google], store).status == Status.MISSING


def test_retired_id_stands_for_only_the_nearest_of_two_directions(store):
    near = Stop("f1", STOP.name, *offset(STOP.lat, STOP.lon, 0, 20))
    far = Stop("f2", STOP.name, *offset(STOP.lat, STOP.lon, 180, 20))
    fetch_stop(near, FakePlaces([place(f"{STOP.name} # f99933", distance=30)]), store)
    fetch_stop(far, FakePlaces([]), store)

    rows = {row.stop_id: row.status for row in build_dataset([near, far], store)}

    assert rows == {"f1": Status.REIDENTIFIED, "f2": Status.MISSING}


def test_legacy_stop_beside_cotral_stops_is_substituted(store):
    legacy = Stop("1038", "STIMIGLIANO BV", STOP.lat, STOP.lon)
    far, near = (Stop(i, "TARANO", *offset(STOP.lat, STOP.lon, 90, d)) for i, d in (("f2", 56), ("f1", 41)))
    outside = Stop("f3", "TARANO", *offset(STOP.lat, STOP.lon, 90, 500))
    fetch_stop(legacy, FakePlaces([]), store)

    row = build_dataset([legacy, far, near, outside], store)[0]

    assert row.status == Status.SUBSTITUTED
    assert row.substitute_ids == "f1;f2"


def test_cotral_stop_beside_other_cotral_stops_is_missing_not_substituted(store):
    neighbour = Stop("f4207", "GAETA", *offset(STOP.lat, STOP.lon, 90, 30))
    fetch_stop(STOP, FakePlaces([]), store)

    assert build_dataset([STOP, neighbour], store)[0].status == Status.MISSING


def test_every_gtfs_stop_gets_a_row_with_its_gtfs_columns(store):
    other = Stop("f4207", "GAETA", 41.2, 13.5, location_type="1", parent_station="p")
    fetch_stop(STOP, FakePlaces([]), store)

    row = build_dataset([other, STOP], store)[0]

    assert row.stop_id == "f4207"
    assert row.status == Status.NOT_CHECKED
    assert (row.location_type, row.parent_station) == ("1", "p")


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
    fetch_stop(STOP, FakePlaces([]), store)
    record = next(store.records())

    assert record["stop"]["stop_id"] == STOP.stop_id
    assert record["request"]["body"]["locationRestriction"]["circle"]["center"] == {
        "latitude": STOP.lat, "longitude": STOP.lon,
    }
    assert "places.location" in record["request"]["field_mask"]


def test_transport_error_skips_stop_without_saving(store):
    fetched = fetch_stops([STOP], FakePlaces(error=TransportError("down")), store)

    assert fetched == 0
    assert not store.has(STOP.stop_id)


def test_dataset_csv_starts_with_the_gtfs_columns(store, tmp_path):
    fetch_stop(STOP, FakePlaces([place("X # f3583", distance=5)]), store)
    out = tmp_path / "stops_corrected.csv"

    write_dataset(build_dataset([STOP], store), CorrectedStop, out)

    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames[:6] == [
        "stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station",
    ]
    assert [(r["stop_id"], r["status"], r["coord_source"]) for r in rows] == [("f3583", "verified", "places")]


def test_corrected_stops_load_at_their_corrected_position(store, tmp_path):
    google = place("X # f3583", distance=50)
    fetch_stop(STOP, FakePlaces([google]), store)
    out = tmp_path / "stops_corrected.csv"
    write_dataset(build_dataset([STOP], store), CorrectedStop, out)

    stop, status = load_corrected_stops(out)["f3583"]

    assert status == Status.VERIFIED
    assert stop.lat == google["location"]["latitude"]
    assert stop.name == STOP.name
