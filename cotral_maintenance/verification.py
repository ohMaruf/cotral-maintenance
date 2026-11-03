"""Phase 1: check Cotral stops against Google Maps and correct them (Places API).

Two steps, kept separate for reproducibility:
1. fetch: one Nearby Search per stop; the raw request and response are stored
   as-is. A stored file marks the stop as done, which makes runs resumable.
2. build: the corrected-stops dataset is derived from the GTFS and the raw files
   only, so it can be rebuilt offline at any time and always gives the same result.

Google names Cotral stops "<name> # <stop_id>", which is what we match on. Every
response also returns the neighbouring stops, so all raw responses together form
a catalogue of Google's stops: a stop can be found through another stop's search.

Google and the GTFS are not the same version of the network, so each stop gets a
status, tried in this order, and a `reason` in words:
- verified: Google has the stop under its id. Google's position is used.
- reidentified: Google does not have the id, but has a stop with the same name
  under an id that is not in the GTFS. Cotral gave the stop a new id and Google
  kept the old one, so Google's position is used.
- substituted: a legacy (non "f<digits>") id that Google does not have, with
  Cotral stops right next to it, which took over from it.
- missing: Google does not have it. If the same-name stop on Google has an id
  that is in the GTFS, it is a different stop, so this does not count as a match.
- not_checked: no search has been made for the stop yet.
"""

import csv
import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .errors import TransportError
from .fileutils import RawStore
from .geo import distance_m
from .models import Stop
from .places import FIELD_MASK, SEARCH_NEARBY_URL, PlacesSource, build_nearby_request
from .provenance import utc_now
from .stops import STOP_ID_IN_NAME, is_cotral_stop

logger = logging.getLogger(__name__)

SEARCH_RADIUS_M = 250.0
# A stop that changed id may also have moved, but stays in the same part of town.
# Without this limit, two towns' "Liceo scientifico" stops could be matched.
REIDENTIFY_MAX_M = 2000.0
# 1038, in the March 2026 feed, was 41-56 m from the Cotral stops that replaced it.
SUBSTITUTE_MAX_M = 100.0
LIST_SEPARATOR = ";"


class Status(StrEnum):
    VERIFIED = "verified"
    REIDENTIFIED = "reidentified"
    SUBSTITUTED = "substituted"
    MISSING = "missing"
    NOT_CHECKED = "not_checked"


# Stops known to stand where the dataset says they do.
CONFIRMED = (Status.VERIFIED, Status.REIDENTIFIED)
# Stops known not to be there.
GONE = (Status.SUBSTITUTED, Status.MISSING)


@dataclass(frozen=True)
class CorrectedStop:
    """One row of the corrected-stops dataset: the columns of GTFS stops.txt, with
    the corrected position in stop_lat/stop_lon, then how it was arrived at.

    offset_m is the distance between the Google and the GTFS positions.
    """

    stop_id: str
    stop_name: str
    stop_lat: float
    stop_lon: float
    location_type: str
    parent_station: str
    status: Status
    reason: str
    coord_source: str
    gtfs_lat: float
    gtfs_lon: float
    offset_m: float | None = None
    google_stop_id: str | None = None
    substitute_ids: str | None = None
    match_count: int = 0
    nearby_cotral_ids: str | None = None
    fetched_at: str | None = None
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


def fetch_stop(stop: Stop, client: PlacesSource, store: RawStore, force: bool = False) -> bool:
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
    stops: Sequence[Stop], client: PlacesSource, store: RawStore, force: bool = False
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
    match = STOP_ID_IN_NAME.search(place.get("displayName", {}).get("text", ""))
    return match.group(1) if match else None


def comparable_name(name: str) -> str:
    """A name without case and punctuation: "FROSINONE| Liceo" == "FROSINONE | Liceo"."""
    return " ".join(re.findall(r"\w+", name.casefold()))


def name_on_google(place: dict) -> str:
    return STOP_ID_IN_NAME.sub("", place.get("displayName", {}).get("text", ""))


def distance_to(stop: Stop, place: dict) -> float:
    location = place["location"]
    return distance_m(stop.lat, stop.lon, location["latitude"], location["longitude"])


def match_retired_ids(stops: Sequence[Stop], retired: Sequence[dict]) -> dict[str, dict]:
    """Pair stops Google does not have with same-name places whose id left the GTFS.

    Nearest pairs first, each place used once: the two directions of a stop share
    a name, and one retired place cannot stand for both.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    for place in retired:
        by_name[comparable_name(name_on_google(place))].append(place)
    candidates = [
        (distance_to(stop, place), stop.stop_id, place["id"], place)
        for stop in stops
        for place in by_name[comparable_name(stop.name)]
        if distance_to(stop, place) <= REIDENTIFY_MAX_M
    ]
    matches: dict[str, dict] = {}
    used: set[str] = set()
    for _, stop_id, place_id, place in sorted(candidates, key=lambda c: c[:3]):
        if stop_id not in matches and place_id not in used:
            matches[stop_id] = place
            used.add(place_id)
    return matches


def find_substitutes(stop: Stop, cotral_stops: Sequence[Stop]) -> list[str]:
    """Ids of the Cotral stops next to `stop`, nearest first."""
    nearby = [(distance_m(stop.lat, stop.lon, o.lat, o.lon), o.stop_id) for o in cotral_stops]
    return [stop_id for distance, stop_id in sorted(nearby) if distance <= SUBSTITUTE_MAX_M]


def place_columns(place: dict) -> dict:
    return {
        "place_id": place.get("id"),
        "place_name": place.get("displayName", {}).get("text"),
        "primary_type": place.get("primaryType"),
        "types": LIST_SEPARATOR.join(place.get("types", [])),
        "formatted_address": place.get("formattedAddress"),
        "short_address": place.get("shortFormattedAddress"),
        "google_maps_uri": place.get("googleMapsUri"),
        "business_status": place.get("businessStatus"),
        "wheelchair_accessible_entrance": place.get("accessibilityOptions", {}).get(
            "wheelchairAccessibleEntrance"
        ),
        "plus_code": place.get("plusCode", {}).get("globalCode"),
        "photo_count": len(place.get("photos", [])),
    }


def correct_stop(
    stop: Stop,
    record: dict | None,
    matches: Sequence[dict],
    retired: dict | None,
    substitutes: Sequence[str],
) -> CorrectedStop:
    """Derive one dataset row. Pure: same inputs, same row."""
    common = {
        "stop_id": stop.stop_id,
        "stop_name": stop.name,
        "location_type": stop.location_type,
        "parent_station": stop.parent_station,
        "gtfs_lat": stop.lat,
        "gtfs_lon": stop.lon,
        "match_count": len(matches),
    }
    if record:
        nearby = {cid for p in record["response"]["places"] if (cid := cotral_id_of(p)) and cid != stop.stop_id}
        common["nearby_cotral_ids"] = LIST_SEPARATOR.join(sorted(nearby))
        common["fetched_at"] = record["fetched_at"]

    def from_google(place: dict, status: Status, reason: str) -> CorrectedStop:
        return CorrectedStop(
            **common,
            **place_columns(place),
            status=status,
            reason=reason,
            coord_source="places",
            stop_lat=place["location"]["latitude"],
            stop_lon=place["location"]["longitude"],
            offset_m=round(distance_to(stop, place), 2),
            google_stop_id=cotral_id_of(place),
        )

    def from_gtfs(status: Status, reason: str, **extra) -> CorrectedStop:
        return CorrectedStop(
            **common, **extra, status=status, reason=reason, coord_source="gtfs", stop_lat=stop.lat, stop_lon=stop.lon
        )

    if matches:
        place = min(matches, key=lambda p: distance_to(stop, p))
        return from_google(
            place, Status.VERIFIED, f"On Google under this id, {distance_to(stop, place):.0f} m from the GTFS position."
        )
    if record is None:
        return from_gtfs(Status.NOT_CHECKED, "No Places search made for this stop yet.")
    if retired:
        return from_google(
            retired,
            Status.REIDENTIFIED,
            f"Not on Google under this id. Google's {cotral_id_of(retired)} has the same name, is not in the "
            f"GTFS and is {distance_to(stop, retired):.0f} m away, so it is taken to be this stop's old id.",
        )
    if substitutes:
        return from_gtfs(
            Status.SUBSTITUTED,
            f"Legacy id, not on Google, with Cotral stops within {SUBSTITUTE_MAX_M:.0f} m that took over from it.",
            substitute_ids=LIST_SEPARATOR.join(substitutes),
        )
    return from_gtfs(
        Status.MISSING,
        f"Not on Google under this id, nor under a retired id with the same name within {REIDENTIFY_MAX_M:.0f} m.",
    )


def build_dataset(stops: Sequence[Stop], store: RawStore) -> list[CorrectedStop]:
    """One row per stop of the GTFS, in its order, whether checked yet or not.

    A full run gives the final answer: `missing` can become `verified` or
    `reidentified` once a neighbour's search has returned the Google stop.
    """
    records = {record["stop"]["stop_id"]: record for record in store.records()}
    places = {place["id"]: place for record in records.values() for place in record["response"]["places"]}
    by_cotral_id: dict[str, list[dict]] = defaultdict(list)
    for place in places.values():
        if cotral_id := cotral_id_of(place):
            by_cotral_id[cotral_id].append(place)

    gtfs_ids = {stop.stop_id for stop in stops}
    retired_places = [p for cid, ps in by_cotral_id.items() if cid not in gtfs_ids for p in ps]
    not_on_google = [s for s in stops if s.stop_id in records and s.stop_id not in by_cotral_id]
    retired = match_retired_ids(not_on_google, retired_places)
    cotral_stops = [stop for stop in stops if is_cotral_stop(stop)]

    legacy = {s.stop_id for s in not_on_google if s.stop_id not in retired and not is_cotral_stop(s)}
    return [
        correct_stop(
            stop,
            records.get(stop.stop_id),
            by_cotral_id.get(stop.stop_id, []),
            retired.get(stop.stop_id),
            find_substitutes(stop, cotral_stops) if stop.stop_id in legacy else [],
        )
        for stop in stops
    ]


def load_corrected_stops(path: Path) -> dict[str, tuple[Stop, Status]]:
    """Each stop at its corrected position, with its status, by stop id."""
    with path.open(newline="", encoding="utf-8") as f:
        return {
            row["stop_id"]: (
                Stop(
                    row["stop_id"], row["stop_name"], float(row["stop_lat"]), float(row["stop_lon"]),
                    row["location_type"], row["parent_station"],
                ),
                Status(row["status"]),
            )
            for row in csv.DictReader(f)
        }
