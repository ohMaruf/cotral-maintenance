import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cotral_maintenance.geo import distance_m
from cotral_maintenance.osm_store import OsmStore, StopFeature
from cotral_maintenance.runstore import RunStore
from cotral_review.api import create_app
from cotral_review.config import Settings

from .conftest import IDS, JPEG
from .explore_fixtures import NO_IMAGERY, NOT_FOUND, UNSCORED, write_csv

URL = "/api/explorations"
REAL_RUN = Path("runs/smoke-local")


@pytest.fixture
def explore_settings(settings: Settings, tmp_path: Path) -> Settings:
    write_csv(tmp_path / "truth.csv", [{"stop_id": "a1", "lat": 41.0, "lon": 12.0002}])
    store = OsmStore(tmp_path / "osm.sqlite3")
    store.create()
    store.add_stops([
        StopFeature("n2", "shelter", 41.0010, 12.0, "", "Near", "", {}),
        StopFeature("n1", "bus_stop", 41.0, 12.0005, "A1", "Via Roma", "Cotral", {}),
        StopFeature("w3", "platform", 41.01, 12.0, "", "Far", "", {}),  # ~1.1 km away
    ])
    return settings


@pytest.fixture
def explore(explore_settings: Settings) -> TestClient:
    return TestClient(create_app(explore_settings))


def test_list_has_one_exploration_per_stop_in_run_order(explore):
    runs = explore.get(URL).json()
    assert [r["run_id"] for r in runs] == [*IDS, NOT_FOUND, NO_IMAGERY, UNSCORED]
    assert all(r["run_id"] == r["stop_id"] for r in runs)
    first = runs[0]
    assert (first["name"], first["outcome"], first["outcome_reason"], first["model"]) == (
        "Stop a1", "found", "the explorer ended: outcome", "qwen3.8-27b")
    assert (first["turns"], first["seconds"], first["scan_date"]) == (4, 61.5, "2025-06")
    assert (first["billed_static"], first["billed_tiles"], first["events"], first["photos"]) == (2, 8, 3, 3)
    assert first["started_at"].startswith("2026-11-06T11:00") and first["finished_at"].startswith("2026-11-06T11:01")
    assert first["harness"] == {"version": "0.11.1", "git_commit": "da028ea", "git_dirty": True,
                                "prompt_sha256": "ab" * 32, "explorer_model": "qwen3.8-27b",
                                "confirmer_model": "same model, fresh call"}
    assert (first["budget_unit"], first["budget_used"], first["budget_max"], first["max_photos"]) == ("images", 1, 12, 14)
    assert (first["billed_used"], first["stop_photos_used"], first["tiles_used"], first["tiles_max"]) == (2, 2, 8, 42)
    assert first["start_kind"] == "osm_ref" and "event_list" not in first


def test_errors_against_the_verified_position(explore):
    first = explore.get(f"{URL}/a1").json()
    assert first["err_gtfs_m"] == pytest.approx(distance_m(41.0, 12.0, 41.0, 12.0002))
    assert first["err_found_m"] == pytest.approx(distance_m(41.0001, 12.0, 41.0, 12.0002))
    assert explore.get(f"{URL}/b2").json()["err_found_m"] is None  # no verified position


def test_stops_without_a_search_have_a_minimal_exploration(explore):
    failed = explore.get(f"{URL}/{NO_IMAGERY}").json()
    assert (failed["outcome"], failed["outcome_reason"]) == ("no_imagery", "no Street View from 2024 on along the path")
    assert (failed["photos"], failed["events"], failed["budget_used"], failed["budget_max"]) == (0, 0, 0, 0)
    assert (failed["billed_used"], failed["tiles_used"], failed["start_kind"]) == (None, None, None)
    assert failed["photo_list"] == [] and failed["event_list"] == [] and failed["transcript"] == []
    assert failed["path"] == [] and failed["candidates"] == [] and failed["report"] is None
    assert [p["kind"] for p in failed["positions"]] == ["gtfs"]


def test_start_kind_falls_back_to_the_start_source(explore, run_dir):
    with RunStore(run_dir) as store:
        store.put_start({"stop_id": NOT_FOUND, "source": "places", "lat": 41.0, "lon": 12.0004})
    assert explore.get(f"{URL}/{NOT_FOUND}").json()["start_kind"] == "places"
    assert [p["kind"] for p in explore.get(f"{URL}/{NOT_FOUND}").json()["positions"]] == ["gtfs", "places"]


def test_events_interleave_thoughts_and_tool_calls_in_transcript_order(explore):
    body = explore.get(f"{URL}/a1").json()
    events = body["event_list"]
    assert [e["seq"] for e in events] == list(range(1, 8))
    assert [e["kind"] for e in events] == [
        "thought", "thought", "begin", "look", "thought", "submit_found", "thought"]
    reasoning, said = events[0], events[1]
    assert reasoning["summary"] == "Look first." and reasoning["error"] is None and reasoning["photos"] == []
    assert reasoning["raw"] == {"request": None, "response": "Look first."}
    assert said["summary"] == "I will begin."


def test_tool_events_carry_args_result_photos_and_budget(explore):
    body = explore.get(f"{URL}/a1").json()
    begin, failed, submit = body["event_list"][2], body["event_list"][3], body["event_list"][5]
    assert begin["summary"] == "STOP s1: Stop" and begin["photos"] == [1] and begin["photos_used"] == 1
    assert begin["raw"] == {"request": {}, "response": "STOP s1: Stop\nmore"} and begin["budget_used"] == 1
    assert (failed["error"], failed["summary"]) == ("no panorama within 25 m", "ERROR: no panorama within 25 m")
    assert failed["raw"]["request"] == {"from_m": 900} and failed["raw"]["response"] == failed["error"]
    assert submit["photos"] == [2, 3] and submit["photos_used"] == 3
    used = [e["photos_used"] for e in body["event_list"]]
    assert used == sorted(used)


def test_events_without_a_transcript_are_the_record_events(explore, run_dir):
    with RunStore(run_dir) as store:
        with store.transaction() as c:
            c.execute("DELETE FROM transcripts WHERE stop_id = 'a1'")
    body = explore.get(f"{URL}/a1").json()
    assert [e["kind"] for e in body["event_list"]] == ["begin", "look", "submit_found"]
    assert body["report"] is None and body["transcript"] == []


def test_transcript_and_report(explore):
    body = explore.get(f"{URL}/a1").json()
    assert body["report"] == "I found it.\nSecond line."
    assert [line.get("turn") for line in body["transcript"]] == [1, 1, 2, 2, None, 3, 3, 4]
    assert body["transcript"][4] == {"confirm": 1, "attempt": 1, "photo": "x.jpg", "status": "confirmed"}


def test_photos_are_media_urls_with_copyright(explore, run_dir):
    body = explore.get(f"{URL}/a1").json()
    photos = body["photo_list"]
    assert [p["index"] for p in photos] == [1, 2, 3]
    first = photos[0]
    assert first["url"].startswith(f"{URL}/a1/photos/") and first["url"].endswith(".jpg") and len(first["url"].rsplit("/", 1)[1]) == 68
    assert (first["copyright"], first["toward"], first["date"], first["shot"], first["opening"]) == (
        "© Google", "sweep_ahead", "2025-06", 1, True)
    assert [p["billed"] for p in photos] == [True, True, False]
    assert (body["stop_photos"], body["close_up"]) == ([2, 3], 1)  # the close-up is the search photo
    assert body["candidates"][0]["confirmer_note"] == "A blue pole." and body["candidates"][0]["confirm_photo"] == 1
    assert body["limits"] == {"along_from": -400.0, "along_to": 400.0} and len(body["path"]) == 3
    assert explore.get(first["url"]).status_code == 200


def test_positions_with_errors(explore, run_dir):
    with RunStore(run_dir) as store:
        store.put_start({"stop_id": "a1", "source": "places", "lat": 41.0, "lon": 12.0004})
    positions = {p["kind"]: p for p in explore.get(f"{URL}/a1").json()["positions"]}
    assert set(positions) == {"gtfs", "places", "verified", "estimate"}
    assert positions["verified"]["error_m"] is None and positions["verified"]["label"] == "Verified"
    assert positions["places"]["error_m"] == pytest.approx(distance_m(41.0, 12.0004, 41.0, 12.0002))
    assert (positions["estimate"]["lat"], positions["estimate"]["lon"]) == (41.0001, 12.0)


def test_osm_features_within_200_m_of_gtfs_position(explore):
    assert explore.get(f"{URL}/a1").json()["osm_features"] == [
        {"id": "n1", "kind": "bus_stop", "lat": 41.0, "lon": 12.0005, "ref": "A1", "name": "Via Roma",
         "operator": "Cotral"},
        {"id": "n2", "kind": "shelter", "lat": 41.001, "lon": 12.0, "ref": "", "name": "Near", "operator": ""},
    ]


def test_missing_osm_store_and_truth_give_no_features_and_no_errors(settings, caplog):
    client = TestClient(create_app(settings))
    with caplog.at_level("WARNING"):
        body = client.get(f"{URL}/a1").json()
        assert client.get(f"{URL}/b2").json()["osm_features"] == []
    assert body["osm_features"] == [] and body["err_gtfs_m"] is None
    assert len([r for r in caplog.records if "no OSM store" in r.message]) == 1


def test_harness_versions_and_filter(explore, run_dir):
    with RunStore(run_dir) as store:
        row = store.exploration("b2")
        store.put_exploration(row | {"harness": {"version": "0.9.0"}}, [], [])
        store.put_exploration(row | {"stop_id": "c3", "harness": {"version": "0.10.0"}}, [], [])
        store.put_exploration(row | {"stop_id": "d4", "harness": {}}, [], [])
    assert explore.get(f"{URL}/harness-versions").json() == [
        {"version": "0.11.1", "runs": 4}, {"version": "0.10.0", "runs": 1}, {"version": "0.9.0", "runs": 1},
        {"version": "unversioned", "runs": 1}]
    ids = lambda v: [r["run_id"] for r in explore.get(URL, params={"harness": v}).json()]  # noqa: E731
    assert ids("0.10.0") == ["c3"] and ids("unversioned") == ["d4"] and ids("9.9") == []
    assert len(ids("0.11.1")) == 4


def test_broken_record_is_422(explore, run_dir):
    with RunStore(run_dir) as store:
        store.put_exploration(store.exploration("b2") | {"record": {"photos": [{"index": 1}]}}, [], [])
    assert explore.get(f"{URL}/b2").status_code == 422


@pytest.mark.parametrize("stop_id", ["nope", "bad%20id", "..", "%2e%2e", "..%2Fruns", "harness"])
def test_unknown_stop_is_404(explore, stop_id):
    assert explore.get(f"{URL}/{stop_id}").status_code == 404


def test_explorations_are_read_on_every_request(explore, run_dir):
    assert explore.get(f"{URL}/b2").json()["outcome"] == "found"
    with RunStore(run_dir) as store:
        store.put_exploration(store.exploration("b2") | {"status": "not_found"}, [], [])
    assert explore.get(f"{URL}/b2").json()["outcome"] == "not_found"


def test_photo_served_with_cache_header(explore):
    r = explore.get(explore.get(f"{URL}/a1").json()["photo_list"][1]["url"])
    assert r.status_code == 200 and r.content.startswith(JPEG)
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"


def test_photo_404(explore, run_dir):
    sha = explore.get(f"{URL}/a1").json()["photo_list"][0]["url"].rsplit("/", 1)[1]
    other = explore.get(f"{URL}/b2").json()["photo_list"][0]["url"].rsplit("/", 1)[1]
    stray = run_dir / "media" / "ff" / f"{'f' * 64}.jpg"  # on disk, but no photo of any stop
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(JPEG)
    for path in [
        f"{URL}/a1/photos/{other}", f"{URL}/a1/photos/{'f' * 64}.jpg", f"{URL}/a1/photos/{sha[:-4]}",
        f"{URL}/a1/photos/..%2F..%2Frun.sqlite", f"{URL}/a1/photos/%2e%2e", f"{URL}/{NO_IMAGERY}/photos/{sha}",
        f"{URL}/..%2Fa1/photos/{sha}", f"{URL}/nope/photos/{sha}",
    ]:
        assert explore.get(path).status_code == 404, path
    assert explore.get(f"{URL}/a1/photos/{sha}").status_code == 200


@pytest.mark.skipif(not (REAL_RUN / "run.sqlite").is_file(), reason="no real run present")
def test_real_run_converts(tmp_path):
    settings = Settings(
        run=REAL_RUN, database=tmp_path / "r.sqlite3", shape_verdicts_db=tmp_path / "v.sqlite3",
        frontend_dist=tmp_path / "dist")
    client = TestClient(create_app(settings))
    for summary in client.get(URL).json():
        body = client.get(f"{URL}/{summary['run_id']}").json()
        used = [e["photos_used"] for e in body["event_list"]]
        assert used == sorted(used) and len(used) >= summary["events"]
        assert [e["seq"] for e in body["event_list"]] == list(range(1, len(used) + 1))
        for photo in body["photo_list"]:
            assert client.get(photo["url"]).status_code == 200
    assert client.get("/api/results").status_code == 200
