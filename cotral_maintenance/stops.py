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

COTRAL_STOP_ID = re.compile(r"f\d+[A-Z]?")
STOP_ID_IN_NAME = re.compile(r'\s*#\s*([^\s"]+)"?\s*$')
PAIR_MAX_DISTANCE_M = 150.0


def load_stops(path: Path) -> list[Stop]:
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
    by_id = {stop.stop_id: stop for stop in stops}
    missing = [stop_id for stop_id in stop_ids if stop_id not in by_id]
    if missing:
        raise StopNotFoundError(f"Unknown stop id(s): {', '.join(missing)}")
    return [by_id[stop_id] for stop_id in stop_ids]


def is_cotral_stop(stop: Stop) -> bool:
    return COTRAL_STOP_ID.fullmatch(stop.stop_id) is not None


def sample_order(stops: Iterable[Stop], seed: int) -> list[Stop]:
    def rank(stop: Stop) -> str:
        return hashlib.sha256(f"{seed}:{stop.stop_id}".encode()).hexdigest()

    return sorted(stops, key=rank)


def find_pairs(stops: Iterable[Stop], all_stops: Iterable[Stop]) -> dict[str, Stop]:
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
