import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from blobs import components
from cotral_blue import rgb_to_hsv


def panels(rgb: np.ndarray) -> list[tuple[float, float, int]]:
    h, s, v = rgb_to_hsv(rgb)
    mask = (np.abs(h - 215) < 20) & (s > 0.25) & (v > 0.15) & (v < 0.65)
    out = []
    for ys, xs in components(mask):
        n, bh, bw = len(xs), np.ptp(ys) + 1, np.ptp(xs) + 1
        if 20 <= n <= 6000 and n >= 0.5 * bh * bw and 0.6 <= bh / bw <= 3.5:
            out.append((xs.mean(), ys.mean(), n))
    return out


def main() -> None:
    d = Path(sys.argv[1])
    truth = json.loads((d / "truth.json").read_text())
    hit = n = fa = 0
    for name, t in truth.items():
        ps = panels(np.asarray(Image.open(d / f"{name}.png").convert("RGB")) / 255.0)
        near = [p for p in ps if t and abs(p[0] - t[0]) <= 40 and abs(p[1] - t[1]) <= 70]
        fa += len(ps) - len(near)
        if t:
            n += 1
            hit += bool(near)
        print(f"{name:30s} {'HIT ' if near else 'miss'} {len(ps) - len(near)} other")
    print(f"\nrecall {hit}/{n}; false alarms {fa} on {len(truth)} bands ({fa / len(truth):.1f} per band)")


if __name__ == "__main__":
    main()
