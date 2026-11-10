"""Stop-like OSM objects near a position, from the local OSM store (cotral_maintenance/osm_store.py)."""

import logging
from pathlib import Path

from cotral_maintenance.geo import distance_m
from cotral_maintenance.osm_store import OsmStore, bbox_around

from .explore_schemas import OsmFeature

logger = logging.getLogger(__name__)

RADIUS_M = 200.0


class OsmLookup:
    """A missing store file means no features (logged once), never an error."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._warned = False

    def near(self, lat: float, lon: float, radius_m: float = RADIUS_M) -> list[OsmFeature]:
        if not self.path.is_file():
            if not self._warned:
                logger.warning("no OSM store at %s: OSM features are left out", self.path)
                self._warned = True
            return []
        features = OsmStore(self.path).stops_in(bbox_around(lat, lon, radius_m))
        return [
            OsmFeature(id=f.osm_id, kind=f.kind, lat=f.lat, lon=f.lon, ref=f.ref, name=f.name, operator=f.operator)
            for f in sorted(features, key=lambda f: f.osm_id)
            if distance_m(lat, lon, f.lat, f.lon) <= radius_m
        ]
