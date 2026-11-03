"""Stops as the review tool sees them: manifest, photos, model scores and evidence.

Loaded once at startup into an immutable index; the data does not change while serving.
"""

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from cotral_maintenance.storage import MANIFEST_NAME

from .catalog import CATEGORY_KEYS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhotoFile:
    view: str
    file: str
    distance_m: float | None
    heading: float | None
    copyright: str | None


@dataclass
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float
    imagery_date: str | None
    photos: list[PhotoFile]
    # model key -> category key -> value
    scores: dict[str, dict[str, float]] = field(default_factory=dict)
    # model key -> category key -> one-sentence reason, where the model gives one
    evidence: dict[str, dict[str, str]] = field(default_factory=dict)

    def photo(self, file: str) -> PhotoFile | None:
        return next((p for p in self.photos if p.file == file), None)


class StopIndex:
    """All stops with a manifest, by stop id."""

    def __init__(self, stops: dict[str, Stop], models: list[str]) -> None:
        self._stops = dict(sorted(stops.items()))
        self.models = models

    def __len__(self) -> int:
        return len(self._stops)

    def __contains__(self, stop_id: object) -> bool:
        return stop_id in self._stops

    def get(self, stop_id: str) -> Stop | None:
        return self._stops.get(stop_id)

    def all(self) -> list[Stop]:
        return list(self._stops.values())

    def ids(self) -> list[str]:
        return list(self._stops)


def load_manifests(images_dir: Path) -> dict[str, Stop]:
    stops = {}
    for manifest_path in sorted(images_dir.glob(f"*/{MANIFEST_NAME}")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stop = manifest["stop"]
        photos = []
        for image in manifest["images"]:
            shot = image.get("shot") or {}
            photos.append(PhotoFile(
                view=image["view"], file=image["file"], distance_m=shot.get("distance_m"),
                heading=shot.get("heading"), copyright=(shot.get("pano") or {}).get("copyright"),
            ))
        stops[stop["stop_id"]] = Stop(
            stop_id=stop["stop_id"], name=stop["name"], lat=stop["lat"], lon=stop["lon"],
            imagery_date=manifest.get("imagery_date"), photos=photos,
        )
    return stops


def attach_scores(stops: dict[str, Stop], model: str, scores_csv: Path) -> bool:
    """Add one model's scores CSV (the phase 3 layout) to the stops it covers.
    Returns False when the file does not exist."""
    if not scores_csv.is_file():
        logger.warning("no scores for %s at %s", model, scores_csv)
        return False
    with scores_csv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            stop = stops.get(row["stop_id"])
            if stop is not None:
                stop.scores[model] = {k: float(row[k]) for k in CATEGORY_KEYS if row.get(k) not in (None, "")}
    return True


def attach_gemma_evidence(stops: dict[str, Stop], raw_dir: Path, model: str = "gemma") -> None:
    """Gemma's per-category reasons, from the raw records of experiments/gemma."""
    if not raw_dir.is_dir():
        return
    for path in sorted(raw_dir.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        stop, args = stops.get(record["stop"]["stop_id"]), record.get("arguments")
        if stop is None or not args:
            continue
        reasons = {k: args[f"{k}_evidence"] for k in CATEGORY_KEYS if f"{k}_evidence" in args}
        if "sign_evidence" in args:
            reasons["classifiable"] = args["sign_evidence"]
        stop.evidence[model] = reasons


def load_index(images_dir: Path, score_sources: dict[str, Path], gemma_raw_dir: Path) -> StopIndex:
    stops = load_manifests(images_dir)
    models = [m for m, path in score_sources.items() if attach_scores(stops, m, path)]
    if "gemma" in models:
        attach_gemma_evidence(stops, gemma_raw_dir)
    logger.info("loaded %d stops, models %s", len(stops), models)
    return StopIndex(stops, models)
