"""Build the local OSM store (osm_store.py) from the dataset's OSM extracts: `cotral osm build`.

Input: the dataset's `osm` sources (for Cotral, Geofabrik's Central and Southern Italy extracts), each checked
against its sha256. `cotral osm download` replaces them with their newest copies, for making a new dataset.
Only what lies within REGION_MARGIN_DEG of the network's extent (from the GTFS stops) is kept:
  - roads a bus may drive on, with the one-way rule for a bus
  - every stop-like object (bus stops, platforms, stop positions, public-transport
    shelters, bus stations), whatever its tagging
Output: the OSM store (replaced). pyosmium is in the "osm" extra.
"""

import logging
import re
import time
from pathlib import Path

import requests

from .dataset import Source, sha256_file
from .osm_store import OsmStore, Road, StopFeature, bus_road, stop_kind
from .provenance import utc_now
from .stops import load_stops

BUILD_VERSION = 2  # bump when the build's output changes for the same extracts (what is kept, how)
REGION_MARGIN_DEG = 0.05  # about 5 km around the network's extent
BATCH = 20_000
TAG_KEYS = ("highway", "public_transport", "amenity")

logger = logging.getLogger(__name__)


def network_region(stops_file: Path) -> tuple[float, float, float, float]:
    stops = [s for s in load_stops(stops_file) if re.fullmatch(r"f\d+", s.stop_id)]
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
    import osmium

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


def download(sources: list[Source]) -> list[dict]:
    """Download the newest copy of each OSM source from its url (Geofabrik's "-latest" files change daily), in
    place of the pinned one: for making a new dataset. Returns what to write in the manifest."""
    out = []
    for source in sources:
        if not source.url:
            raise ValueError(f"{source.file} has no url")
        tmp = source.path.with_name(source.path.name + ".part")
        source.path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s", source.url)
        with requests.get(source.url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        tmp.replace(source.path)
        out.append({"file": source.file, "sha256": sha256_file(source.path), "retrieved": utc_now()[:10]})
    return out


def build(sources: list[Source], store_path: Path, stops_file: Path) -> dict:
    """Build the store from the dataset's OSM extracts, each checked against its sha256 first. The store records
    the build version and the extracts' sha256: what the ingest version is made of, the same on every machine."""
    import osmium  # noqa: F401  (the "osm" extra; checked before the store is emptied)

    if not sources:
        raise ValueError("the dataset has no osm source")
    bad = {s.file: state for s in sources if (state := s.state()) != "ok"}
    if bad:
        raise ValueError(f"OSM extracts not usable: {bad} (`cotral inputs fetch`; Git LFS pointers need `git lfs pull`)")
    extracts = [s.path for s in sources]
    region = network_region(stops_file)
    store = OsmStore(store_path)
    store.create()
    totals = {"roads": 0, "stops": 0}
    for path in extracts:
        start = time.monotonic()
        n_roads, n_stops = read_extract(path, store, region)
        totals["roads"] += n_roads
        totals["stops"] += n_stops
        logger.info("%s: %d roads, %d stop-like objects in %.0f s", path.name, n_roads, n_stops,
                    time.monotonic() - start)
    store.set_meta({
        "built_at": utc_now(), "build_version": str(BUILD_VERSION), "region": ",".join(f"{v:.4f}" for v in region),
        "extracts": ",".join(p.name for p in extracts),
        "extracts_sha256": ",".join(s.sha256 for s in sources),
    })
    return totals
