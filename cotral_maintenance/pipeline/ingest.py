import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from ..caches import BudgetExhausted, UsageLedger
from ..fileutils import RawStore
from ..models import Stop
from ..osm_match import match_osm
from ..osm_store import OsmStore
from ..places import PlacesClient
from ..routes import load_services
from ..runstore import RunStore
from ..stops import is_cotral_stop
from ..verification import CONFIRMED, build_dataset, fetch_stop

logger = logging.getLogger(__name__)

PLACES_WORKERS = 8


def stop_rows(stops: list[Stop], services: dict[str, list]) -> list[dict]:
    return [{"stop_id": s.stop_id, "name": s.name, "gtfs_lat": s.lat, "gtfs_lon": s.lon,
             "services": [asdict(v) for v in services.get(s.stop_id, [])]} for s in stops]


def select_into_run(run: RunStore, stops: list[Stop], gtfs_dir) -> int:
    known = set(run.stop_ids())
    new = [s for s in stops if s.stop_id not in known]
    if not new:
        return 0
    logger.info("Reading the GTFS services of %d stops", len(new))
    services = load_services(gtfs_dir, [s.stop_id for s in new])
    missing = [s.stop_id for s in new if not services.get(s.stop_id)]
    if missing:
        logger.warning("%d stops have no trips in the GTFS (searched without a path): %s", len(missing),
                       ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
    return run.add_stops(stop_rows(new, services))


def ingest(run: RunStore, stop_ids: list[str], all_stops: list[Stop], osm: OsmStore, places_cache: RawStore,
           make_places: Callable[[], PlacesClient] | None, ledger: UsageLedger | None, key: str | None) -> dict:
    by_id = {s.stop_id: s for s in all_stops}
    cotral = [s for s in all_stops if is_cotral_stop(s)]
    stops = [by_id[i] for i in stop_ids]
    matches = {s.stop_id: match_osm(s, osm, cotral) for s in stops}
    need_places = [s for s in stops if matches[s.stop_id] is None]
    logger.info("OSM has %d of %d stops; %d go to Places", len(stops) - len(need_places), len(stops),
                len(need_places))
    fetched = 0
    if need_places and make_places is not None:
        fetched = _fetch_places(need_places, places_cache, make_places, ledger, key)
    corrected = {row.stop_id: row for row in build_dataset(all_stops, places_cache)} if need_places else {}

    counts = {"osm": 0, "places": 0, "gtfs": 0, "places_fetched": fetched, "waiting_for_places": 0}
    for s in stops:
        m = matches[s.stop_id]
        if m is None and make_places is not None and not places_cache.has(s.stop_id):
            counts["waiting_for_places"] += 1
            continue
        row: dict = {"stop_id": s.stop_id}
        if m is not None:
            f = m.feature
            row |= {"source": "osm", "lat": f.lat, "lon": f.lon,
                    "osm": {"osm_id": f.osm_id, "kind": f.kind, "how": m.how, "from_gtfs_m": round(m.from_gtfs_m, 1),
                            "ref": f.ref, "name": f.name, "operator": f.operator}}
        else:
            c = corrected.get(s.stop_id)
            if c is not None and places_cache.has(s.stop_id):
                row["places"] = {"status": str(c.status), "reason": c.reason, "lat": c.stop_lat, "lon": c.stop_lon,
                                 "offset_m": c.offset_m, "place_id": c.place_id, "place_name": c.place_name,
                                 "google_stop_id": c.google_stop_id, "fetched_at": c.fetched_at}
            if c is not None and c.status in CONFIRMED and c.coord_source == "places":
                row |= {"source": "places", "lat": c.stop_lat, "lon": c.stop_lon}
            else:
                row |= {"source": "gtfs", "lat": s.lat, "lon": s.lon}
        run.put_start(row)
        counts[row["source"]] += 1
    if counts["waiting_for_places"]:
        logger.warning("%d stops have no Places answer yet (budget or errors): not ingested, retried next run",
                       counts["waiting_for_places"])
    return counts


def _fetch_places(stops: list[Stop], cache: RawStore, make_client: Callable[[], PlacesClient],
                  ledger: UsageLedger | None, key: str | None) -> int:
    todo = [s for s in stops if not cache.has(s.stop_id)]
    if not todo:
        return 0

    def one(stop: Stop) -> bool:
        reservation = None
        if ledger is not None and key is not None:
            try:
                reservation = ledger.reserve(key, {"places": 1})
            except BudgetExhausted as error:
                logger.warning("No Places search for %s: %s", stop.stop_id, error)
                return False
        billed = 0
        try:
            with make_client() as client:
                billed = int(fetch_stop(stop, client, cache))
        except Exception as error:
            logger.warning("Places search failed for %s: %s", stop.stop_id, error)
        finally:
            if reservation is not None:
                ledger.settle(reservation, {"places": billed})
        return bool(billed)

    with ThreadPoolExecutor(PLACES_WORKERS) as pool:
        return sum(pool.map(one, todo))
