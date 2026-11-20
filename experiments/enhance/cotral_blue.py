"""Scratch: make Cotral navy (H~219, S~0.42, V~0.33 on the reference sign) stand out in Street View photos.

    uv run python experiments/enhance/cotral_blue.py OUT_DIR IMAGE...
writes <name>_mask.png (where the navy is) and <name>_enh.png (navy made vivid, the rest muted) for each image.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

HUE, HUE_TOL = 219.0, 28.0  # degrees
S_MIN, V_MIN, V_MAX = 0.18, 0.10, 0.62


def rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    return h * 60, np.where(mx > 0, d / np.maximum(mx, 1e-6), 0), mx


def navy_weight(rgb: np.ndarray) -> np.ndarray:
    """0..1 per pixel: how much it looks like the sign's navy."""
    h, s, v = rgb_to_hsv(rgb)
    dh = np.abs((h - HUE + 180) % 360 - 180)
    wh = np.clip(1 - dh / HUE_TOL, 0, 1)
    ws = np.clip((s - S_MIN) / 0.12, 0, 1)
    wv = np.clip((v - V_MIN) / 0.05, 0, 1) * np.clip((V_MAX - v) / 0.08, 0, 1)
    return wh * ws * wv


def enhance(rgb: np.ndarray) -> np.ndarray:
    w = navy_weight(rgb)[..., None]
    grey = rgb.mean(-1, keepdims=True)
    muted = grey + 0.55 * (rgb - grey)                # everything else: less colour
    vivid = np.array([0.05, 0.25, 1.0]) * (0.55 + 0.45 * grey / 0.4)  # navy: saturated bright blue
    return np.clip(muted * (1 - w) + np.clip(vivid, 0, 1) * w, 0, 1)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[2:]:
        rgb = np.asarray(Image.open(name).convert("RGB")).astype(float) / 255
        stem = Path(name).stem
        Image.fromarray((navy_weight(rgb) * 255).astype(np.uint8)).save(out / f"{stem}_mask.png")
        Image.fromarray((enhance(rgb) * 255).astype(np.uint8)).save(out / f"{stem}_enh.png")


if __name__ == "__main__":
    main()
