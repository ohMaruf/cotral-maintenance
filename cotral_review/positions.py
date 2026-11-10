"""Verified and Places positions of a stop, from the CSVs written by the position pipelines.

Loaded once at startup; a missing file just means no positions of that kind.
"""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

Coords = tuple[float, float]


def read_coords(path: Path, lat_column: str = "lat", lon_column: str = "lon",
                only: tuple[str, str] | None = None) -> dict[str, Coords]:
    """stop_id -> (lat, lon) of a CSV; `only=(column, value)` keeps the matching rows. Missing file: empty."""
    if not path.is_file():
        logger.info("no positions at %s", path)
        return {}
    coords: dict[str, Coords] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if only and row.get(only[0]) != only[1]:
                continue
            try:
                coords[row["stop_id"]] = (float(row[lat_column]), float(row[lon_column]))
            except (KeyError, ValueError):
                continue
    return coords


@dataclass(frozen=True)
class PositionIndex:
    verified: dict[str, Coords] = field(default_factory=dict)
    places: dict[str, Coords] = field(default_factory=dict)

    @classmethod
    def load(cls, truth_csv: Path, places_csv: Path) -> "PositionIndex":
        return cls(
            verified=read_coords(truth_csv),
            places=read_coords(places_csv, "stop_lat", "stop_lon", only=("coord_source", "places")),
        )
