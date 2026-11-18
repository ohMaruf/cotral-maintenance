import sqlite3
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from cotral_maintenance.geo import distance_m
from cotral_maintenance.runstore import RunStore, RunStoreError
from cotral_review import config
from cotral_review.__main__ import main
from cotral_review.api import create_app
from cotral_review.run import open_run

from .conftest import IDS
from .explore_fixtures import NO_IMAGERY, NOT_FOUND, UNSCORED


def test_run_info_summarises_the_run(client):
    assert client.get("/api/run").json() == {
        "name": "r1", "stops": 7, "ingested": {"osm": 1, "places": 1}, "scored": 4,
        "explored": {"found": 5, "not_found": 1, "no_imagery": 1}, "billed": {"static": 6, "tiles": 40},
        "profiles": [{"key": "1", "name": "first", "description": "one"},
                     {"key": "2", "name": "second", "description": "two"},
                     {"key": "10", "name": "tenth", "description": "ten"}],
    }


def test_results_rank_the_worst_first_then_list_what_needs_review(client):
    rows = client.get("/api/results").json()
    assert [r["stop_id"] for r in rows] == ["d4", "c3", "b2", "a1", NOT_FOUND, NO_IMAGERY, UNSCORED]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, None, None, None]
    assert [r["needs_review"] for r in rows] == [False] * 4 + [True] * 3
    reasons = [r["review_reason"] for r in rows[4:]]  # the wording is export.py's
    assert reasons[0].startswith("the explorer did not find the stop") and "Street View" in reasons[1]
    assert reasons[2] == "not scored yet" and rows[0]["review_reason"] == ""
    worst = rows[0]
    assert (worst["priority"], worst["shelter"], worst["stop_visible"]) == (4.0, 1.0, 0.9)
    assert (worst["status"], worst["evidence"], worst["explorer_model"], worst["scorer_model"]) == (
        "found", "cotral_sign", "qwen3.8-27b", "imajev-4b")
    assert (worst["lat"], worst["lon"], worst["start_source"], worst["found_from_gtfs_m"]) == (
        pytest.approx(41.0031), 12.0, None, pytest.approx(distance_m(41.0, 12.0, 41.0031, 12.0), abs=0.1))
    assert (rows[3]["start_source"], rows[3]["start_lat"]) == ("osm", 41.0)


def test_results_include_the_stop_photos_as_urls(client):
    rows = {r["stop_id"]: r for r in client.get("/api/results").json()}
    assert len(rows["a1"]["photos"]) == 2 and rows[UNSCORED]["photos"] and rows[NOT_FOUND]["photos"] == []
    for url in rows["a1"]["photos"] + rows[UNSCORED]["photos"]:
        assert url.startswith("/api/explorations/") and client.get(url).status_code == 200
    assert rows[NOT_FOUND]["lat"] is None and rows[NOT_FOUND]["explore_reason"] == "call cap"


def test_results_of_a_run_without_scores(run_dir, settings):
    with RunStore(run_dir) as store:
        store.forget("score", store.stop_ids())
    client = TestClient(create_app(settings))
    assert client.get("/api/stops").json() == [] and client.get("/api/catalog").json()["models"] == []
    assert all(r["needs_review"] for r in client.get("/api/results").json())


def test_the_run_is_opened_read_only(run_dir):
    with open_run(run_dir) as run:
        assert run.summary()["stops"] == 7
        with pytest.raises(sqlite3.OperationalError):
            run.set_meta("x", 1)
    assert not list(run_dir.glob("run.sqlite-*"))  # no WAL or journal left behind


def test_the_database_file_is_not_modified(run_dir, settings):
    before = (run_dir / "run.sqlite").stat().st_mtime_ns, (run_dir / "run.sqlite").read_bytes()
    client = TestClient(create_app(settings))
    for path in ("/api/stops", "/api/results", "/api/run", "/api/explorations", "/api/explorations/a1"):
        assert client.get(path).status_code == 200
    after = (run_dir / "run.sqlite").stat().st_mtime_ns, (run_dir / "run.sqlite").read_bytes()
    assert before == after


def test_missing_run_is_refused_with_a_message(tmp_path, settings, capsys):
    with pytest.raises(RunStoreError, match="no run at .*nope"):
        create_app(replace(settings, run=tmp_path / "nope"))
    with pytest.raises(RunStoreError, match="--run runs/<RUN>"):
        create_app(replace(settings, run=None))
    with pytest.raises(SystemExit) as exit_:
        main(["serve", "--run", str(tmp_path / "nope"), "--database", str(tmp_path / "j.sqlite3")])
    assert exit_.value.code == 2 and "no run at" in capsys.readouterr().err


def test_a_run_of_another_schema_is_refused(run_dir):
    with sqlite3.connect(run_dir / "run.sqlite") as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RunStoreError, match="schema 99"):
        open_run(run_dir)


def test_run_setting_comes_from_the_environment_relative_to_the_repository(monkeypatch):
    monkeypatch.setenv("COTRAL_REVIEW_RUN", "runs/x")
    assert config.Settings.from_env().run == config.Path("runs/x")
    assert config.repo_path("runs/x") == config.REPO_ROOT / "runs" / "x"
    assert config.repo_path("/abs/runs/x") == config.Path("/abs/runs/x")
    monkeypatch.delenv("COTRAL_REVIEW_RUN")
    assert config.Settings.from_env().run is None
