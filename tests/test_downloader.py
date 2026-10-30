import json

import pytest

from cotral_maintenance.downloader import Outcome, download_stop, download_stops
from cotral_maintenance.errors import ApiError, NoImageryError, ServerError, TransportError
from cotral_maintenance.geo import distance_m, offset
from cotral_maintenance.models import PanoMetadata, Stop, View
from cotral_maintenance.panoramas import VIEWS, find_nearby_shots, plan_shots
from cotral_maintenance.storage import ImageStore

STOP = Stop(stop_id="1019", name="GAETA", lat=41.2, lon=13.5)


def pano_near_stop(pano_id: str, bearing: float, distance: float, date: str = "2025-05") -> PanoMetadata:
    lat, lon = offset(STOP.lat, STOP.lon, bearing, distance)
    return PanoMetadata(pano_id=pano_id, lat=lat, lon=lon, date=date, copyright="© Google")


# A road running east-west: panoramas 1 m and 7 m west, 8 m east, plus one 22 m north.
PANOS = [
    pano_near_stop("at", 270, 1),
    pano_near_stop("west", 270, 7),
    pano_near_stop("east", 90, 8, date="2023-09"),
    pano_near_stop("north", 0, 22),
]


def requests_by_view(client) -> dict[str, tuple[str, float]]:
    return {view: (pano_id, round(heading)) for pano_id, heading, view in client.image_requests}


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


def test_converging_shots_come_from_opposite_sides_and_face_the_stop(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    requests = requests_by_view(client)
    # "at" is nearest but not 5-10 m away; west and east are, on opposite sides.
    assert {requests["converge_a"], requests["converge_b"]} == {("west", 90), ("east", 270)}


def test_sky_shots_look_outwards_from_the_nearest_panorama(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    requests = requests_by_view(client)
    assert {requests["sky_a"], requests["sky_b"]} == {("at", 270), ("at", 90)}


def test_converging_falls_back_to_wider_distances():
    client = FakeClient(panos=[pano_near_stop("n", 0, 15), pano_near_stop("s", 180, 16)])

    plan = plan_shots(find_nearby_shots(client, STOP))

    assert {plan["converge_a"].pano.pano_id, plan["converge_b"].pano.pano_id} == {"n", "s"}


def test_single_panorama_gives_one_converging_shot(store):
    client = FakeClient(panos=[pano_near_stop("only", 270, 6)])

    results = download_stop(STOP, VIEWS, client, store)

    outcomes = {r.view.name: r.outcome for r in results}
    assert outcomes["converge_b"] == Outcome.NO_IMAGERY
    assert outcomes["converge_a"] == outcomes["sky_a"] == outcomes["sky_b"] == Outcome.DOWNLOADED


def test_sidecar_records_distance_and_heading(store):
    results = download_stop(STOP, VIEWS, FakeClient(), store)

    path = next(r.path for r in results if r.view.name == "sky_a")
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["shot"]["pano"]["pano_id"] == "at"
    assert sidecar["shot"]["distance_m"] == pytest.approx(1, abs=0.1)


def test_manifest_dates_the_stop_by_its_oldest_image(store):
    download_stop(STOP, VIEWS, FakeClient(), store)

    manifest = json.loads(store.manifest_path(STOP.stop_id).read_text())
    assert manifest["imagery_date"] == "2023-09"
    assert manifest["converge_separation_deg"] == pytest.approx(180, abs=1)
    assert [i["view"] for i in manifest["images"]] == [v.name for v in VIEWS]


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

    results = download_stops([STOP], [View("converge_a")], client, store)

    assert [r.outcome for r in results] == [Outcome.FAILED]


def test_api_error_is_fatal(store):
    client = FakeClient(metadata_error=ApiError("REQUEST_DENIED"))

    with pytest.raises(ApiError):
        download_stops([STOP], [View("converge_a")], client, store)


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
    user_pano = PanoMetadata("user", *offset(STOP.lat, STOP.lon, 90, 7), copyright="© Some User")
    client = FakeClient(panos=[pano_near_stop("west", 270, 7), user_pano])

    download_stop(STOP, VIEWS, client, store)

    assert {pano_id for pano_id, _, _ in client.image_requests} == {"west"}
