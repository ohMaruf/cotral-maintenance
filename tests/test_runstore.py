import json

import pytest

from cotral_maintenance.pipeline.bundle import bundle, unbundle
from cotral_maintenance.pipeline.explore import _rewrite
from cotral_maintenance.pipeline.export import rows, write_results
from cotral_maintenance.runstore import RunStore, RunStoreError, media_path

STOPS = [{"stop_id": f"f{i}", "name": f"Stop {i}", "gtfs_lat": 41.9 + i / 1000, "gtfs_lon": 12.5,
          "services": [{"shape_id": "s1", "trips": 3, "previous": [], "next": []}]} for i in range(1, 5)]


def exploration(stop_id, status="found", photos=()):
    return {"stop_id": stop_id, "status": status, "reason": None if status == "found" else "stalled",
            "lat": 41.9 if status == "found" else None, "lon": 12.5 if status == "found" else None,
            "evidence": "cotral_sign" if status == "found" else None, "stop_photos": list(photos),
            "explorer": {"model": "qwen3.8-27b"}, "harness": {"version": "0.11.1"}, "billed_static": 5,
            "billed_tiles": 8, "turns": 7, "seconds": 120.0, "started_at": "t0", "finished_at": "t1",
            "record": {"outcome": {"status": status}}}


def photo_row(idx, sha):
    return {"idx": idx, "media": sha, "toward": "stop_photo", "pano_id": "p", "date": "2025-04", "heading": 90.0,
            "fov": 50.0, "pitch": 0.0, "width": 640, "height": 640, "lat": 41.9, "lon": 12.5}


@pytest.fixture
def run(tmp_path):
    store = RunStore(tmp_path / "runs" / "r1", create=True)
    store.add_stops(STOPS)
    yield store
    store.close()


def score_row(stop_id, condition, visible=0.9, photos=()):
    return {"stop_id": stop_id, "photos": list(photos), "scorer": {"model": "imajev-4b"}, "condition": condition,
            "has_shelter": 0.1, "shelter": None, "has_seating": 0.9, "seating": 0.75, "waiting_area": 0.75,
            "accessibility": 0.5, "has_lamp": 0.8, "stop_visible": visible, "answers": {}, "seconds": 3.0}


def test_missing_run_is_refused(tmp_path):
    with pytest.raises(RunStoreError):
        RunStore(tmp_path / "nope")


def test_stops_keep_their_order_and_are_added_once(run):
    assert run.add_stops(STOPS[:2]) == 0
    assert run.stop_ids() == ["f1", "f2", "f3", "f4"]
    assert run.stop("f2")["services"][0]["shape_id"] == "s1"


def test_pending_follows_each_phase(run):
    run.put_start({"stop_id": "f1", "source": "osm", "lat": 1.0, "lon": 2.0, "osm": {"osm_id": "n1"}})
    assert run.pending("ingest") == ["f2", "f3", "f4"]
    assert run.start("f1")["osm"] == {"osm_id": "n1"}
    run.put_exploration(exploration("f1"), [], [])
    assert run.pending("explore", ["f1", "f2"]) == ["f2"]


def test_media_is_content_addressed(run):
    a = run.put_media(b"jpeg-bytes")
    assert run.put_media(b"jpeg-bytes") == a
    assert media_path(run.root, a).read_bytes() == b"jpeg-bytes"


def test_exploration_replaces_older_results_and_forget_cascades(run):
    sha = run.put_media(b"x")
    run.put_exploration(exploration("f1", photos=[sha]), [photo_row(1, sha)], [{"turn": 1}])
    run.put_score(score_row("f1", 0.5, photos=[sha]))
    run.put_exploration(exploration("f1", "not_found"), [], [])  # explored again: the old score goes
    assert run.query("SELECT COUNT(*) FROM scores")[0][0] == 0
    assert run.query("SELECT COUNT(*) FROM photos")[0][0] == 0
    run.forget("explore", ["f1"])
    assert run.exploration("f1") is None


def test_usage_accumulates(run):
    run.add_usage("2026-11", "k1", "static", 3)
    run.add_usage("2026-11", "k1", "static", 4)
    assert run.summary()["billed"] == {"static": 7}


def test_results_rank_scored_stops_and_list_the_rest_for_review(run):
    for stop_id, condition in (("f1", 0.7), ("f2", 0.2)):
        run.put_exploration(exploration(stop_id), [], [])
        run.put_score(score_row(stop_id, condition))
    run.put_exploration(exploration("f3", "not_found"), [], [])
    run.put_exploration(exploration("f4"), [], [])
    run.put_score(score_row("f4", 0.1, visible=0.2))
    out = rows(run)
    assert [(r["stop_id"], r.get("rank")) for r in out][:2] == [("f2", 1), ("f1", 2)]  # worst condition first
    assert out[0]["missing"] == "shelter"
    review = {r["stop_id"]: r["review_reason"] for r in out if r["needs_review"]}
    assert review == {"f3": "the explorer did not find the stop (stalled)",
                      "f4": "the scorer does not see the stop in its photos"}
    path, n = write_results(run)
    assert n == 4 and "condition" in open(path).readline()


def test_bundle_round_trip_with_only_stop_photos(tmp_path, run):
    stop_photo, search_photo = run.put_media(b"stop"), run.put_media(b"search")
    run.put_exploration(exploration("f1", photos=[stop_photo]), [photo_row(1, search_photo), photo_row(2, stop_photo)],
                        [])
    root = run.root
    run.close()
    archive, n = bundle(root, tmp_path / "r1.tar.zst", media="stop")
    assert n == 1
    target = unbundle(archive, tmp_path / "elsewhere")
    assert media_path(target, stop_photo).is_file() and not media_path(target, search_photo).exists()
    with RunStore(target) as copy:
        assert copy.exploration("f1")["stop_photos"] == [stop_photo]
    with pytest.raises(FileExistsError):
        unbundle(archive, tmp_path / "elsewhere")


def test_record_paths_become_media_hashes():
    shas = {"photos/01_a.jpg": "aaa", "maps/map_001.png": "mmm"}
    record = {"photos": [{"file": "photos/01_a.jpg"}], "events": [{"photos": ["maps/map_001.png", "other"]}],
              "outcome": {"stop_photos": ["photos/01_a.jpg"], "close_up": None}}
    out = json.loads(json.dumps(record), object_hook=lambda d: _rewrite(d, shas))
    assert out["photos"][0]["file"] == "aaa"
    assert out["events"][0]["photos"] == ["mmm", "other"]
    assert out["outcome"]["stop_photos"] == ["aaa"]


@pytest.mark.parametrize("old", [1, 2])
def test_older_runs_keep_their_explorations_and_lose_their_scores(tmp_path, old):
    import sqlite3

    root = tmp_path / "old"
    store = RunStore(root, create=True)
    store.add_stops(STOPS[:1])
    store.put_exploration(exploration("f1"), [], [])
    store.close()
    with sqlite3.connect(root / "run.sqlite") as conn:  # an older run's scores table
        conn.executescript("DROP TABLE scores; CREATE TABLE scores (stop_id TEXT, priority REAL);"
                           f"INSERT INTO scores VALUES ('f1', 3.0); PRAGMA user_version={old};")
    with RunStore(root) as upgraded:
        assert upgraded.exploration("f1")["status"] == "found"
        assert upgraded.query("SELECT COUNT(*) FROM scores")[0][0] == 0
        upgraded.put_score(score_row("f1", 0.4))


def test_rows_carry_the_version_and_invocation_that_made_them(run):
    from cotral_maintenance.pipeline.export import versions

    seq = run.begin_invocation({}, {}, {})
    run.add_version("aaa", {"phase": "explore", "harness": {"version": "1"}}, seq)
    run.stamp["explore"] = ("aaa", seq)
    run.put_exploration(exploration("f1"), [], [])
    run.stamp["explore"] = ("bbb", seq)
    run.put_exploration(exploration("f2"), [], [])
    row = run.query("SELECT version, invocation FROM explorations WHERE stop_id = 'f1'")[0]
    assert (row["version"], row["invocation"]) == ("aaa", seq)
    assert run.versions_in("explore") == {"aaa": 1, "bbb": 1}
    assert run.versions_summary()["explore"] == {"rows": {"aaa": 1, "bbb": 1}, "mixed": True}
    assert versions(run)["versions"]["aaa"]["detail"]["harness"] == {"version": "1"}


def test_schema_3_explorations_get_their_version_back(tmp_path):
    import sqlite3

    from cotral_maintenance.versions import explore_detail, fingerprint

    root = tmp_path / "old"
    with RunStore(root, create=True) as store:
        store.add_stops(STOPS[:1])
        store.put_exploration(exploration("f1"), [], [])
        e = store.exploration("f1")
    with sqlite3.connect(root / "run.sqlite") as conn:
        conn.executescript("UPDATE explorations SET version = NULL; PRAGMA user_version=3;")
    with RunStore(root) as upgraded:
        expected = fingerprint(explore_detail(e["harness"], e["explorer"]))
        assert upgraded.versions_in("explore") == {expected: 1}
        assert upgraded.version_details()[expected]["phase"] == "explore"


def test_versions_ignore_speed_settings_and_git():
    from cotral_maintenance.versions import explore_detail, fingerprint

    a = explore_detail({"version": "1", "git": {"commit": "x"}}, {"model": "m", "concurrency": 1,
                                                                   "server": {"port": 8080, "args": ["-c", "1"]}})
    b = explore_detail({"version": "1", "git": {"commit": "y"}}, {"model": "m", "concurrency": 2,
                                                                   "server": {"port": 9000, "args": ["-c", "1"]}})
    c = explore_detail({"version": "2"}, {"model": "m", "server": {"args": ["-c", "1"]}})
    assert fingerprint(a) == fingerprint(b) != fingerprint(c)


def test_merge_takes_a_found_row_over_a_failed_one_and_else_the_later_run(tmp_path):
    from cotral_maintenance.pipeline.merge import MergeError, merge

    runs = tmp_path / "runs"
    first, second = RunStore(runs / "a", create=True), RunStore(runs / "b", create=True)
    first.add_stops(STOPS[:3])
    second.add_stops([STOPS[1], STOPS[2], STOPS[0], STOPS[3]])
    old, new = first.put_media(b"old photo"), second.put_media(b"new photo")
    first.put_exploration(exploration("f1"), [], [])
    first.put_exploration(exploration("f2", "not_found"), [], [])
    first.put_exploration(exploration("f3", photos=[old]), [photo_row(1, old)], [{"turn": 1}])
    first.put_score(score_row("f3", 0.3, photos=[old]))
    second.put_exploration(exploration("f1", "not_found"), [], [])
    second.put_exploration(exploration("f2", photos=[new]), [photo_row(1, new)], [{"turn": 2}])
    second.put_exploration(exploration("f3", photos=[new]), [photo_row(1, new)], [])
    second.put_exploration(exploration("f4"), [], [])
    first.add_usage("2026-11", "k", "static", 3)
    second.add_usage("2026-11", "k", "static", 4)
    first.close()
    second.close()

    summary = merge(runs / "m", [runs / "a", runs / "b"])
    assert summary["stops"] == 4 and summary["found"] == 4 and summary["from"] == {"a": 1, "b": 3}
    with RunStore(runs / "m") as m:
        assert m.stop_ids() == ["f1", "f2", "f3", "f4"]
        assert m.exploration("f1")["status"] == "found"
        assert m.exploration("f2")["stop_photos"] == [new] and media_path(runs / "m", new).is_file()
        assert m.exploration("f3")["stop_photos"] == [new]
        assert m.query("SELECT COUNT(*) FROM scores")[0][0] == 0
        assert m.summary()["billed"] == {"static": 7}
    assert (runs / "m" / "results.csv").is_file()
    with pytest.raises(MergeError, match="already exists"):
        merge(runs / "m", [runs / "a", runs / "b"])
    with pytest.raises(MergeError, match="no run"):
        merge(runs / "n", [runs / "a", runs / "missing"])
    assert not (runs / "n").exists()


def test_merge_never_loses_an_exploration_to_a_run_that_did_not_finish_it(tmp_path):
    from cotral_maintenance.pipeline.merge import merge

    runs = tmp_path / "runs"
    first, second = RunStore(runs / "a", create=True), RunStore(runs / "b", create=True)
    first.add_stops(STOPS[:2])
    second.add_stops(STOPS[:2])
    first.put_exploration(exploration("f1", "not_found"), [], [])
    first.put_exploration(exploration("f2", "not_found"), [], [])
    second.put_exploration({**exploration("f2", "not_found"), "status": "error", "reason": "server down"}, [], [])
    first.close()
    second.close()
    merge(runs / "m", [runs / "a", runs / "b"])
    with RunStore(runs / "m") as m:
        assert m.exploration("f1")["status"] == "not_found"
        assert m.exploration("f2")["status"] == "not_found"


def test_merge_copies_every_image_a_stop_refers_to(tmp_path):
    from cotral_maintenance.pipeline.merge import merge

    runs = tmp_path / "runs"
    first, second = RunStore(runs / "a", create=True), RunStore(runs / "b", create=True)
    first.add_stops(STOPS[:1])
    second.add_stops(STOPS[1:2])
    piece, aerial = first.put_media(b"scan piece"), first.put_media(b"map")
    first.put_exploration({**exploration("f1"), "record": {"aerial": aerial, "scans": [{"pieces": [{"file": piece}]}]}},
                          [], [])
    second.put_exploration(exploration("f2"), [], [])
    first.close()
    second.close()
    merge(runs / "m", [runs / "a", runs / "b"])
    assert media_path(runs / "m", piece).is_file() and media_path(runs / "m", aerial).is_file()
