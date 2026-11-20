"""Phase 2, explore: find each stop in Street View with the LLM explorer, and keep 1-2 photos of it.

Several stops are explored at once (`concurrency` in the profile): each worker has its own Google
clients and its own pair of server slots (explorer, confirmer), so llama-server batches their
tokens together and the GPU stays busy while other workers wait on Google or on their tools.
Before a stop starts, the most it could bill is reserved in the usage ledger; a stop that would
go over the month's cap is not started.

A finished stop is stored at once (its record, photos, transcript); a stop interrupted half-way
is not stored, and is explored again by the next run.
"""

import hashlib
import json
import logging
import queue
import shutil
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ApiError, CotralMaintenanceError
from ..caches import BudgetExhausted, MetadataCache, UsageLedger
from ..explorer import HARNESS_VERSION
from ..explorer.aerial import EsriTiles, draw_aerial, place_found
from ..explorer.drawing import draw_map
from ..explorer.llm import ChatClient, Explorer, LlmConfirmer, LlmScanner
from ..explorer.session import MAX_IMAGES, MAX_SCAN_TILES, MAX_TILES, Session
from ..explorer.tileviews import TileViews
from ..explorer.world import build_world
from ..models import Stop, View
from ..osm_store import OsmStore
from ..provenance import git_state, utc_now
from ..routes import Service, load_shapes
from ..runstore import RunStore
from ..settings import GoogleKey, ModelSpec, Paths
from ..streetview import StreetViewClient
from ..tiles import MapTilesClient

logger = logging.getLogger(__name__)

PROMPT = Path(__file__).resolve().parents[1] / "explorer" / "prompt.md"


@dataclass
class ExploreContext:
    run: RunStore
    paths: Paths
    google: GoogleKey
    key_id: str
    spec: ModelSpec
    all_stops: dict[str, Stop]
    osm: OsmStore
    metadata: MetadataCache
    ledger: UsageLedger
    stop_event: threading.Event = field(default_factory=threading.Event)
    stop_reason: str = ""
    max_turns: int | None = None

    def stop(self, reason: str) -> None:
        if not self.stop_event.is_set():
            self.stop_reason = reason
        self.stop_event.set()

    @property
    def harness(self) -> dict:
        return harness(self.paths)


def harness(paths: Paths) -> dict:
    """The harness that explores: its version, the prompt's sha256, the reference images' sha256, git."""
    prompt = PROMPT.read_bytes()
    refs = hashlib.sha256()
    for path in [paths.reference_sign, *paths.lookalikes]:
        if path.is_file():
            refs.update(path.name.encode() + b"\0" + path.read_bytes())
    return {"version": HARNESS_VERSION, "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
            "references_sha256": refs.hexdigest(), "git": git_state()}


def explorer_description(spec: ModelSpec) -> dict:
    return {**spec.describe(), "confirmer": "same model, fresh call"}


def explore(ctx: ExploreContext, stop_ids: list[str], on_done: Callable[[str, str], None] | None = None) -> dict:
    """Explore the stops; returns counts per outcome. Stops when the budget runs out or ctx.stop_event is set."""
    rows = {i: ctx.run.stop(i) for i in stop_ids}
    shape_ids = {s["shape_id"] for r in rows.values() for s in r["services"]}
    shapes = load_shapes(ctx.paths.gtfs, shape_ids) if shape_ids else {}
    slots: queue.Queue = queue.Queue()
    for worker in range(ctx.spec.concurrency):
        slots.put((2 * worker, 2 * worker + 1) if ctx.spec.dialect == "llamacpp" else (None, None))
    counts: dict[str, int] = {}
    budget_out = threading.Event()

    def task(stop_id: str) -> str:
        if ctx.stop_event.is_set() or budget_out.is_set():
            return "skipped"
        try:
            reservation = ctx.ledger.reserve(ctx.key_id, {"static": MAX_IMAGES, "tiles": MAX_TILES + MAX_SCAN_TILES})
        except BudgetExhausted as error:
            if not budget_out.is_set():
                logger.warning("Google budget: %s. No more stops are started; re-run next month (or raise the cap).",
                               error)
            budget_out.set()
            return "skipped"
        slot_pair = slots.get()
        billed = {"static": 0, "tiles": 0}
        try:
            return explore_stop(ctx, rows[stop_id], shapes, slot_pair, billed)
        except ApiError as error:
            if error.fatal:
                ctx.stop(f"Google refused a request: {error}")
                raise
            logger.warning("%s: a Google request failed (%s); not stored, explored again next run", stop_id, error)
            return "failed"
        except CotralMaintenanceError as error:
            logger.warning("%s: %s; not stored, explored again next run", stop_id, error)
            return "failed"
        finally:
            slots.put(slot_pair)
            ctx.ledger.settle(reservation, billed)
            month = reservation.month
            for api, n in billed.items():
                ctx.run.add_usage(month, ctx.key_id, api, n)

    with ThreadPoolExecutor(ctx.spec.concurrency, thread_name_prefix="explore") as pool:
        futures = {pool.submit(task, i): i for i in stop_ids}
        try:
            for done, future in enumerate(as_completed(futures), 1):
                stop_id = futures[future]
                try:
                    status = future.result()
                except Exception:  # a bug in one stop must not end a run of hundreds
                    logger.exception("Exploring %s failed", stop_id)
                    status = "crashed"
                counts[status] = counts.get(status, 0) + 1
                if status != "skipped":
                    logger.info("[%d/%d] %s: %s", done, len(stop_ids), stop_id, status)
                if on_done:
                    on_done(stop_id, status)
        except KeyboardInterrupt:
            ctx.stop_event.set()
            for f in futures:
                f.cancel()
            logger.warning("Interrupted: waiting for the stops in flight to stop (they are not stored)")
            raise
    return counts


def progress_line(stop_id: str, entry: dict) -> None:
    """One log line per explorer turn and per confirmer call, so a stop in progress shows that it is moving."""
    if "tool_calls" in entry:
        calls = ", ".join(f"{c['name']}({c['arguments'][:80]})" for c in entry["tool_calls"]) or "no tool call"
        timings = entry.get("timings") or {}
        logger.info("%s turn %d: %s (%.0f s, %s prompt tokens new, %s generated)", stop_id, entry["turn"], calls,
                    entry.get("seconds") or 0, timings.get("prompt_n"), timings.get("predicted_n"))
    elif "error" in entry and "turn" in entry:
        logger.warning("%s turn %d: %s", stop_id, entry["turn"], entry["error"][:200])
    elif "confirm" in entry:
        logger.info("%s confirmer: %s on %s", stop_id, entry.get("status"), entry.get("photo"))
    elif "scan" in entry:
        logger.info("%s scan: %s on %s", stop_id, entry.get("status"), entry.get("piece"))


def explore_stop(ctx: ExploreContext, row: dict, shapes: dict, slots: tuple[int | None, int | None],
                 billed: dict[str, int]) -> str:
    stop_id = row["stop_id"]
    work = ctx.run.root / "work" / stop_id
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    transcript: list[dict] = []
    lock = threading.Lock()

    def log(entry: dict) -> None:
        with lock:
            transcript.append({"at": utc_now(), **entry})
        progress_line(stop_id, entry)

    started_at, t0 = utc_now(), time.monotonic()
    sv = StreetViewClient(ctx.google.api_key, 20.0, ctx.google.referrer)
    tiles_client = MapTilesClient(ctx.google.api_key, ctx.paths.cache / "tiles", 20.0, ctx.google.referrer)
    tiles = TileViews(tiles_client)
    explorer_slot, confirmer_slot = slots
    spec = ctx.spec
    client = ChatClient(spec.server.url, spec.model, spec.dialect, spec.sampling, spec.template, spec.max_tokens,
                        request=spec.request)
    confirmer = LlmConfirmer(client, ctx.paths.reference_sign, ctx.paths.lookalikes, log, confirmer_slot)
    scanner = LlmScanner(client, ctx.paths.reference_sign, log, confirmer_slot)
    base = {"stop_id": stop_id, "explorer": explorer_description(spec),
            "harness": ctx.harness, "started_at": started_at}
    session: Session | None = None
    try:
        made = make_session(ctx, row, shapes, work, sv, tiles, confirmer, scanner)
        if isinstance(made, tuple):
            return _store_without_search(ctx, base, *made, t0, transcript)
        session = made
        agent = Explorer(client, PROMPT.read_text(), [ctx.paths.reference_sign, *ctx.paths.lookalikes], draw_map,
                         explorer_slot, should_stop=ctx.stop_event.is_set)
        if ctx.max_turns:
            agent.max_turns = ctx.max_turns
        ended, turns = agent.run(session, log)
        if ended == "interrupted":
            return "interrupted"
        if ended.startswith("server unreachable"):
            ctx.stop(f"the explorer server is unreachable ({ended})")
            logger.error("The explorer server is unreachable (%s); stopping", ended)
            return "server_down"
        session.finish(f"the explorer ended: {ended}")
        _store(ctx, base, session, ended, turns, t0, transcript, work)
        return session.outcome["status"]
    finally:
        if session is not None:
            billed.update(session.billed_requests())
        sv.close()
        tiles_client.close()
        shutil.rmtree(work, ignore_errors=True)


def make_session(ctx: ExploreContext, row: dict, shapes: dict, work: Path, sv: StreetViewClient, tiles: TileViews,
                 confirmer, scanner) -> Session | tuple[str, str]:
    stop_id = row["stop_id"]
    stop = ctx.all_stops.get(stop_id) or Stop(stop_id, row["name"], row["gtfs_lat"], row["gtfs_lon"])
    services = [Service(s["shape_id"], s["trips"], tuple(s["previous"]), tuple(s["next"])) for s in row["services"]]
    start = ctx.run.start(stop_id) or {}
    places = (start["lat"], start["lon"]) if start.get("source") == "places" else None
    try:
        world = build_world(stop, services, shapes, ctx.all_stops, places, ctx.osm, ctx.metadata)
    except ValueError as error:
        return "error", f"world: {error}"
    if not world.panoramas:
        return "no_imagery", "no Street View from 2024 on along the path"
    world.found = place_found(world, [(r["stop_id"], r["name"], r["lat"], r["lon"]) for r in ctx.run.query(
        "select e.stop_id, s.name, e.lat, e.lon from explorations e join stops s using (stop_id) "
        "where e.status = 'found' and e.lat is not null and e.stop_id != ?", (stop_id,))])
    aerial = None
    esri = EsriTiles(ctx.paths.cache / "street_map")
    try:
        aerial = draw_aerial(world, work / "aerial.jpg", esri)
    except Exception as error:
        logger.warning("%s: no aerial map (%s)", stop_id, error)
    finally:
        esri.close()

    def fetch(pano_id: str, heading: float, fov: float, pitch: float, width: int, height: int) -> bytes:
        return sv.get_image(pano_id, heading, View("agent", pitch=pitch, fov=fov, size=f"{width}x{height}"))

    return Session(world, work, ctx.paths.cache / "streetview_images", ctx.metadata, fetch, confirmer, tiles,
                   {k: v for k, v in ctx.harness.items() if k != "git"}, aerial=aerial, scanner=scanner)


def _store_without_search(ctx: ExploreContext, base: dict, status: str, reason: str, t0: float,
                          transcript: list[dict]) -> str:
    ctx.run.put_exploration({**base, "status": status, "reason": reason, "billed_static": 0, "billed_tiles": 0,
                             "turns": 0, "seconds": round(time.monotonic() - t0, 1), "finished_at": utc_now(),
                             "record": {"outcome": {"status": status, "reason": reason}}}, [], transcript)
    return status


def _store(ctx: ExploreContext, base: dict, session: Session, ended: str, turns: int, t0: float,
           transcript: list[dict], work: Path) -> None:
    """Move the run's files into the store's media and rewrite every file reference as a sha256."""
    shas: dict[str, str] = {}
    for path in sorted(work.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            shas[str(path.relative_to(work))] = ctx.run.put_media(path.read_bytes())
    record = session.record()
    record = json.loads(json.dumps(record), object_hook=lambda d: _rewrite(d, shas))
    outcome = record["outcome"] or {}
    photos = [{"idx": p["index"], "media": p["file"], "toward": p["toward"], "pano_id": p["pano_id"],
               "date": p["date"], "heading": p["heading"], "fov": p["fov"], "pitch": p["pitch"], "width": p["width"],
               "height": p["height"], "lat": p["lat"], "lon": p["lon"]} for p in record["photos"]]
    billed = session.billed_requests()
    ctx.run.put_exploration({
        **base, "status": outcome.get("status", "not_found"), "reason": outcome.get("reason") or ended,
        "lat": outcome.get("lat"), "lon": outcome.get("lon"), "position_basis": outcome.get("position_basis"),
        "evidence": outcome.get("evidence"), "plate_text": outcome.get("plate_text"),
        "scan_date": outcome.get("scan_date"), "stop_photos": outcome.get("stop_photos") or [],
        "billed_static": billed["static"], "billed_tiles": billed["tiles"], "turns": turns,
        "seconds": round(time.monotonic() - t0, 1), "finished_at": utc_now(), "record": record,
    }, photos, transcript)


def _rewrite(d: dict, shas: dict[str, str]) -> dict:
    """Replace work-directory file paths by media sha256s, wherever the record mentions them."""
    for k, v in d.items():
        if isinstance(v, str) and v in shas:
            d[k] = shas[v]
        elif isinstance(v, list):
            d[k] = [shas.get(x, x) if isinstance(x, str) else x for x in v]
    return d
