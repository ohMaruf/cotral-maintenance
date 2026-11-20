import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import far_band
from far_band import Frame

from cotral_maintenance.explorer.geometry import Camera, PathFrame
from cotral_maintenance.explorer.llm import ChatClient, image_part
from cotral_maintenance.render import render_view
from cotral_maintenance.settings import GoogleKey, Paths, load_profile
from cotral_maintenance.tiles import MapTilesClient

FULL_PX = 1254
BAND_SCALE = 3.9
CASES = [
    {"run": "test-nvfp4-11", "stop": "f13310", "photo": 1, "sign_px": 157},
    {"run": "test-nvfp4-11", "stop": "f306", "photo": 6, "sign_latlon": (42.148483, 12.114685)},
]
PROMPT = ("PHOTO: a street-level photo. Is a Cotral bus stop sign like the REFERENCE anywhere in it? It can be small, "
          "far away, blurry, partly hidden or seen at an angle; the panel is the same on both sides. Reply with JSON "
          'only: {"sign": true, "x": X, "y": Y} with X, Y the centre of the sign on a 0-1000 grid of the photo '
          '(0,0 top left, 1000,1000 bottom right), or {"sign": false}.')


def load(case: dict):
    db = sqlite3.connect(f"runs/{case['run']}/run.sqlite")
    rec = json.loads(db.execute("SELECT record FROM explorations WHERE stop_id=?", (case["stop"],)).fetchone()[0])
    ph = next(p for p in rec["photos"] if p["index"] == case["photo"])
    f = Frame(ph["lat"], ph["lon"])
    path = PathFrame([f.xy(*p) for p in rec["path"]], rec["start_s"])
    cam = Camera((0.0, 0.0), ph["heading"], ph["fov"], ph["pitch"], ph["width"], ph["height"])
    if "sign_px" in case:
        bearing = cam.bearing_of(case["sign_px"])
    else:
        x, y = f.xy(*case["sign_latlon"])
        bearing = math.degrees(math.atan2(x, y)) % 360
    return ph, cam, path, bearing


def answer(client: ChatClient, reference: dict, image: Path) -> tuple[dict | None, str]:
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "REFERENCE: the Cotral bus stop sign."}, reference,
        {"type": "text", "text": PROMPT}, image_part(image)]}]
    status, body, _ = client.complete(messages, [], None, seed=1)
    text = (body["choices"][0]["message"].get("content") or "") if status == 200 else str(body)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return (json.loads(m.group(0)) if m else None), text
    except json.JSONDecodeError:
        return None, text


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default=None)
    p.add_argument("--out", default="crop-ab")
    p.add_argument("--near-m", type=float, default=5.0)
    args = p.parse_args()
    far_band.NEAR_M = args.near_m
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    key, paths = GoogleKey.from_env(), Paths.from_env()
    spec = load_profile(paths, args.profile).explorer
    client = ChatClient(spec.server.url, spec.model, spec.dialect, spec.sampling, spec.template, 400,
                        request=spec.request)
    reference = image_part(paths.reference_sign)
    with MapTilesClient(key.api_key, paths.cache / "tiles", 20.0, key.referrer) as tiles:
        for case in CASES:
            ph, cam, path, bearing = load(case)
            box = far_band.band(cam, path, ph["along"])
            full_cam = Camera((0.0, 0.0), cam.heading, cam.fov, cam.pitch, FULL_PX, FULL_PX)
            g = tiles.get_geometry(ph["pano_id"])
            full = render_view(tiles, g, cam.heading, cam.pitch, cam.fov, FULL_PX, FULL_PX)
            k = FULL_PX / cam.width
            crop = tuple(round(v * k) for v in box)
            name = f"{case['stop']}_{case['photo']}"
            full.save(out / f"{name}_full.png")
            full.crop(crop).save(out / f"{name}_crop.png")
            b0, b1 = cam.bearing_of(box[0]), cam.bearing_of(box[2])
            fov = (b1 - b0) % 360
            band_cam = Camera((0.0, 0.0), (b0 + fov / 2) % 360, fov,
                              (cam.elevation_of(box[1]) + cam.elevation_of(box[3])) / 2,
                              int((box[2] - box[0]) * BAND_SCALE), int((box[3] - box[1]) * BAND_SCALE))
            render_view(tiles, g, band_cam.heading, band_cam.pitch, band_cam.fov, band_cam.width,
                        band_cam.height).save(out / f"{name}_crop4x.png")
            for kind, view, offset, size in (
                    ("full", full_cam, (0, 0), (FULL_PX, FULL_PX)),
                    ("crop", full_cam, crop[:2], (crop[2] - crop[0], crop[3] - crop[1])),
                    ("crop4x", band_cam, (0, 0), (band_cam.width, band_cam.height))):
                j, text = answer(client, reference, out / f"{name}_{kind}.png")
                verdict = "no answer"
                if j is not None and j.get("sign") and all(isinstance(j.get(c), (int, float)) for c in "xy"):
                    px = offset[0] + j["x"] / 1000 * size[0]
                    miss = abs((view.bearing_of(px) - bearing + 180) % 360 - 180)
                    verdict = f"said yes, {miss:.1f}° from the sign: {'ON THE SIGN' if miss <= 1.5 else 'elsewhere'}"
                elif j is not None:
                    verdict = "said no sign"
                print(f"{name} {kind:6s}: {verdict}   reply: {text.strip()[:120]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
