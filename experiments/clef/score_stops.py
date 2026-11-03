"""Score bus stop maintenance needs with mlx-community/clef-flash-8bit.

One model call per stop: all its photos and all questions together, so every
score uses evidence from every photo. Built for the full ~14k stops: results are
appended to a JSONL file one stop at a time, and stops already in it are skipped,
so a run can be stopped and resumed.

Scores are real numbers in [0, 4], the expected level under the model's
probabilities. For shelter, seating, signage and lighting, level 4 includes
"missing": a stop without them needs maintenance.

classifiable, in [0, 1], is the model's probability that the stop's sign is visible
in the photos: if the model cannot find the stop, its scores describe something
else. Stops below a threshold go to human review.

Usage: .venv/bin/python score_stops.py [image_dir] [--out scores.jsonl]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from huggingface_hub import snapshot_download
from PIL import Image

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
LEVELS = len(AREA_LEVELS)

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
CATEGORIES = [*ELEMENTS, *AREAS]

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


def load_stop(stop_dir: Path) -> tuple[dict, list[Path], list[str | None]]:
    """(manifest or {}, image paths, view names) in shot plan order when there is a manifest."""
    manifest_path = stop_dir / "stop.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        return manifest, [stop_dir / i["file"] for i in manifest["images"]], [i["view"] for i in manifest["images"]]
    images = sorted(stop_dir.glob("*.jpg"))
    return {}, images, [None] * len(images)


def state_for(manifest: dict, views: list[str | None]) -> dict:
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
        "stop_name": (manifest.get("stop") or {}).get("name"),
    }
    if any(views):
        state["photos"] = [f"Photo {i}: {VIEW_ROLES.get(v, v)}" for i, v in enumerate(views, 1)]
    return state


def summarise(answers: dict) -> dict:
    out = {k: answers[k]["score"] for k in [*CATEGORIES, "requires_maintenance"]}
    out["classifiable"] = answers["classifiable"]["noul"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", nargs="?", default="../../images")
    parser.add_argument("--out", default="scores.jsonl")
    parser.add_argument("--model", default="mlx-community/clef-flash-8bit")
    args = parser.parse_args()

    out = Path(args.out)
    done = {json.loads(line)["stop_id"] for line in out.read_text().splitlines()} if out.exists() else set()
    stop_dirs = [p for p in sorted(Path(args.image_dir).iterdir()) if p.is_dir() and p.name not in done]
    print(f"{len(done)} stops already scored, {len(stop_dirs)} to go", file=sys.stderr)

    path = snapshot_download(args.model)
    sys.path.insert(0, path)
    import clef_mlx

    model = clef_mlx.load(path)
    columns = [*CATEGORIES, "requires_maintenance", "classifiable"]
    print(f"{'stop':8} {'date':8} " + " ".join(f"{c[:11]:>11}" for c in columns) + "     time")

    with out.open("a") as f:
        for stop_dir in stop_dirs:
            manifest, paths, views = load_stop(stop_dir)
            if not paths:
                continue
            t0 = time.perf_counter()
            response = model.systemone({
                "model": "clef-flash",
                "state": state_for(manifest, views),
                "images": [Image.open(p).convert("RGB") for p in paths],
                "questions": QUESTIONS,
            })
            scores = summarise(response["answers"])
            latency = time.perf_counter() - t0
            f.write(json.dumps({
                "stop_id": stop_dir.name,
                "imagery_date": manifest.get("imagery_date"),
                "images": [p.name for p in paths],
                "input_tokens": response["usage"]["input_tokens"],
                "latency_s": round(latency, 2),
                "scores": scores,
                "raw": response["answers"],
            }, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{stop_dir.name:8} {manifest.get('imagery_date') or '-':8} "
                  + " ".join(f"{scores[c]:11.2f}" for c in columns)
                  + f"  {latency:5.1f}s ({response['usage']['input_tokens']} tokens)")


if __name__ == "__main__":
    main()
