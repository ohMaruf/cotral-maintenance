import io
import json
import math
import os
import shutil
import sys
import threading
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_client import ClaudeCodeClient
from cotral_maintenance.caches import UsageLedger, key_id, open_metadata_cache
from cotral_maintenance.explorer.drawing import draw_map
from cotral_maintenance.explorer.llm import (MAX_REPEATS, STALL_END, STALL_NUDGE, TOOLS, LlmConfirmer, LlmScanner,
                                             call, check, progress)
from cotral_maintenance.explorer.session import MAX_IMAGES, MAX_SCAN_TILES, MAX_TILES, ToolError
from cotral_maintenance.explorer.tileviews import TileViews
from cotral_maintenance.osm_store import OsmStore
from cotral_maintenance.pipeline.explore import ExploreContext, make_session
from cotral_maintenance.routes import load_shapes
from cotral_maintenance.runstore import RunStore
from cotral_maintenance.settings import GoogleKey, Paths
from cotral_maintenance.stops import load_stops
from cotral_maintenance.streetview import StreetViewClient
from cotral_maintenance.tiles import MapTilesClient

STOP = os.environ["DEVLOOP_STOP"]
SOURCE = os.environ["DEVLOOP_SOURCE_RUN"]
OUT = Path(os.environ["DEVLOOP_OUT"])
MAX_TURNS = int(os.environ.get("DEVLOOP_MAX_TURNS", "45"))
VISION_MODEL = os.environ.get("DEVLOOP_VISION_MODEL", "haiku")
TRUTH = json.loads((Path(__file__).resolve().parent / "truth.json").read_text())

mcp = MCPServer("explorer")
lock = threading.Lock()
state: dict = {"session": None, "turns": 0, "stalled": 0, "repeats": 0, "last_failure": None, "ended": None}
log_file = OUT / STOP / "log.jsonl"


def log(entry: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def build():
    paths = Paths.from_env()
    google = GoogleKey.from_env()
    run = RunStore(paths.runs / SOURCE)
    row = run.stop(STOP)
    shapes = load_shapes(paths.gtfs, {s["shape_id"] for s in row["services"]})
    sv = StreetViewClient(google.api_key, 20.0, google.referrer)
    metadata = open_metadata_cache(paths.cache, sv.get_metadata)
    ledger = UsageLedger(paths.cache / "usage.sqlite")
    kid = key_id(google.api_key)
    state["reservation"] = ledger.reserve(kid, {"static": MAX_IMAGES, "tiles": MAX_TILES + MAX_SCAN_TILES})
    state["ledger"] = ledger
    ctx = ExploreContext(run, paths, google, kid, None, {s.stop_id: s for s in load_stops(paths.gtfs / "stops.txt")},
                         OsmStore(paths.osm_store), metadata, ledger)
    client = ClaudeCodeClient(VISION_MODEL, str(ROOT))
    confirmer = LlmConfirmer(client, paths.reference_sign, paths.lookalikes, log)
    scanner = LlmScanner(client, paths.reference_sign, log)
    work = OUT / STOP / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    tiles = TileViews(MapTilesClient(google.api_key, paths.cache / "tiles", 20.0, google.referrer))
    made = make_session(ctx, row, shapes, work, sv, tiles, confirmer, scanner)
    if isinstance(made, tuple):
        raise ValueError(f"{STOP}: {made[0]} ({made[1]})")
    state["references"] = [paths.reference_sign, *paths.lookalikes]
    return made


def finish(reason: str) -> None:
    session = state["session"]
    if state["ended"] is not None or session is None:
        return
    state["ended"] = reason
    session.finish(f"the explorer ended: {reason}")
    session.save()
    billed = session.billed_requests()
    state["ledger"].settle(state["reservation"], billed)
    outcome = session.outcome or {}
    summary = {"stop": STOP, "status": outcome.get("status"), "ended": reason, "turns": state["turns"],
               "images": session.explore_used, "tiles": len(session.tiles_paid), "scan_tiles": len(session.scan_tiles),
               "billed": billed, "lat": outcome.get("lat"), "lon": outcome.get("lon"),
               "evidence": outcome.get("evidence"), "plate": outcome.get("plate_text")}
    truth = TRUTH.get(STOP)
    if truth and outcome.get("lat") is not None:
        dy = (outcome["lat"] - truth[0]) * 111320
        dx = (outcome["lon"] - truth[1]) * 111320 * math.cos(math.radians(truth[0]))
        summary["from_truth_m"] = round(math.hypot(dx, dy), 1)
    with (OUT / "results.jsonl").open("a") as f:
        f.write(json.dumps(summary) + "\n")


def jpeg(path: Path) -> Image:
    img = PILImage.open(path).convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return Image(data=buffer.getvalue(), format="jpeg")


def run_tool(name: str, args: dict) -> list:
    with lock:
        if state["ended"] is not None:
            return [f"The search is over ({state['ended']}). Stop now."]
        if state["session"] is None:
            if name != "begin":
                return ["Call begin() first."]
            state["session"] = build()
        session = state["session"]
        state["turns"] += 1
        before = progress(session)
        problem = check(name, args)
        failed = None
        try:
            if problem:
                raise ToolError(problem)
            result = call(session, name, args, state["references"], draw_map)
            content = [result.text, *(jpeg(p) for p in result.images)]
        except ToolError as error:
            session.log_error(name, args, str(error))
            failed = f"{name}:{error}"
            content = [f"ERROR: {error}"]
        log({"turn": state["turns"], "tool": name, "args": args, "error": failed})
        state["repeats"] = state["repeats"] + 1 if failed and failed == state["last_failure"] else (1 if failed else 0)
        state["last_failure"] = failed
        state["stalled"] = 0 if progress(session) != before else state["stalled"] + 1
        if session.outcome is not None:
            finish("outcome")
        elif state["repeats"] >= MAX_REPEATS:
            finish("stuck repeating a failing call")
        elif session.exhausted():
            finish(session.exhausted())
        elif state["stalled"] >= STALL_END:
            finish("stalled")
        elif state["turns"] >= MAX_TURNS:
            finish("turn cap")
        if state["ended"] is not None:
            content.append(f"HARNESS: the search is over ({state['ended']}). Stop now.")
        elif state["repeats"] >= 2:
            content.append("HARNESS: That call failed again with the same error. Read the error, fix the arguments "
                           "or do something else.")
        elif state["stalled"] == STALL_NUDGE:
            content.append("HARNESS: The last turns changed nothing.")
        return content


SPECS = {t["function"]["name"]: t["function"] for t in TOOLS}


def register(name: str, fn) -> None:
    mcp.tool(name=name, description=SPECS[name]["description"])(fn)


def begin() -> list:
    return run_tool("begin", {})


def sweep(at_m: float) -> list:
    return run_tool("sweep", {"at_m": at_m})


def zoom(photo: int, x: float, y: float, fov: float, what: str) -> list:
    return run_tool("zoom", {"photo": photo, "x": x, "y": y, "fov": fov, "what": what})


def look_from(candidate: int) -> list:
    return run_tool("look_from", {"candidate": candidate})


def mark_candidate(photo: int, x: float, y: float, kind: str, same_as: int | None = None) -> list:
    return run_tool("mark_candidate", {"photo": photo, "x": x, "y": y, "kind": kind, "same_as": same_as})


def confirm(candidate: int) -> list:
    return run_tool("confirm", {"candidate": candidate})


def submit_found(candidate: int) -> list:
    return run_tool("submit_found", {"candidate": candidate})


def find_other_scans(at_m: float) -> list:
    return run_tool("find_other_scans", {"at_m": at_m})


def show_map() -> list:
    return run_tool("show_map", {})


for _fn in (begin, sweep, zoom, look_from, mark_candidate, confirm, submit_found, find_other_scans, show_map):
    register(_fn.__name__, _fn)

if __name__ == "__main__":
    mcp.run()
