"""Narrow, full-resolution views rendered from Map Tiles, priced in tiles before they are fetched.

The explorer looks broadly with Static API images (640x640, one billed request each) and
narrows in with these (one billed request per tile, about 45 px per degree at the top zoom).
A narrow view needs 1-4 tiles: aimed exactly at the horizon it straddles a row of tiles,
so `plan` nudges heading and pitch by a few degrees (the target stays well inside the frame)
to the cheapest framing.
"""

import itertools
from collections.abc import Iterable

from ..render import render_view, tiles_for_view, to_jpeg
from ..tiles import MapTilesClient, PanoGeometry

NUDGES = (0.0, 1.5, -1.5, 3.0, -3.0)  # degrees tried on heading and pitch
MAX_NUDGE_SHARE = 0.3  # a nudge moves the target at most this share of the half-width off centre

Tile = tuple[str, int, int, int]  # pano id, zoom, x, y


class TileViews:
    def __init__(self, client: MapTilesClient) -> None:
        self.client = client
        self._geometry: dict[str, PanoGeometry] = {}

    @property
    def fetched(self) -> int:
        """Tiles actually fetched from Google (billed); tiles on disk cost nothing."""
        return self.client.tiles_fetched

    def geometry(self, pano_id: str) -> PanoGeometry:
        if pano_id not in self._geometry:
            self._geometry[pano_id] = self.client.get_geometry(pano_id)  # free metadata request
        return self._geometry[pano_id]

    def tiles(self, pano_id: str, heading: float, pitch: float, fov: float, width: int, height: int) -> set[Tile]:
        return {(pano_id, *t) for t in tiles_for_view(self.geometry(pano_id), heading, pitch, fov, width, height)}

    def plan(self, pano_id: str, heading: float, pitch: float, fov: float, width: int, height: int,
             paid: Iterable[Tile]) -> tuple[float, float, set[Tile]]:
        """(heading, pitch, tiles still to pay for) of the cheapest framing near the one asked for."""
        paid = set(paid)
        limit = fov / 2 * MAX_NUDGE_SHARE
        best = None
        for dh, dp in itertools.product(NUDGES, NUDGES):
            if abs(dh) > limit or abs(dp) > limit:
                continue
            new = self.tiles(pano_id, heading + dh, pitch + dp, fov, width, height) - paid
            key = (len(new), abs(dh) + abs(dp))
            if best is None or key < best[0]:
                best = (key, heading + dh, pitch + dp, new)
        return best[1], best[2], best[3]

    def render(self, pano_id: str, heading: float, pitch: float, fov: float, width: int, height: int) -> bytes:
        return to_jpeg(render_view(self.client, self.geometry(pano_id), heading, pitch, fov, width, height))
