"""Thin client for the Street View Static API (metadata + image endpoints)."""

import logging
from typing import Protocol, Self

from .errors import ApiError, NoImageryError, ServerError
from .models import PanoMetadata, View
from .transport import build_session, parse_json, send

logger = logging.getLogger(__name__)

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

NO_IMAGERY_STATUSES = frozenset({"ZERO_RESULTS", "NOT_FOUND"})
SERVER_ERROR_STATUS = "UNKNOWN_ERROR"


class ImageSource(Protocol):
    """What the rest of the package needs from a client; lets tests pass a fake."""

    def get_metadata(self, lat: float, lon: float, radius_m: float) -> PanoMetadata: ...
    def get_image(self, pano_id: str, heading: float, view: View) -> bytes: ...


class StreetViewClient:
    def __init__(self, api_key: str, timeout_s: float = 20.0) -> None:
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._session = build_session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def get_metadata(self, lat: float, lon: float, radius_m: float) -> PanoMetadata:
        """Find the nearest outdoor panorama. Metadata requests are free of charge."""
        location = f"{lat},{lon}"
        data = parse_json(
            self._get(
                METADATA_URL,
                {"location": location, "radius": f"{radius_m:.0f}", "source": "outdoor"},
            )
        )
        status = data.get("status", "MISSING_STATUS")
        if status in NO_IMAGERY_STATUSES:
            raise NoImageryError(f"No panorama within {radius_m:.0f} m of {location}")
        if status == SERVER_ERROR_STATUS:
            raise ServerError(f"{status} for {location}")
        if status != "OK":
            raise ApiError(status, data.get("error_message", ""))
        return PanoMetadata(
            pano_id=data["pano_id"],
            lat=data["location"]["lat"],
            lon=data["location"]["lng"],
            date=data.get("date"),
            copyright=data.get("copyright", ""),
        )

    def get_image(self, pano_id: str, heading: float, view: View) -> bytes:
        """Download one image of a specific panorama. Billed per request."""
        response = self._get(
            IMAGE_URL, {"pano": pano_id, "heading": f"{heading:.1f}", **view.to_params()}
        )
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ApiError("UNEXPECTED_CONTENT", f"expected an image, got {content_type!r}")
        return response.content

    def _get(self, url: str, params: dict[str, str]):
        return send(
            self._session, "GET", url, self._timeout_s, params={**params, "key": self._api_key}
        )
