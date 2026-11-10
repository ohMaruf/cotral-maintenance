"""Measure, on the verified stops, what snapping shapes to roads changes, and what OSM offers.

For every verified stop (data/ground_truth_manual.csv), take its main shape (most
trips) within REACH_M along it, snap it onto the OSM roads (cotral_maintenance/
roadpath.py) and compare the raw shape and the snapped path:
  - distance and side of travel of the verified position, and of the GTFS one
  - straightness: how far the path strays from a straight line within ±STRAIGHT_M
    of the stop (a straight "road frame" search misses what lies off that line)
  - detours: a stretch near the stop where the path covers at least DETOUR_MIN_M
    but ends up less than a third of that from where it started (loops, out-and-back
    spurs into a square or a station)
and count the OSM stop-like objects of every kind near the verified position.

Output:
  data/route_paths/stops.csv   one row per stop
  data/route_paths/paths.json  snapped paths per stop and shape, for the Shapes page
Prints a summary.

Usage, from the repository root (after build_osm_store.py):
    .venv/bin/python experiments/explore/route_paths.py [--limit N]
"""

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.fileutils import write_dataset, write_json_atomic
from cotral_maintenance.osm_store import STOP_KINDS, OsmStore, bbox_around
from cotral_maintenance.roadpath import LocalFrame, RoadGraph, locate, match, polyline_length
from cotral_maintenance.routes import clip, load_services, load_shapes
from cotral_maintenance.stops import load_stops

GTFS = Path("GTFS_COTRAL")
TRUTH = Path("data/ground_truth_manual.csv")
STORE = Path("data/osm/osm.sqlite3")
OUT_DIR = Path("data/route_paths")
REACH_M = 1200.0
ROAD_MARGIN_M = 300.0
STRAIGHT_M = 150.0
STRAIGHT_TOLERANCE_M = 15.0
DETOUR_WINDOW_M = 300.0
DETOUR_MIN_M = 100.0
DETOUR_MAX_M = 800.0
SAMPLE_M = 10.0
OSM_RADII_M = (15, 30, 50)


@dataclass
class StopRow:
    stop_id: str
    offset_m: float  # verifier's correction
    shape_id: str
    trips: int
    services: int
    pieces: int
    unmatched_points: int
    raw_length_m: float
    path_length_m: float
    truth_raw_m: float
    truth_path_m: float
    truth_side_raw: str
    truth_side_path: str
    gtfs_side_path: str
    gtfs_path_m: float
    straight_dev_raw_m: float
    straight_dev_path_m: float
    detour_near_raw: bool
    detour_near_path: bool
    stop_on_path_detour: bool
    osm_nearest_m: float | None
    osm_nearest_kind: str
    osm_within: str  # JSON: radius -> kind -> count
    seconds: float


def resample(points, step=SAMPLE_M):
    """(along, x, y) every `step` metres along a polyline."""
    out, run = [(0.0, *points[0])], 0.0
    next_at = step
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        while length and next_at <= run + length:
            t = (next_at - run) / length
            out.append((next_at, a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
            next_at += step
        run += length
    return out


def straight_deviation(points, along0) -> float:
    """Max distance of the polyline from the chord between its points at along0 ± STRAIGHT_M."""
    samples = [s for s in resample(points) if abs(s[0] - along0) <= STRAIGHT_M]
    if len(samples) < 3:
        return 0.0
    (_, ax, ay), (_, bx, by) = samples[0], samples[-1]
    chord = math.hypot(bx - ax, by - ay)
    if chord < 1:
        return max(math.hypot(x - ax, y - ay) for _, x, y in samples)
    return max(abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / chord for _, x, y in samples)


def detours(points, along0) -> list[tuple[float, float]]:
    """(start, end) along the polyline of detours within DETOUR_WINDOW_M of along0."""
    samples = [s for s in resample(points) if abs(s[0] - along0) <= DETOUR_WINDOW_M]
    found = []
    for i, (si, xi, yi) in enumerate(samples):
        for sj, xj, yj in samples[i + 1:]:
            path = sj - si
            if path > DETOUR_MAX_M:
                break
            if path >= DETOUR_MIN_M and math.hypot(xj - xi, yj - yi) < path / 3:
                found.append((si, sj))
    return found


def side(offset: float) -> str:
    return "right" if offset > 0 else "left" if offset < 0 else "on"


def nearest_piece(pieces, p):
    return min(pieces, key=lambda piece: locate(piece, p)[2]) if pieces else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if not STORE.is_file():
        raise SystemExit(f"{STORE} missing: run experiments/explore/build_osm_store.py")

    truth = {r["stop_id"]: r for r in csv.DictReader(TRUTH.open(encoding="utf-8"))}
    ids = sorted(truth)[: args.limit] if args.limit else sorted(truth)
    gtfs = {s.stop_id: s for s in load_stops(GTFS / "stops.txt")}
    services = load_services(GTFS, ids)
    shapes = load_shapes(GTFS, {s.shape_id for v in services.values() for s in v})
    store = OsmStore(STORE)

    rows: list[StopRow] = []
    paths: dict[str, dict[str, list]] = {}
    for stop_id in ids:
        if stop_id not in gtfs or not services.get(stop_id):
            continue
        start = time.monotonic()
        stop, t = gtfs[stop_id], truth[stop_id]
        frame = LocalFrame(stop.lat, stop.lon)
        tp, gp = frame.to_xy(float(t["lat"]), float(t["lon"])), (0.0, 0.0)
        roads = store.roads_in(bbox_around(stop.lat, stop.lon, REACH_M + ROAD_MARGIN_M))
        graph = RoadGraph(roads, frame)

        paths[stop_id] = {}
        main_row = None
        for service in services[stop_id]:
            points = shapes.get(service.shape_id)
            if not points or len(points) < 2:
                continue
            raw = [frame.to_xy(*p) for p in clip(points, stop.lat, stop.lon, REACH_M)]
            matched = match(raw, graph)
            paths[stop_id][service.shape_id] = [[[round(a, 6), round(b, 6)] for a, b in piece]
                                                for piece in matched.latlon()]
            if main_row is not None:
                continue
            piece = nearest_piece(matched.pieces, tp)
            if piece is None or len(piece) < 2:
                continue
            raw_along, raw_off, raw_d = locate(raw, tp)
            along, off, d = locate(piece, tp)
            _, g_off, g_d = locate(piece, gp)
            path_detours = detours(piece, along)
            features = store.stops_in(bbox_around(float(t["lat"]), float(t["lon"]), max(OSM_RADII_M)))
            dists = sorted((math.dist(tp, frame.to_xy(f.lat, f.lon)), f.kind) for f in features)
            within = {r: dict(Counter(k for dd, k in dists if dd <= r)) for r in OSM_RADII_M}
            main_row = StopRow(
                stop_id=stop_id, offset_m=float(t["offset_m"]), shape_id=service.shape_id, trips=service.trips,
                services=len(services[stop_id]), pieces=len(matched.pieces), unmatched_points=matched.unmatched,
                raw_length_m=round(polyline_length(raw), 1), path_length_m=round(matched.length, 1),
                truth_raw_m=round(raw_d, 1), truth_path_m=round(d, 1), truth_side_raw=side(raw_off),
                truth_side_path=side(off), gtfs_side_path=side(g_off), gtfs_path_m=round(g_d, 1),
                straight_dev_raw_m=round(straight_deviation(raw, raw_along), 1),
                straight_dev_path_m=round(straight_deviation(piece, along), 1),
                detour_near_raw=bool(detours(raw, raw_along)), detour_near_path=bool(path_detours),
                stop_on_path_detour=any(a <= along <= b for a, b in path_detours),
                osm_nearest_m=round(dists[0][0], 1) if dists else None,
                osm_nearest_kind=dists[0][1] if dists else "",
                osm_within=json.dumps(within, sort_keys=True), seconds=0.0,
            )
        if main_row:
            main_row.seconds = round(time.monotonic() - start, 2)
            rows.append(main_row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_dataset(rows, StopRow, OUT_DIR / "stops.csv")
    write_json_atomic(OUT_DIR / "paths.json", {"reach_m": REACH_M, "stops": paths})
    summarise(rows)
    return 0


def pct(n: int, total: int) -> str:
    return f"{n} ({n / total:.0%})" if total else "0"


def summarise(rows: list[StopRow]) -> None:
    n = len(rows)
    med = lambda xs: round(statistics.median(xs), 1)  # noqa: E731
    print(f"{n} verified stops with a shape; median {med([r.seconds for r in rows])} s per stop")
    print(f"snapping: {pct(sum(r.pieces == 1 for r in rows), n)} in one piece; "
          f"path/raw length median {med([r.path_length_m / r.raw_length_m for r in rows if r.raw_length_m])}")
    print(f"verified -> raw shape: median {med([r.truth_raw_m for r in rows])} m, "
          f"within 10 m {pct(sum(r.truth_raw_m <= 10 for r in rows), n)}, "
          f"right of travel {pct(sum(r.truth_side_raw == 'right' for r in rows), n)}")
    print(f"verified -> snapped path: median {med([r.truth_path_m for r in rows])} m, "
          f"within 10 m {pct(sum(r.truth_path_m <= 10 for r in rows), n)}, "
          f"right of travel {pct(sum(r.truth_side_path == 'right' for r in rows), n)}")
    print(f"GTFS position left of the snapped path: {pct(sum(r.gtfs_side_path == 'left' for r in rows), n)}")
    for name, key in (("raw shape", "straight_dev_raw_m"), ("snapped path", "straight_dev_path_m")):
        bent = sum(getattr(r, key) > STRAIGHT_TOLERANCE_M for r in rows)
        print(f"{name}: strays > {STRAIGHT_TOLERANCE_M:.0f} m from a straight line within ±{STRAIGHT_M:.0f} m "
              f"of the stop for {pct(bent, n)}")
    print(f"detour within ±{DETOUR_WINDOW_M:.0f} m: raw shape {pct(sum(r.detour_near_raw for r in rows), n)}, "
          f"snapped path {pct(sum(r.detour_near_path for r in rows), n)}; "
          f"verified stop on the detour itself {pct(sum(r.stop_on_path_detour for r in rows), n)}")
    for radius in OSM_RADII_M:
        any_kind = sum(bool(json.loads(r.osm_within)[str(radius)]) for r in rows)
        kinds = Counter()
        for r in rows:
            for kind in json.loads(r.osm_within)[str(radius)]:
                kinds[kind] += 1
        detail = ", ".join(f"{k} {kinds[k]}" for k in STOP_KINDS if kinds[k])
        print(f"OSM stop-like object within {radius} m of the verified position: {pct(any_kind, n)} ({detail})")


if __name__ == "__main__":
    sys.exit(main())
