"""Loading bus stops from the GTFS stops.txt file."""

import csv
import hashlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from .errors import StopNotFoundError
from .models import Stop

logger = logging.getLogger(__name__)

# Cotral's own stops have ids "f<digits>". Other ids are stops shared with other
# operators, depots, or legacy stops, and are out of scope by default.
COTRAL_STOP_ID = re.compile(r"f\d+")


def load_stops(path: Path) -> list[Stop]:
    """Read all stops from a GTFS stops.txt, skipping malformed rows."""
    stops = []
    with path.open(newline="", encoding="utf-8") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            try:
                stops.append(
                    Stop(
                        stop_id=row["stop_id"],
                        name=row["stop_name"],
                        lat=float(row["stop_lat"]),
                        lon=float(row["stop_lon"]),
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
