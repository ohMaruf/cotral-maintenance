import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..roadpath import XY

SIDEWALK_M = 6.0
CAMERA_HEIGHT_M = 2.5
IMAGE_PX = 640
MIN_RANGE_M, MAX_RANGE_M = 2.0, 80.0
PASS_TOLERANCE_M = 4.0


def compass(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, dy)) % 360


def unit(bearing: float) -> XY:
    b = math.radians(bearing)
    return math.sin(b), math.cos(b)


def angle_diff(a: float, b: float) -> float:
    d = (a - b + 180) % 360 - 180
    return 180.0 if d == -180 else d


class PathFrame:
    def __init__(self, points: Sequence[XY], start_s: float) -> None:
        if len(points) < 2:
            raise ValueError("a path needs at least two points")
        self.points = list(points)
        self.cum = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.start_s = start_s

    @property
    def first(self) -> float:
        return -self.start_s

    @property
    def last(self) -> float:
        return self.cum[-1] - self.start_s

    def _segment(self, along: float) -> tuple[int, float]:
        s = min(max(along + self.start_s, 0.0), self.cum[-1])
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        length = self.cum[hi] - self.cum[lo]
        return lo, 0.0 if length == 0 else (s - self.cum[lo]) / length

    def point(self, along: float, offset: float = 0.0) -> XY:
        i, t = self._segment(along)
        a, b = self.points[i], self.points[i + 1]
        x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        if offset:
            rx, ry = self.right(along)
            x, y = x + offset * rx, y + offset * ry
        return x, y

    def bearing(self, along: float) -> float:
        i, _ = self._segment(along)
        a, b = self.points[i], self.points[i + 1]
        return compass(b[0] - a[0], b[1] - a[1])

    def right(self, along: float) -> XY:
        dx, dy = unit(self.bearing(along))
        return dy, -dx

    def sidewalk(self, along: float) -> XY:
        return self.point(along, SIDEWALK_M)

    def along_near(self, p: XY, around: float, window: float) -> float:
        lo, hi = max(around - window, self.first), min(around + window, self.last)
        n = max(2, int((hi - lo) / 0.5))
        return min((lo + i * (hi - lo) / n for i in range(n + 1)), key=lambda a: math.dist(self.point(a), p))

    def locate(self, p: XY) -> tuple[float, float, float]:
        hits = []
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            length = self.cum[i + 1] - self.cum[i]
            if length == 0:
                continue
            t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length ** 2))
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d = math.dist(p, q)
            cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
            hits.append((d, self.cum[i] + t * length - self.start_s, -math.copysign(d, cross) if cross else 0.0))
        nearest = min(h[0] for h in hits)
        close = [h for h in hits if h[0] <= nearest + PASS_TOLERANCE_M]
        right = [h for h in close if h[2] > 0]
        d, along, offset = min(right or close)
        return along, offset, d


@dataclass(frozen=True)
class Camera:
    position: XY
    heading: float
    fov: float
    pitch: float = 0.0
    width: int = IMAGE_PX
    height: int = IMAGE_PX

    @property
    def focal_px(self) -> float:
        return (self.width / 2) / math.tan(math.radians(self.fov / 2))

    def bearing_of(self, x: float) -> float:
        return (self.heading + math.degrees(math.atan((x - self.width / 2) / self.focal_px))) % 360

    def elevation_of(self, y: float) -> float:
        return self.pitch - math.degrees(math.atan((y - self.height / 2) / self.focal_px))

    def column_of(self, p: XY) -> float | None:
        d = angle_diff(compass(p[0] - self.position[0], p[1] - self.position[1]), self.heading)
        if abs(d) > self.fov / 2:
            return None
        return self.width / 2 + self.focal_px * math.tan(math.radians(d))

    def row_of(self, p: XY, height_m: float) -> float:
        d = max(math.dist(p, self.position), 0.1)
        elevation = math.degrees(math.atan((height_m - CAMERA_HEIGHT_M) / d))
        return self.height / 2 - self.focal_px * math.tan(math.radians(elevation - self.pitch))

    def ground_range(self, y: float) -> float | None:
        elevation = self.elevation_of(y)
        if elevation >= -0.5:
            return None
        return min(max(CAMERA_HEIGHT_M / math.tan(math.radians(-elevation)), MIN_RANGE_M), MAX_RANGE_M)

    def pixels_across(self, size_m: float, distance_m: float) -> float:
        return size_m / max(distance_m, 0.1) * self.focal_px


def ray_point(origin: XY, bearing: float, distance: float) -> XY:
    ux, uy = unit(bearing)
    return origin[0] + distance * ux, origin[1] + distance * uy


def ray_to_sidewalk(path: PathFrame, origin: XY, bearing: float) -> XY | None:
    previous = None
    step = 0.5
    d = MIN_RANGE_M
    while d <= MAX_RANGE_M:
        p = ray_point(origin, bearing, d)
        _, offset, _ = path.locate(p)
        gap = offset - SIDEWALK_M
        if previous is not None and (previous <= 0 < gap or previous >= 0 > gap):
            return p
        previous = gap
        d += step
    return None


def triangulate(rays: Sequence[tuple[XY, float]]) -> tuple[XY, float] | None:
    if len(rays) < 2:
        return None
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (ox, oy), bearing in rays:
        ux, uy = unit(bearing)
        nx, ny = uy, -ux
        c = nx * ox + ny * oy
        a11 += nx * nx
        a12 += nx * ny
        a22 += ny * ny
        b1 += nx * c
        b2 += ny * c
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-3:
        return None
    x = (b1 * a22 - b2 * a12) / det
    y = (a11 * b2 - a12 * b1) / det
    residuals = [(uy * (x - ox) - ux * (y - oy)) for (ox, oy), b in rays for ux, uy in [unit(b)]]
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    return (x, y), rms
