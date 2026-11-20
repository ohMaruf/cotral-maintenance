import math
from pathlib import Path

from PIL import Image, ImageDraw

from .geometry import SIDEWALK_M, ray_point
from .session import Session

SIZE = 900
MARGIN = 40
STATE_COLOUR = {"not_looked": (200, 200, 200), "glimpsed": (190, 220, 245), "blocked": (240, 200, 60),
                "seen_close": (40, 170, 90),
                "hidden": (240, 150, 40), "unscanned": (90, 90, 90)}
CONE_M = 25.0


def draw_map(session: Session, out: Path) -> Path:
    w = session.world
    lo, hi = w.limits
    pts = [w.path.point(a) for a in _steps(lo - 20, hi + 20, 5)]
    pts += [w.frame.to_xy(p.lat, p.lon) for p in session.photos]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 60.0) + 40
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    scale = (SIZE - 2 * MARGIN) / span

    def px(p):
        return (SIZE / 2 + (p[0] - cx) * scale, SIZE / 2 - (p[1] - cy) * scale)

    img = Image.new("RGB", (SIZE, SIZE + 60), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.line([px(w.path.point(a)) for a in _steps(w.path.first, w.path.last, 3)], fill=(150, 150, 150), width=2)
    d.line([px(w.path.point(a)) for a in _steps(lo, hi, 3)], fill=(60, 60, 60), width=4)
    for a in _steps(lo, hi, 25):
        p, b = w.path.point(a), w.path.bearing(a)
        tip, l1, l2 = ray_point(p, b, 4), ray_point(p, b + 150, 4), ray_point(p, b - 150, 4)
        d.polygon([px(tip), px(l1), px(l2)], fill=(60, 60, 60))
    for a, state in zip(session.cells, session.state, strict=True):
        d.line([px(w.path.point(a - 2, SIDEWALK_M)), px(w.path.point(a + 2, SIDEWALK_M))],
               fill=STATE_COLOUR[state], width=7)
    for p in w.panoramas:
        x, y = px(w.frame.to_xy(p.lat, p.lon))
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(110, 110, 200))
    for ph in session.photos:
        o = w.frame.to_xy(ph.lat, ph.lon)
        cone = [px(o)] + [px(ray_point(o, ph.heading + t, CONE_M)) for t in _steps(-ph.fov / 2, ph.fov / 2, 5)]
        d.polygon(cone, outline=(230, 160, 0), width=2)
        x, y = px(o)
        d.rectangle([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255), outline=(0, 0, 0))
        d.text((x - 6, y - 6), str(ph.index), fill=(0, 0, 0))
    for items, colour in ((w.starts, (200, 40, 40)), (w.hints, (130, 60, 200)), (w.others, (0, 0, 0))):
        for it in items:
            x, y = px(w.frame.to_xy(it.lat, it.lon))
            d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=colour, width=3)
            d.text((x + 8, y - 6), it.label[:28], fill=colour)
    for c in session.candidates:
        x, y = px(w.frame.to_xy(c.lat, c.lon))
        colour = {"confirmed": (20, 150, 60), "rejected": (200, 0, 0)}.get(c.status, (230, 120, 0))
        d.regular_polygon((x, y, 9), 4, fill=colour)
        d.text((x + 10, y - 6), f"C{c.index} {c.status}", fill=colour)
    bar = 50 * scale
    d.line([(MARGIN, SIZE - 20), (MARGIN + bar, SIZE - 20)], fill=(0, 0, 0), width=3)
    d.text((MARGIN, SIZE - 15), "50 m", fill=(0, 0, 0))
    legend = ("sidewalk: grey not looked, pale blue glimpsed, yellow blocked from one side, green seen close, orange hidden, dark unscanned | "
              "red rings: starting positions, purple: OSM hints, black: other stops | squares: photos")
    d.text((10, SIZE + 10), legend, fill=(0, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _steps(lo: float, hi: float, step: float):
    n = max(1, int(math.ceil((hi - lo) / step)))
    return [lo + i * (hi - lo) / n for i in range(n + 1)]
