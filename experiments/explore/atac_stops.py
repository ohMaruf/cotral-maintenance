"""Match ATAC stops (Rome's city operator) to Cotral stops in Rome, as candidate positions.

ATAC and Cotral share many stops inside Rome but not their ids or name spelling
("TIBURTINA/PORTONACCIO" vs "ROMA | Via Tiburtina Via Portonaccio"). A Cotral stop
named "ROMA | ..." matches an ATAC stop when:
  - the ATAC stop is within MAX_FROM_GTFS_M of the Cotral GTFS position,
  - their names share a word (street names, after dropping "via", "piazza", ...),
  - the ATAC stop is on the RIGHT of the Cotral trip's direction of travel, within
    MAX_FROM_SHAPE_M of its shape: same-named ATAC stops usually exist for both
    directions, and a stop is always on the right (doors open on the right).
The nearest such ATAC stop wins.

Output: data/atac_stops.csv with stop_id, lat, lon, atac_stop_id, atac_name,
gtfs_offset_m, candidates (name matches within reach, either side).

Usage, from the repository root:
    .venv/bin/python experiments/explore/atac_stops.py
"""

import csv
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.geo import bearing_deg, distance_m  # noqa: E402

COTRAL = Path("GTFS_COTRAL")
ATAC = Path("GTFS_ATAC")
OUT = Path("data/atac_stops.csv")
MAX_FROM_GTFS_M = 150.0
MAX_FROM_SHAPE_M = 25.0
GRID = 200  # cells per degree for the spatial index: about 550 m x 400 m here
NOISE = {"via", "viale", "piazza", "piazzale", "largo", "roma", "di", "del", "della", "dei", "degli",
         "le", "la", "il", "fs", "staz", "stazione", "metro", "fermata"}
COLUMNS = ("stop_id", "lat", "lon", "atac_stop_id", "atac_name", "gtfs_offset_m", "candidates")


def words(name: str) -> set[str]:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"#.*", "", name).split("|", 1)[-1]
    return {w for w in re.findall(r"[a-z]{3,}", name) if w not in NOISE}


def local(lat0, lon0, lat, lon):
    d = distance_m(lat0, lon0, lat, lon)
    b = math.radians(bearing_deg(lat0, lon0, lat, lon))
    return d * math.sin(b), d * math.cos(b)


def right_of(lat, lon, shape):
    """(distance to the shape, signed distance: + right of travel)."""
    xy = [local(lat, lon, a, b) for a, b in shape]
    best = (math.inf, 0.0)
    for (ax, ay), (bx, by) in zip(xy, xy[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 < 1e-6:
            continue
        t = max(0.0, min(1.0, (-ax * dx - ay * dy) / length2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[0]:
            best = (d, -(dx * -py - dy * -px) / math.sqrt(length2))
    return best


def main() -> int:
    cotral = {r["stop_id"]: r for r in csv.DictReader((COTRAL / "stops.txt").open(encoding="utf-8"))
              if r["stop_name"].upper().startswith("ROMA |")}
    atac = [r for r in csv.DictReader((ATAC / "stops.txt").open(encoding="utf-8-sig")) if r.get("location_type") in ("", "0")]
    grid = defaultdict(list)
    for a in atac:
        grid[(round(float(a["stop_lat"]) * GRID), round(float(a["stop_lon"]) * GRID))].append(a)

    trip_shape = {r["trip_id"]: r["shape_id"] for r in csv.DictReader((COTRAL / "trips.txt").open(encoding="utf-8"))}
    shapes_of: dict[str, Counter] = defaultdict(Counter)
    with (COTRAL / "stop_times.txt").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["stop_id"] in cotral:
                shapes_of[r["stop_id"]][trip_shape.get(r["trip_id"], "")] += 1
    wanted = {s for c in shapes_of.values() for s in c}
    shapes = defaultdict(list)
    with (COTRAL / "shapes.txt").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["shape_id"] in wanted:
                shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lat"]), float(r["shape_pt_lon"])))
    shapes = {k: [(a, b) for _, a, b in sorted(v)] for k, v in shapes.items()}

    out, no_shape = [], 0
    for stop_id, s in sorted(cotral.items()):
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        cell = (round(lat * GRID), round(lon * GRID))
        named = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for a in grid[(cell[0] + dy, cell[1] + dx)]:
                    d = distance_m(lat, lon, float(a["stop_lat"]), float(a["stop_lon"]))
                    if d <= MAX_FROM_GTFS_M and words(s["stop_name"]) & words(a["stop_name"]):
                        named.append((d, a))
        if not named:
            continue
        common = shapes_of.get(stop_id, Counter()).most_common(1)
        shape = shapes.get(common[0][0]) if common else None
        if not shape:
            no_shape += 1
            continue
        right = []
        for d, a in named:
            dist, signed = right_of(float(a["stop_lat"]), float(a["stop_lon"]), shape)
            if dist <= MAX_FROM_SHAPE_M and signed > 0:
                right.append((d, a))
        if not right:
            continue
        d, a = min(right, key=lambda pair: pair[0])
        out.append({"stop_id": stop_id, "lat": float(a["stop_lat"]), "lon": float(a["stop_lon"]),
                    "atac_stop_id": a["stop_id"], "atac_name": a["stop_name"], "gtfs_offset_m": round(d, 1),
                    "candidates": len(named)})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out)
    print(f"Wrote {len(out)} of {len(cotral)} Cotral stops in Rome to {OUT}; {no_shape} skipped for lack of a shape")
    return 0


if __name__ == "__main__":
    sys.exit(main())
