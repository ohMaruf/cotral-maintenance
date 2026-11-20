import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .osm_store import Road

SIGMA_M = 15.0
BETA_M = 60.0
CANDIDATE_RADIUS_M = 60.0
MAX_CANDIDATES = 6
EARTH_M = 6_371_000.0

XY = tuple[float, float]


@dataclass(frozen=True)
class LocalFrame:
    lat0: float
    lon0: float

    def to_xy(self, lat: float, lon: float) -> XY:
        k = math.pi / 180 * EARTH_M
        return (lon - self.lon0) * k * math.cos(math.radians(self.lat0)), (lat - self.lat0) * k

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        k = math.pi / 180 * EARTH_M
        return self.lat0 + y / k, self.lon0 + x / (k * math.cos(math.radians(self.lat0)))


@dataclass(frozen=True)
class Segment:
    u: int
    v: int
    way_id: int
    a: XY
    b: XY
    length: float
    forward: bool
    backward: bool


@dataclass(frozen=True)
class Candidate:
    segment: int
    t: float
    point: XY
    distance: float
    direction: int = 1


@dataclass(frozen=True)
class Route:
    length: float
    points: tuple[XY, ...]


State = tuple[int, int]


class RoadGraph:
    def __init__(self, roads: Sequence[Road], frame: LocalFrame) -> None:
        self.frame = frame
        self.xy: dict[int, XY] = {}
        self.segments: list[Segment] = []
        self.out: dict[int, list[tuple[int, float]]] = {}
        for road in roads:
            for node_id, (lat, lon) in zip(road.node_ids, road.coords, strict=True):
                self.xy.setdefault(node_id, frame.to_xy(lat, lon))
            for u, v in zip(road.node_ids, road.node_ids[1:]):
                if u == v:
                    continue
                a, b = self.xy[u], self.xy[v]
                length = math.dist(a, b)
                forward, backward = road.oneway >= 0, road.oneway <= 0
                self.segments.append(Segment(u, v, road.way_id, a, b, length, forward, backward))
                if forward:
                    self.out.setdefault(u, []).append((v, length))
                if backward:
                    self.out.setdefault(v, []).append((u, length))

    def candidates(self, p: XY, radius: float = CANDIDATE_RADIUS_M, limit: int = MAX_CANDIDATES) -> list[Candidate]:
        found = []
        for i, s in enumerate(self.segments):
            t, q = _project(p, s.a, s.b)
            d = math.dist(p, q)
            if d <= radius:
                if s.forward:
                    found.append(Candidate(i, t, q, d, 1))
                if s.backward:
                    found.append(Candidate(i, t, q, d, -1))
        found.sort(key=lambda c: c.distance)
        return found[: 2 * limit]

    def _turn_allowed(self, node: int, came_from: int, to: int) -> bool:
        return to != came_from or all(m == came_from for m, _ in self.out.get(node, ()))

    def routes_from(self, source: Candidate, targets: Sequence[Candidate], max_length: float) -> list[Route | None]:
        s = self.segments[source.segment]
        results: list[Route | None] = [None] * len(targets)
        for j, target in enumerate(targets):
            if target.segment == source.segment and target.direction == source.direction:
                along = (target.t - source.t) * s.length * source.direction
                if along >= 0:
                    results[j] = Route(along, (source.point, target.point))
        if source.direction > 0:
            start: State = (s.v, s.u)
            cost = (1 - source.t) * s.length
        else:
            start, cost = (s.u, s.v), source.t * s.length
        dist, previous = self._dijkstra(start, cost, max_length)
        by_node: dict[int, list[tuple[float, State]]] = {}
        for state, d in dist.items():
            by_node.setdefault(state[0], []).append((d, state))
        for j, target in enumerate(targets):
            g = self.segments[target.segment]
            entry, other, extra = (g.u, g.v, target.t * g.length) if target.direction > 0 else \
                (g.v, g.u, (1 - target.t) * g.length)
            options = [(d + extra, state) for d, state in by_node.get(entry, ())
                       if self._turn_allowed(entry, state[1], other)]
            if not options:
                continue
            length, state = min(options)
            if length <= max_length and (results[j] is None or length < results[j].length):
                nodes = _unwind(previous, state)
                results[j] = Route(length, (source.point, *(self.xy[n] for n in nodes), target.point))
        return results

    def _dijkstra(self, start: State, cost: float, max_length: float):
        dist: dict[State, float] = {}
        previous: dict[State, State | None] = {}
        counter = 0
        heap = [(cost, counter, start, None)]
        while heap:
            d, _, state, before = heapq.heappop(heap)
            if state in dist or d > max_length:
                continue
            dist[state], previous[state] = d, before
            node, came_from = state
            for m, length in self.out.get(node, ()):
                if self._turn_allowed(node, came_from, m) and (m, node) not in dist:
                    counter += 1
                    heapq.heappush(heap, (d + length, counter, (m, node), state))
        return dist, previous


def _unwind(previous: dict[State, State | None], state: State) -> list[int]:
    nodes = [state[0]]
    while previous[state] is not None:
        state = previous[state]
        nodes.append(state[0])
    return nodes[::-1]


def _project(p: XY, a: XY, b: XY) -> tuple[float, XY]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return t, (a[0] + t * dx, a[1] + t * dy)


@dataclass
class MatchedPath:
    frame: LocalFrame
    pieces: list[list[XY]] = field(default_factory=list)
    matched: int = 0
    unmatched: int = 0

    @property
    def length(self) -> float:
        return sum(polyline_length(p) for p in self.pieces)

    def latlon(self) -> list[list[tuple[float, float]]]:
        return [[self.frame.to_latlon(*p) for p in piece] for piece in self.pieces]


def match(points: Sequence[XY], graph: RoadGraph, sigma: float = SIGMA_M, beta: float = BETA_M) -> MatchedPath:
    path = MatchedPath(graph.frame)
    chain: _Chain | None = None
    for p in points:
        candidates = graph.candidates(p)
        if not candidates:
            path.unmatched += 1
            continue
        if chain is None or not chain.extend(p, candidates):
            if chain is not None:
                chain.finish(path)
            chain = _Chain(graph, sigma, beta, p, candidates)
    if chain is not None:
        chain.finish(path)
    return path


class _Chain:
    def __init__(self, graph: RoadGraph, sigma: float, beta: float, p: XY, candidates: list[Candidate]) -> None:
        self.graph, self.sigma, self.beta = graph, sigma, beta
        self.last_point = p
        self.first = candidates
        self.last = candidates
        self.score = [self._emit(c) for c in candidates]
        self.back: list[list[tuple[int, Route] | None]] = []

    def _emit(self, c: Candidate) -> float:
        return -0.5 * (c.distance / self.sigma) ** 2

    def extend(self, q: XY, targets: list[Candidate]) -> bool:
        straight = math.dist(self.last_point, q)
        limit = max(3 * straight, straight + 300.0)
        routes = [self.graph.routes_from(s, targets, limit) if self.score[i] > -math.inf else [None] * len(targets)
                  for i, s in enumerate(self.last)]
        score, pointers = [], []
        for j, target in enumerate(targets):
            best: tuple[float, tuple[int, Route] | None] = (-math.inf, None)
            for i, per_source in enumerate(routes):
                route = per_source[j]
                if route is not None:
                    value = self.score[i] - abs(route.length - straight) / self.beta
                    if value > best[0]:
                        best = (value, (i, route))
            score.append(best[0] + self._emit(target) if best[1] else -math.inf)
            pointers.append(best[1])
        if all(v == -math.inf for v in score):
            return False
        self.score, self.last, self.last_point = score, targets, q
        self.back.append(pointers)
        return True

    def finish(self, path: MatchedPath) -> None:
        j = max(range(len(self.score)), key=self.score.__getitem__)
        routes: list[Route] = []
        for pointers in reversed(self.back):
            i, route = pointers[j]
            routes.append(route)
            j = i
        routes.reverse()
        piece = [self.first[j].point]
        for route in routes:
            piece.extend(route.points[1:])
        path.pieces.append(_dedupe(piece))
        path.matched += len(self.back) + 1


def _dedupe(points: list[XY]) -> list[XY]:
    out = [points[0]]
    for p in points[1:]:
        if math.dist(p, out[-1]) > 0.01:
            out.append(p)
    return out


def polyline_length(points: Sequence[XY]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def locate(points: Sequence[XY], p: XY) -> tuple[float, float, float]:
    best = (math.inf, 0.0, 0.0)
    run = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length == 0:
            continue
        t, q = _project(p, a, b)
        d = math.dist(p, q)
        if d < best[0]:
            cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
            best = (d, run + t * length, -math.copysign(d, cross) if cross else 0.0)
        run += length
    distance, along, offset = best
    return along, offset, distance
