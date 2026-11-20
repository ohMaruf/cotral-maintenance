import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

from .fileutils import write_atomic
from .transport import build_session, parse_json, send

logger = logging.getLogger(__name__)

SESSION_URL = "https://tile.googleapis.com/v1/createSession"
METADATA_URL = "https://tile.googleapis.com/v1/streetview/metadata"
TILE_URL = "https://tile.googleapis.com/v1/streetview/tiles/{z}/{x}/{y}"

MAX_ZOOM = 5


@dataclass(frozen=True)
class PanoGeometry:
    pano_id: str
    image_width: int
    image_height: int
    tile_width: int
    tile_height: int
    heading: float
    tilt: float
    roll: float

    def size_at(self, zoom: int) -> tuple[int, int]:
        shift = MAX_ZOOM - zoom
        return self.image_width >> shift, self.image_height >> shift


class TileSource(Protocol):
    def get_geometry(self, pano_id: str) -> PanoGeometry: ...
    def get_tile(self, pano_id: str, zoom: int, x: int, y: int) -> bytes: ...


class MapTilesClient:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        timeout_s: float = 20.0,
        referrer: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._timeout_s = timeout_s
        self._session = build_session(referrer)
        self._token: str | None = None
        self.tiles_fetched = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _session_token(self) -> str:
        if self._token is None:
            data = parse_json(send(
                self._session, "POST", SESSION_URL, self._timeout_s,
                params={"key": self._api_key}, json={"mapType": "streetview", "language": "it-IT", "region": "IT"},
            ))
            self._token = data["session"]
        return self._token

    def _get(self, url: str, params: dict[str, str]):
        return send(
            self._session, "GET", url, self._timeout_s,
            params={**params, "session": self._session_token(), "key": self._api_key},
        )

    def get_geometry(self, pano_id: str) -> PanoGeometry:
        data = parse_json(self._get(METADATA_URL, {"panoId": pano_id}))
        return PanoGeometry(
            pano_id=pano_id,
            image_width=data["imageWidth"],
            image_height=data["imageHeight"],
            tile_width=data["tileWidth"],
            tile_height=data["tileHeight"],
            heading=data["heading"],
            tilt=data.get("tilt", 90.0),
            roll=data.get("roll", 0.0),
        )

    def get_tile(self, pano_id: str, zoom: int, x: int, y: int) -> bytes:
        path = self._cache_dir / pano_id / str(zoom) / f"{x}_{y}.jpg"
        if path.is_file():
            return path.read_bytes()
        data = self._get(TILE_URL.format(z=zoom, x=x, y=y), {"panoId": pano_id}).content
        self.tiles_fetched += 1
        write_atomic(path, data)
        return data
