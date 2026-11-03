"""Rendering perspective views from Street View panorama tiles.

A panorama is an equirectangular image: x is the compass direction, y the angle
above or below the horizon. For each pixel of the requested view we compute the
direction it looks in, fetch only the tiles those directions fall on, and sample
them bilinearly. The zoom level is the lowest that has at least as much detail
as the output, so no more tiles are paid for than needed.
"""

import io
import math

import numpy as np
from PIL import Image

from .models import PanoMetadata, View
from .streetview import ImageSource
from .tiles import MAX_ZOOM, PanoGeometry, TileSource

JPEG_QUALITY = 92


def choose_zoom(geometry: PanoGeometry, pixels_per_degree: float) -> int:
    """Lowest zoom whose panorama has at least `pixels_per_degree`, capped at full size."""
    for zoom in range(1, MAX_ZOOM + 1):
        if geometry.size_at(zoom)[0] / 360 >= pixels_per_degree:
            return zoom
    return MAX_ZOOM


def view_directions(
    heading: float, pitch: float, fov: float, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    """(compass heading, elevation) in degrees for the centre of every output pixel.

    `fov` is horizontal, as in the Static API.
    """
    focal = (width / 2) / math.tan(math.radians(fov) / 2)
    x, y = np.meshgrid(
        np.arange(width) + 0.5 - width / 2,
        height / 2 - (np.arange(height) + 0.5),
    )
    p = math.radians(pitch)
    # Tilt the camera up by `pitch`: rotate (y, forward) about the camera's x axis.
    up = y * math.cos(p) + focal * math.sin(p)
    forward = -y * math.sin(p) + focal * math.cos(p)
    yaw = heading + np.degrees(np.arctan2(x, forward))
    elevation = np.degrees(np.arctan2(up, np.hypot(x, forward)))
    return yaw, elevation


def level_to_panorama(
    yaw: np.ndarray, elevation: np.ndarray, geometry: PanoGeometry
) -> tuple[np.ndarray, np.ndarray]:
    """Map level-world directions (relative to the panorama heading) into the
    panorama's own frame, which is tilted by `tilt - 90` and rolled by `roll`.

    The rotation directions are not documented; these were chosen by matching
    renders against Static API images of the same panoramas (correlation 0.94-0.98).
    """
    yaw_r, el_r = np.radians(yaw), np.radians(elevation)
    x = np.cos(el_r) * np.sin(yaw_r)  # right
    y = np.sin(el_r)  # up
    z = np.cos(el_r) * np.cos(yaw_r)  # forward
    t = math.radians(90 - geometry.tilt)
    y, z = y * math.cos(t) + z * math.sin(t), -y * math.sin(t) + z * math.cos(t)
    r = math.radians(geometry.roll)
    x, y = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
    return np.degrees(np.arctan2(x, z)), np.degrees(np.arcsin(np.clip(y, -1, 1)))


def render_view(
    source: TileSource,
    geometry: PanoGeometry,
    heading: float,
    pitch: float,
    fov: float,
    width: int,
    height: int,
) -> Image.Image:
    zoom = choose_zoom(geometry, width / fov)
    pano_w, pano_h = geometry.size_at(zoom)
    tile_w, tile_h = geometry.tile_width, geometry.tile_height

    yaw, elevation = view_directions(heading, pitch, fov, width, height)
    # Relative to the panorama's centre column, which faces geometry.heading.
    rel_yaw, rel_elevation = level_to_panorama(yaw - geometry.heading, elevation, geometry)
    px = ((rel_yaw / 360 + 0.5) % 1.0) * pano_w - 0.5
    py = np.clip((90 - rel_elevation) / 180 * pano_h - 0.5, 0, pano_h - 1)

    x0 = np.floor(px).astype(int)
    y0 = np.floor(py).astype(int)
    fx, fy = (px - x0)[..., None], (py - y0)[..., None]
    x0 %= pano_w
    x1 = (x0 + 1) % pano_w
    y1 = np.minimum(y0 + 1, pano_h - 1)

    # Only the band of tile rows the view covers is assembled, at full panorama width.
    row_first, row_last = y0.min() // tile_h, y1.max() // tile_h
    band_top = row_first * tile_h
    band = np.zeros(((row_last - row_first + 1) * tile_h, pano_w, 3), dtype=np.uint8)
    columns = np.unique(np.concatenate([x0.ravel(), x1.ravel()]) // tile_w)
    for row in range(row_first, row_last + 1):
        for col in columns:
            tile = np.asarray(Image.open(io.BytesIO(
                source.get_tile(geometry.pano_id, zoom, int(col), int(row))
            )).convert("RGB"))
            # Edge tiles may be padded beyond the panorama; keep only what fits.
            h = min(tile.shape[0], band.shape[0] - (row - row_first) * tile_h)
            w = min(tile.shape[1], pano_w - col * tile_w)
            top = (row - row_first) * tile_h
            band[top:top + h, col * tile_w:col * tile_w + w] = tile[:h, :w]

    y0, y1 = y0 - band_top, y1 - band_top
    pixels = (
        band[y0, x0] * (1 - fx) * (1 - fy)
        + band[y0, x1] * fx * (1 - fy)
        + band[y1, x0] * (1 - fx) * fy
        + band[y1, x1] * fx * fy
    )
    return Image.fromarray(np.clip(pixels + 0.5, 0, 255).astype(np.uint8))


def to_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


class RenderedStreetView:
    """ImageSource that finds panoramas with the (free) Static API metadata endpoint
    and renders images from Map Tiles, at any size, instead of the Static API's 640x640.
    """

    def __init__(self, metadata: ImageSource, tiles: TileSource) -> None:
        self._metadata = metadata
        self._tiles = tiles
        self._geometry: dict[str, PanoGeometry] = {}

    def get_metadata(self, lat: float, lon: float, radius_m: float) -> PanoMetadata:
        return self._metadata.get_metadata(lat, lon, radius_m)

    def get_image(self, pano_id: str, heading: float, view: View) -> bytes:
        if pano_id not in self._geometry:
            self._geometry[pano_id] = self._tiles.get_geometry(pano_id)
        width, height = (int(n) for n in view.size.split("x"))
        image = render_view(
            self._tiles, self._geometry[pano_id], heading, view.pitch, view.fov, width, height
        )
        return to_jpeg(image)
