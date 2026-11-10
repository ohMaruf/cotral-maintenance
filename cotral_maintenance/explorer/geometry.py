"""Geometry of the explorer: metres along the bus's path, cameras, rays and sight lines.

Everything is in a LocalFrame (metres, x east, y north). Positions on the path are
`along` (metres from the start, + in the direction of travel) and `offset` (metres
from the path's centre line, + right of travel). The right-hand sidewalk of travel
is approximated by the line at offset SIDEWALK_M.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..roadpath import XY

SIDEWALK_M = 6.0  # centre line to the right-hand kerb side, typical two-lane road
CAMERA_HEIGHT_M = 2.5  # Street View camera above the ground
IMAGE_PX = 640
MIN_RANGE_M, MAX_RANGE_M = 2.0, 80.0
PASS_TOLERANCE_M = 4.0  # passes of an out-and-back stretch closer than this count as the same place


def compass(dx: float, dy: float) -> float:
    """Compass bearing (0 = north, 90 = east) of a direction in the local frame."""
    return math.degrees(math.atan2(dx, dy)) % 360


def unit(bearing: float) -> XY:
    b = math.radians(bearing)
    return math.sin(b), math.cos(b)


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference a - b, in (-180, 180]."""
    d = (a - b + 180) % 360 - 180
    return 180.0 if d == -180 else d


class PathFrame:
    """A polyline in travel order, measured in metres along it from a start point."""

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
        while hi - lo > 1:  # binary search for the segment holding s
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
        """Direction of travel at that point, as a compass bearing."""
        i, _ = self._segment(along)
        a, b = self.points[i], self.points[i + 1]
        return compass(b[0] - a[0], b[1] - a[1])

    def right(self, along: float) -> XY:
        """Unit vector pointing to the right of travel."""
        dx, dy = unit(self.bearing(along))
        return dy, -dx

    def sidewalk(self, along: float) -> XY:
        return self.point(along, SIDEWALK_M)

    def along_near(self, p: XY, around: float, window: float) -> float:
        """The position on the path within `window` metres of `around` that is nearest to p: places a
        point on one particular pass where the path goes by the same place twice."""
        lo, hi = max(around - window, self.first), min(around + window, self.last)
        n = max(2, int((hi - lo) / 0.5))
        return min((lo + i * (hi - lo) / n for i in range(n + 1)), key=lambda a: math.dist(self.point(a), p))

    def locate(self, p: XY) -> tuple[float, float, float]:
        """(along, offset, distance) of a point against the path. Where the path passes the same place
        more than once (an out-and-back stretch), the pass that has the point on its right wins: a stop
        is on the right of the pass the bus serves it from."""
        hits = []
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            length = self.cum[i + 1] - self.cum[i]
            if length == 0:
                continue
            t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length ** 2))
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d = math.dist(p, q)
            cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])  # > 0: left
            hits.append((d, self.cum[i] + t * length - self.start_s, -math.copysign(d, cross) if cross else 0.0))
        nearest = min(h[0] for h in hits)
        close = [h for h in hits if h[0] <= nearest + PASS_TOLERANCE_M]
        right = [h for h in close if h[2] > 0]
        d, along, offset = min(right or close)
        return along, offset, d


@dataclass(frozen=True)
class Camera:
    """A pinhole view from a panorama: `fov` is horizontal, pixels are of a width x height image."""

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
        """Compass bearing of a pixel column."""
        return (self.heading + math.degrees(math.atan((x - self.width / 2) / self.focal_px))) % 360

    def elevation_of(self, y: float) -> float:
        """Angle above the horizon of a pixel row (exact at the centre column)."""
        return self.pitch - math.degrees(math.atan((y - self.height / 2) / self.focal_px))

    def column_of(self, p: XY) -> float | None:
        """Pixel column where a ground point appears, or None if outside the field of view."""
        d = angle_diff(compass(p[0] - self.position[0], p[1] - self.position[1]), self.heading)
        if abs(d) > self.fov / 2:
            return None
        return self.width / 2 + self.focal_px * math.tan(math.radians(d))

    def row_of(self, p: XY, height_m: float) -> float:
        """Pixel row where something height_m above the ground at p appears (flat ground)."""
        d = max(math.dist(p, self.position), 0.1)
        elevation = math.degrees(math.atan((height_m - CAMERA_HEIGHT_M) / d))
        return self.height / 2 - self.focal_px * math.tan(math.radians(elevation - self.pitch))

    def ground_range(self, y: float) -> float | None:
        """Distance to the ground point seen at pixel row y, or None if the row is above the horizon."""
        elevation = self.elevation_of(y)
        if elevation >= -0.5:
            return None
        return min(max(CAMERA_HEIGHT_M / math.tan(math.radians(-elevation)), MIN_RANGE_M), MAX_RANGE_M)

    def pixels_across(self, size_m: float, distance_m: float) -> float:
        """Width in pixels of an object of that size, seen face-on at that distance."""
        return size_m / max(distance_m, 0.1) * self.focal_px


def ray_point(origin: XY, bearing: float, distance: float) -> XY:
    ux, uy = unit(bearing)
    return origin[0] + distance * ux, origin[1] + distance * uy


def ray_to_sidewalk(path: PathFrame, origin: XY, bearing: float) -> XY | None:
    """Where a sight line first reaches the right-hand sidewalk line, within MAX_RANGE_M."""
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
    """Least-squares crossing point of sight lines (origin, bearing), with the RMS distance
    of the point from the lines. None if the lines are (nearly) parallel."""
    if len(rays) < 2:
        return None
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (ox, oy), bearing in rays:
        ux, uy = unit(bearing)
        nx, ny = uy, -ux  # normal of the line
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
