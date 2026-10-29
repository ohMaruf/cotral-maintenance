"""Score bus stop maintenance needs with mlx-community/clef-flash-8bit.

Each stop directory (images/<stop_id>/*.jpg) is scored jointly: all its photos go into one request.
With --per-image, every photo is also scored on its own for comparison.

Scores are expected values over 5 severity levels, so they are real numbers in [0, 4]:
0 = no maintenance needed ... 4 = severe. "<category>_visible" is the probability that the
element is visible in the photos at all, to tell "fine" apart from "not shown".

Usage: .venv/bin/python score_stops.py [image_dir] [--per-image] [--out scores.json]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from huggingface_hub import snapshot_download
from PIL import Image

SEVERITY = [
    "No maintenance needed: in good condition",
    "Minor: small cosmetic issues (dirt, faded paint, light wear)",
    "Moderate: visible wear or damage that should be fixed",
    "Significant: clearly damaged, deficient or partly missing",
    "Severe: broken, missing, unsafe or unusable",
]

CATEGORIES = {
    "shelter": "the bus shelter (roof, panels, frame, glass). A stop that clearly has no shelter counts as deficient.",
    "seating": "seating for waiting passengers (benches, seats). A stop that clearly has no seating counts as deficient.",
    "signage": "bus stop signage (stop pole, stop sign, timetable or route information): missing, damaged, faded, illegible or tilted.",
    "waiting_area": "the passenger waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown vegetation, standing space).",
    "lighting": "lighting at the stop (street lamps or shelter lights near the waiting area): missing, damaged or poorly placed.",
    "accessibility": "accessibility (kerb height, ramps, step-free access, tactile paving, uneven or broken surfaces, obstacles blocking wheelchairs or prams).",
}


def build_questions() -> dict:
    questions = {}
    for name, what in CATEGORIES.items():
        questions[f"{name}_visible"] = {
            "type": "noul",
            "instructions": f"Is {what.split(' (')[0]} visible in at least one of the photos?",
        }
        questions[name] = {
            "type": "score",
            "instructions": f"How much maintenance does {what} Judge only from what the photos show.",
            "criteria": SEVERITY,
        }
    questions["requires_maintenance"] = {
        "type": "score",
        "instructions": (
            "Overall, how much does this bus stop and its immediate surroundings require maintenance? "
            "Consider everything visible: the categories above and anything else (road surface at the stop, "
            "graffiti, vandalism, litter bins, fences, drainage, vegetation, safety hazards)."
        ),
        "criteria": SEVERITY,
    }
    return questions


QUESTIONS = build_questions()
SCORE_KEYS = [*CATEGORIES, "requires_maintenance"]


def state_for(stop_dir: Path, n_images: int) -> dict:
    metas = [json.loads(p.read_text()) for p in sorted(stop_dir.glob("*.json"))]
    stop = metas[0]["stop"] if metas else {}
    return {
        "task": (
            f"These {n_images} street-level photos all show the same Cotral bus stop from different angles. "
            "Assess how much maintenance the stop needs, combining evidence across all photos."
            if n_images > 1 else
            "This street-level photo shows a Cotral bus stop. Assess how much maintenance the stop needs."
        ),
        "stop_name": stop.get("name"),
        "stop_id": stop.get("stop_id"),
    }


def flatten(answers: dict) -> dict:
    out = {k: answers[k]["score"] for k in SCORE_KEYS}
    out.update({f"{k}_visible": answers[f"{k}_visible"]["noul"] for k in CATEGORIES})
    return out


def score(model, stop_dir: Path, images: list[Path]) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    response = model.systemone({
        "model": "clef-flash",
        "state": state_for(stop_dir, len(images)),
        "images": [Image.open(p).convert("RGB") for p in images],
        "questions": QUESTIONS,
    })
    meta = {"latency_s": round(time.perf_counter() - t0, 2), "input_tokens": response["usage"]["input_tokens"]}
    return response["answers"], meta


def print_row(label: str, flat: dict) -> None:
    cells = "  ".join(f"{flat[k]:4.2f}({flat.get(f'{k}_visible', 1):.2f})" if k in CATEGORIES
                      else f"{flat[k]:4.2f}" for k in SCORE_KEYS)
    print(f"{label:28} {cells}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", nargs="?", default="../../images")
    parser.add_argument("--per-image", action="store_true", help="also score each photo on its own")
    parser.add_argument("--out", default="scores.json")
    parser.add_argument("--model", default="mlx-community/clef-flash-8bit")
    args = parser.parse_args()

    path = snapshot_download(args.model)
    sys.path.insert(0, path)
    import clef_mlx

    model = clef_mlx.load(path)
    print(f"{'':28} " + "  ".join(f"{k[:10]:>10}" for k in SCORE_KEYS) + "   score(visible)")

    results = []
    for stop_dir in sorted(p for p in Path(args.image_dir).iterdir() if p.is_dir()):
        images = sorted(stop_dir.glob("*.jpg"))
        if not images:
            continue
        answers, meta = score(model, stop_dir, images)
        entry = {"stop_dir": str(stop_dir), "images": [p.name for p in images], **meta,
                 "joint": flatten(answers), "joint_raw": answers}
        print_row(f"{stop_dir.name} joint x{len(images)} {meta['latency_s']:.1f}s", entry["joint"])
        if args.per_image:
            entry["per_image"] = {}
            for img in images:
                answers, meta = score(model, stop_dir, [img])
                entry["per_image"][img.name] = flatten(answers)
                print_row(f"  {img.name[:20]} {meta['latency_s']:.1f}s", entry["per_image"][img.name])
        results.append(entry)

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
