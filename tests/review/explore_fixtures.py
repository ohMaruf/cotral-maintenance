"""Builders of explore records, positions CSVs and a shape check for the tests."""

import csv
import json
from pathlib import Path


def photo(index: int, file: str, **extra) -> dict:
    return {
        "index": index, "pano_id": f"pano{index}", "date": "2025-06", "along": -5.0, "offset": 1.5, "heading": 90.0,
        "fov": 100.0, "pitch": 0.0, "toward": "forward", "file": f"photos/{file}", "lat": 41.0, "lon": 12.0, **extra,
    }


def event(seq: int, tool: str, result: str | None = "ok", args: dict | None = None, photos: list[str] | None = None,
          photos_used: int = 0, error: str | None = None) -> dict:
    return {
        "seq": seq, "at": f"2026-11-06T11:00:{seq:02d}+00:00", "tool": tool, "args": args or {},
        "result": None if error else result, "photos": photos or [], "photos_used": photos_used, "error": error,
    }


CHECKLIST = {"fermata_or_bus_text": "yes", "cotral_logo": "no", "shelter": "unsure"}


def agent_record(stop_id: str = "s1", outcome: dict | None = None, running: bool = False) -> dict:
    """A finished run: begin (two photos), a look, a rejected and a refused call, a checklist, a submission."""
    done = {"status": "found", "candidate": 1, "lat": 41.0001, "lon": 12.0, "evidence": "other_stop_sign"}
    events = [
        event(1, "begin", "STOP s1: Stop s1\nmore", photos=["photos/one.jpg", "photos/two.jpg"], photos_used=2),
        event(2, "look", "PHOTO 3: from the panorama", {"from_m": 5}, ["photos/three.jpg"], 3),
        event(3, "look", None, {"from_m": 900}, [], 3, error="no panorama within 25 m"),
        event(4, "answer_checklist", "Candidate 1 CONFIRMED\nbecause", {"candidate": 1}, [], 3),
        event(5, "submit_found", "Submitted.", {"candidate": 1}, [], 3),
    ]
    return {
        "layout": "agent-explorer/1",
        "stop": {"stop_id": stop_id, "name": f"Stop {stop_id}", "lat": 41.0, "lon": 12.0},
        "started_at": "2026-11-06T11:00:00+00:00", "saved_at": "2026-11-06T11:05:00+00:00",
        "limits": [-400.0, 400.0], "max_photos": 14, "path": [[40.999, 11.999], [41.0, 12.0], [41.001, 12.001]],
        "start_s": 10.0,
        "starts": [
            {"label": "Places", "kind": "places", "lat": 41.0, "lon": 12.0004, "along": 0.0, "offset": 3.0, "ref": ""},
            {"label": "GTFS", "kind": "gtfs", "lat": 41.0, "lon": 12.0, "along": 0.0, "offset": 3.0, "ref": ""},
        ],
        "hints": [], "others": [], "previous": None, "next": None, "panoramas": [], "cells": [],
        "photos": [photo(1, "one.jpg"), photo(2, "two.jpg", toward="across"), photo(3, "three.jpg", fov=60.0)],
        "candidates": [{
            "index": 1, "kind": "sign", "views": [[3, 90.0]], "lat": 41.0001, "lon": 12.0, "along": 4.0,
            "offset": 2.0, "status": "confirmed", "checklist": CHECKLIST, "plate_text": "",
            "evidence": "other_stop_sign", "basis": "triangulated",
        }],
        "events": events[:2] if running else events,
        "outcome": None if running else (outcome or done),
    }


def sweep_record(stop_id: str = "n1") -> dict:
    """A finished run of the sweep harness: the opening sweep, a zoom, a confirmation, a submission."""
    def sweep_photo(index: int, file: str, toward: str, shot: int) -> dict:
        return photo(index, file, toward=toward, shot=shot, width=1536, height=768, parent=None)

    def sweeps(used: int, photos_used: int, **kw) -> dict:
        return {"photos_used": photos_used, "sweeps_used": used, **kw}

    events = [
        {**event(1, "begin", "STOP n1: Stop n1\nmore", photos=["photos/s1a.jpg", "photos/s1b.jpg"]), **sweeps(1, 2)},
        {**event(2, "zoom", "PHOTO 3: zoom x8 into photo 1", {"photo": 1, "x": 700, "y": 300, "fov": 12.0},
                 ["photos/z.jpg"]), **sweeps(1, 3)},
        {**event(3, "sweep", None, {"from_m": 900}, error="no panorama within 25 m"), **sweeps(1, 3)},
        {**event(4, "confirm", "Candidate 1 CONFIRMED\nbecause", {"candidate": 1, "from_m": None}, ["photos/c.jpg"]),
         **sweeps(1, 4)},
        {**event(5, "submit_found", "Submitted.", {"candidate": 1}), **sweeps(1, 4)},
    ]
    return {
        **agent_record(stop_id),
        "max_photos": 12, "shots_used": 1,
        "budget": {"sweeps": 12, "zooms": 30, "confirms": 6, "used": {"sweeps": 1, "zooms": 1, "confirms": 1}},
        "shared": [{"a_from": 0.0, "a_to": 40.0, "b_from": 100.0, "b_to": 140.0, "opposite": True}],
        "photos": [
            sweep_photo(1, "s1a.jpg", "sweep_ahead", 1), sweep_photo(2, "s1b.jpg", "sweep_behind", 1),
            photo(3, "z.jpg", toward="zoom", fov=12.0, width=768, height=768, shot=0, parent=1),
            photo(4, "c.jpg", toward="confirm", fov=20.0, width=768, height=768, shot=0, parent=None),
        ],
        "candidates": [{
            "index": 1, "kind": "sign", "views": [[3, 90.0, 5.0]], "lat": 41.0001, "lon": 12.0, "along": 4.0,
            "offset": 2.0, "status": "confirmed", "checklist": CHECKLIST, "plate_text": "",
            "evidence": "other_stop_sign", "basis": "triangulated", "confirmer_note": "A blue Cotral pole.",
            "confirm_photo": 4,
        }],
        "events": events,
    }


def image_record(stop_id: str = "i1") -> dict:
    """A finished run of the images harness: two single-photo sweeps, a zoom, a confirmation without a photo,
    and the two stop photos the harness took on submit_found (one of them billed from the cache for free)."""
    def shoot(index: int, file: str, toward: str, **kw) -> dict:
        return photo(index, file, toward=toward, **{"width": 640, "height": 640, "billed": True, "shot": 0, "parent": None, **kw})

    def spent(images: int, photos: int, **kw) -> dict:
        return {"photos_used": photos, "budget_used": images, **kw}

    events = [
        {**event(1, "begin", "STOP i1: Stop i1\nmore", photos=["photos/a.jpg"]), **spent(1, 1)},
        {**event(2, "sweep", "PHOTO 2: sweep 2", {"facing": "behind"}, ["photos/b.jpg"]), **spent(2, 2)},
        {**event(3, "zoom", "PHOTO 3: zoom", {"photo": 1, "x": 5, "y": 5}, ["photos/z.jpg"]), **spent(3, 3)},
        {**event(4, "confirm", "Candidate 1 CONFIRMED\nbecause", {"candidate": 1}), **spent(3, 3)},
        {**event(5, "submit_found", "Submitted.", {"candidate": 1}, ["photos/p1.jpg", "photos/p2.jpg"]), **spent(3, 5)},
    ]
    return {
        **agent_record(stop_id),
        "max_photos": 14,
        "budget": {"unit": "images", "images": 12, "stop_photos": 2, "confirms": 6,
                   "used": {"images": 3, "sweeps": 2, "zooms": 1, "stop_photos": 2, "confirms": 1, "billed": 4}},
        "photos": [
            shoot(1, "a.jpg", "sweep_ahead", shot=1), shoot(2, "b.jpg", "sweep_behind", shot=2),
            shoot(3, "z.jpg", "zoom", parent=1, fov=12.0),
            shoot(4, "p1.jpg", "stop_photo", fov=70.0), shoot(5, "p2.jpg", "stop_photo", fov=60.0, billed=False),
        ],
        "candidates": [{
            "index": 1, "kind": "sign", "views": [[3, 90.0, 5.0]], "lat": 41.0001, "lon": 12.0, "along": 4.0,
            "offset": 2.0, "status": "confirmed", "checklist": CHECKLIST, "plate_text": "",
            "evidence": "other_stop_sign", "basis": "triangulated", "confirmer_note": "A blue Cotral pole.",
            "confirm_photo": 3,
        }],
        "events": events,
        "outcome": {"status": "found", "candidate": 1, "lat": 41.0001, "lon": 12.0, "evidence": "other_stop_sign",
                    "close_up": "photos/z.jpg", "stop_photos": ["photos/p1.jpg", "photos/p2.jpg"]},
    }


def tiles_record(stop_id: str = "t1", version: str = "0.6.0") -> dict:
    """A finished run of harness 0.6: aimed opening from an OSM ref start, a zoom and a look_from from tiles."""
    def view(index: int, file: str, toward: str, **kw) -> dict:
        return photo(index, file, toward=toward, **{"width": 640, "height": 640, "billed": True, **kw})

    def spent(images: int, photos: int, **kw) -> dict:
        return {"photos_used": photos, "budget_used": images, **kw}

    events = [
        {**event(1, "begin", "STOP t1: Stop t1\nmore", photos=["photos/a.jpg"]), **spent(1, 1)},
        {**event(2, "zoom", "PHOTO 2: zoom", {"photo": 1}, ["photos/z.jpg"]), **spent(2, 2)},
        {**event(3, "look_from", "PHOTO 3: from another panorama", {"candidate": 1}, ["photos/l.jpg"]), **spent(3, 3)},
    ]
    return {
        **agent_record(stop_id),
        "harness": {"version": version, "git_commit": "da028ea9b1837bcd18058fb5234c96e1dbb51146", "git_dirty": True,
                    "prompt_sha256": "ab" * 32, "explorer_model": "haiku", "confirmer_model": "haiku"},
        "billed_requests": {"static": 1, "tiles": 10},
        "starts": [
            {"label": "OSM", "kind": "osm_ref", "lat": 41.0, "lon": 12.0001, "along": 0.0, "offset": 3.0, "ref": "A1"},
            {"label": "GTFS", "kind": "gtfs", "lat": 41.0, "lon": 12.0, "along": 0.0, "offset": 3.0, "ref": ""},
        ],
        "budget": {"unit": "images", "images": 12, "stop_photos": 2, "tiles": 42, "confirms": 6,
                   "used": {"images": 3, "sweeps": 0, "zooms": 1, "look_froms": 1, "tiles": 10, "stop_photos": 0,
                            "confirms": 0, "billed": 1}},
        "photos": [
            view(1, "a.jpg", "aimed"),
            view(2, "z.jpg", "zoom", parent=1, fov=12.0, source="tiles", tiles=2, width=512, height=512),
            view(3, "l.jpg", "look_from", fov=30.0, source="tiles", tiles=8, billed=True),
        ],
        "candidates": [], "events": events,
        "outcome": {"status": "not_found", "reason": "call cap"},
    }


def _line(**kw) -> str:
    return json.dumps(kw)


def tool_use(id: str, name: str, **args) -> dict:
    return {"type": "tool_use", "id": id, "name": f"mcp__explorer__{name}", "input": args}


def transcript(report: str = "I found it.\nSecond line.") -> str:
    """init, thinking (one empty), text, tool calls (one refused before the explorer), the result line."""
    def assistant(*blocks: dict) -> str:
        return _line(type="assistant", message={"content": list(blocks)})

    def result(id: str, text: str, error: bool = False) -> str:
        block = {"type": "tool_result", "tool_use_id": id, "content": [{"type": "text", "text": text},
                                                                         {"type": "image", "source": {}}]}
        return _line(type="user", message={"content": [{**block, "is_error": True} if error else block]})

    return "\n".join([
        _line(type="system", subtype="init", model="claude-test-1"),
        _line(type="system", subtype="thinking_tokens", estimated_tokens=5),
        assistant({"type": "thinking", "thinking": ""}, tool_use("t1", "begin")),
        result("t1", "STOP s1"),
        assistant({"type": "thinking", "thinking": "Look ahead first."}),
        assistant({"type": "text", "text": "I will look ahead."}, tool_use("t2", "look", from_m=5)),
        result("t2", "PHOTO 3"),
        assistant(tool_use("t3", "mark_clear", photo="two")),
        result("t3", "InputValidationError: photo must be an integer", error=True),
        assistant(tool_use("t4", "look", from_m=900)),
        result("t4", "no panorama within 25 m", error=True),
        assistant({"type": "text", "text": "Checking the candidate."}, tool_use("t5", "answer_checklist", candidate=1)),
        result("t5", "Candidate 1 CONFIRMED"),
        assistant(tool_use("t6", "submit_found", candidate=1)),
        result("t6", "Submitted."),
        "{not json, a line being written",
        _line(type="result", result=report),
    ]) + "\n"


def write_run(runs: Path, name: str, record: dict, lines: str | None = None, config: dict | None = None,
              photos: tuple[str, ...] = ("one.jpg",)) -> Path:
    run = runs / name
    (run / "photos").mkdir(parents=True)
    (run / "record.json").write_text(json.dumps(record))
    if lines is not None:
        (run / "transcript.jsonl").write_text(lines)
    if config is not None:
        (run / "config.json").write_text(json.dumps(config))
    for photo_name in photos:
        (run / "photos" / photo_name).write_bytes(b"\xff\xd8fake-jpeg")
    return run


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
