"""Local OpenStreetMap store: drivable roads and stop-like objects, in SQLite.

Built once from Geofabrik extracts (experiments/explore/build_osm_store.py), then
queried by bounding box through R-tree indexes, so a stop's neighbourhood loads in
milliseconds without any server.

Roads keep what routing a bus needs: the node ids (for connectivity), the
coordinates, the highway class, the name, and the one-way rule *for a bus*
(`oneway:bus` / `oneway:psv` override `oneway`; roundabouts are one-way).

Stop-like objects are every way OSM mappers record a stop, whatever the tagging:
  bus_stop       highway=bus_stop
  platform       public_transport=platform or highway=platform
  stop_position  public_transport=stop_position (where the bus halts, on the road)
  shelter        amenity=shelter + shelter_type=public_transport, without stop tags
  bus_station    amenity=bus_station
Ways (a shelter drawn as a building) and multipolygon relations (a bus station's
platforms) are stored at the centre of their outline.
"""

import json
import re
import sqlite3
from math import cos, radians
from array import array
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

# Roads a bus may drive on. Tracks, paths, footways and the like are left out.
BUS_HIGHWAYS = frozenset({
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
    "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
    "service", "road", "busway", "bus_guideway",
})
CLOSED_ACCESS = frozenset({"no", "private"})
OPEN_ACCESS = frozenset({"yes", "designated", "permissive", "destination"})
STOP_KINDS = ("bus_stop", "platform", "stop_position", "shelter", "bus_station")

BBox = tuple[float, float, float, float]  # south, west, north, east


@dataclass(frozen=True)
class Road:
    way_id: int
    highway: str
    name: str
    oneway: int  # for a bus: 1 along the node order, -1 against it, 0 both ways
    node_ids: tuple[int, ...]
    coords: tuple[tuple[float, float], ...]  # (lat, lon) per node


@dataclass(frozen=True)
class StopFeature:
    osm_id: str  # "n123", "w456", "r789"
    kind: str  # one of STOP_KINDS
    lat: float
    lon: float
    ref: str
    name: str
    operator: str
    tags: Mapping[str, str]


def bus_road(tags: Mapping[str, str]) -> tuple[str, int] | None:
    """(highway, oneway for a bus) if a bus may use the road, else None."""
    highway = tags.get("highway", "")
    if highway not in BUS_HIGHWAYS:
        return None
    if highway != "busway" and tags.get("area") == "yes":
        return None
    for key in ("access", "motor_vehicle", "vehicle"):
        if tags.get(key) in CLOSED_ACCESS and not (
                tags.get("bus") in OPEN_ACCESS or tags.get("psv") in OPEN_ACCESS):
            return None
    return highway, _bus_oneway(tags)


def _bus_oneway(tags: Mapping[str, str]) -> int:
    for key in ("oneway:bus", "oneway:psv"):
        value = tags.get(key)
        if value == "no":
            return 0
        if value in ("yes", "1", "true"):
            return 1
        if value == "-1":
            return -1
    value = tags.get("oneway")
    if value in ("yes", "1", "true"):
        return 1
    if value == "-1":
        return -1
    if value == "no":
        return 0
    if tags.get("junction") in ("roundabout", "circular") or tags.get("highway") == "motorway":
        return 1
    return 0


def stop_kind(tags: Mapping[str, str]) -> str | None:
    """The kind of stop-like object the tags describe, or None."""
    if tags.get("highway") == "bus_stop":
        return "bus_stop"
    if tags.get("public_transport") == "platform" or tags.get("highway") == "platform":
        return "platform"
    if tags.get("public_transport") == "stop_position":
        return "stop_position"
    if tags.get("amenity") == "bus_station":
        return "bus_station"
    if tags.get("amenity") == "shelter" and tags.get("shelter_type") == "public_transport":
        return "shelter"
    return None


class OsmStore:
    """Read and write access to the store file. One short-lived connection per call."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    # ---- building ----

    def create(self) -> None:
        """A new empty store; an existing file is replaced."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(f"""
                PRAGMA user_version = {SCHEMA_VERSION};
                CREATE TABLE roads (
                    way_id INTEGER PRIMARY KEY, highway TEXT NOT NULL, name TEXT NOT NULL,
                    oneway INTEGER NOT NULL, node_ids BLOB NOT NULL, coords BLOB NOT NULL);
                CREATE VIRTUAL TABLE roads_rtree USING rtree(way_id, south, north, west, east);
                CREATE TABLE stops (
                    osm_id TEXT PRIMARY KEY, rtree_id INTEGER UNIQUE NOT NULL, kind TEXT NOT NULL,
                    lat REAL NOT NULL, lon REAL NOT NULL, ref TEXT NOT NULL, name TEXT NOT NULL,
                    operator TEXT NOT NULL, tags TEXT NOT NULL);
                CREATE VIRTUAL TABLE stops_rtree USING rtree(id, south, north, west, east);
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def add_roads(self, roads: Iterable[Road]) -> int:
        count = 0
        with closing(self._connect()) as conn, conn:
            for road in roads:
                lats = [c[0] for c in road.coords]
                lons = [c[1] for c in road.coords]
                conn.execute("INSERT OR REPLACE INTO roads VALUES (?, ?, ?, ?, ?, ?)", (
                    road.way_id, road.highway, road.name, road.oneway,
                    array("q", road.node_ids).tobytes(), array("d", [v for c in road.coords for v in c]).tobytes()))
                conn.execute("INSERT OR REPLACE INTO roads_rtree VALUES (?, ?, ?, ?, ?)",
                             (road.way_id, min(lats), max(lats), min(lons), max(lons)))
                count += 1
        return count

    def add_stops(self, stops: Iterable[StopFeature]) -> int:
        count = 0
        with closing(self._connect()) as conn, conn:
            for stop in stops:
                numeric = _numeric_id(stop.osm_id)
                conn.execute("INSERT OR REPLACE INTO stops VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    stop.osm_id, numeric, stop.kind, stop.lat, stop.lon, stop.ref, stop.name, stop.operator,
                    json.dumps(dict(stop.tags), ensure_ascii=False, sort_keys=True)))
                conn.execute("INSERT OR REPLACE INTO stops_rtree VALUES (?, ?, ?, ?, ?)",
                             (numeric, stop.lat, stop.lat, stop.lon, stop.lon))
                count += 1
        return count

    def set_meta(self, values: Mapping[str, str]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", values.items())

    # ---- reading ----

    def meta(self) -> dict[str, str]:
        with closing(self._connect()) as conn:
            return dict(conn.execute("SELECT key, value FROM meta"))

    def roads_in(self, bbox: BBox) -> list[Road]:
        """Roads whose bounding box meets bbox."""
        south, west, north, east = bbox
        with closing(self._connect()) as conn:
            rows = conn.execute("""
                SELECT r.way_id, r.highway, r.name, r.oneway, r.node_ids, r.coords
                FROM roads_rtree t JOIN roads r ON r.way_id = t.way_id
                WHERE t.north >= ? AND t.south <= ? AND t.east >= ? AND t.west <= ?""",
                                (south, north, west, east)).fetchall()
        return [_road(row) for row in rows]

    def stops_in(self, bbox: BBox) -> list[StopFeature]:
        south, west, north, east = bbox
        with closing(self._connect()) as conn:
            rows = conn.execute("""
                SELECT s.osm_id, s.kind, s.lat, s.lon, s.ref, s.name, s.operator, s.tags
                FROM stops_rtree t JOIN stops s ON s.rtree_id = t.id
                WHERE t.north >= ? AND t.south <= ? AND t.east >= ? AND t.west <= ?""",
                                (south, north, west, east)).fetchall()
        return [StopFeature(osm_id=r[0], kind=r[1], lat=r[2], lon=r[3], ref=r[4], name=r[5], operator=r[6],
                            tags=json.loads(r[7])) for r in rows]

    def stops_with_ref(self, ref: str) -> list[StopFeature]:
        """Stop-like objects whose `ref` lists this value (case-insensitive; refs may hold several, `;`-separated)."""
        wanted = ref.strip().lower()
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT osm_id, kind, lat, lon, ref, name, operator, tags FROM stops "
                                "WHERE lower(ref) LIKE ?", (f"%{wanted}%",)).fetchall()
        return [StopFeature(osm_id=r[0], kind=r[1], lat=r[2], lon=r[3], ref=r[4], name=r[5], operator=r[6],
                            tags=json.loads(r[7])) for r in rows
                if wanted in (p for p in re.split(r"[;,\s]+", r[4].lower()) if p)]

    def all_stops(self) -> Iterator[StopFeature]:
        with closing(self._connect()) as conn:
            for r in conn.execute("SELECT osm_id, kind, lat, lon, ref, name, operator, tags FROM stops"):
                yield StopFeature(osm_id=r[0], kind=r[1], lat=r[2], lon=r[3], ref=r[4], name=r[5], operator=r[6],
                                  tags=json.loads(r[7]))


def _numeric_id(osm_id: str) -> int:
    """A unique integer per element for the R-tree: the element number times 3, plus 0, 1 or 2
    for a node, a way or a relation."""
    kind, number = osm_id[0], int(osm_id[1:])
    if kind not in "nwr":
        raise ValueError(f"unsupported OSM element {osm_id}")
    return number * 3 + "nwr".index(kind)


def _road(row: tuple) -> Road:
    node_ids = array("q")
    node_ids.frombytes(row[4])
    flat = array("d")
    flat.frombytes(row[5])
    coords = tuple((flat[i], flat[i + 1]) for i in range(0, len(flat), 2))
    return Road(way_id=row[0], highway=row[1], name=row[2], oneway=row[3], node_ids=tuple(node_ids), coords=coords)


def bbox_around(lat: float, lon: float, radius_m: float) -> BBox:
    """A bounding box reaching radius_m from (lat, lon) in every direction."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(cos(radians(lat)), 1e-6))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon
