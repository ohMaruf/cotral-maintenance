import json
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cotral_maintenance.geo import distance_m
from cotral_maintenance.osm_store import OsmStore, StopFeature
from cotral_review.api import create_app
from cotral_review.config import Settings

from .conftest import JPEG
from .explore_fixtures import agent_record, image_record, sweep_record, tiles_record, transcript, write_csv, write_run

REAL_RUNS = Path("data/agent_runs")


@pytest.fixture
def explore_settings(tmp_path: Path) -> Settings:
    runs = tmp_path / "runs"
    write_run(runs, "s1_20261106T110000", agent_record("s1"), transcript(),
              {"stop_id": "s1", "model": "haiku"}, photos=("one.jpg", "unlisted.jpg"))
    write_run(runs, "s2_20261106T120000", agent_record("s2", running=True), None, {"stop_id": "s2", "model": "haiku"})
    write_run(runs, "s3_20261106T130000", agent_record("s3", outcome={"status": "not_found", "reason": "call cap"}),
              transcript(), None)
    write_run(runs, "odd", {"layout": "something-else"})
    (runs / "broken" / "photos").mkdir(parents=True)
    (runs / "broken" / "record.json").write_text("{not json")
    (runs / "cache").mkdir()  # not a run
    (runs / "secret.jpg").write_bytes(JPEG)
    write_csv(tmp_path / "truth.csv", [{"stop_id": "s1", "lat": 41.0, "lon": 12.0002}])
    store = OsmStore(tmp_path / "osm.sqlite3")
    store.create()
    store.add_stops([
        StopFeature("n2", "shelter", 41.0010, 12.0, "", "Near", "", {}),
        StopFeature("n1", "bus_stop", 41.0, 12.0005, "A1", "Via Roma", "Cotral", {}),
        StopFeature("w3", "platform", 41.01, 12.0, "", "Far", "", {}),  # ~1.1 km away
    ])
    write_csv(tmp_path / "places.csv", [{"stop_id": "s1", "stop_lat": 41.0, "stop_lon": 12.0004, "coord_source": "places"}])
    return Settings(
        agent_runs_dir=runs, truth_csv=tmp_path / "truth.csv", osm_store=tmp_path / "osm.sqlite3",
        places_csv=tmp_path / "places.csv", shape_check_json=tmp_path / "shape_check" / "stops.json",
        shape_verdicts_db=tmp_path / "verdicts.sqlite3", database=tmp_path / "review.sqlite3",
        frontend_dist=tmp_path / "dist",
    )


@pytest.fixture
def explore(explore_settings: Settings) -> TestClient:
    return TestClient(create_app(explore_settings))


S1 = "/api/explorations/s1_20261106T110000"
S2 = "/api/explorations/s2_20261106T120000"


def test_list_skips_unreadable_runs_and_sorts(explore):
    runs = explore.get("/api/explorations").json()
    assert [r["run_id"] for r in runs] == ["s1_20261106T110000", "s2_20261106T120000", "s3_20261106T130000"]
    first = runs[0]
    assert first["stop_id"] == "s1" and first["name"] == "Stop s1" and first["outcome"] == "found"
    assert first["outcome_reason"] is None and first["model"] == "claude-test-1"
    assert first["photos"] == 3 and first["max_photos"] == 14 and first["events"] == 9
    assert first["started_at"].startswith("2026-11-06T11:00") and first["finished_at"].startswith("2026-11-06T11:05")
    assert first["err_gtfs_m"] == pytest.approx(distance_m(41.0, 12.0, 41.0, 12.0002))
    assert first["err_found_m"] == pytest.approx(distance_m(41.0001, 12.0, 41.0, 12.0002))
    assert "event_list" not in first
    assert runs[2]["outcome"] == "not_found" and runs[2]["outcome_reason"] == "call cap"
    assert runs[2]["err_found_m"] is None


def test_old_runs_budget_counts_photos(explore):
    first = explore.get("/api/explorations").json()[0]
    assert (first["budget_unit"], first["budget_used"], first["budget_max"]) == ("photos", 3, 14)
    assert first["zooms_used"] == 0 and first["confirms_used"] == 0
    body = explore.get(S1).json()
    assert [e["budget_used"] for e in body["event_list"]] == [e["photos_used"] for e in body["event_list"]]
    photo = body["photo_list"][0]
    assert (photo["width"], photo["height"], photo["shot"], photo["parent"]) == (None, None, 0, None)
    assert body["candidates"][0]["confirmer_note"] == "" and body["candidates"][0]["confirm_photo"] is None


def test_sweep_run_budget_photos_and_candidates(explore, explore_settings):
    write_run(explore_settings.agent_runs_dir, "n1_20261109T100000", sweep_record(), None, None,
              photos=("s1a.jpg", "s1b.jpg", "z.jpg", "c.jpg"))
    listed = [r for r in explore.get("/api/explorations").json() if r["stop_id"] == "n1"][0]
    assert (listed["budget_unit"], listed["budget_used"], listed["budget_max"]) == ("sweeps", 1, 12)
    assert (listed["zooms_used"], listed["confirms_used"], listed["photos"], listed["max_photos"]) == (1, 1, 4, 12)
    body = explore.get("/api/explorations/n1_20261109T100000").json()
    assert [(e["photos_used"], e["budget_used"]) for e in body["event_list"]] == [(2, 1), (3, 1), (3, 1), (4, 1), (4, 1)]
    photos = body["photo_list"]
    assert [(p["toward"], p["shot"], p["parent"], p["width"], p["height"]) for p in photos] == [
        ("sweep_ahead", 1, None, 1536, 768), ("sweep_behind", 1, None, 1536, 768),
        ("zoom", 0, 1, 768, 768), ("confirm", 0, None, 768, 768)]
    assert [p["opening"] for p in photos] == [True, True, False, False]
    candidate = body["candidates"][0]
    assert candidate["confirmer_note"] == "A blue Cotral pole." and candidate["confirm_photo"] == 4
    assert explore.get(photos[2]["url"]).status_code == 200


def test_image_run_budget_billing_and_stop_photos(explore, explore_settings):
    write_run(explore_settings.agent_runs_dir, "i1_20261109T150000", image_record(), None, None,
              photos=("a.jpg", "b.jpg", "z.jpg", "p1.jpg", "p2.jpg"))
    listed = [r for r in explore.get("/api/explorations").json() if r["stop_id"] == "i1"][0]
    assert (listed["budget_unit"], listed["budget_used"], listed["budget_max"]) == ("images", 3, 12)
    assert (listed["billed_used"], listed["stop_photos_used"], listed["zooms_used"], listed["confirms_used"]) == (4, 2, 1, 1)
    assert (listed["photos"], listed["max_photos"]) == (5, 14)
    body = explore.get("/api/explorations/i1_20261109T150000").json()
    assert (body["stop_photos"], body["close_up"]) == ([4, 5], 3)
    assert [(e["photos_used"], e["budget_used"]) for e in body["event_list"]] == [(1, 1), (2, 2), (3, 3), (3, 3), (5, 3)]
    photos = body["photo_list"]
    assert [(p["toward"], p["billed"], p["parent"]) for p in photos] == [
        ("sweep_ahead", True, None), ("sweep_behind", True, None), ("zoom", True, 1),
        ("stop_photo", True, None), ("stop_photo", False, None)]
    assert body["candidates"][0]["confirm_photo"] == 3
    assert explore.get(photos[4]["url"]).status_code == 200


def test_older_runs_have_no_billing_or_stop_photos(explore, explore_settings):
    write_run(explore_settings.agent_runs_dir, "n1_20261109T100000", sweep_record(), None, None,
              photos=("s1a.jpg", "s1b.jpg", "z.jpg", "c.jpg"))
    body = explore.get("/api/explorations/n1_20261109T100000").json()
    assert (body["billed_used"], body["stop_photos_used"], body["stop_photos"], body["close_up"]) == (None, 0, [], None)
    assert all(p["billed"] is None for p in body["photo_list"])
    assert [e["budget_used"] for e in explore.get(S1).json()["event_list"]][:1] == [2]


def test_harness_run_exposes_version_billing_tiles_start_and_photo_sources(explore, explore_settings):
    write_run(explore_settings.agent_runs_dir, "t1_20261109T160000", tiles_record(), None, None,
              photos=("a.jpg", "z.jpg", "l.jpg"))
    listed = [r for r in explore.get("/api/explorations").json() if r["stop_id"] == "t1"][0]
    assert listed["harness"] == {
        "version": "0.6.0", "git_commit": "da028ea9b1837bcd18058fb5234c96e1dbb51146", "git_dirty": True,
        "prompt_sha256": "ab" * 32, "explorer_model": "haiku", "confirmer_model": "haiku"}
    assert (listed["billed_static"], listed["billed_tiles"], listed["tiles_used"], listed["tiles_max"]) == (1, 10, 10, 42)
    assert listed["start_kind"] == "osm_ref"
    body = explore.get("/api/explorations/t1_20261109T160000").json()
    assert [(p["toward"], p["source"], p["tiles"]) for p in body["photo_list"]] == [
        ("aimed", "static", 0), ("zoom", "tiles", 2), ("look_from", "tiles", 8)]
    assert [e["kind"] for e in body["event_list"]] == ["begin", "zoom", "look_from"]


def test_unversioned_runs_and_harness_from_config(explore, explore_settings):
    old = explore.get(S1).json()
    assert old["harness"] == {"version": "unversioned", "git_commit": None, "git_dirty": None, "prompt_sha256": None,
                              "explorer_model": None, "confirmer_model": None}
    assert (old["billed_static"], old["billed_tiles"], old["tiles_used"], old["tiles_max"]) == (None,) * 4
    assert old["start_kind"] == "places"
    assert {p["source"] for p in old["photo_list"]} == {"static"} and {p["tiles"] for p in old["photo_list"]} == {0}
    record = tiles_record("c1")
    config = {"harness": record.pop("harness")}
    write_run(explore_settings.agent_runs_dir, "c1_20261109T160000", record, None, config)
    assert explore.get("/api/explorations/c1_20261109T160000").json()["harness"]["version"] == "0.6.0"


def test_filter_and_list_harness_versions_newest_first(explore, explore_settings):
    runs = explore_settings.agent_runs_dir
    write_run(runs, "a_1", tiles_record("a", "0.6.0"), None, None)
    write_run(runs, "b_1", tiles_record("b", "0.10.0"), None, None)
    write_run(runs, "c_1", tiles_record("c", "0.7"), None, None)
    assert explore.get("/api/explorations/harness-versions").json() == [
        {"version": "0.10.0", "runs": 1}, {"version": "0.7", "runs": 1}, {"version": "0.6.0", "runs": 1},
        {"version": "unversioned", "runs": 3}]
    ids = lambda v: [r["run_id"] for r in explore.get("/api/explorations", params={"harness": v}).json()]  # noqa: E731
    assert ids("0.10.0") == ["b_1"] and ids("0.6.0") == ["a_1"] and ids("9.9") == []
    assert len(ids("unversioned")) == 3
    assert len(explore.get("/api/explorations").json()) == 6


def test_running_run_has_no_outcome_transcript_or_finish_time(explore):
    body = explore.get(S2).json()
    assert body["outcome"] == "running" and body["outcome_reason"] is None and body["finished_at"] is None
    assert body["model"] == "haiku"  # config.json, there is no transcript yet
    assert body["report"] is None
    assert [e["kind"] for e in body["event_list"]] == ["begin", "look"]
    assert body["err_found_m"] is None and [p["kind"] for p in body["positions"]] == ["gtfs", "places"]


def test_events_interleave_thoughts_and_tool_calls_in_transcript_order(explore):
    events = explore.get(S1).json()["event_list"]
    assert [e["seq"] for e in events] == list(range(1, 10))
    assert [e["kind"] for e in events] == [
        "begin", "thought", "thought", "look", "tool_error", "look", "thought", "answer_checklist", "submit_found"]
    thought = events[1]
    assert thought["summary"] == "Look ahead first." and thought["error"] is None and thought["photos"] == []
    assert thought["raw"] == {"request": None, "response": "Look ahead first."}
    assert events[2]["summary"] == "I will look ahead."


def test_tool_events_carry_args_result_photos_and_budget(explore):
    events = explore.get(S1).json()["event_list"]
    begin, look = events[0], events[3]
    assert begin["summary"] == "STOP s1: Stop s1" and begin["photos"] == [1, 2] and begin["photos_used"] == 2
    assert begin["raw"] == {"request": {}, "response": "STOP s1: Stop s1\nmore"}
    assert look["photos"] == [3] and look["photos_used"] == 3 and look["raw"]["request"] == {"from_m": 5}
    used = [e["photos_used"] for e in events]
    assert used == sorted(used) and used[-1] == 3
    assert events[4]["photos_used"] == 3  # carried over a refused call


def test_error_events(explore):
    events = explore.get(S1).json()["event_list"]
    refused, failed = events[4], events[5]
    assert refused["kind"] == "tool_error" and refused["error"] == "InputValidationError: photo must be an integer"
    assert refused["summary"] == "ERROR: InputValidationError: photo must be an integer"
    assert refused["raw"]["request"] == {"tool": "mcp__explorer__mark_clear", "photo": "two"}
    assert failed["kind"] == "look" and failed["error"] == "no panorama within 25 m"
    assert failed["summary"] == "ERROR: no panorama within 25 m" and failed["raw"]["response"] == failed["error"]


def test_events_without_transcript_are_the_record_events(explore, explore_settings):
    (explore_settings.agent_runs_dir / "s1_20261106T110000" / "transcript.jsonl").unlink()
    body = explore.get(S1).json()
    assert [e["kind"] for e in body["event_list"]] == ["begin", "look", "look", "answer_checklist", "submit_found"]
    assert body["report"] is None and body["model"] == "haiku"


def test_report_and_model_from_the_transcript(explore):
    body = explore.get(S1).json()
    assert body["report"] == "I found it.\nSecond line." and body["model"] == "claude-test-1"
    assert explore.get("/api/explorations/s3_20261106T130000").json()["model"] == "claude-test-1"


def test_photos_path_candidates_and_limits(explore):
    body = explore.get(S1).json()
    assert body["limits"] == {"along_from": -400.0, "along_to": 400.0}
    assert body["path"] == [[40.999, 11.999], [41.0, 12.0], [41.001, 12.001]]
    assert [p["index"] for p in body["photo_list"]] == [1, 2, 3]
    photo = body["photo_list"][0]
    assert photo["url"] == f"{S1}/photos/one.jpg"
    assert (photo["fov"], photo["pitch"], photo["along_m"], photo["right_m"]) == (100.0, 0.0, -5.0, 1.5)
    assert (photo["toward"], photo["copyright"], photo["date"]) == ("forward", None, "2025-06")
    assert [p["opening"] for p in body["photo_list"]] == [True, True, False]
    candidate = body["candidates"][0]
    assert candidate["along_m"] == 4.0 and candidate["right_m"] == 2.0 and candidate["status"] == "confirmed"
    assert candidate["evidence"] == "other_stop_sign" and candidate["basis"] == "triangulated"
    assert candidate["checklist"] == {"fermata_or_bus_text": "yes", "cotral_logo": "no", "shelter": "unsure"}


def test_positions_with_errors(explore):
    positions = {p["kind"]: p for p in explore.get(S1).json()["positions"]}
    assert set(positions) == {"gtfs", "places", "verified", "estimate"}
    assert positions["verified"]["error_m"] is None and positions["verified"]["label"] == "Verified"
    assert positions["places"]["error_m"] == pytest.approx(distance_m(41.0, 12.0004, 41.0, 12.0002))
    assert positions["estimate"]["label"] == "Submitted position"
    assert (positions["estimate"]["lat"], positions["estimate"]["lon"]) == (41.0001, 12.0)


def test_missing_truth_gives_null_errors_and_no_estimate_when_not_found(explore):
    body = explore.get("/api/explorations/s3_20261106T130000").json()
    assert body["err_gtfs_m"] is None and body["err_found_m"] is None
    assert [p["kind"] for p in body["positions"]] == ["gtfs", "places"]


def test_osm_features_within_200_m_of_gtfs_position(explore):
    features = explore.get(S1).json()["osm_features"]
    assert features == [
        {"id": "n1", "kind": "bus_stop", "lat": 41.0, "lon": 12.0005, "ref": "A1", "name": "Via Roma",
         "operator": "Cotral"},
        {"id": "n2", "kind": "shelter", "lat": 41.001, "lon": 12.0, "ref": "", "name": "Near", "operator": ""},
    ]


def test_missing_osm_store_gives_no_features(explore_settings, caplog):
    client = TestClient(create_app(replace(explore_settings, osm_store=explore_settings.osm_store.parent / "no.db")))
    with caplog.at_level("WARNING"):
        assert client.get(S1).json()["osm_features"] == []
        assert client.get(S2).json()["osm_features"] == []
    assert len([r for r in caplog.records if "no OSM store" in r.message]) == 1


def test_unknown_layout_is_422(explore):
    for run in ("odd", "broken"):
        assert explore.get(f"/api/explorations/{run}").status_code == 422


def test_unknown_or_malformed_run_is_404(explore):
    for run in ("nope", "bad%20id", "cache", "..", "%2e%2e", "..%2Fruns"):
        assert explore.get(f"/api/explorations/{run}").status_code == 404, run


def test_runs_are_read_on_every_request(explore, explore_settings):
    write_run(explore_settings.agent_runs_dir, "s4_20261106T140000", agent_record("s4", running=True))
    assert [r["run_id"] for r in explore.get("/api/explorations").json()][-1] == "s4_20261106T140000"
    (explore_settings.agent_runs_dir / "s2_20261106T120000" / "record.json").write_text(
        json.dumps(agent_record("s2")))
    assert explore.get(S2).json()["outcome"] == "found"


def test_photo_served_with_cache_header(explore):
    r = explore.get(f"{S1}/photos/one.jpg")
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "public, max-age=86400"


@pytest.mark.parametrize("path", [
    f"{S1}/photos/unlisted.jpg",             # on disk but not in the record
    f"{S1}/photos/two.jpg",                  # in the record but not on disk
    f"{S1}/photos/..%2F..%2Fsecret.jpg",
    f"{S1}/photos/..%2Frecord.json",
    f"{S1}/photos/%2e%2e",
    f"{S1}/photos/record.json",
    "/api/explorations/..%2Fs1_20261106T110000/photos/one.jpg",
    "/api/explorations/nope/photos/one.jpg",
    "/api/explorations/odd/photos/one.jpg",
])
def test_photo_404(explore, path):
    assert explore.get(path).status_code == 404


def test_photo_listed_with_a_path_outside_photos_is_404(explore, explore_settings):
    record = agent_record("s5")
    record["photos"][0]["file"] = "../../secret.jpg"
    write_run(explore_settings.agent_runs_dir, "evil", record)
    assert explore.get("/api/explorations/evil/photos/secret.jpg").status_code == 404


def test_missing_directory_gives_empty_list(explore_settings, tmp_path):
    client = TestClient(create_app(replace(explore_settings, agent_runs_dir=tmp_path / "absent")))
    assert client.get("/api/explorations").json() == []


def real_runs() -> list[Path]:
    return sorted(p for p in REAL_RUNS.glob("*/record.json")) if REAL_RUNS.is_dir() else []


@pytest.mark.skipif(not real_runs(), reason="no real agent run present")
def test_real_runs_convert(tmp_path):
    settings = Settings(
        agent_runs_dir=REAL_RUNS, images_dir=tmp_path / "none", score_sources={}, database=tmp_path / "r.sqlite3",
        shape_verdicts_db=tmp_path / "v.sqlite3", frontend_dist=tmp_path / "dist",
    )
    client = TestClient(create_app(settings))
    listed = client.get("/api/explorations").json()
    assert {r["run_id"] for r in listed} == {p.parent.name for p in real_runs()}
    for run in listed:
        body = client.get(f"/api/explorations/{run['run_id']}").json()
        used = [e["photos_used"] for e in body["event_list"]]
        assert used == sorted(used) and used[-1] <= len(body["photo_list"])
        budget = [e["budget_used"] for e in body["event_list"]]
        assert budget == sorted(budget) and budget[-1] <= run["budget_max"]
        assert [e["seq"] for e in body["event_list"]] == list(range(1, len(used) + 1))
        record = json.loads((REAL_RUNS / run["run_id"] / "record.json").read_text())
        assert run["harness"]["version"] != "unversioned" and run["tiles_max"] == record["budget"]["tiles"]
        assert run["billed_static"] is not None and run["start_kind"] in ("osm_ref", "osm_nearest", "places", "gtfs")
        for photo in body["photo_list"]:
            assert client.get(photo["url"]).status_code == 200
