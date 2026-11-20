import logging
import math
from dataclasses import dataclass, field

from ..caches import MetadataCache
from ..osm_match import OsmMatch, match_osm
from ..osm_store import OsmStore, bbox_around
from ..roadpath import LocalFrame, RoadGraph, match
from ..routes import Service, clip
from ..stops import Stop, is_cotral_stop
from .geometry import PathFrame, angle_diff

logger = logging.getLogger(__name__)

REACH_M = 1500.0
MAX_LIMIT_M = 1000.0
LIMIT_MARGIN_M = 30.0
PANO_STEP_M = 10.0
PANO_RADIUS_M = 15.0
UNSCANNED_M = 15.0
HINT_MAX_OFFSET_M = 25.0
OTHER_STOP_MAX_OFFSET_M = 30.0
MIN_SCAN_DATE = "2024-01"
CELL_M = 4.0
START_REACH_M = 25.0


@dataclass(frozen=True)
class Placed:
    label: str
    kind: str
    lat: float
    lon: float
    along: float
    offset: float
    ref: str = ""


@dataclass(frozen=True)
class Panorama:
    pano_id: str
    lat: float
    lon: float
    date: str
    along: float
    offset: float
    copyright: str


@dataclass
class World:
    stop: Stop
    frame: LocalFrame
    path: PathFrame
    limits: tuple[float, float]
    starts: list[Placed]
    hints: list[Placed]
    others: list[Placed]
    panoramas: list[Panorama] = field(default_factory=list)
    previous: Placed | None = None
    next: Placed | None = None
    found: list[Placed] = field(default_factory=list)

    def cells(self) -> list[float]:
        lo, hi = self.limits
        n = int(math.ceil((hi - lo) / CELL_M))
        return [lo + (i + 0.5) * CELL_M for i in range(n)]

    def scanned(self, along: float) -> bool:
        p = self.path.point(along)
        return any(math.dist(p, self.frame.to_xy(q.lat, q.lon)) <= UNSCANNED_M for q in self.panoramas)

    def latlon(self, p) -> tuple[float, float]:
        return self.frame.to_latlon(*p)


def build_world(stop: Stop, services: list[Service], shapes: dict[str, list[tuple[float, float]]],
                all_stops: dict[str, Stop], places: tuple[float, float] | None, store: OsmStore,
                metadata: MetadataCache) -> World:
    world = _build_world(stop, services, shapes, all_stops, places, store, metadata, 0.0)
    shift = _visible_start_shift(world)
    if shift:
        world = _build_world(stop, services, shapes, all_stops, places, store, metadata, shift)
    return world


def _visible_start_shift(world: World) -> float:
    start = world.starts[0]
    if not start.kind.startswith("osm") or world.scanned(start.along):
        return 0.0
    q = world.frame.to_xy(start.lat, start.lon)
    best = None
    for a in _frange(world.path.first, world.path.last, 2.0):
        p = world.path.point(a)
        d = math.dist(p, q)
        if d > START_REACH_M or not world.scanned(a):
            continue
        rx, ry = world.path.right(a)
        on_right = (q[0] - p[0]) * rx + (q[1] - p[1]) * ry > 0
        key = (not on_right, d)
        if best is None or key < best[0]:
            best = (key, a)
    return best[1] - start.along if best else 0.0


def _build_world(stop: Stop, services: list[Service], shapes: dict[str, list[tuple[float, float]]],
                 all_stops: dict[str, Stop], places: tuple[float, float] | None, store: OsmStore,
                 metadata: MetadataCache, start_shift: float) -> World:
    frame = LocalFrame(stop.lat, stop.lon)
    service = next((s for s in services if len(shapes.get(s.shape_id, [])) >= 2), None)
    if service is None:
        raise ValueError(f"no shape serves {stop.stop_id}")
    raw = clip(shapes[service.shape_id], stop.lat, stop.lon, REACH_M)
    roads = store.roads_in(bbox_around(stop.lat, stop.lon, REACH_M + 300))
    matched = match([frame.to_xy(*p) for p in raw], RoadGraph(roads, frame))
    pieces = matched.pieces or [[frame.to_xy(*p) for p in raw]]
    probe = PathFrame(min(pieces, key=lambda pc: _distance_to(pc, (0.0, 0.0))), 0.0)
    gtfs_s, _, _ = probe.locate((0.0, 0.0))

    osm = match_osm(stop, store, [s for s in all_stops.values() if is_cotral_stop(s)])
    start_ll = (osm.feature.lat, osm.feature.lon) if osm else places or (stop.lat, stop.lon)
    start_s, _, _ = probe.locate(frame.to_xy(*start_ll))
    path = PathFrame(probe.points, start_s + start_shift)

    def place(label, kind, lat, lon, ref="", before=None):
        xy = frame.to_xy(lat, lon)
        if before is None:
            along, offset, _ = path.locate(xy)
        else:
            along, offset = _locate_part(path, xy, gtfs_s - start_s - start_shift, before)
        return Placed(label, kind, lat, lon, along, offset, ref)

    starts = [place(_osm_label(osm), f"osm_{osm.how}", osm.feature.lat, osm.feature.lon, osm.feature.ref)] if osm else []
    if osm and start_shift:
        o = starts[0]
        p0, (rx, ry) = path.point(0.0), path.right(0.0)
        xy = frame.to_xy(o.lat, o.lon)
        starts[0] = Placed(o.label, o.kind, o.lat, o.lon, 0.0, (xy[0] - p0[0]) * rx + (xy[1] - p0[1]) * ry, o.ref)
    if places and math.hypot(*frame.to_xy(*places)) > 2.0:
        starts.append(place("Places", "places", *places))
    starts.append(place("GTFS", "gtfs", stop.lat, stop.lon))
    prev_stop = next((all_stops[i] for i in service.previous if i in all_stops), None)
    next_stop = next((all_stops[i] for i in service.next if i in all_stops), None)
    previous = place(f"{prev_stop.stop_id} {prev_stop.name}", "stop", prev_stop.lat, prev_stop.lon,
                     prev_stop.stop_id, before=True) if prev_stop else None
    following = place(f"{next_stop.stop_id} {next_stop.name}", "stop", next_stop.lat, next_stop.lon,
                      next_stop.stop_id, before=False) if next_stop else None

    lo = max(previous.along / 2 if previous else path.first, -MAX_LIMIT_M, path.first)
    hi = min(following.along / 2 if following else path.last, MAX_LIMIT_M, path.last)
    lo = min(lo, min(s.along for s in starts) - LIMIT_MARGIN_M)
    hi = max(hi, max(s.along for s in starts) + LIMIT_MARGIN_M)
    lo, hi = max(lo, path.first), min(hi, path.last)

    hints = []
    for f in store.stops_in(bbox_around(stop.lat, stop.lon, max(-lo, hi) + 100)):
        if osm and f.osm_id == osm.feature.osm_id:
            continue
        h = place(f"OSM {f.kind.replace('_', ' ')}" + (f" '{f.name}'" if f.name else ""), f.kind, f.lat, f.lon, f.ref)
        if lo - 20 <= h.along <= hi + 20 and abs(h.offset) <= HINT_MAX_OFFSET_M:
            hints.append(h)
    others = []
    south, west, north, east = bbox_around(stop.lat, stop.lon, max(-lo, hi) + 100)
    for other in all_stops.values():
        if other.stop_id == stop.stop_id or not (south <= other.lat <= north and west <= other.lon <= east):
            continue
        o = place(f"{other.stop_id} {other.name}", "stop", other.lat, other.lon, other.stop_id)
        if lo <= o.along <= hi and abs(o.offset) <= OTHER_STOP_MAX_OFFSET_M:
            others.append(o)

    world = World(stop=stop, frame=frame, path=path, limits=(lo, hi), starts=starts,
                  hints=sorted(hints, key=lambda h: h.along), others=sorted(others, key=lambda o: o.along),
                  previous=previous, next=following)
    world.panoramas = find_panoramas(world, metadata)
    return world


def _osm_label(osm: OsmMatch) -> str:
    f = osm.feature
    what = f"OSM {f.kind.replace('_', ' ')}" + (f" '{f.name}'" if f.name else "")
    if osm.how == "ref":
        return f"{what} with this stop's id ({f.ref})"
    return f"{what}, the stop-like object nearest this stop"


def find_panoramas(world: World, metadata: MetadataCache, at: float | None = None) -> list[Panorama]:
    lo, hi = world.limits
    if at is None:
        first = math.ceil((lo + world.path.start_s) / PANO_STEP_M) * PANO_STEP_M - world.path.start_s
        probes = [(a, 0.0, PANO_RADIUS_M) for a in _frange(first, hi, PANO_STEP_M)]
    else:
        probes = [(at + da, off, 6.0) for da in (-6.0, 0.0, 6.0) for off in (-14.0, -9.0, -4.0, 4.0, 9.0, 14.0)]
    found: dict[str, Panorama] = {p.pano_id: p for p in world.panoramas}
    for along, offset, radius in probes:
        lat, lon = world.latlon(world.path.point(along, offset))
        m = metadata.get(lat, lon, radius)
        if m is None or m.pano_id in found or not m.is_google or not m.date or m.date < MIN_SCAN_DATE:
            continue
        a, off, _ = world.path.locate(world.frame.to_xy(m.lat, m.lon))
        found[m.pano_id] = Panorama(m.pano_id, m.lat, m.lon, m.date, a, off, m.copyright)
    metadata.save()
    return sorted(found.values(), key=lambda p: p.along)


def _frange(lo: float, hi: float, step: float):
    v = lo
    while v <= hi + 1e-9:
        yield v
        v += step


def _distance_to(points, p) -> float:
    return min(math.dist(p, q) for q in points)


def _locate_part(path: PathFrame, xy, split_along: float, before: bool) -> tuple[float, float]:
    best = (math.inf, 0.0, 0.0)
    steps = int((path.last - path.first) / 2) + 1
    for i in range(steps + 1):
        a = path.first + i * (path.last - path.first) / steps
        if (a > split_along) if before else (a < split_along):
            continue
        p = path.point(a)
        d = math.dist(p, xy)
        if d < best[0]:
            rx, ry = path.right(a)
            best = (d, a, (xy[0] - p[0]) * rx + (xy[1] - p[1]) * ry)
    return best[1], best[2]


@dataclass(frozen=True)
class SharedStretch:
    a_from: float
    a_to: float
    b_from: float
    b_to: float
    opposite: bool


def shared_stretches(path: PathFrame, lo: float, hi: float, step: float = 5.0, near: float = 12.0,
                     min_gap: float = 40.0, min_length: float = 15.0) -> list[SharedStretch]:
    samples = list(_frange(lo, hi, step))
    others = list(_frange(max(lo - 100, path.first), min(hi + 100, path.last), step / 2))
    pairs: list[tuple[float, float, bool]] = []
    for a in samples:
        p = path.point(a)
        best = min(((math.dist(p, path.point(b)), b) for b in others if abs(b - a) >= min_gap),
                   default=(math.inf, 0.0))
        if best[0] <= near:
            b = best[1]
            pairs.append((a, b, abs(angle_diff(path.bearing(a), path.bearing(b))) > 120))
    runs: list[list[tuple[float, float, bool]]] = []
    for pair in pairs:
        last = runs[-1][-1] if runs else None
        if last and pair[0] - last[0] <= step * 1.5 and abs(pair[1] - last[1]) <= step * 3 and pair[2] == last[2]:
            runs[-1].append(pair)
        else:
            runs.append([pair])
    out = []
    for run in runs:
        a1, a2 = run[0][0], run[-1][0]
        bs = [b for _, b, _ in run]
        if a2 - a1 < min_length or (min(bs) < a1 and max(bs) >= lo):
            continue
        out.append(SharedStretch(a1, a2, run[0][1], run[-1][1], run[0][2]))
    return out
