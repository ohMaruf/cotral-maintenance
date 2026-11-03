"""Phase 3: score the maintenance needs of stops from their photos with Clef.

One model call per stop: all its photos and all questions together, so every
score uses evidence from every photo. Two steps, as in phase 1:
1. score: the request and the model's full answer are stored as-is, one file per
   stop. A stored file marks the stop as done, which makes runs resumable.
2. build: the scores dataset is derived from the raw files only.

Scores are real numbers in [0, 4], the expected level under the model's
probabilities. For shelter, seating, signage and lighting, level 4 includes
"missing": a stop without them needs maintenance.

classifiable, in [0, 1], is the model's probability that the stop's sign is visible
in the photos: if the model cannot find the stop, its scores describe something
else. Stops below a threshold go to human review.
"""

import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from PIL import Image

from .fileutils import RawStore
from .models import Stop
from .provenance import utc_now
from .storage import ImageStore

logger = logging.getLogger(__name__)

# Pinned: clef_mlx.py, which we run, comes from this repository.
MODEL_ID = "mlx-community/clef-flash-8bit"
MODEL_REVISION = "5a195dc147926b63b1d139691ed4480ca9f92c0e"

ELEMENT_LEVELS = [
    "Present and in good condition",
    "Present, minor issues: dirt, faded paint, light wear",
    "Present, moderate wear or damage that should be fixed",
    "Present, significant damage or deficiency",
    "Missing, broken or unusable",
]
AREA_LEVELS = [
    "Good: no maintenance needed",
    "Minor issues: dirt, litter, light wear",
    "Moderate problems that should be fixed",
    "Significant problems",
    "Severe: unsafe or unusable",
]

ELEMENTS = {
    "shelter": "the bus shelter (a covered structure where passengers wait)",
    "seating": "seating for waiting passengers (benches or seats)",
    "signage": "the Cotral bus stop sign (usually a blue sign on a pole, possibly with a timetable)",
    "lighting": "lighting at the stop (street lamps near the waiting area, or lights in the shelter)",
}
AREAS = {
    "waiting_area": "the waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown "
    "vegetation, standing space)",
    "accessibility": "accessibility (a proper raised platform or kerb, step-free access, even surfaces, no "
    "obstacles for wheelchairs or prams)",
}

VIEW_ROLES = {
    f"sweep_{i}": f"looks straight across the road at the stop's sidewalk, {where} along the road"
    for i, where in enumerate(
        ("about 24 m before the mapped stop position", "about 8 m before it", "about 8 m after it",
         "about 24 m after it"),
        start=1,
    )
}


def build_questions() -> dict:
    questions = {
        name: {"type": "score", "instructions": f"State of {what}?", "criteria": ELEMENT_LEVELS}
        for name, what in ELEMENTS.items()
    }
    questions.update({
        name: {"type": "score", "instructions": f"State of {what}?", "criteria": AREA_LEVELS}
        for name, what in AREAS.items()
    })
    questions["requires_maintenance"] = {
        "type": "score",
        "instructions": (
            "Overall, how much does this bus stop require maintenance or improvement? Count missing facilities "
            "and anything else visible at the stop (road surface, graffiti, vandalism, litter, drainage, "
            "vegetation, hazards)."
        ),
        "criteria": AREA_LEVELS,
    }
    questions["classifiable"] = {
        "type": "noul",
        # Literal on purpose: a question listing every way a stop can be unjudgeable
        # gave 0.14-0.34 on stops whose sign is plainly visible; this gives 0.44-0.80.
        "instructions": "Is there a blue bus stop sign on a pole on this sidewalk in any of the photos?",
    }
    return questions


QUESTIONS = build_questions()


@dataclass(frozen=True)
class StopScores:
    """One row of the scores dataset."""

    stop_id: str
    stop_name: str
    imagery_date: str | None
    shelter: float
    seating: float
    signage: float
    lighting: float
    waiting_area: float
    accessibility: float
    requires_maintenance: float
    classifiable: float
    image_count: int
    latency_s: float
    scored_at: str


class ScoreSource(Protocol):
    """What the rest of the package needs from the model; lets tests pass a fake."""

    def score(self, request: dict, images: list[Image.Image]) -> dict: ...


class ClefScorer:
    """Clef on the local GPU. Loading takes a few seconds and about 11 GB of memory."""

    def __init__(self) -> None:
        # Imported here: the other phases should not pay for loading MLX.
        from huggingface_hub import snapshot_download

        path = snapshot_download(MODEL_ID, revision=MODEL_REVISION)
        sys.path.insert(0, path)
        import clef_mlx

        self._model = clef_mlx.load(path)

    def score(self, request: dict, images: list[Image.Image]) -> dict:
        return self._model.systemone({**request, "images": images})


def build_request(stop: Stop, views: Sequence[str]) -> dict:
    state = {
        "task": (
            f"These {len(views)} street-level photos cover the sidewalk where a Cotral bus stop is mapped. The "
            "mapped position can be tens of metres off, so the stop may appear in any of them. Find it and "
            "judge it using all photos together. A stop on the far side of the road is a different stop: "
            "ignore it."
        ),
        "what_a_cotral_stop_looks_like": (
            "Cotral is the regional bus operator of Lazio, Italy. Its stops are marked by a blue sign on a pole, "
            "sometimes with a timetable panel, and may have a shelter and seating."
        ),
        "photo_artifacts": (
            "The photos are cut from Google Street View panoramas taken from a moving car. Blur, stitching "
            "seams, vertical objects that look sliced, bent or doubled, blurred faces and number plates, and "
            "parts of the camera car at the bottom are artifacts of the camera, not damage at the stop. Do "
            "not let them affect any score."
        ),
        "stop_name": stop.name,
        "photos": [f"Photo {i}: {VIEW_ROLES.get(view, view)}" for i, view in enumerate(views, 1)],
    }
    return {"model": "clef-flash", "state": state, "questions": QUESTIONS}


def score_stop(stop: Stop, source: ScoreSource, images: ImageStore, store: RawStore) -> None:
    """Score one stop from its downloaded images and store the result."""
    manifest = images.read_manifest(stop.stop_id)
    request = build_request(stop, [image["view"] for image in manifest["images"]])
    files = [image["file"] for image in manifest["images"]]
    photos = [Image.open(images.root / stop.stop_id / file).convert("RGB") for file in files]
    start = time.perf_counter()
    response = source.score(request, photos)
    latency = time.perf_counter() - start
    store.save(
        stop.stop_id,
        {
            "stop": asdict(stop),
            "model": {"id": MODEL_ID, "revision": MODEL_REVISION},
            "imagery_date": manifest["imagery_date"],
            "images": files,
            "request": request,
            "response": response,
            "latency_s": round(latency, 2),
            "scored_at": utc_now(),
        },
    )


def score_stops(stops: Sequence[Stop], source: ScoreSource, images: ImageStore, store: RawStore) -> int:
    """Score every stop in order. A stop that cannot be scored is logged and skipped,
    so that one bad image does not end a run of many hours."""
    scored = 0
    for index, stop in enumerate(stops, start=1):
        try:
            score_stop(stop, source, images, store)
        except (ValueError, OSError) as exc:
            logger.error("[%d/%d] Failed stop %s (%s): %s", index, len(stops), stop.stop_id, stop.name, exc)
            continue
        scored += 1
        logger.info("[%d/%d] Scored stop %s (%s)", index, len(stops), stop.stop_id, stop.name)
    return scored


def score_row(record: dict) -> StopScores:
    """Derive one dataset row from a raw record. Pure: same record, same row."""
    answers = record["response"]["answers"]
    scores = {name: round(answers[name]["score"], 3) for name in [*ELEMENTS, *AREAS, "requires_maintenance"]}
    return StopScores(
        stop_id=record["stop"]["stop_id"],
        stop_name=record["stop"]["name"],
        imagery_date=record["imagery_date"],
        **scores,
        classifiable=round(answers["classifiable"]["noul"], 3),
        image_count=len(record["images"]),
        latency_s=record["latency_s"],
        scored_at=record["scored_at"],
    )


def build_dataset(store: RawStore) -> list[StopScores]:
    return [score_row(record) for record in store.records()]
