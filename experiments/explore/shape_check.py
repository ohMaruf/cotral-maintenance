"""Visual check: do the GTFS shapes, and the shapes snapped onto OSM roads, pass by the
verified stop positions?

Picks the verified stops worth a look, each with the reasons ("flags"):
  moved             the verifier moved it at least --min-offset metres
  left_of_path      the verified position is left of the snapped path (stops never are)
                    by more than SIDE_TOLERANCE_M
  far_from_path     the verified position is over FAR_M from the snapped path
  on_detour         the verified position is on a loop or out-and-back stretch
(the last three from data/route_paths/stops.csv, see route_paths.py). For each it
records, for the Shapes page of the review app:
  - the shapes of the trips serving it, around the stop, with direction arrows, and
    each shape snapped onto the roads (data/route_paths/paths.json)
  - the GTFS, Places (when fetched) and verified positions
  - every OSM stop-like object nearby, of any kind (data/osm/osm.sqlite3)
  - the previous and next stops of those trips
Output: data/shape_check/stops.json (layout in docs/explore-api.md). Verdicts are
recorded on the page (./start.sh, then /shapes) and exported as CSV.

Usage, from the repository root (after route_paths.py):
    .venv/bin/python experiments/explore/shape_check.py [--min-offset 50]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.fileutils import write_json_atomic
from cotral_maintenance.geo import bearing_deg
from cotral_maintenance.osm_store import OsmStore, bbox_around
from cotral_maintenance.provenance import utc_now
from cotral_maintenance.roadpath import LocalFrame, locate
from cotral_maintenance.routes import clip, load_services, load_shapes
from cotral_maintenance.stops import load_stops

GTFS = Path("GTFS_COTRAL")
TRUTH = Path("data/ground_truth_manual.csv")
CORRECTED = Path("data/stops_corrected.csv")
STORE = Path("data/osm/osm.sqlite3")
ROUTE_PATHS = Path("data/route_paths")
OUT = Path("data/shape_check/stops.json")
CLIP_M = 1200.0  # shape drawn this far along it from the stop, each way
ARROW_EVERY_M = 120.0
FEATURES_WITHIN_M = 200.0
SIDE_TOLERANCE_M = 3.0
FAR_M = 25.0


def arrows(points):
    """{lat, lon, bearing} every ARROW_EVERY_M along a polyline of (lat, lon)."""
    frame = LocalFrame(*points[0])
    xy = [frame.to_xy(*p) for p in points]
    out, run = [], ARROW_EVERY_M / 2
    for (a, b), (pa, pb) in zip(zip(points, points[1:]), zip(xy, xy[1:])):
        seg = ((pb[0] - pa[0]) ** 2 + (pb[1] - pa[1]) ** 2) ** 0.5
        while seg > 0 and run <= seg:
            f = run / seg
            out.append({"lat": round(a[0] + f * (b[0] - a[0]), 6), "lon": round(a[1] + f * (b[1] - a[1]), 6),
                        "bearing": round(bearing_deg(*a, *b))})
            run += ARROW_EVERY_M
        run -= seg
    return out


def flags_of(row: dict, min_offset: float) -> list[str]:
    flags = []
    if float(row["offset_m"]) >= min_offset:
        flags.append("moved")
    if row["truth_side_path"] == "left" and float(row["truth_path_m"]) > SIDE_TOLERANCE_M:
        flags.append("left_of_path")
    if float(row["truth_path_m"]) > FAR_M:
        flags.append("far_from_path")
    if row["stop_on_path_detour"] == "True":
        flags.append("on_detour")
    return flags


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-offset", type=float, default=50.0, help="verifier correction, metres")
    args = parser.parse_args()
    for needed in (STORE, ROUTE_PATHS / "stops.csv"):
        if not needed.is_file():
            raise SystemExit(f"{needed} missing: run build_osm_store.py, then route_paths.py")

    truth = {r["stop_id"]: r for r in read_csv(TRUTH)}
    measured = {r["stop_id"]: r for r in read_csv(ROUTE_PATHS / "stops.csv")}
    snapped = json.loads((ROUTE_PATHS / "paths.json").read_text(encoding="utf-8"))["stops"]
    flags = {i: f for i, r in measured.items() if (f := flags_of(r, args.min_offset))}
    for stop_id, t in truth.items():  # moved stops without a measured path still count
        if stop_id not in measured and float(t["offset_m"]) >= args.min_offset:
            flags[stop_id] = ["moved"]

    stops = {s.stop_id: s for s in load_stops(GTFS / "stops.txt")}
    places = {r["stop_id"]: r for r in read_csv(CORRECTED) if r["coord_source"] == "places"}
    services = load_services(GTFS, flags)
    shapes = load_shapes(GTFS, {s.shape_id for v in services.values() for s in v})
    store = OsmStore(STORE)

    def position(stop_id):
        s = stops.get(stop_id)
        return {"id": stop_id, "name": s.name, "lat": s.lat, "lon": s.lon} if s else None

    data = []
    for stop_id in sorted(flags, key=lambda i: -float(truth[i]["offset_m"])):
        t, g = truth[stop_id], stops[stop_id]
        tlat, tlon = float(t["lat"]), float(t["lon"])
        frame = LocalFrame(g.lat, g.lon)
        tp = frame.to_xy(tlat, tlon)
        routes, neighbours = [], {}
        for service in services.get(stop_id, []):
            points = shapes.get(service.shape_id, [])
            if len(points) < 2:
                continue
            part = clip(points, g.lat, g.lon, CLIP_M)
            xy = [frame.to_xy(*p) for p in part]
            _, truth_off, truth_d = locate(xy, tp)
            _, _, gtfs_d = locate(xy, (0.0, 0.0))
            pieces = snapped.get(stop_id, {}).get(service.shape_id, [])
            path = None
            if pieces:
                nearest = min(pieces, key=lambda pc: locate([frame.to_xy(*p) for p in pc], tp)[2])
                _, off, d = locate([frame.to_xy(*p) for p in nearest], tp)
                path = (round(d, 1), "right" if off > 0 else "left")
            for nb in (*service.previous, *service.next):
                if nb not in neighbours and (p := position(nb)):
                    neighbours[nb] = p
            routes.append({
                "shape": service.shape_id, "trips": service.trips,
                "points": [[round(a, 6), round(b, 6)] for a, b in part], "arrows": arrows(part),
                "truth_m": round(truth_d, 1), "truth_side": "right" if truth_off > 0 else "left",
                "gtfs_m": round(gtfs_d, 1), "prev": list(service.previous), "next": list(service.next),
                "matched": pieces or None,
                "truth_path_m": path[0] if path else None, "truth_path_side": path[1] if path else None,
            })
        p = places.get(stop_id)
        features = store.stops_in(bbox_around(tlat, tlon, FEATURES_WITHIN_M))
        data.append({
            "id": stop_id, "name": g.name, "offset_m": float(t["offset_m"]), "flags": flags[stop_id],
            "has_sign": t["has_sign"], "comments": t["comments"],
            "gtfs": [g.lat, g.lon], "truth": [tlat, tlon],
            "places": [float(p["stop_lat"]), float(p["stop_lon"])] if p else None,
            "osm_features": [{"id": f.osm_id, "kind": f.kind, "lat": round(f.lat, 7), "lon": round(f.lon, 7),
                              "ref": f.ref, "name": f.name, "operator": f.operator} for f in features],
            "routes": routes, "neighbours": list(neighbours.values()),
        })

    write_json_atomic(OUT, {"generated_at": utc_now(), "min_offset_m": args.min_offset, "stops": data})
    counts = {f: sum(f in d["flags"] for d in data) for f in ("moved", "left_of_path", "far_from_path", "on_detour")}
    print(f"Wrote {OUT}: {len(data)} stops ({', '.join(f'{k} {v}' for k, v in counts.items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
