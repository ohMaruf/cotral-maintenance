import csv
import io
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cotral_review.api import create_app
from cotral_review.config import Settings
from cotral_review.shapes import ShapeVerdictRepository

from .explore_fixtures import write_shape_check

URL = "/api/shape-check"


@pytest.fixture
def shape_settings(settings: Settings, tmp_path: Path) -> Settings:
    write_shape_check(tmp_path / "stops.json")
    return replace(settings, shape_check_json=tmp_path / "stops.json")


@pytest.fixture
def shapes(shape_settings: Settings) -> TestClient:
    return TestClient(create_app(shape_settings))


def put(client, stop_id="s1", **body):
    return client.put(f"{URL}/verdicts/{stop_id}", json={"verdict": "on_route", "note": "", **body})


def test_shape_check_is_served(shapes):
    body = shapes.get(URL).json()
    assert body["min_offset_m"] == 30.0 and [s["id"] for s in body["stops"]] == ["s1", "s2"]
    assert body["stops"][0]["routes"][0]["points"][0] == [41.0, 12.0]


def test_new_fields_are_served(shapes):
    s1, s2 = shapes.get(URL).json()["stops"]
    assert s1["flags"] == ["moved", "left_of_path"]
    assert [f["kind"] for f in s1["osm_features"]] == ["bus_stop", "future_kind"]
    r = s1["routes"][0]
    assert len(r["matched"]) == 2 and r["truth_path_m"] == 4.5 and r["truth_path_side"] == "left"
    assert s2["routes"][0]["matched"] is None and s2["routes"][0]["truth_path_side"] is None


@pytest.mark.parametrize("drop", ["flags", "osm_features"])
def test_stop_without_required_new_field_fails_loudly(shape_settings, tmp_path, drop):
    data = json.loads(shape_settings.shape_check_json.read_text())
    del data["stops"][0][drop]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        create_app(Settings(**{**vars(shape_settings), "shape_check_json": bad}))


def test_stop_with_empty_flags_fails_loudly(shape_settings, tmp_path):
    data = json.loads(shape_settings.shape_check_json.read_text())
    data["stops"][0]["flags"] = []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        create_app(Settings(**{**vars(shape_settings), "shape_check_json": bad}))


def test_missing_shape_check_is_404(shape_settings, tmp_path):
    client = TestClient(create_app(Settings(**{**vars(shape_settings), "shape_check_json": tmp_path / "absent.json"})))
    r = client.get(URL)
    assert r.status_code == 404 and r.json()["detail"].endswith("run experiments/explore/shape_check.py")
    assert client.get(f"{URL}/verdicts.csv").status_code == 404
    assert put(client).status_code == 404
    assert client.get(f"{URL}/verdicts").json() == []


def test_invalid_shape_check_fails_loudly(shape_settings, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"stops": []}')
    with pytest.raises(ValueError):
        create_app(Settings(**{**vars(shape_settings), "shape_check_json": bad}))


def test_put_get_and_upsert(shapes):
    assert shapes.get(f"{URL}/verdicts").json() == []
    first = put(shapes, rater="ann", note="fine").json()
    assert first["stop_id"] == "s1" and first["verdict"] == "on_route" and first["rater"] == "ann"
    assert first["updated_at"]
    second = put(shapes, verdict="off_route", note="no").json()
    assert second["verdict"] == "off_route" and second["rater"] is None
    put(shapes, stop_id="s2", verdict=None, note="just a note")
    rows = shapes.get(f"{URL}/verdicts").json()
    assert [(r["stop_id"], r["verdict"], r["note"]) for r in rows] == [
        ("s1", "off_route", "no"), ("s2", None, "just a note"),
    ]


def test_verdicts_persist_across_restarts(shape_settings):
    put(TestClient(create_app(shape_settings)))
    assert [v.stop_id for v in ShapeVerdictRepository(shape_settings.shape_verdicts_db).list()] == ["s1"]


def test_schema_version_is_tracked(shape_settings):
    ShapeVerdictRepository(shape_settings.shape_verdicts_db)
    with sqlite3.connect(shape_settings.shape_verdicts_db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_put_unknown_stop_is_404(shapes):
    assert put(shapes, stop_id="zzz").status_code == 404


@pytest.mark.parametrize("body", [
    {"verdict": "maybe", "note": ""},
    {"verdict": "on_route", "note": "x" * 2001},
    {"verdict": "on_route"},
    {"note": ""},
    {"verdict": "on_route", "note": "", "rater": "r" * 81},
])
def test_put_invalid_body_is_422(shapes, body):
    assert shapes.put(f"{URL}/verdicts/s1", json=body).status_code == 422


def test_note_of_2000_characters_is_accepted(shapes):
    assert put(shapes, note="x" * 2000).status_code == 200


def test_csv_export(shapes):
    put(shapes, verdict="off_route", note="line, with comma", rater="ann")
    r = shapes.get(f"{URL}/verdicts.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == "attachment; filename=shape_check_verdicts.csv"
    reader = csv.DictReader(io.StringIO(r.text))
    assert reader.fieldnames == ["stop_id", "offset_m", "verdict", "note", "closest_shape_m", "has_osm", "rater",
                                 "updated_at", "flags"]
    rows = list(reader)
    assert [row["stop_id"] for row in rows] == ["s1", "s2"]
    s1, s2 = rows
    assert (s1["offset_m"], s1["verdict"], s1["note"], s1["closest_shape_m"], s1["has_osm"], s1["rater"]) == (
        "80.0", "off_route", "line, with comma", "5.5", "1", "ann")
    assert s1["updated_at"]
    assert (s2["verdict"], s2["note"], s2["closest_shape_m"], s2["has_osm"], s2["rater"], s2["updated_at"]) == (
        "", "", "3.0", "0", "", "")
    assert (s1["flags"], s2["flags"]) == ("moved;left_of_path", "far_from_path")
