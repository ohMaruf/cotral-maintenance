"""Building one explorer session: the world of a stop, the image sources, the confirmer.

Shared by the MCP server (Claude Code runs, agent_server.py) and the local Qwen runner
(qwen_run.py), so both explore with exactly the same harness.
"""

import csv
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.config import Settings  # noqa: E402
from cotral_maintenance.explorer.confirmer import Confirmer  # noqa: E402
from cotral_maintenance.explorer.session import Session  # noqa: E402
from cotral_maintenance.explorer.tileviews import TileViews  # noqa: E402
from cotral_maintenance.explorer.world import MetadataCache, build_world  # noqa: E402
from cotral_maintenance.models import View  # noqa: E402
from cotral_maintenance.osm_store import OsmStore  # noqa: E402
from cotral_maintenance.routes import load_services, load_shapes  # noqa: E402
from cotral_maintenance.stops import load_stops  # noqa: E402
from cotral_maintenance.streetview import StreetViewClient  # noqa: E402
from cotral_maintenance.tiles import MapTilesClient  # noqa: E402

GTFS = Path("GTFS_COTRAL")
PLACES = Path("data/stops_corrected.csv")
STORE = Path("data/osm/osm.sqlite3")
CACHE = Path("data/agent_runs/cache")
TILES = Path("data/tiles")
REFERENCE = Path("inputs/GROUND_TRUTH/stop_sign_reference.png")
LOOKALIKES = Path("inputs/GROUND_TRUTH/lookalikes")


def build_session(run_dir: Path, config: dict, make_confirmer: Callable[[Path], Confirmer]) -> Session:
    """`make_confirmer(log_dir)` gives the confirmer; everything else is the same for every explorer model."""
    stop_id = config["stop_id"]
    stops = {s.stop_id: s for s in load_stops(GTFS / "stops.txt")}
    services = load_services(GTFS, [stop_id])[stop_id]
    shapes = load_shapes(GTFS, {s.shape_id for s in services})
    places = None
    with PLACES.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["stop_id"] == stop_id and r["coord_source"] == "places":
                places = (float(r["stop_lat"]), float(r["stop_lon"]))
    settings = Settings.from_env()
    client = StreetViewClient(settings.api_key, settings.request_timeout_s, settings.referrer)
    metadata = MetadataCache(CACHE / "metadata.json", client.get_metadata)
    world = build_world(stops[stop_id], services, shapes, stops, places, OsmStore(STORE), metadata)

    def fetch(pano_id: str, heading: float, fov: float, pitch: float, width: int, height: int) -> bytes:
        # One billed Static API request (the session counts them against the per-stop budget).
        return client.get_image(pano_id, heading, View("agent", pitch=pitch, fov=fov, size=f"{width}x{height}"))

    tiles = TileViews(MapTilesClient(settings.api_key, TILES, settings.request_timeout_s, settings.referrer))
    return Session(world, run_dir, CACHE / "images", metadata, fetch, make_confirmer(run_dir / "confirmer"), tiles,
                   config.get("harness"))
