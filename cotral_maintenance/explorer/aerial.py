"""The aerial map given to the explorer at begin(): existing imagery, only the route and keypoints drawn on it.

Esri World Imagery (Vantor captures, 0.3-0.5 m per pixel, 2024-2025 around the first stops checked) at zoom 18,
the 600 m square around the start, resized to SIZE px. Drawn on it: the bus's path (with arrows for the direction
of travel and metre labels every 50 m on the right-hand side of travel, so the two passes of an out-and-back road
are told apart), the start, OSM hints, other stops (GTFS positions) and other stops already FOUND in this run
(confirmed positions, a few metres accurate). Google's satellite imagery is refused for EEA accounts; we draw
nothing that already exists.

Tiles are cached on disk: a stop's map costs about 40 tile requests the first time, nothing after.
Imagery: Esri, Vantor, Earthstar Geographics. Check Esri's terms before a bulk run.
"""

import io
import logging
import math
from collections.abc import Callable
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from ..fileutils import write_atomic
from .world import Placed, World

logger = logging.getLogger(__name__)

TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ZOOM = 18
HALF_M = 300.0
SIZE = 800  # px: 0.75 m per pixel
LABEL_EVERY_M = 50
ATTRIBUTION = "Imagery: Esri, Vantor, Earthstar Geographics"

FetchTile = Callable[[int, int, int], bytes]  # z, x, y -> jpeg bytes


class EsriTiles:
    """World Imagery tiles, cached on disk by z/x/y."""

    def __init__(self, cache_dir: Path, timeout_s: float = 20.0) -> None:
        self.cache_dir = cache_dir
        self.timeout_s = timeout_s
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "cotral-maintenance research"
        self.fetched = 0

    def __call__(self, z: int, x: int, y: int) -> bytes:
        path = self.cache_dir / str(z) / str(x) / f"{y}.jpg"
        if path.is_file():
            return path.read_bytes()
        r = self.session.get(TILE_URL.format(z=z, x=x, y=y), timeout=self.timeout_s)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, r.content)
        self.fetched += 1
        return r.content

    def close(self) -> None:
        self.session.close()


def world_px(lat: float, lon: float, z: int = ZOOM) -> tuple[float, float]:
    """Web Mercator pixel of a point at zoom z (256 px tiles)."""
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def metres_per_px(lat: float, z: int = ZOOM) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / 2 ** z


def draw_aerial(world: World, out: Path, fetch: FetchTile) -> Path:
    start = world.starts[0]
    cx, cy = world_px(start.lat, start.lon)
    half = HALF_M / metres_per_px(start.lat)
    x0, y0 = cx - half, cy - half
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int((cx + half) // 256), int((cy + half) // 256)
    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            canvas.paste(Image.open(io.BytesIO(fetch(ZOOM, tx, ty))).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    left, top = x0 - tx0 * 256, y0 - ty0 * 256
    img = canvas.crop((int(left), int(top), int(left + 2 * half), int(top + 2 * half))).resize((SIZE, SIZE),
                                                                                                Image.LANCZOS)
    scale = SIZE / (2 * half)
    d = ImageDraw.Draw(img, "RGBA")

    def px(lat: float, lon: float) -> tuple[float, float]:
        x, y = world_px(lat, lon)
        return (x - x0) * scale, (y - y0) * scale

    def at(along: float) -> tuple[float, float]:
        return px(*world.latlon(world.path.point(along)))

    def inside(p) -> bool:
        return 0 <= p[0] < SIZE and 0 <= p[1] < SIZE

    lo, hi = world.limits
    d.line([at(a) for a in _steps(lo, hi, 3.0)], fill=(255, 40, 140, 210), width=5)
    big, small = _font(18), _font(14)
    a = math.ceil(lo / LABEL_EVERY_M) * LABEL_EVERY_M
    while a <= hi:
        (x, y), (x2, y2) = at(a), at(min(a + 3, hi))
        if inside((x, y)) and (x, y) != (x2, y2):
            ang = math.atan2(y2 - y, x2 - x)
            tip = (x + 12 * math.cos(ang), y + 12 * math.sin(ang))
            d.polygon([tip, (x + 9 * math.cos(ang + 2.5), y + 9 * math.sin(ang + 2.5)),
                       (x + 9 * math.cos(ang - 2.5), y + 9 * math.sin(ang - 2.5))], fill=(255, 255, 0),
                      outline=(0, 0, 0))
            # on the RIGHT of travel (image y points down): each pass of a shared road gets its own side
            _label(d, (x - 28 * math.sin(ang), y + 28 * math.cos(ang)), f"{a:+.0f}", big, (160, 0, 70))
        a += LABEL_EVERY_M
    x, y = px(start.lat, start.lon)
    d.ellipse([x - 11, y - 11, x + 11, y + 11], outline=(255, 255, 0), width=4)
    for h in world.hints:
        x, y = px(h.lat, h.lon)
        if inside((x, y)):
            d.rectangle([x - 6, y - 6, x + 6, y + 6], fill=(30, 110, 255), outline=(255, 255, 255), width=2)
            _label(d, (x, y - 20), "OSM " + h.kind.replace("_", " "), small, (20, 70, 200))
    found = {o.ref for o in world.found}
    for o in world.others:
        if o.ref in found:  # drawn once, as found
            continue
        _stop_dot(d, px(o.lat, o.lon), (255, 140, 0), f"{o.ref} (other stop)", small, (150, 70, 0))
    for o in world.found:
        _stop_dot(d, px(o.lat, o.lon), (40, 220, 90), f"{o.ref} FOUND", small, (0, 110, 40))
    _label(d, (140, 14), f"{world.stop.stop_id}: 600 m x 600 m, north up", big, (0, 0, 0))
    _label(d, (SIZE - 170, SIZE - 12), ATTRIBUTION, small, (60, 60, 60))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=88)
    return out


def caption(world: World) -> str:
    found = f" Green dots: other stops already FOUND (their signs are confirmed: never submit them)." \
        if world.found else ""
    return ("AERIAL MAP (existing aerial imagery, north up, 600 m x 600 m around the start): the pink line is the bus's "
            "path, the yellow arrows its direction of travel, the labels its positions in metres (each on the "
            "right-hand side of its pass); the yellow ring is the start, blue squares are OSM hints, orange dots other "
            "stops (timetable positions)." + found + " Use it to plan where to look; the imagery can be a few metres "
            "off the road and some years old.")


def _stop_dot(d, xy, fill, text, font, colour) -> None:
    x, y = xy
    if 0 <= x < SIZE and 0 <= y < SIZE:
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=fill, outline=(0, 0, 0), width=2)
        _label(d, (x, y + 20), text, font, colour)


def _label(d, xy, text: str, font, fg, bg=(255, 255, 255, 225)) -> None:
    b = d.textbbox((0, 0), text, font=font)
    w, h = b[2] - b[0], b[3] - b[1]
    tx, ty = xy[0] - w / 2, xy[1] - h / 2 - b[1]
    d.rectangle([tx - 3, ty + b[1] - 2, tx + w + 3, ty + b[1] + h + 2], fill=bg)
    d.text((tx, ty), text, fill=fg, font=font)


def _font(size: int):
    for f in ("DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _steps(lo: float, hi: float, step: float) -> list[float]:
    n = max(1, int(math.ceil((hi - lo) / step)))
    return [lo + i * (hi - lo) / n for i in range(n + 1)]


def place_found(world: World, found: list[tuple[str, str, float, float]]) -> list[Placed]:
    """Other stops already found in this run, (stop_id, name, lat, lon) of their confirmed signs, placed on the path;
    only those within the search limits and the map."""
    out = []
    for stop_id, name, lat, lon in found:
        if stop_id == world.stop.stop_id:
            continue
        xy = world.frame.to_xy(lat, lon)
        if math.hypot(*xy) > HALF_M * 1.5:
            continue
        along, offset, _ = world.path.locate(xy)
        # the same name across the road: very likely the stop of the other direction, this stop's partner
        partner = name.strip().lower() == world.stop.name.strip().lower() and offset < 0
        out.append(Placed(f"{stop_id} {name} (found)", "found_partner" if partner else "found", lat, lon, along,
                          offset, stop_id))
    return out
