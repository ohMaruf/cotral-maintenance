"""Scratch: does a navy-blob detector find the signs the explorer found? Recall and false blobs on wide photos.

    uv run python experiments/enhance/blobs.py runs/test-nvfp4-5 runs/test-nvfp4-7 ...
For every found stop: its wide photos (opening/sweep) whose view holds the found position within 70 m;
a hit is a blob within 14 px of the projected column and 70 px of the horizon.
"""

import json
import math
import sqlite3
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from cotral_blue import navy_weight  # noqa: E402

W_MIN, AREA = 0.35, (3, 400)


def components(mask: np.ndarray):
    """(ys, xs) of each 4-connected component of a boolean mask."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q, pts = deque([(y0, x0)]), []
        seen[y0, x0] = True
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    q.append((yy, xx))
        yield np.array(pts).T


def blobs(rgb: np.ndarray) -> list[tuple[float, float, int]]:
    out = []
    for ys, xs in components(navy_weight(rgb) > W_MIN):
        pts = xs
        bh, bw = np.ptp(ys) + 1, np.ptp(xs) + 1
        # compact: a sign, not a shadow band or a stretch of sky
        if AREA[0] <= len(pts) <= AREA[1] and len(pts) >= 0.35 * bh * bw and bw <= 40 and bh <= 40:
            out.append((xs.mean(), ys.mean(), len(pts)))
    return out


def project(cam_lat, cam_lon, heading, fov, width, lat, lon):
    dy = (lat - cam_lat) * 111320
    dx = (lon - cam_lon) * 111320 * math.cos(math.radians(cam_lat))
    off = ((math.degrees(math.atan2(dx, dy)) - heading + 180) % 360) - 180
    if abs(off) >= fov / 2 - 1:
        return None, math.hypot(dx, dy)
    return width / 2 + width / 2 * math.tan(math.radians(off)) / math.tan(math.radians(fov / 2)), math.hypot(dx, dy)


def main() -> None:
    hits = total = false = photos_n = 0
    for run in map(Path, sys.argv[1:]):
        db = sqlite3.connect(run / "run.sqlite")
        for stop, lat, lon in db.execute("SELECT stop_id, lat, lon FROM explorations WHERE status='found'"):
            for idx, toward, media, clat, clon, hd, fov, pitch, w, h in db.execute(
                    "SELECT idx, toward, media, lat, lon, heading, fov, pitch, width, height FROM photos "
                    "WHERE stop_id=? AND (toward LIKE 'sweep%' OR toward LIKE 'opening%')", (stop,)):
                rgb = np.asarray(Image.open(run / "media" / media[:2] / f"{media}.jpg").convert("RGB")) / 255.0
                bs = blobs(rgb)
                photos_n += 1
                x, d = project(clat, clon, hd, fov, w, lat, lon)
                near = [b for b in bs if x is not None and abs(b[0] - x) <= 14 and abs(b[1] - h / 2) <= 70]
                false += len(bs) - len(near)
                if x is None or d > 70:
                    continue
                total += 1
                hits += bool(near)
                print(f"{run.name} {stop} photo {idx:2d} {toward:15s} d={d:5.1f} m x={x:5.0f} "
                      f"{'HIT ' + str([(round(b[0]), round(b[1]), b[2]) for b in near]) if near else 'miss'}")
    print(f"\nsign in view within 70 m: {hits}/{total} found by a blob;  "
          f"{false} other blobs on {photos_n} wide photos ({false / max(photos_n, 1):.1f} per photo)")


if __name__ == "__main__":
    main()
