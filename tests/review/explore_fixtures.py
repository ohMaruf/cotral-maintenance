"""Builders of a small run store (stops, explorations, photos, scores) and of a shape check for the tests."""

import csv
import json
from pathlib import Path

from cotral_maintenance.runstore import SCORE_COLUMNS, RunStore

JPEG = b"\xff\xd8fake-jpeg"
IDS = ["a1", "b2", "c3", "d4"]  # found and scored
UNSCORED = "g7"  # found, not scored yet
NOT_FOUND = "e5"
NO_IMAGERY = "f6"
ANSWER = {"unknown_probability": 0.234, "confidence": 0.41, "abstained": False}


def photo_record(index: int, sha: str, toward: str, **extra) -> dict:
    return {"index": index, "pano_id": f"pano{index}", "date": "2025-06", "along": -5.0, "offset": 1.5,
            "heading": 90.0, "fov": 100.0, "pitch": 0.0, "toward": toward, "file": sha, "lat": 41.0, "lon": 12.0,
            "width": 640, "height": 640, "billed": True, "shot": 0, "parent": None, **extra}


def event(seq: int, tool: str, result: str | None = "ok", args: dict | None = None, photos: list[str] | None = None,
          photos_used: int = 0, budget_used: int = 0, error: str | None = None) -> dict:
    return {"seq": seq, "at": f"2026-11-06T11:00:{seq:02d}+00:00", "tool": tool, "args": args or {},
            "result": None if error else result, "photos": photos or [], "photos_used": photos_used,
            "budget_used": budget_used, "error": error}


def turn(n: int, content: str | None = None, reasoning: str | None = None, tools: tuple[str, ...] = ()) -> dict:
    return {"turn": n, "seconds": 1.5, "finish": "tool_calls" if tools else "stop", "usage": {}, "timings": {},
            "reasoning": reasoning, "content": content,
            "tool_calls": [{"name": t, "arguments": "{}"} for t in tools]}


def found_stop(store: RunStore, stop_id: str, lat: float = 41.0001, lon: float = 12.0) -> None:
    """A finished exploration: begin (one photo), a refused look, submit_found with two stop photos."""
    search = store.put_media(JPEG + f"search-{stop_id}".encode())
    close = [store.put_media(JPEG + f"{stop_id}-{n}".encode()) for n in (1, 2)]
    photos = [photo_record(1, search, "sweep_ahead", shot=1), photo_record(2, close[0], "stop_photo", fov=70.0),
              photo_record(3, close[1], "stop_photo", fov=60.0, billed=False, heading=70.0)]
    events = [
        event(1, "begin", "STOP s1: Stop\nmore", photos=[search], photos_used=1, budget_used=1),
        event(2, "look", None, {"from_m": 900}, photos_used=1, budget_used=1, error="no panorama within 25 m"),
        event(3, "submit_found", "Submitted.", {"candidate": 1}, photos=close, photos_used=3, budget_used=1),
    ]
    record = {
        "layout": "agent-explorer/1", "harness": {"version": "0.11.1"}, "billed_requests": {"static": 2, "tiles": 8},
        "stop": {"stop_id": stop_id, "name": f"Stop {stop_id}", "lat": 41.0, "lon": 12.0},
        "limits": [-400.0, 400.0], "max_photos": 14, "path": [[40.999, 11.999], [41.0, 12.0], [41.001, 12.001]],
        "starts": [{"label": "OSM", "kind": "osm_ref", "lat": 41.0, "lon": 12.0001, "along": 0.0, "offset": 3.0,
                    "ref": "A1"}],
        "budget": {"unit": "images", "images": 12, "stop_photos": 2, "tiles": 42, "confirms": 6,
                   "used": {"images": 1, "sweeps": 1, "zooms": 0, "look_froms": 0, "tiles": 8, "stop_photos": 2,
                            "confirms": 1, "billed": 2}},
        "photos": photos,
        "candidates": [{"index": 1, "kind": "sign", "lat": lat, "lon": lon, "along": 4.0, "offset": 2.0,
                        "status": "confirmed", "checklist": {"cotral_logo": "no"}, "evidence": "cotral_sign",
                        "basis": "triangulated", "confirmer_note": "A blue pole.", "confirm_photo": 1}],
        "events": events,
        "outcome": {"status": "found", "candidate": 1, "lat": lat, "lon": lon, "evidence": "cotral_sign",
                    "close_up": search, "stop_photos": close},
    }
    transcript = [
        turn(1, "I will begin.", "Look first.", ("begin",)), {"turn": 1, "tool": "begin", "result": "STOP", "images": []},
        turn(2, None, None, ("look",)), {"turn": 2, "tool": "look", "result": "ERROR: no panorama", "images": []},
        {"confirm": 1, "attempt": 1, "photo": "x.jpg", "status": "confirmed"},
        turn(3, "Submitting.", None, ("submit_found",)), {"turn": 3, "tool": "submit_found", "result": "Submitted.", "images": []},
        turn(4, "I found it.\nSecond line."),
    ]
    row = {"stop_id": stop_id, "status": "found", "reason": "the explorer ended: outcome", "lat": lat, "lon": lon,
           "position_basis": "triangulated", "evidence": "cotral_sign", "scan_date": "2025-06", "stop_photos": close,
           "explorer": {"model": "qwen3.8-27b", "confirmer": "same model, fresh call"},
           "harness": {"version": "0.11.1", "prompt_sha256": "ab" * 32, "git": {"commit": "da028ea", "dirty": True}},
           "billed_static": 2, "billed_tiles": 8, "turns": 4, "seconds": 61.5,
           "started_at": "2026-11-06T11:00:00+00:00", "finished_at": "2026-11-06T11:01:01+00:00", "record": record}
    store.put_exploration(row, [{"idx": p["index"], "media": p["file"], "toward": p["toward"], "pano_id": p["pano_id"],
                                 "date": "2025-06", "heading": p["heading"], "fov": p["fov"], "pitch": 0.0,
                                 "width": 640, "height": 640, "lat": 41.0, "lon": 12.0} for p in photos],
                          transcript)


def without_search(store: RunStore, stop_id: str, status: str, reason: str) -> None:
    store.put_exploration(
        {"stop_id": stop_id, "status": status, "reason": reason, "explorer": {"model": "qwen3.8-27b"},
         "harness": {"version": "0.11.1"}, "billed_static": 0, "billed_tiles": 0, "turns": 0, "seconds": 0.5,
         "started_at": "t0", "finished_at": "t1", "record": {"outcome": {"status": status, "reason": reason}}},
        [], [])


def score(store: RunStore, stop_id: str, maintenance: float, visible: float = 0.9) -> None:
    exploration = store.exploration(stop_id)
    store.put_score({
        "stop_id": stop_id, "photos": exploration["stop_photos"], "scorer": {"model": "imajev-4b"},
        **{c: 1.0 for c in SCORE_COLUMNS}, "requires_maintenance": maintenance, "stop_visible": visible,
        "answers": {c: ANSWER for c in SCORE_COLUMNS if c != "signage"} | {"signage": {**ANSWER, "abstained": True}},
        "seconds": 3.0})


def build_run(root: Path) -> Path:
    """Seven stops: four found and scored (maintenance 1.0 for a1 .. 4.0 for d4), one found and not scored, two failed."""
    store = RunStore(root, create=True)
    ids = [*IDS, NOT_FOUND, NO_IMAGERY, UNSCORED]
    store.add_stops([{"stop_id": i, "name": f"Stop {i}", "gtfs_lat": 41.0, "gtfs_lon": 12.0,
                      "services": [{"shape_id": "s1", "trips": 3, "previous": [], "next": []}]} for i in ids])
    store.put_start({"stop_id": "a1", "source": "osm", "lat": 41.0, "lon": 12.0001, "osm": {"osm_id": "n1"}})
    store.put_start({"stop_id": "b2", "source": "places", "lat": 41.0, "lon": 12.0004, "places": {"status": "ok"}})
    for i, stop_id in enumerate(IDS):
        found_stop(store, stop_id, lat=41.0001 + i / 1000)
        score(store, stop_id, 1.0 + i)
    found_stop(store, UNSCORED)
    without_search(store, NOT_FOUND, "not_found", "call cap")
    without_search(store, NO_IMAGERY, "no_imagery", "no Street View from 2024 on along the path")
    store.add_usage("2026-11", "k1", "static", 6)
    store.add_usage("2026-11", "k1", "tiles", 40)
    store.set_meta("profile:2", {"name": "second", "description": "two"})
    store.set_meta("profile:10", {"name": "tenth", "description": "ten"})
    store.set_meta("profile:1", {"name": "first", "description": "one"})
    store.close()
    return root


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def route(truth_m: float) -> dict:
    return {
        "shape": "7785", "trips": 3, "points": [[41.0, 12.0], [41.1, 12.1]],
        "arrows": [{"lat": 41.05, "lon": 12.05, "bearing": 45}], "truth_m": truth_m, "truth_side": "right",
        "gtfs_m": 9.0, "prev": [], "next": ["s2"],
        "matched": [[[41.0, 12.0], [41.05, 12.05]], [[41.06, 12.06], [41.1, 12.1]]],
        "truth_path_m": 4.5, "truth_path_side": "left",
    }


def osm_feature(kind: str = "bus_stop", lon: float = 12.001) -> dict:
    return {"id": "n1", "kind": kind, "lat": 41.0, "lon": lon, "ref": "A1", "name": "Via Roma", "operator": ""}


def shape_stop(
    stop_id: str, offset_m: float, routes: list[dict],
    flags: list[str] | None = None, osm_features: list[dict] | None = None,
) -> dict:
    return {
        "id": stop_id, "name": f"Stop {stop_id}", "offset_m": offset_m, "flags": flags or ["moved"],
        "osm_features": osm_features or [], "has_sign": "yes", "comments": "",
        "gtfs": [41.0, 12.0], "truth": [41.0, 12.001], "places": None, "routes": routes,
        "neighbours": [{"id": "s9", "name": "Other", "lat": 41.0, "lon": 12.0}],
    }


def write_shape_check(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": "2026-11-07T10:00:00Z", "min_offset_m": 30.0,
        "stops": [
            shape_stop("s1", 80.0, [route(12.0), route(5.5)], 
                       flags=["moved", "left_of_path"], osm_features=[osm_feature(), osm_feature("future_kind", 12.0)]),
            shape_stop("s2", 40.0, [{**route(3.0), "matched": None, "truth_path_m": None, "truth_path_side": None}],
                       flags=["far_from_path"]),
        ],
    }))
