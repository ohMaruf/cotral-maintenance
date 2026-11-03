import json
import math

import pytest

from cotral_maintenance.downloader import Outcome, download_stop, download_stops
from cotral_maintenance.errors import ApiError, NoImageryError, ServerError, TransportError
from cotral_maintenance.geo import distance_m, offset
from cotral_maintenance.models import PanoMetadata, Stop, View
from cotral_maintenance.panoramas import VIEWS, plan_shots
from cotral_maintenance.storage import ImageStore

STOP = Stop(stop_id="1019", name="GAETA", lat=41.2, lon=13.5)


def pano_at(pano_id: str, east: float, north: float, date: str = "2025-05") -> PanoMetadata:
    """A panorama `east`, `north` metres from the stop."""
    bearing = math.degrees(math.atan2(east, north)) % 360
    lat, lon = offset(STOP.lat, STOP.lon, bearing, math.hypot(east, north))
    return PanoMetadata(pano_id=pano_id, lat=lat, lon=lon, date=date, copyright="© Google")


def street(north: float = -5.0, date: str = "2025-05") -> list[PanoMetadata]:
    """An east-west road `north` metres from the stop, a panorama every 4 m for 80 m."""
    return [pano_at(f"x{east:+03d}", east, north, date) for east in range(-40, 41, 4)]


# The stop is on the north sidewalk of a road 5 m south of it.
PANOS = street()


def east_of(pano_id: str) -> int:
    return int(pano_id[1:])


def requests_by_view(client) -> dict[str, tuple[str, float]]:
    return {view: (pano_id, round(heading) % 360) for pano_id, heading, view in client.image_requests}


class FakeClient:
    """Returns the nearest of a fixed set of panoramas, like the real metadata endpoint."""

    def __init__(self, panos=PANOS, metadata_error: Exception | None = None) -> None:
        self.panos = panos
        self.metadata_error = metadata_error
        self.metadata_calls = 0
        self.image_requests: list[tuple[str, float, str]] = []

    def get_metadata(self, lat: float, lon: float, radius_m: float) -> PanoMetadata:
        self.metadata_calls += 1
        if self.metadata_error:
            raise self.metadata_error
        in_range = [
            (distance_m(lat, lon, p.lat, p.lon), p)
            for p in self.panos
            if distance_m(lat, lon, p.lat, p.lon) <= radius_m
        ]
        if not in_range:
            raise NoImageryError("none")
        return min(in_range, key=lambda pair: pair[0])[1]

    def get_image(self, pano_id: str, heading: float, view: View) -> bytes:
        self.image_requests.append((pano_id, heading, view.name))
        return b"jpeg-bytes"


@pytest.fixture
def store(tmp_path):
    return ImageStore(tmp_path)


def test_sweep_looks_across_the_road_at_the_stop_sidewalk(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    assert {heading for _, heading in requests_by_view(client).values()} == {0}  # north


def test_sweep_spreads_along_the_road_around_the_stop(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    positions = sorted(east_of(pano_id) for pano_id, _ in requests_by_view(client).values())
    assert positions == [-24, -8, 8, 24]


def stop_at(stop_id: str, east: float, north: float) -> Stop:
    pano = pano_at(stop_id, east, north)
    return Stop(stop_id=stop_id, name=STOP.name, lat=pano.lat, lon=pano.lon)


@pytest.mark.parametrize("pair_north, expected_heading", [(-12.0, 0), (12.0, 180)])
def test_stop_on_the_road_line_sweeps_the_sidewalk_away_from_its_pair(pair_north, expected_heading):
    # The coordinates are on the road line; the opposite-direction stop is 25 m
    # along the road, across it (south of the road in the first case).
    pair = stop_at("pair", 25, pair_north + 0.5)

    plan = plan_shots(FakeClient(panos=street(north=0.5)), STOP, pair)

    assert {round(s.heading) % 360 for s in plan.values()} == {expected_heading}
    assert len(plan) == 4


def test_stop_off_the_road_line_trusts_its_coordinates_over_its_pair():
    # The stop is clearly north of the road; a misplaced pair on the same side is ignored.
    plan = plan_shots(FakeClient(), STOP, stop_at("pair", 20, 3))

    assert {round(s.heading) % 360 for s in plan.values()} == {0}


def test_only_one_sidewalk_is_ever_swept():
    plan = plan_shots(FakeClient(panos=street(north=0.5)), STOP)

    assert len({round(s.heading) % 360 for s in plan.values()}) == 1
    assert sorted(east_of(s.pano.pano_id) for s in plan.values()) == [-24, -8, 8, 24]


def test_junction_sweeps_along_the_street_with_most_panoramas():
    # The stop's street runs east-west; a shorter side street crosses it at the stop.
    side_street = [pano_at(f"s{n:+03d}", 3, n) for n in (-24, -18, -12, 12, 18)]

    plan = plan_shots(FakeClient(panos=[*street(), *side_street]), STOP)

    assert {round(s.heading) % 360 for s in plan.values()} == {0}
    assert sorted(east_of(s.pano.pano_id) for s in plan.values()) == [-24, -8, 8, 24]


def test_sweep_skips_panoramas_from_another_drive():
    panos = [p for p in street() if p.pano_id != "x+24"] + [pano_at("old", 24, -5, date="2022-05")]

    plan = plan_shots(FakeClient(panos=panos), STOP)

    assert "old" not in {s.pano.pano_id for s in plan.values()}
    assert len(plan) == 3


def test_single_panorama_gives_one_shot_at_the_stop(store):
    client = FakeClient(panos=[pano_at("only", -6, 0)])

    results = download_stop(STOP, VIEWS, client, store)

    outcomes = {r.view.name: r.outcome for r in results}
    assert outcomes == {
        "sweep_1": Outcome.DOWNLOADED, "sweep_2": Outcome.NO_IMAGERY,
        "sweep_3": Outcome.NO_IMAGERY, "sweep_4": Outcome.NO_IMAGERY,
    }
    assert requests_by_view(client)["sweep_1"] == ("only", 90)


def test_sidecar_records_distance_and_heading(store):
    results = download_stop(STOP, VIEWS, FakeClient(), store)

    for result in results:
        sidecar = json.loads(result.path.with_suffix(".json").read_text())
        pano = next(p for p in PANOS if p.pano_id == sidecar["shot"]["pano"]["pano_id"])
        assert sidecar["shot"]["distance_m"] == pytest.approx(distance_m(pano.lat, pano.lon, STOP.lat, STOP.lon))
        assert round(sidecar["shot"]["heading"]) % 360 == 0


def test_manifest_lists_images_in_plan_order_with_their_date(store):
    download_stop(STOP, VIEWS, FakeClient(panos=street(date="2024-03")), store)

    manifest = json.loads(store.manifest_path(STOP.stop_id).read_text())
    assert manifest["imagery_date"] == "2024-03"
    assert [i["view"] for i in manifest["images"]] == [v.name for v in VIEWS]


def test_manifest_is_removed_when_no_images_remain(store):
    download_stop(STOP, VIEWS, FakeClient(), store)
    for view in VIEWS:
        store.image_path(STOP.stop_id, view).unlink()

    store.write_manifest(STOP, VIEWS)

    assert not store.manifest_path(STOP.stop_id).exists()


def test_manifest_is_rebuilt_when_all_images_are_cached(store):
    download_stop(STOP, VIEWS, FakeClient(), store)
    store.manifest_path(STOP.stop_id).unlink()

    download_stop(STOP, VIEWS, FakeClient(), store)

    assert store.manifest_path(STOP.stop_id).is_file()


def test_second_run_uses_cache(store):
    download_stop(STOP, VIEWS, FakeClient(), store)
    client = FakeClient()

    results = download_stop(STOP, VIEWS, client, store)

    assert {r.outcome for r in results} == {Outcome.CACHED}
    assert client.metadata_calls == 0
    assert client.image_requests == []


def test_force_redownloads(store):
    download_stop(STOP, VIEWS, FakeClient(), store)
    client = FakeClient()

    results = download_stop(STOP, VIEWS, client, store, force=True)

    assert {r.outcome for r in results} == {Outcome.DOWNLOADED}
    assert len(client.image_requests) == len(VIEWS)


def test_only_missing_views_are_fetched(store):
    download_stop(STOP, VIEWS[:1], FakeClient(), store)
    client = FakeClient()

    results = download_stop(STOP, VIEWS[:2], client, store)

    assert sorted(r.outcome.value for r in results) == ["cached", "downloaded"]
    assert len(client.image_requests) == 1


def test_no_panoramas_is_reported_not_raised(store):
    results = download_stop(STOP, VIEWS, FakeClient(panos=[]), store)

    assert {r.outcome for r in results} == {Outcome.NO_IMAGERY}


def test_transport_error_skips_stop(store):
    client = FakeClient(metadata_error=TransportError("down"))

    results = download_stops([STOP], [View("sweep_1")], client, store)

    assert [r.outcome for r in results] == [Outcome.FAILED]


def test_api_error_is_fatal(store):
    client = FakeClient(metadata_error=ApiError("REQUEST_DENIED"))

    with pytest.raises(ApiError):
        download_stops([STOP], [View("sweep_1")], client, store)


def test_server_error_at_one_sample_point_is_skipped(store):
    class FlakyPointClient(FakeClient):
        def get_metadata(self, lat, lon, radius_m):
            if self.metadata_calls == 3:
                self.metadata_calls += 1
                raise ServerError("UNKNOWN_ERROR")
            return super().get_metadata(lat, lon, radius_m)

    results = download_stop(STOP, VIEWS, FlakyPointClient(), store)

    assert {r.outcome for r in results} == {Outcome.DOWNLOADED}


def test_user_photospheres_are_ignored(store):
    user_pano = PanoMetadata("user", *offset(STOP.lat, STOP.lon, 0, 1), copyright="© Some User")
    client = FakeClient(panos=[*PANOS, user_pano])

    download_stop(STOP, VIEWS, client, store)

    assert "user" not in {pano_id for pano_id, _, _ in client.image_requests}


def test_billed_image_requests_stay_within_budget(store):
    # Budget: 5 billed requests per stop, one of which is the phase 1 Places search.
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    assert len(client.image_requests) <= 4
