"""Loading bus stops from the GTFS stops.txt file."""

import csv
import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from .errors import StopNotFoundError
from .geo import distance_m
from .models import Stop

logger = logging.getLogger(__name__)

# Cotral's own stops have ids "f<digits>", two with a trailing letter (f8270A). Other
# ids are stops shared with other operators, depots, or legacy stops, and are out of
# scope by default. F34502 is among them: a duplicate of f34502, 3 m away.
COTRAL_STOP_ID = re.compile(r"f\d+[A-Z]?")
# Cotral's feed, and Google, name stops "<name> # <stop_id>". Double quotes inside
# a name are not escaped in the feed, so the CSV reader leaves one after the id.
STOP_ID_IN_NAME = re.compile(r'\s*#\s*([^\s"]+)"?\s*$')
# A stop for the opposite direction has the same name and stands across the road,
# usually within a few tens of metres. 86% of Cotral stops have one within 150 m.
PAIR_MAX_DISTANCE_M = 150.0


def load_stops(path: Path) -> list[Stop]:
    """Read all stops from a GTFS stops.txt, skipping malformed rows."""
    stops = []
    with path.open(newline="", encoding="utf-8") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            try:
                stops.append(
                    Stop(
                        stop_id=row["stop_id"],
                        name=STOP_ID_IN_NAME.sub("", row["stop_name"]),
                        lat=float(row["stop_lat"]),
                        lon=float(row["stop_lon"]),
                        location_type=row.get("location_type", "0"),
                        parent_station=row.get("parent_station", ""),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed row %d in %s: %s", line_no, path, exc)
    logger.debug("Loaded %d stops from %s", len(stops), path)
    return stops


def select_stops(stops: Iterable[Stop], stop_ids: Iterable[str]) -> list[Stop]:
    """Return the stops with the given ids, in the requested order."""
    by_id = {stop.stop_id: stop for stop in stops}
    missing = [stop_id for stop_id in stop_ids if stop_id not in by_id]
    if missing:
        raise StopNotFoundError(f"Unknown stop id(s): {', '.join(missing)}")
    return [by_id[stop_id] for stop_id in stop_ids]


def is_cotral_stop(stop: Stop) -> bool:
    return COTRAL_STOP_ID.fullmatch(stop.stop_id) is not None


def sample_order(stops: Iterable[Stop], seed: int) -> list[Stop]:
    """Deterministic pseudo-random order: the first N stops are a reproducible random sample.

    Each stop's position depends only on (seed, stop_id), so larger samples extend
    smaller ones, and adding or removing stops never reorders the others.
    """

    def rank(stop: Stop) -> str:
        return hashlib.sha256(f"{seed}:{stop.stop_id}".encode()).hexdigest()

    return sorted(stops, key=rank)


def find_pairs(stops: Iterable[Stop], all_stops: Iterable[Stop]) -> dict[str, Stop]:
    """For each stop, its opposite-direction stop: the nearest other stop with the
    same name within PAIR_MAX_DISTANCE_M. Stops without one are left out."""
    by_name: dict[str, list[Stop]] = defaultdict(list)
    for other in all_stops:
        by_name[other.name].append(other)
    pairs = {}
    for stop in stops:
        others = [
            (distance_m(stop.lat, stop.lon, o.lat, o.lon), o)
            for o in by_name[stop.name] if o.stop_id != stop.stop_id
        ]
        nearest = min(others, key=lambda pair: pair[0], default=None)
        if nearest and nearest[0] <= PAIR_MAX_DISTANCE_M:
            pairs[stop.stop_id] = nearest[1]
    return pairs
