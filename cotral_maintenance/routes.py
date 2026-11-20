import csv
from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from .geo import distance_m

LatLon = tuple[float, float]


@dataclass(frozen=True)
class Service:
    shape_id: str
    trips: int
    previous: tuple[str, ...]
    next: tuple[str, ...]


def load_services(gtfs_dir: Path, stop_ids: Collection[str]) -> dict[str, list[Service]]:
    wanted = set(stop_ids)
    trip_shape = {r["trip_id"]: r["shape_id"] for r in _rows(gtfs_dir / "trips.txt")}
    counts: dict[str, Counter] = defaultdict(Counter)

    def flush(trip: str, calls: list[tuple[int, str]]) -> None:
        calls.sort()
        shape = trip_shape.get(trip, "")
        for i, (_, stop_id) in enumerate(calls):
            if stop_id in wanted:
                before = calls[i - 1][1] if i else ""
                after = calls[i + 1][1] if i + 1 < len(calls) else ""
                counts[stop_id][(shape, before, after)] += 1

    current, calls = None, []
    for r in _rows(gtfs_dir / "stop_times.txt"):
        if r["trip_id"] != current:
            if calls:
                flush(current, calls)
            current, calls = r["trip_id"], []
        calls.append((int(r["stop_sequence"]), r["stop_id"]))
    if calls:
        flush(current, calls)

    services = {}
    for stop_id, by_key in counts.items():
        by_shape: dict[str, list] = defaultdict(lambda: [0, set(), set()])
        for (shape, before, after), n in by_key.items():
            entry = by_shape[shape]
            entry[0] += n
            if before:
                entry[1].add(before)
            if after:
                entry[2].add(after)
        services[stop_id] = sorted(
            (Service(shape, n, tuple(sorted(b)), tuple(sorted(a))) for shape, (n, b, a) in by_shape.items() if shape),
            key=lambda s: (-s.trips, s.shape_id))
    return services


def load_shapes(gtfs_dir: Path, shape_ids: Collection[str]) -> dict[str, list[LatLon]]:
    wanted = set(shape_ids)
    points: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for r in _rows(gtfs_dir / "shapes.txt"):
        if r["shape_id"] in wanted:
            points[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lat"]),
                                          float(r["shape_pt_lon"])))
    return {k: [(lat, lon) for _, lat, lon in sorted(v)] for k, v in points.items()}


def clip(points: list[LatLon], lat: float, lon: float, reach_m: float) -> list[LatLon]:
    nearest = min(range(len(points)), key=lambda i: distance_m(lat, lon, *points[i]))
    lo = hi = nearest
    run = 0.0
    while lo > 0 and run < reach_m:
        run += distance_m(*points[lo - 1], *points[lo])
        lo -= 1
    run = 0.0
    while hi < len(points) - 1 and run < reach_m:
        run += distance_m(*points[hi], *points[hi + 1])
        hi += 1
    return points[lo: hi + 1]


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)
