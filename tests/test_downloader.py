import json

import pytest

from cotral_maintenance.downloader import Outcome, download_stop, download_stops
from cotral_maintenance.errors import ApiError, NoImageryError, ServerError, TransportError
from cotral_maintenance.geo import distance_m, offset
from cotral_maintenance.models import PanoMetadata, Stop, View
from cotral_maintenance.storage import ImageStore

STOP = Stop(stop_id="1019", name="GAETA", lat=41.2, lon=13.5)


def pano_near_stop(pano_id: str, bearing: float, distance: float) -> PanoMetadata:
    lat, lon = offset(STOP.lat, STOP.lon, bearing, distance)
    return PanoMetadata(pano_id=pano_id, lat=lat, lon=lon, date="2025-05", copyright="© Google")


# West of the stop at 5 m, north at 22 m, south at 41 m.
PANOS = [
    pano_near_stop("near", 270, 5),
    pano_near_stop("mid", 0, 22),
    pano_near_stop("far", 180, 41),
]
VIEWS = [View(distance_m=0), View(distance_m=20), View(distance_m=40)]


class FakeClient:
    """Returns the nearest of a fixed set of panoramas, like the real metadata endpoint."""

    def __init__(self, panos=PANOS, metadata_error: Exception | None = None) -> None:
        self.panos = panos
        self.metadata_error = metadata_error
        self.metadata_calls = 0
        self.image_requests: list[tuple[str, float]] = []

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
        self.image_requests.append((pano_id, heading))
        return b"jpeg-bytes"


@pytest.fixture
def store(tmp_path):
    return ImageStore(tmp_path)


def test_each_view_uses_panorama_closest_to_its_distance(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    assert [pano_id for pano_id, _ in client.image_requests] == ["near", "mid", "far"]


def test_camera_is_aimed_at_the_stop(store):
    client = FakeClient()

    download_stop(STOP, VIEWS, client, store)

    headings = [round(heading) for _, heading in client.image_requests]
    # Panoramas lie west, north and south of the stop, so cameras face east, south and north.
    assert headings == [90, 180, 0]


def test_sidecar_records_distance_and_heading(store):
    results = download_stop(STOP, [View(distance_m=0)], FakeClient(), store)

    sidecar = json.loads(results[0].path.with_suffix(".json").read_text())
    assert sidecar["shot"]["pano"]["pano_id"] == "near"
    assert sidecar["shot"]["distance_m"] == pytest.approx(5, abs=0.1)
    assert sidecar["shot"]["heading"] == pytest.approx(90, abs=0.1)


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
    assert len(client.image_requests) == 3


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

    results = download_stops([STOP], [View()], client, store)

    assert [r.outcome for r in results] == [Outcome.FAILED]


def test_api_error_is_fatal(store):
    client = FakeClient(metadata_error=ApiError("REQUEST_DENIED"))

    with pytest.raises(ApiError):
        download_stops([STOP], [View()], client, store)


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
    user_pano = PanoMetadata("user", *offset(STOP.lat, STOP.lon, 0, 20), copyright="© Some User")
    client = FakeClient(panos=[PANOS[0], user_pano])

    download_stop(STOP, [View(distance_m=20)], client, store)

    assert [pano_id for pano_id, _ in client.image_requests] == ["near"]
