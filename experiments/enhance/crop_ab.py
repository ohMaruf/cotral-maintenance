"""A/B test: does cropping a photo to the far sidewalk degrade what the explorer model can see?

Each wide photo (opening or sweep) of the found stops in the given runs is shown four ways:
  A  the Static API photo the explorer gets today (640x640, 110°)
  B  the same view rendered from tiles at ~2x (1254x1254, zoom 3)
  D  B cropped to the far sidewalk band (20-80 m, 3-14 m right, 0-4 m up): the same pixels, cropped
  C  the band rendered at ~4x (zoom 4)
B vs D isolates cropping; C vs D adds resolution; A is today.
Positives: the found sign 20-70 m away inside the band. Negatives: photos where neither the found sign nor any
other known stop is in view within 150 m. The model gets the reference sign and one image, and answers whether a
Cotral sign is there and where (0-1000 grid). A point counts when it is on the sign: within max(1.5°, the sign's
half-width) of its bearing and between its foot and top (±1°).

Run on the server, from the repository root, with the explorer's server up:
    uv run python experiments/enhance/crop_ab.py build OUT runs/RUN ... --dry-run   # count tiles, fetch nothing
    uv run python experiments/enhance/crop_ab.py build OUT runs/RUN ...             # render (billed tiles)
    uv run python experiments/enhance/crop_ab.py eval OUT --profile remote-nvfp4 [--repeats 3]
    uv run python experiments/enhance/crop_ab.py report OUT
`eval` resumes: answers already in OUT/answers.jsonl are not asked again.
"""

import argparse
import json
import math
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from far_band import NEAR_M, Frame, band

from cotral_maintenance.explorer.geometry import CAMERA_HEIGHT_M, Camera, PathFrame
from cotral_maintenance.explorer.llm import ChatClient, image_part
from cotral_maintenance.render import render_view, tiles_for_view
from cotral_maintenance.settings import GoogleKey, Paths, load_profile
from cotral_maintenance.tiles import MapTilesClient

FULL_PX = 1254  # 11.4 px/degree over 110°: zoom 3
BAND_SCALE = 3.9  # band pixels per Static API pixel: 22.7 px/degree, zoom 4
POSITIVE_M = 70.0
NEGATIVE_CLEAR_M = 150.0
CONDITIONS = ("A", "B", "D", "C")

PROMPT = ("PHOTO: a street-level photo. Is a Cotral bus stop sign like the REFERENCE anywhere in it? It can be small, "
          "far away, blurry, partly hidden or seen at an angle; the panel is the same on both sides. Reply with JSON "
          'only: {"sign": true, "x": X, "y": Y} with X, Y the centre of the sign on a 0-1000 grid of the photo '
          '(0,0 top left, 1000,1000 bottom right), or {"sign": false}.')


def camera_json(c: Camera) -> dict:
    return {"position": list(c.position), "heading": c.heading, "fov": c.fov, "pitch": c.pitch,
            "width": c.width, "height": c.height}


def camera_of(j: dict) -> Camera:
    return Camera(tuple(j["position"]), j["heading"], j["fov"], j["pitch"], j["width"], j["height"])


def candidates(runs: list[Path], limit_negatives: int):
    """(run, stop, photo record, Camera, path, sign xy, distance, band box, kind) per usable wide photo."""
    seen, negatives = set(), 0
    for run in runs:
        db = sqlite3.connect(run / "run.sqlite")
        for stop, slat, slon, rec in db.execute(
                "SELECT stop_id, lat, lon, record FROM explorations WHERE status='found' ORDER BY stop_id"):
            rec = json.loads(rec)
            if rec.get("layout") != "agent-explorer/1":
                continue
            f = Frame(slat, slon)
            path = PathFrame([f.xy(*p) for p in rec["path"]], rec["start_s"])
            others = [f.xy(o["lat"], o["lon"]) for o in rec.get("others", [])]
            for ph in rec["photos"]:
                if not ph["toward"].startswith(("sweep", "opening")):
                    continue
                key = (ph["pano_id"], round(ph["heading"]))
                if key in seen:  # runs share stops and photos
                    continue
                cam = Camera(f.xy(ph["lat"], ph["lon"]), ph["heading"], ph["fov"], ph["pitch"],
                             ph["width"], ph["height"])
                box = band(cam, path, ph["along"])
                if box is None:
                    continue
                d = math.dist((0.0, 0.0), cam.position)
                sx = cam.column_of((0.0, 0.0))
                if sx is not None and NEAR_M <= d <= POSITIVE_M:
                    sy = cam.row_of((0.0, 0.0), 2.2)
                    if not (box[0] <= sx <= box[2] and box[1] <= sy <= box[3]):
                        continue
                    kind = "positive"
                elif (sx is None or d > NEGATIVE_CLEAR_M) and not any(
                        cam.column_of(o) is not None and math.dist(o, cam.position) <= NEGATIVE_CLEAR_M
                        for o in others):
                    if negatives >= limit_negatives:
                        continue
                    negatives += 1
                    kind = "negative"
                else:
                    continue
                seen.add(key)
                yield run, stop, ph, cam, d, box, kind


def views(cam: Camera, box) -> tuple[Camera, tuple[int, int, int, int], Camera]:
    """B's camera, D's crop of B (pixels), C's camera."""
    full = Camera(cam.position, cam.heading, cam.fov, cam.pitch, FULL_PX, FULL_PX)
    k = FULL_PX / cam.width
    crop = tuple(round(v * k) for v in box)
    x0, y0, x1, y1 = box
    b0, b1 = cam.bearing_of(x0), cam.bearing_of(x1)
    fov = (b1 - b0) % 360
    pitch = (cam.elevation_of(y0) + cam.elevation_of(y1)) / 2
    band_cam = Camera(cam.position, (b0 + fov / 2) % 360, fov, pitch,
                      int((x1 - x0) * BAND_SCALE), int((y1 - y0) * BAND_SCALE))
    return full, crop, band_cam


def cmd_build(args) -> int:
    out = Path(args.out)
    key, paths = GoogleKey.from_env(), Paths.from_env()
    items, tiles = [], set()
    with MapTilesClient(key.api_key, paths.cache / "tiles", 20.0, key.referrer) as client:
        rows = list(candidates([Path(r) for r in args.runs], args.negatives))
        for run, stop, ph, cam, d, box, kind in rows:
            g = client.get_geometry(ph["pano_id"])
            full, crop, band_cam = views(cam, box)
            for c in (full, band_cam):
                tiles |= {(ph["pano_id"], *t) for t in tiles_for_view(g, c.heading, c.pitch, c.fov, c.width, c.height)}
            if args.dry_run:
                continue
            name = f"{run.name}_{stop}_{ph['index']:02d}"
            (out / "images").mkdir(parents=True, exist_ok=True)
            shutil.copy(run / "media" / ph["file"][:2] / f"{ph['file']}.jpg", out / "images" / f"{name}_A.jpg")
            b_img = render_view(client, g, full.heading, full.pitch, full.fov, full.width, full.height)
            b_img.save(out / "images" / f"{name}_B.png")
            b_img.crop(crop).save(out / "images" / f"{name}_D.png")
            render_view(client, g, band_cam.heading, band_cam.pitch, band_cam.fov, band_cam.width,
                        band_cam.height).save(out / "images" / f"{name}_C.png")
            items.append({"name": name, "kind": kind, "distance_m": d, "run": run.name, "stop": stop,
                          "photo": ph["index"],
                          "conditions": {
                              "A": {"file": f"{name}_A.jpg", "camera": camera_json(cam), "offset": [0, 0]},
                              "B": {"file": f"{name}_B.png", "camera": camera_json(full), "offset": [0, 0]},
                              "D": {"file": f"{name}_D.png", "camera": camera_json(full), "offset": crop[:2],
                                    "size": [crop[2] - crop[0], crop[3] - crop[1]]},
                              "C": {"file": f"{name}_C.png", "camera": camera_json(band_cam), "offset": [0, 0]}}})
    kinds = [r[-1] for r in rows]
    print(f"{kinds.count('positive')} positives, {kinds.count('negative')} negatives; "
          f"{len(tiles)} tiles{' would be fetched (less what is cached)' if args.dry_run else ''}")
    if not args.dry_run:
        (out / "items.json").write_text(json.dumps(items, indent=1))
    return 0


def parse_reply(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(j.get("sign"), bool):
        return None
    if j["sign"] and not all(isinstance(j.get(k), (int, float)) for k in ("x", "y")):
        return None
    return j


def cmd_eval(args) -> int:
    out = Path(args.out)
    paths = Paths.from_env()
    spec = load_profile(paths, args.profile).explorer
    client = ChatClient(spec.server.url, spec.model, spec.dialect, spec.sampling, spec.template, 400,
                        request=spec.request)
    items = json.loads((out / "items.json").read_text())
    answers_path = out / "answers.jsonl"
    done = set()
    if answers_path.exists():
        for line in answers_path.read_text().splitlines():
            a = json.loads(line)
            done.add((a["name"], a["condition"], a["repeat"]))
    reference = image_part(paths.reference_sign)
    conditions = args.conditions.split(",")
    with answers_path.open("a") as f:
        for rep in range(args.repeats):
            for item in items:
                for cond in conditions:
                    if (item["name"], cond, rep) in done:
                        continue
                    messages = [{"role": "user", "content": [
                        {"type": "text", "text": "REFERENCE: the Cotral bus stop sign."}, reference,
                        {"type": "text", "text": PROMPT},
                        image_part(out / "images" / item["conditions"][cond]["file"])]}]
                    status, body, seconds = client.complete(messages, [], None, seed=1000 + rep)
                    text = body["choices"][0]["message"].get("content") if status == 200 else body
                    usage = body.get("usage", {}) if status == 200 else {}
                    f.write(json.dumps({"name": item["name"], "condition": cond, "repeat": rep, "status": status,
                                        "reply": text, "seconds": round(seconds, 1),
                                        "prompt_tokens": usage.get("prompt_tokens")}) + "\n")
                    f.flush()
                    print(f"{item['name']} {cond} rep {rep}: {status} {str(text)[:80]!r} ({seconds:.0f} s)")
    return 0


def on_sign(item: dict, cond: str, x: float, y: float) -> bool:
    c = item["conditions"][cond]
    cam = camera_of(c["camera"])
    w, h = c.get("size", [cam.width, cam.height])
    px, py = c["offset"][0] + x / 1000 * w, c["offset"][1] + y / 1000 * h
    sign = (0.0, 0.0)
    d = math.dist(sign, cam.position)
    bearing = math.degrees(math.atan2(-cam.position[0], -cam.position[1])) % 360
    off = abs((cam.bearing_of(px) - bearing + 180) % 360 - 180)
    elevation = cam.elevation_of(py)
    foot = math.degrees(math.atan(-CAMERA_HEIGHT_M / d)) - 1
    top = math.degrees(math.atan((4.0 - CAMERA_HEIGHT_M) / d)) + 1
    return off <= max(1.5, math.degrees(math.atan(1.0 / d))) and foot <= elevation <= top


def cmd_report(args) -> int:
    out = Path(args.out)
    items = {i["name"]: i for i in json.loads((out / "items.json").read_text())}
    rows = [json.loads(line) for line in (out / "answers.jsonl").read_text().splitlines()]
    score: dict[tuple[str, int], dict[str, bool | None]] = {}  # (name, repeat) -> condition -> correct
    print(f"{'cond':4s} {'pos':>4s} {'said yes':>9s} {'on sign':>8s} {'neg':>4s} {'false yes':>10s} "
          f"{'invalid':>8s} {'tokens':>7s} {'s/call':>7s}")
    for cond in CONDITIONS:
        rs = [r for r in rows if r["condition"] == cond]
        if not rs:
            continue
        pos = yes = hit = neg = fp = bad = 0
        for r in rs:
            item = items[r["name"]]
            j = parse_reply(r["reply"]) if r["status"] == 200 else None
            correct = None
            if j is None:
                bad += 1
            elif item["kind"] == "positive":
                yes += j["sign"]
                correct = bool(j["sign"]) and on_sign(item, cond, j["x"], j["y"])
                hit += correct
            else:
                fp += j["sign"]
                correct = not j["sign"]
            if item["kind"] == "positive":
                pos += 1
            else:
                neg += 1
            score.setdefault((r["name"], r["repeat"]), {})[cond] = correct
        tokens = [r["prompt_tokens"] for r in rs if r.get("prompt_tokens")]
        print(f"{cond:4s} {pos:4d} {yes:9d} {hit:8d} {neg:4d} {fp:10d} {bad:8d} "
              f"{sum(tokens) / max(len(tokens), 1):7.0f} {sum(r['seconds'] for r in rs) / len(rs):7.1f}")
    print("\npaired (same photo and repeat): first right & second wrong / first wrong & second right")
    for a, b in (("B", "D"), ("D", "C"), ("A", "C"), ("A", "D")):
        both = [s for s in score.values() if s.get(a) is not None and s.get(b) is not None]
        print(f"  {a} vs {b}: {sum(s[a] and not s[b] for s in both)} / {sum(s[b] and not s[a] for s in both)}"
              f"  (of {len(both)})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("runs", nargs="+")
    b.add_argument("--negatives", type=int, default=40, help="at most this many negatives (default 40)")
    b.add_argument("--dry-run", action="store_true", help="count the tiles; fetch and write nothing")
    e = sub.add_parser("eval")
    e.add_argument("out")
    e.add_argument("--profile", default=None)
    e.add_argument("--conditions", default=",".join(CONDITIONS))
    e.add_argument("--repeats", type=int, default=1, help="ask each image this many times (seeds differ)")
    r = sub.add_parser("report")
    r.add_argument("out")
    args = p.parse_args()
    return {"build": cmd_build, "eval": cmd_eval, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
