import io

import numpy as np
import pytest
from PIL import Image

from cotral_maintenance.models import View
from cotral_maintenance.render import (
    RenderedStreetView, choose_zoom, level_to_panorama, render_view, view_directions,
)
from cotral_maintenance.tiles import PanoGeometry

TILE = 512


def geometry(heading: float = 0.0, tilt: float = 90.0, roll: float = 0.0) -> PanoGeometry:
    return PanoGeometry("pano", 16384, 8192, TILE, TILE, heading, tilt, roll)


class FakeTiles:
    """A synthetic panorama: red encodes the column's compass offset from the
    panorama centre (0-255 over 360 degrees), green the row's elevation."""

    def __init__(self, geometry: PanoGeometry) -> None:
        self.geometry = geometry
        self.requested: set[tuple[int, int, int]] = set()

    def get_geometry(self, pano_id: str) -> PanoGeometry:
        return self.geometry

    def get_tile(self, pano_id: str, zoom: int, x: int, y: int) -> bytes:
        self.requested.add((zoom, x, y))
        width, height = self.geometry.size_at(zoom)
        cols = (np.arange(TILE) + x * TILE + 0.5) / width
        rows = (np.arange(TILE) + y * TILE + 0.5) / height
        tile = np.zeros((TILE, TILE, 3), dtype=np.uint8)
        tile[..., 0] = (cols * 255)[None, :]
        tile[..., 1] = (rows * 255)[:, None]
        buffer = io.BytesIO()
        Image.fromarray(tile).save(buffer, format="PNG")
        return buffer.getvalue()


def test_centre_pixel_looks_at_heading_and_pitch():
    yaw, elevation = view_directions(heading=70, pitch=10, fov=60, width=101, height=101)

    assert yaw[50, 50] == pytest.approx(70)
    assert elevation[50, 50] == pytest.approx(10)
    # Edges of the view are half the field of view to each side.
    assert yaw[50, 0] == pytest.approx(70 - 30, abs=0.5)


def test_level_panorama_is_left_unchanged():
    yaw, elevation = level_to_panorama(np.array([30.0]), np.array([-5.0]), geometry())

    assert yaw[0] == pytest.approx(30)
    assert elevation[0] == pytest.approx(-5)


def test_tilt_shifts_the_horizon():
    _, elevation = level_to_panorama(np.array([0.0]), np.array([0.0]), geometry(tilt=88.0))

    assert elevation[0] == pytest.approx(2.0)


def test_zoom_is_the_lowest_with_enough_detail():
    # Full width 16384 px: zoom 2 is 2048 px (5.7 px/deg), zoom 3 is 4096 px (11.4 px/deg).
    assert choose_zoom(geometry(), pixels_per_degree=10) == 3
    assert choose_zoom(geometry(), pixels_per_degree=100) == 5


def test_render_samples_the_panorama_in_the_viewed_direction():
    tiles = FakeTiles(geometry(heading=200))

    image = np.asarray(render_view(tiles, tiles.geometry, heading=290, pitch=0, fov=30, width=64, height=64))

    # Looking 90 degrees right of the panorama centre: column at 3/4 of the width, on the horizon.
    assert image[32, 32, 0] == pytest.approx(0.75 * 255, abs=2)
    assert image[32, 32, 1] == pytest.approx(0.5 * 255, abs=2)


def test_render_fetches_only_the_tiles_it_needs():
    tiles = FakeTiles(geometry())

    render_view(tiles, tiles.geometry, heading=0, pitch=0, fov=30, width=256, height=256)

    zoom = choose_zoom(tiles.geometry, 256 / 30)
    columns, rows = (n // TILE for n in tiles.geometry.size_at(zoom))
    assert 0 < len(tiles.requested) < columns * rows / 4


def test_render_wraps_around_the_panorama_seam():
    tiles = FakeTiles(geometry())

    # Looking straight behind the panorama centre, where x wraps from the last column to 0.
    image = np.asarray(render_view(tiles, tiles.geometry, heading=180, pitch=0, fov=20, width=64, height=64))

    assert image[32, 10, 0] > 200  # left of centre: end of the panorama
    assert image[32, 54, 0] < 50  # right of centre: start of the panorama


def test_rendered_street_view_returns_a_jpeg_of_the_view_size():
    source = RenderedStreetView(metadata=None, tiles=FakeTiles(geometry()))

    data = source.get_image("pano", 0, View("v", fov=60, size="320x200"))

    assert Image.open(io.BytesIO(data)).size == (320, 200)
