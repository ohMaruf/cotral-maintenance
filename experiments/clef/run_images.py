"""Run mlx-community/clef-flash-8bit over the Street View stop images.

Usage: .venv/bin/python run_images.py [image_dir] [--out results.json]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from huggingface_hub import snapshot_download
from PIL import Image

QUESTIONS = {
    "stop_visible": {
        "type": "noul",
        "instructions": "Is a bus stop (pole with a bus stop sign, or a bus shelter) visible in the image?",
    },
    "shelter": {
        "type": "noul",
        "instructions": "Is there a bus shelter (a covered waiting structure) visible?",
    },
    "bench": {
        "type": "noul",
        "instructions": "Is there a bench or seating for waiting passengers visible?",
    },
    "scene": {
        "type": "choice",
        "instructions": "What kind of place is shown?",
        "criteria": {
            "urban_street": "A street in a town or city centre",
            "suburban": "A residential or suburban road",
            "rural": "A country road or open countryside",
            "parking_or_lot": "A car park, square or open paved area",
            "waterfront": "A seafront, harbour or promenade",
        },
    },
    "condition": {
        "type": "score",
        "instructions": "How well maintained does the visible street furniture and pavement look?",
        "criteria": ["Badly damaged or neglected", "Worn, needs some work", "Acceptable", "Good condition"],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", nargs="?", default="../../images")
    parser.add_argument("--out", default="results.json")
    parser.add_argument("--model", default="mlx-community/clef-flash-8bit")
    args = parser.parse_args()

    path = snapshot_download(args.model)
    sys.path.insert(0, path)
    import clef_mlx

    t0 = time.perf_counter()
    model = clef_mlx.load(path)
    print(f"loaded in {time.perf_counter() - t0:.1f}s", file=sys.stderr)

    results = []
    for img_path in sorted(Path(args.image_dir).glob("*/*.jpg")):
        meta_path = img_path.with_suffix(".json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        stop = meta.get("stop", {})
        state = {
            "task": "Inspect this street-level photo taken at a Cotral bus stop location for maintenance review.",
            "stop_name": stop.get("name"),
            "photo_date": meta.get("shot", {}).get("pano", {}).get("date"),
        }
        t0 = time.perf_counter()
        response = model.systemone({
            "model": "clef-flash",
            "state": state,
            "images": [Image.open(img_path).convert("RGB")],
            "questions": QUESTIONS,
        })
        latency = time.perf_counter() - t0
        answers = response["answers"]
        results.append({"image": str(img_path), "latency_s": round(latency, 2),
                        "input_tokens": response["usage"]["input_tokens"], "answers": answers})
        print(f"{img_path.parent.name}/{img_path.name:32} {latency:5.2f}s  "
              f"stop={answers['stop_visible']['noul']:.2f} shelter={answers['shelter']['noul']:.2f} "
              f"bench={answers['bench']['noul']:.2f} scene={answers['scene']['choice']}"
              f"({answers['scene']['confidence']:.2f}) condition={answers['condition']['score']:.2f}/3")

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
