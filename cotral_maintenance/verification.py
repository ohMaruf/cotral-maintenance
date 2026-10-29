"""Phase 1: verify Cotral stops against Google Maps transit stops (Places API).

Two steps, kept separate for reproducibility:
1. fetch: one Nearby Search per stop; the raw request and response are stored
   as-is. A stored file marks the stop as done, which makes runs resumable.
2. build: the verified-stops dataset is derived from the raw files only, so it
   can be rebuilt offline at any time and always gives the same result.

Google names Cotral stops "<name> # <stop_id>", which is what we match on.
"""

import csv
import io
import json
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .errors import TransportError
from .fileutils import write_atomic, write_json_atomic
from .geo import distance_m
from .models import Stop
from .places import FIELD_MASK, SEARCH_NEARBY_URL, PlacesSource, build_nearby_request
from .provenance import utc_now

logger = logging.getLogger(__name__)

SEARCH_RADIUS_M = 250.0
COTRAL_ID_IN_NAME = re.compile(r"#\s*(\S+)\s*$")
LIST_SEPARATOR = ";"


@dataclass(frozen=True)
class VerifiedStop:
    """One row of the verified-stops dataset.

    lat/lon come from Google when verified, otherwise from the GTFS file
    (see coord_source). offset_m is the distance between the two positions.
    """

    stop_id: str
    stop_name: str
    verified: bool
    lat: float
    lon: float
    coord_source: str
    gtfs_lat: float
    gtfs_lon: float
    match_count: int
    nearby_cotral_ids: str
    fetched_at: str
    offset_m: float | None = None
    place_id: str | None = None
    place_name: str | None = None
    primary_type: str | None = None
    types: str | None = None
    formatted_address: str | None = None
    short_address: str | None = None
    google_maps_uri: str | None = None
    business_status: str | None = None
    wheelchair_accessible_entrance: bool | None = None
    plus_code: str | None = None
    photo_count: int | None = None


class RawPlacesStore:
    """Raw Places records, one JSON file per stop: <root>/<stop_id>.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, stop_id: str) -> Path:
        return self.root / f"{stop_id}.json"

    def has(self, stop_id: str) -> bool:
        return self.path(stop_id).is_file()

    def save(self, stop_id: str, record: dict) -> None:
        write_json_atomic(self.path(stop_id), record)

    def records(self) -> Iterator[dict]:
        """All stored records, ordered by stop id."""
        for path in sorted(self.root.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))


def fetch_stop(stop: Stop, client: PlacesSource, store: RawPlacesStore, force: bool = False) -> bool:
    """Query Places for one stop unless already stored. Returns True if the API was called."""
    if not force and store.has(stop.stop_id):
        return False
    request = build_nearby_request(stop.lat, stop.lon, SEARCH_RADIUS_M)
    places = client.search_nearby(request)
    store.save(
        stop.stop_id,
        {
            "stop": asdict(stop),
            "request": {"url": SEARCH_NEARBY_URL, "field_mask": FIELD_MASK, "body": request},
            "response": {"places": places},
            "fetched_at": utc_now(),
        },
    )
    return True


def fetch_stops(
    stops: Sequence[Stop], client: PlacesSource, store: RawPlacesStore, force: bool = False
) -> int:
    """Fetch every stop in order. Network failures skip the stop; ApiError propagates."""
    fetched = 0
    for index, stop in enumerate(stops, start=1):
        try:
            called_api = fetch_stop(stop, client, store, force)
        except TransportError as exc:
            logger.error("[%d/%d] Failed stop %s (%s): %s", index, len(stops), stop.stop_id, stop.name, exc)
            continue
        if called_api:
            fetched += 1
            logger.info("[%d/%d] Fetched stop %s (%s)", index, len(stops), stop.stop_id, stop.name)
        else:
            logger.debug("[%d/%d] Already fetched: stop %s", index, len(stops), stop.stop_id)
    return fetched


def cotral_id_of(place: dict) -> str | None:
    match = COTRAL_ID_IN_NAME.search(place.get("displayName", {}).get("text", ""))
    return match.group(1) if match else None


def verify_record(record: dict) -> VerifiedStop:
    """Derive one dataset row from a raw record. Pure: same record, same row."""
    stop = Stop(**record["stop"])
    places = record["response"]["places"]
    matches = [p for p in places if cotral_id_of(p) == stop.stop_id]
    nearby_ids = sorted({cid for p in places if (cid := cotral_id_of(p)) and cid != stop.stop_id})
    common = {
        "stop_id": stop.stop_id,
        "stop_name": stop.name,
        "gtfs_lat": stop.lat,
        "gtfs_lon": stop.lon,
        "match_count": len(matches),
        "nearby_cotral_ids": LIST_SEPARATOR.join(nearby_ids),
        "fetched_at": record["fetched_at"],
    }
    if not matches:
        return VerifiedStop(**common, verified=False, lat=stop.lat, lon=stop.lon, coord_source="gtfs")

    def offset_from_gtfs(place: dict) -> float:
        loc = place["location"]
        return distance_m(stop.lat, stop.lon, loc["latitude"], loc["longitude"])

    place = min(matches, key=offset_from_gtfs)
    return VerifiedStop(
        **common,
        verified=True,
        lat=place["location"]["latitude"],
        lon=place["location"]["longitude"],
        coord_source="places",
        offset_m=round(offset_from_gtfs(place), 2),
        place_id=place.get("id"),
        place_name=place.get("displayName", {}).get("text"),
        primary_type=place.get("primaryType"),
        types=LIST_SEPARATOR.join(place.get("types", [])),
        formatted_address=place.get("formattedAddress"),
        short_address=place.get("shortFormattedAddress"),
        google_maps_uri=place.get("googleMapsUri"),
        business_status=place.get("businessStatus"),
        wheelchair_accessible_entrance=place.get("accessibilityOptions", {}).get(
            "wheelchairAccessibleEntrance"
        ),
        plus_code=place.get("plusCode", {}).get("globalCode"),
        photo_count=len(place.get("photos", [])),
    )


def build_dataset(store: RawPlacesStore) -> list[VerifiedStop]:
    return [verify_record(record) for record in store.records()]


def write_dataset(rows: Sequence[VerifiedStop], path: Path) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[f.name for f in fields(VerifiedStop)])
    writer.writeheader()
    writer.writerows(asdict(row) for row in rows)
    write_atomic(path, buffer.getvalue().encode("utf-8"))
