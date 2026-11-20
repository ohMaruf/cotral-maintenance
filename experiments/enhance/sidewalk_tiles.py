"""Scratch: tiles only where the sidewalk is. For every spot of the right-hand sidewalk 20-80 m from the camera
(every 2 m along, 3/8/14 m right of the centre line), the footprint of a sign standing there (1 m either side,
0-4 m up) is mapped to panorama tiles; the union is what gets fetched. Compared with the far band's rectangle.
No tiles are fetched (metadata only).

    uv run python experiments/enhance/sidewalk_tiles.py runs/A runs/B ...
"""

import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from far_band import FAR_M, NEAR_M, OFFSETS_M, Frame, band, box_view  # noqa: E402

from cotral_maintenance.explorer.geometry import CAMERA_HEIGHT_M, Camera, PathFrame, compass  # noqa: E402
from cotral_maintenance.render import tiles_for_view  # noqa: E402
from cotral_maintenance.settings import GoogleKey, Paths  # noqa: E402
from cotral_maintenance.tiles import MapTilesClient  # noqa: E402

SIGN_HALF_M, SIGN_TOP_M = 1.0, 4.0


def footprint(cam: Camera, p, ppd: float):
    """A tiny view framing a sign standing at p, at ppd pixels per degree."""
    d = math.dist(p, cam.position)
    heading = compass(p[0] - cam.position[0], p[1] - cam.position[1])
    hw = math.degrees(math.atan(SIGN_HALF_M / d))
    lo = math.degrees(math.atan(-CAMERA_HEIGHT_M / d))
    hi = math.degrees(math.atan((SIGN_TOP_M - CAMERA_HEIGHT_M) / d))
    fov = 2 * hw
    w = max(int(fov * ppd), 2)
    h = max(int((hi - lo) * ppd), 2)
    return heading, (lo + hi) / 2, fov, w, h


def sidewalk_spots(cam: Camera, path: PathFrame, along: float):
    a = max(path.first, along - 130)
    while a <= min(path.last, along + 130):
        for off in OFFSETS_M:
            p = path.point(a, off)
            if cam.column_of(p) is not None and NEAR_M <= math.dist(p, cam.position) <= FAR_M:
                yield p
        a += 2.0


def main() -> None:
    key, paths = GoogleKey.from_env(), Paths.from_env()
    totals = {"band z5": 0, "band z4": 0, "sidewalk z4": 0, "sidewalk z3/z4": 0}
    covered = rows = 0
    with MapTilesClient(key.api_key, paths.cache / "tiles", 20.0, key.referrer) as client:
        for run in map(Path, sys.argv[1:]):
            db = sqlite3.connect(run / "run.sqlite")
            for stop, slat, slon, rec in db.execute(
                    "SELECT stop_id, lat, lon, record FROM explorations WHERE status='found'"):
                rec = json.loads(rec)
                f = Frame(slat, slon)
                path = PathFrame([f.xy(*p) for p in rec["path"]], rec["start_s"])
                for ph in rec["photos"]:
                    if not ph["toward"].startswith(("sweep", "opening")):
                        continue
                    cam = Camera(f.xy(ph["lat"], ph["lon"]), ph["heading"], ph["fov"], ph["pitch"],
                                 ph["width"], ph["height"])
                    if cam.column_of((0, 0)) is None or not NEAR_M <= math.dist((0, 0), cam.position) <= 70:
                        continue
                    box = band(cam, path, ph["along"])
                    if box is None:
                        continue
                    g = client.get_geometry(ph["pano_id"])
                    hd, pt, fov, w, h = box_view(cam, box)
                    z5 = tiles_for_view(g, hd, pt, fov, w, h)
                    z4 = tiles_for_view(g, hd, pt, fov, int(w * 0.95), int(h * 0.95))  # 22.1 px/deg: zoom 4
                    side4, side34 = set(), set()
                    for p in sidewalk_spots(cam, path, ph["along"]):
                        side4 |= tiles_for_view(g, *footprint(cam, p, 22.0))
                        # nearer than 40 m a sign is 0.9-1.7 degrees wide: zoom 3 (11 px/deg) gives it 10-19 px
                        ppd = 11.0 if math.dist(p, cam.position) < 40 else 22.0
                        side34 |= tiles_for_view(g, *footprint(cam, p, ppd))
                    sign = tiles_for_view(g, *footprint(cam, (0.0, 0.0), 22.0))
                    rows += 1
                    covered += sign <= side4
                    for k, v in zip(totals, (z5, z4, side4, side34), strict=True):
                        totals[k] += len(v)
                    print(f"{run.name} {stop} {ph['index']:2d}: band z5 {len(z5):2d}, band z4 {len(z4):2d}, "
                          f"sidewalk z4 {len(side4):2d}, z3/z4 {len(side34):2d}; sign covered {sign <= side4}")
    print(f"\n{rows} photos; sign's tiles inside the sidewalk set: {covered}/{rows}")
    for k, v in totals.items():
        print(f"  {k:15s} {v / rows:5.1f} tiles per photo")


if __name__ == "__main__":
    main()
