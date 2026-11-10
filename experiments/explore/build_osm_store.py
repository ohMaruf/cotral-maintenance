"""Build the local OSM store (cotral_maintenance/osm_store.py) from Geofabrik extracts.

Input: data/osm/extracts/{centro,sud}-latest.osm.pbf (Geofabrik's Central and
Southern Italy: Lazio, Umbria, Tuscany, Abruzzo, Campania, ...), downloaded once.
Only what lies within REGION_MARGIN_DEG of the Cotral network's extent is kept:
  - roads a bus may drive on, with the one-way rule for a bus
  - every stop-like object (bus stops, platforms, stop positions, public-transport
    shelters, bus stations), whatever its tagging
Output: data/osm/osm.sqlite3 (replaced).

Usage, from the repository root (pyosmium is in the "osm" extra):
    uv run --extra osm python experiments/explore/build_osm_store.py
"""

import logging
import re
import sys
import time
from pathlib import Path

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.osm_store import OsmStore, Road, StopFeature, bus_road, stop_kind
from cotral_maintenance.provenance import utc_now
from cotral_maintenance.stops import load_stops

EXTRACTS = (Path("data/osm/extracts/centro-latest.osm.pbf"), Path("data/osm/extracts/sud-latest.osm.pbf"))
STORE = Path("data/osm/osm.sqlite3")
STOPS = Path("GTFS_COTRAL/stops.txt")
REGION_MARGIN_DEG = 0.05  # about 5 km around the network's extent
BATCH = 20_000
TAG_KEYS = ("highway", "public_transport", "amenity")

logger = logging.getLogger("build_osm_store")


def network_region() -> tuple[float, float, float, float]:
    stops = [s for s in load_stops(STOPS) if re.fullmatch(r"f\d+", s.stop_id)]
    lats, lons = [s.lat for s in stops], [s.lon for s in stops]
    m = REGION_MARGIN_DEG
    return min(lats) - m, min(lons) - m, max(lats) + m, max(lons) + m


def inside(lat: float, lon: float, region) -> bool:
    south, west, north, east = region
    return south <= lat <= north and west <= lon <= east


def stop_feature(osm_id: str, kind: str, lat: float, lon: float, tags: dict[str, str]) -> StopFeature:
    return StopFeature(osm_id=osm_id, kind=kind, lat=lat, lon=lon, ref=tags.get("ref", ""),
                       name=tags.get("name", ""), operator=tags.get("operator", ""), tags=tags)


def read_extract(path: Path, store: OsmStore, region) -> tuple[int, int]:
    roads: list[Road] = []
    stops: list[StopFeature] = []
    n_roads = n_stops = 0
    processor = (osmium.FileProcessor(path).with_locations()
                 .with_areas(osmium.filter.KeyFilter(*TAG_KEYS))
                 .with_filter(osmium.filter.KeyFilter(*TAG_KEYS)))
    for obj in processor:
        tags = dict(obj.tags)
        if obj.is_node():
            kind = stop_kind(tags)
            if kind and inside(obj.location.lat, obj.location.lon, region):
                stops.append(stop_feature(f"n{obj.id}", kind, obj.location.lat, obj.location.lon, tags))
        elif obj.is_way():
            nodes = [(n.ref, n.lat, n.lon) for n in obj.nodes if n.location.valid()]
            if len(nodes) < 2 or not any(inside(lat, lon, region) for _, lat, lon in nodes):
                continue
            road = bus_road(tags)
            if road:
                highway, oneway = road
                roads.append(Road(way_id=obj.id, highway=highway, name=tags.get("name", ""), oneway=oneway,
                                  node_ids=tuple(n[0] for n in nodes),
                                  coords=tuple((lat, lon) for _, lat, lon in nodes)))
            kind = stop_kind(tags)
            if kind:  # a stop drawn as an area or a line: keep its centre
                ring = nodes[:-1] if nodes[0][0] == nodes[-1][0] else nodes
                lat = sum(n[1] for n in ring) / len(ring)
                lon = sum(n[2] for n in ring) / len(ring)
                stops.append(stop_feature(f"w{obj.id}", kind, lat, lon, tags))
        elif obj.is_area() and not obj.from_way():  # a multipolygon relation, e.g. a bus station's platforms
            kind = stop_kind(tags)
            ring = [(n.lat, n.lon) for outer in obj.outer_rings() for n in outer if n.location.valid()]
            if kind and ring:
                lat = sum(p[0] for p in ring) / len(ring)
                lon = sum(p[1] for p in ring) / len(ring)
                if inside(lat, lon, region):
                    stops.append(stop_feature(f"r{obj.orig_id()}", kind, lat, lon, tags))
        if len(roads) >= BATCH:
            n_roads += store.add_roads(roads)
            roads.clear()
    n_roads += store.add_roads(roads)
    n_stops += store.add_stops(stops)
    return n_roads, n_stops


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    missing = [p for p in EXTRACTS if not p.is_file()]
    if missing:
        raise SystemExit(f"missing extracts: {', '.join(map(str, missing))} (download from download.geofabrik.de)")
    region = network_region()
    store = OsmStore(STORE)
    store.create()
    for path in EXTRACTS:
        start = time.monotonic()
        n_roads, n_stops = read_extract(path, store, region)
        logger.info("%s: %d roads, %d stop-like objects in %.0f s", path.name, n_roads, n_stops,
                    time.monotonic() - start)
    store.set_meta({
        "built_at": utc_now(), "region": ",".join(f"{v:.4f}" for v in region),
        "extracts": ",".join(f"{p.name}@{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(p.stat().st_mtime))}"
                             for p in EXTRACTS),
    })
    logger.info("wrote %s", STORE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
