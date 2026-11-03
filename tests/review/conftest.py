import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cotral_review.api import create_app
from cotral_review.catalog import CATEGORY_KEYS
from cotral_review.config import Settings

IDS = ["a1", "b2", "c3", "d4"]
JPEG = b"\xff\xd8fake-jpeg"


def make_images(root: Path, ids: list[str] = IDS) -> None:
    for i, stop_id in enumerate(ids):
        stop_dir = root / stop_id
        stop_dir.mkdir(parents=True)
        (stop_dir / "sweep_1_640x640.jpg").write_bytes(JPEG)
        (stop_dir / "unlisted.jpg").write_bytes(JPEG)
        (stop_dir / "stop.json").write_text(json.dumps({
            "stop": {"stop_id": stop_id, "name": f"Stop {stop_id}", "lat": 41.0 + i, "lon": 12.0},
            "imagery_date": "2025-06",
            "images": [{"view": "sweep_1", "file": "sweep_1_640x640.jpg",
                        "shot": {"distance_m": 24.0, "heading": 90.0, "pano": {"copyright": "© Google"}}}],
        }))


def write_scores(path: Path, ids: list[str], base: float) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["stop_id", "stop_name", *CATEGORY_KEYS])
        writer.writeheader()
        for i, stop_id in enumerate(ids):
            writer.writerow({"stop_id": stop_id, "stop_name": stop_id, **{k: base + i / 10 for k in CATEGORY_KEYS}})


def write_gemma_raw(raw_dir: Path, ids: list[str]) -> None:
    raw_dir.mkdir()
    for stop_id in ids:
        (raw_dir / f"{stop_id}.json").write_text(json.dumps({
            "stop": {"stop_id": stop_id},
            "arguments": {"shelter_evidence": f"shelter of {stop_id}", "sign_evidence": "sign seen"},
        }))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    make_images(tmp_path / "images")
    write_scores(tmp_path / "clef.csv", IDS, 1.0)
    write_scores(tmp_path / "gemma.csv", IDS[:3], 2.0)
    write_gemma_raw(tmp_path / "raw", IDS)
    return Settings(
        images_dir=tmp_path / "images",
        score_sources={"clef": tmp_path / "clef.csv", "gemma": tmp_path / "gemma.csv"},
        gemma_raw_dir=tmp_path / "raw",
        database=tmp_path / "review.sqlite3",
        frontend_dist=tmp_path / "dist",
        seed=1,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
