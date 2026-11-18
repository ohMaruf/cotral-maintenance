"""Verified positions of the stops (the manual ground truth), when there are any.

Loaded once at startup; a missing file just means no verified positions.
"""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

Coords = tuple[float, float]


def read_coords(path: Path) -> dict[str, Coords]:
    """stop_id -> (lat, lon) of a CSV. Missing file: empty."""
    if not path.is_file():
        logger.info("no positions at %s", path)
        return {}
    coords: dict[str, Coords] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                coords[row["stop_id"]] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError):
                continue
    return coords


@dataclass(frozen=True)
class PositionIndex:
    verified: dict[str, Coords] = field(default_factory=dict)

    @classmethod
    def load(cls, truth_csv: Path) -> "PositionIndex":
        return cls(verified=read_coords(truth_csv))
