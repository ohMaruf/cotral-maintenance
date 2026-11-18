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


def score_row(stop_id, maintenance, visible=0.9, photos=()):
    return {"stop_id": stop_id, "photos": list(photos), "scorer": {"model": "imajev-4b"}, "shelter": 1.0,
            "seating": 1.0, "signage": 0.5, "lighting": 2.0, "waiting_area": 1.0, "accessibility": 2.0,
            "requires_maintenance": maintenance, "stop_visible": visible, "answers": {}, "seconds": 3.0}


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
    run.put_score(score_row("f1", 2.0, photos=[sha]))
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
    for stop_id, maintenance in (("f1", 1.0), ("f2", 3.0)):
        run.put_exploration(exploration(stop_id), [], [])
        run.put_score(score_row(stop_id, maintenance))
    run.put_exploration(exploration("f3", "not_found"), [], [])
    run.put_exploration(exploration("f4"), [], [])
    run.put_score(score_row("f4", 4.0, visible=0.2))
    out = rows(run)
    assert [(r["stop_id"], r.get("rank")) for r in out][:2] == [("f2", 1), ("f1", 2)]
    review = {r["stop_id"]: r["review_reason"] for r in out if r["needs_review"]}
    assert review == {"f3": "the explorer did not find the stop",
                      "f4": "the scorer does not see the stop in its photos"}
    path, n = write_results(run)
    assert n == 4 and "requires_maintenance" in open(path).readline()


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
