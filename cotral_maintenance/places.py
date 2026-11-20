import logging
from typing import Protocol, Self

from .transport import build_session, parse_json, send

logger = logging.getLogger(__name__)

SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
INCLUDED_TYPES = ("bus_stop", "transit_station")
MAX_RESULT_COUNT = 20

PLACE_FIELDS = (
    "id",
    "displayName",
    "location",
    "types",
    "primaryType",
    "formattedAddress",
    "shortFormattedAddress",
    "googleMapsUri",
    "businessStatus",
    "accessibilityOptions",
    "plusCode",
    "photos",
)
FIELD_MASK = ",".join(f"places.{field}" for field in PLACE_FIELDS)


class PlacesSource(Protocol):
    def search_nearby(self, request: dict) -> list[dict]: ...


def build_nearby_request(lat: float, lon: float, radius_m: float) -> dict:
    return {
        "includedTypes": list(INCLUDED_TYPES),
        "maxResultCount": MAX_RESULT_COUNT,
        "rankPreference": "DISTANCE",
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radius_m}
        },
    }


class PlacesClient:
    def __init__(
        self, api_key: str, timeout_s: float = 20.0, referrer: str | None = None
    ) -> None:
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._session = build_session(referrer)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def search_nearby(self, request: dict) -> list[dict]:
        response = send(
            self._session,
            "POST",
            SEARCH_NEARBY_URL,
            self._timeout_s,
            json=request,
            headers={"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": FIELD_MASK},
        )
        return parse_json(response).get("places", [])
