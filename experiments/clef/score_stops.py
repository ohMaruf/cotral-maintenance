"""Score bus stop maintenance needs with mlx-community/clef-flash-8bit.

All photos of a stop go into one request. When the stop has a stop.json manifest
(the shot plan: converge_a/b face the stop, sky_a/b look up and outwards for lamps),
the photos are sent in plan order and the model is told what each one shows.

Scores are real numbers in [0, 4]: 0 = no maintenance needed ... 4 = severe.
Each is the expected severity under the model's probabilities. For shelter, seating,
signage and lighting, an element that does not appear in any photo counts as missing,
which is severe: the score mixes "visible, in this condition" with "missing" by the
model's probability that the element is visible.

Confidence, in [0, 1], is P(the stop can be judged from these photos) times how
peaked the score distributions are (1 - normalised entropy):
  confidence: averaged over the six category scores.
  maintenance_confidence: for requires_maintenance.

Usage: .venv/bin/python score_stops.py [image_dir] [--out scores.json]
"""

import argparse
import json
import math
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
MISSING_LEVEL = len(SEVERITY) - 1

CATEGORIES = {
    "shelter": "the bus shelter (roof, panels, frame, glass)",
    "seating": "seating for waiting passengers (benches, seats, including seats inside a shelter)",
    "signage": "bus stop signage (stop pole, stop sign, timetable or route information)",
    "waiting_area": "the passenger waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown vegetation, standing space)",
    "lighting": "lighting that illuminates the waiting area (street lamps nearby, or lights built into the shelter)",
    "accessibility": "accessibility (kerb height, ramps, step-free access, tactile paving, uneven or broken surfaces, obstacles blocking wheelchairs or prams)",
}
# Elements a stop may lack entirely; for these, not visible in any photo means missing.
CAN_BE_MISSING = ("shelter", "seating", "signage", "lighting")

VIEW_ROLES = {
    "converge_a": "faces the stop from one side, 5-10 m away",
    "converge_b": "faces the stop from the opposite side",
    "sky_a": "taken at the stop, looking up and outwards along the road, to show street lamps",
    "sky_b": "taken at the stop, looking up and outwards in the other direction",
}


def build_questions() -> dict:
    questions = {}
    for name, what in CATEGORIES.items():
        if name in CAN_BE_MISSING:
            questions[f"{name}_visible"] = {
                "type": "noul",
                "instructions": f"Does {what.split(' (')[0]} appear in at least one of the photos?",
            }
            condition = f"If {what} appears in the photos, how much maintenance does it need?"
        else:
            condition = f"How much maintenance does {what} need?"
        questions[name] = {"type": "score", "instructions": condition, "criteria": SEVERITY}
    questions["requires_maintenance"] = {
        "type": "score",
        "instructions": (
            "Overall, how much does this bus stop and its immediate surroundings require maintenance? "
            "Consider everything visible: the categories above and anything else (road surface at the stop, "
            "graffiti, vandalism, litter bins, fences, drainage, vegetation, safety hazards)."
        ),
        "criteria": SEVERITY,
    }
    questions["assessable"] = {
        "type": "noul",
        "instructions": (
            "Can the maintenance needs of this bus stop be judged reliably from these photos? Answer no if "
            "the photos cannot show the stop and its facilities, for example a large bus station seen only "
            "from outside, a stop hidden by vehicles or works, a stop in a restricted area, the camera not "
            "showing where the stop is, or photos too dark or blurred to judge."
        ),
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


def state_for(stop_dir: Path, manifest: dict, views: list[str | None]) -> dict:
    stop = manifest.get("stop") or {}
    if not stop:
        sidecars = sorted(stop_dir.glob("*.json"))
        stop = json.loads(sidecars[0].read_text()).get("stop", {}) if sidecars else {}
    state = {
        "task": (
            f"These {len(views)} street-level photos all show the same Cotral bus stop. Assess how much "
            "maintenance the stop needs, combining evidence across all photos. Together the photos cover "
            "the stop from several angles."
        ),
        "stop_name": stop.get("name"),
    }
    if any(views):
        state["photos"] = [f"Photo {i}: {VIEW_ROLES.get(v, v)}" for i, v in enumerate(views, 1)]
    return state


def sharpness(probs: list[float]) -> float:
    """1 - normalised entropy: 1 for a certain answer, 0 for a uniform one."""
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    return 1 - entropy / math.log(len(probs))


def category_distribution(answers: dict, name: str) -> list[float]:
    probs = [answers[name]["probabilities"][str(i)] for i in range(len(SEVERITY))]
    if name not in CAN_BE_MISSING:
        return probs
    visible = answers[f"{name}_visible"]["noul"]
    return [visible * p + (1 - visible) * (i == MISSING_LEVEL) for i, p in enumerate(probs)]


def summarise(answers: dict) -> dict:
    assessable = answers["assessable"]["noul"]
    dists = {name: category_distribution(answers, name) for name in CATEGORIES}
    overall = [answers["requires_maintenance"]["probabilities"][str(i)] for i in range(len(SEVERITY))]
    out = {name: round(sum(i * p for i, p in enumerate(d)), 3) for name, d in dists.items()}
    out["requires_maintenance"] = round(sum(i * p for i, p in enumerate(overall)), 3)
    out["confidence"] = round(assessable * sum(map(sharpness, dists.values())) / len(dists), 3)
    out["maintenance_confidence"] = round(assessable * sharpness(overall), 3)
    out["assessable"] = assessable
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", nargs="?", default="../../images")
    parser.add_argument("--out", default="scores.json")
    parser.add_argument("--model", default="mlx-community/clef-flash-8bit")
    args = parser.parse_args()

    path = snapshot_download(args.model)
    sys.path.insert(0, path)
    import clef_mlx

    model = clef_mlx.load(path)
    columns = [*CATEGORIES, "requires_maintenance", "confidence", "maintenance_confidence"]
    print(f"{'stop':8} {'date':8} " + " ".join(f"{c[:11]:>11}" for c in columns))

    results = []
    for stop_dir in sorted(p for p in Path(args.image_dir).iterdir() if p.is_dir()):
        manifest, images, views = load_stop(stop_dir)
        if not images:
            continue
        t0 = time.perf_counter()
        response = model.systemone({
            "model": "clef-flash",
            "state": state_for(stop_dir, manifest, views),
            "images": [Image.open(p).convert("RGB") for p in images],
            "questions": QUESTIONS,
        })
        scores = summarise(response["answers"])
        results.append({
            "stop_id": stop_dir.name,
            "imagery_date": manifest.get("imagery_date"),
            "converge_separation_deg": manifest.get("converge_separation_deg"),
            "images": [p.name for p in images],
            "latency_s": round(time.perf_counter() - t0, 2),
            "input_tokens": response["usage"]["input_tokens"],
            "scores": scores,
            "raw": response["answers"],
        })
        print(f"{stop_dir.name:8} {manifest.get('imagery_date') or '-':8} "
              + " ".join(f"{scores[c]:11.2f}" for c in columns))

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
