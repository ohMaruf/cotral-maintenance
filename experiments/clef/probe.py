"""Perception probe: literal per-image yes/no questions, no maintenance framing."""

import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download
from PIL import Image

QUESTIONS = {
    "lamp": "Is there at least one street lamp (a lamp post or a light fixture on a pole or wall) in the photo?",
    "bench": "Is there at least one bench or public seat in the photo?",
    "bus_sign": "Is there a bus stop sign (a sign on a pole marking a bus stop) in the photo?",
    "shelter": "Is there a bus shelter (a covered structure where passengers wait) in the photo?",
    "people": "Are there people in the photo?",
    "cars": "Are there cars in the photo?",
}

path = snapshot_download("mlx-community/clef-flash-8bit")
sys.path.insert(0, path)
import clef_mlx

model = clef_mlx.load(path)
print(f"{'image':32}" + "".join(f"{k:>10}" for k in QUESTIONS))
for stop in sys.argv[1:]:
    for img in json.loads((Path(stop) / "stop.json").read_text())["images"]:
        response = model.systemone({
            "model": "clef-flash",
            "state": "A street-level photo.",
            "images": [Image.open(Path(stop) / img["file"]).convert("RGB")],
            "questions": {k: {"type": "noul", "instructions": q} for k, q in QUESTIONS.items()},
        })
        a = response["answers"]
        print(f"{Path(stop).name + '/' + img['view']:32}" + "".join(f"{a[k]['noul']:10.2f}" for k in QUESTIONS))
