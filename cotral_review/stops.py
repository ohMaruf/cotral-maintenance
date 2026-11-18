"""Stops as the review tool sees them: the run's scored stops, their photos, scores and evidence.

Loaded once at startup into an immutable index; the run does not change while serving.
"""

import json
import logging
from dataclasses import dataclass, field

from cotral_maintenance.runstore import SCORE_COLUMNS, RunStore

from .catalog import MODEL_KEY, evidence_text

logger = logging.getLogger(__name__)

PHOTO_DESCRIPTIONS = (
    "From the panorama that confirmed the stop",
    "From about 12 m before the stop",
)


@dataclass(frozen=True)
class PhotoFile:
    view: str
    description: str
    sha: str
    heading: float | None


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
    # model key -> category key -> short text
    evidence: dict[str, dict[str, str]] = field(default_factory=dict)

    def photo_shas(self) -> set[str]:
        return {p.sha for p in self.photos}


class StopIndex:
    """The scored stops, by stop id, in the run's order."""

    def __init__(self, stops: dict[str, Stop], model_label: str | None = None) -> None:
        self._stops = stops
        self.model_label = model_label
        self.models = [MODEL_KEY] if stops else []

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


def load_index(run: RunStore) -> StopIndex:
    taken = {(r["stop_id"], r["media"]): r for r in run.query(
        "SELECT stop_id, media, heading, date FROM photos WHERE toward = 'stop_photo'")}
    stops: dict[str, Stop] = {}
    label = None
    for r in run.query(
            "SELECT s.stop_id, s.name, s.gtfs_lat, s.gtfs_lon, st.lat AS start_lat, st.lon AS start_lon, "
            "e.lat, e.lon, e.scan_date, e.stop_photos, sc.scorer, sc.answers, "
            + ", ".join(f"sc.{c}" for c in SCORE_COLUMNS) +
            " FROM stops s JOIN scores sc USING (stop_id) LEFT JOIN starts st USING (stop_id) "
            "LEFT JOIN explorations e USING (stop_id) ORDER BY s.position"):
        stop_id = r["stop_id"]
        shas = json.loads(r["stop_photos"] or "[]")[:len(PHOTO_DESCRIPTIONS)]
        rows = [taken.get((stop_id, sha)) for sha in shas]
        photos = [PhotoFile(f"stop_photo_{i}", PHOTO_DESCRIPTIONS[i - 1], sha, row["heading"] if row else None)
                  for i, (sha, row) in enumerate(zip(shas, rows), 1)]
        date = r["scan_date"] or next((row["date"] for row in rows if row and row["date"]), None)
        lat, lon = next(((a, b) for a, b in ((r["lat"], r["lon"]), (r["start_lat"], r["start_lon"]),
                                            (r["gtfs_lat"], r["gtfs_lon"])) if a is not None))
        answers = json.loads(r["answers"])
        stops[stop_id] = Stop(
            stop_id=stop_id, name=r["name"], lat=lat, lon=lon, imagery_date=date, photos=photos,
            scores={MODEL_KEY: {c: r[c] for c in SCORE_COLUMNS if r[c] is not None}},
            evidence={MODEL_KEY: {c: text for c in SCORE_COLUMNS
                                  if isinstance(answers.get(c), dict) and (text := evidence_text(answers[c]))}},
        )
        label = label or json.loads(r["scorer"]).get("model")
    logger.info("loaded %d scored stops", len(stops))
    return StopIndex(stops, label)
