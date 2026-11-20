import json
import math
import sqlite3
import sys
from pathlib import Path

from cotral_maintenance.explorer.geometry import Camera, PathFrame
from cotral_maintenance.render import render_view, tiles_for_view
from cotral_maintenance.settings import GoogleKey, Paths
from cotral_maintenance.tiles import MapTilesClient

NEAR_M, FAR_M = 20.0, 80.0
SCALE = 4
MARGIN_PX = 12
OFFSETS_M = (3.0, 8.0, 14.0)


class Frame:
    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0, self.lon0, self.k = lat0, lon0, math.cos(math.radians(lat0))

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * 111320 * self.k, (lat - self.lat0) * 111320


def band(cam: Camera, path: PathFrame, along: float) -> tuple[float, float, float, float] | None:
    xs, ys = [], []
    a = max(path.first, along - 130)
    while a <= min(path.last, along + 130):
        for off in OFFSETS_M:
            p = path.point(a, off)
            d = math.dist(p, cam.position)
            x = cam.column_of(p)
            if x is not None and NEAR_M <= d <= FAR_M:
                xs.append(x)
                ys += [cam.row_of(p, 0.0), cam.row_of(p, 4.0)]
        a += 2.0
    if not xs:
        return None
    w, h = cam.width, cam.height
    return (max(min(xs) - MARGIN_PX, 0), max(min(ys) - MARGIN_PX, 0),
            min(max(xs) + MARGIN_PX, w), min(max(ys) + MARGIN_PX, h))


def box_view(cam: Camera, box) -> tuple[float, float, float, int, int]:
    x0, y0, x1, y1 = box
    b0, b1 = cam.bearing_of(x0), cam.bearing_of(x1)
    fov = (b1 - b0) % 360
    heading = (b0 + fov / 2) % 360
    pitch = (cam.elevation_of(y0) + cam.elevation_of(y1)) / 2
    return heading, pitch, fov, int((x1 - x0) * SCALE), int((y1 - y0) * SCALE)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    key, paths = GoogleKey.from_env(), Paths.from_env()
    rows, inside, tiles_total, truth = 0, 0, 0, {}
    with MapTilesClient(key.api_key, paths.cache / "tiles", 20.0, key.referrer) as client:
        for run in map(Path, sys.argv[2:]):
            db = sqlite3.connect(run / "run.sqlite")
            for stop, slat, slon, rec in db.execute(
                    "SELECT stop_id, lat, lon, record FROM explorations WHERE status='found'"):
                rec = json.loads(rec)
                if rec.get("layout") != "agent-explorer/1":
                    continue
                f = Frame(slat, slon)
                path = PathFrame([f.xy(*p) for p in rec["path"]], rec["start_s"])
                sign = (0.0, 0.0)
                for ph in rec["photos"]:
                    if not ph["toward"].startswith(("sweep", "opening")):
                        continue
                    cam = Camera(f.xy(ph["lat"], ph["lon"]), ph["heading"], ph["fov"], ph["pitch"],
                                 ph["width"], ph["height"])
                    d = math.dist(sign, cam.position)
                    sx = cam.column_of(sign)
                    if sx is None or not NEAR_M <= d <= 70:
                        continue
                    box = band(cam, path, ph["along"])
                    rows += 1
                    sy = cam.row_of(sign, 2.2)
                    hit = box is not None and box[0] <= sx <= box[2] and box[1] <= sy <= box[3]
                    inside += hit
                    if box is None:
                        print(f"{run.name} {stop} photo {ph['index']:2d} d={d:4.0f} m: no band")
                        continue
                    view = box_view(cam, box)
                    geometry = client.get_geometry(ph["pano_id"])
                    n = len(tiles_for_view(geometry, *view))
                    tiles_total += n
                    name = f"{run.name}_{stop}_{ph['index']}"
                    render_view(client, geometry, *view).save(out / f"{name}.png")
                    bcam = Camera(cam.position, view[0], view[2], view[1], view[3], view[4])
                    bx = bcam.column_of(sign)
                    truth[name] = None if bx is None or not hit else [bx, bcam.row_of(sign, 2.2), d]
                    print(f"{run.name} {stop} photo {ph['index']:2d} d={d:4.0f} m: band "
                          f"{box[2] - box[0]:.0f}x{box[3] - box[1]:.0f} px, {n} tiles, sign "
                          f"{'inside' if hit else f'OUTSIDE at ({sx:.0f}, {sy:.0f})'}")
    (out / "truth.json").write_text(json.dumps(truth, indent=1))
    print(f"\nsign inside the far band: {inside}/{rows}; tiles {tiles_total} ({tiles_total / max(rows, 1):.1f} per photo)")


if __name__ == "__main__":
    main()
