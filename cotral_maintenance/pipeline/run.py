"""The end-to-end pipeline on one run: GTFS records in, ranked maintenance scores out.

    ingest   GTFS -> OSM (Geofabrik) -> Places -> GTFS: where each stop's search starts (CPU, Places API)
    explore  the LLM explorer finds each stop in Street View and keeps 1-2 photos of it (GPU, Street View)
    score    Imajev scores each found stop from its photos (GPU)
    export   results.csv, ranked

Explore and score need different models, and one GPU holds one of them at a time, so the stops are
taken in chunks: explore a chunk, swap the server, score it, write the results, next chunk. Results
come in from the first chunk on, and a long run (thousands of stops, over months of Street View
budget) can be stopped and resumed anywhere: every stop is stored as soon as it is done.
"""

import logging
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..caches import UsageLedger, key_id, open_metadata_cache, this_month
from ..fileutils import RawStore
from ..models import Stop
from ..osm_store import OsmStore
from ..places import PlacesClient
from ..provenance import git_state, sha256_file
from ..runstore import RunStore
from ..servers import ManagedServer
from ..settings import GoogleKey, Paths, Profile
from ..streetview import StreetViewClient
from .explore import ExploreContext, explore
from .export import write_results
from .ingest import ingest, select_into_run
from .score import make_scorer, score, scorable

logger = logging.getLogger(__name__)

PHASES = ("ingest", "explore", "score")


@dataclass
class RunRequest:
    run_id: str
    profile: Profile
    stops: list[Stop] | None  # None: the stops already in the run
    phases: tuple[str, ...] = PHASES
    chunk: int = 50
    force: tuple[str, ...] = ()
    caps: dict[str, int] = field(default_factory=dict)
    allow_new_gtfs: bool = False


class Servers:
    """At most one model server up at a time: asking for the other one stops the current one first."""

    def __init__(self, profile: Profile, paths: Paths, logs: Path) -> None:
        self.specs = {"explorer": profile.explorer.server, "scorer": profile.scorer.server}
        self.paths = paths
        self.logs = logs
        self.current: tuple[str, ManagedServer] | None = None

    def ensure(self, role: str) -> None:
        if self.current and self.current[0] == role:
            return
        self.stop()
        server = ManagedServer(role, self.specs[role], self.paths.models, self.logs / f"{role}-server.log")
        server.__enter__()
        self.current = (role, server)

    def stop(self) -> None:
        if self.current:
            self.current[1].stop()
            self.current = None


def host_info() -> dict:
    info = {"hostname": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version(),
            "cpus": os.cpu_count()}
    if shutil.which("nvidia-smi"):
        try:
            info["gpu"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                          "--format=csv,noheader"], capture_output=True, text=True,
                                         timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def run_pipeline(req: RunRequest, paths: Paths) -> dict:
    stops_file = paths.gtfs / "stops.txt"
    all_stops = {s.stop_id: s for s in _load_all_stops(stops_file)}
    run = RunStore(paths.runs / req.run_id, create=True)
    counts: dict = {}
    status = "error"
    seq = run.begin_invocation(host_info(), {"run_id": req.run_id, "profile": req.profile.name,
                                             "phases": list(req.phases), "chunk": req.chunk, "force": list(req.force),
                                             "stops": None if req.stops is None else len(req.stops)}, git_state())
    servers = Servers(req.profile, paths, run.logs_dir)
    try:
        _check_inputs(run, stops_file, req.allow_new_gtfs)
        run.set_meta(f"profile:{seq}", {"name": req.profile.name, "description": req.profile.description,
                                        "explorer": req.profile.explorer.describe(),
                                        "scorer": req.profile.scorer.describe()})
        if req.stops is not None:
            counts["selected"] = select_into_run(run, req.stops, paths.gtfs)
        targets = [s.stop_id for s in req.stops] if req.stops is not None else run.stop_ids()
        for phase in req.force:
            run.forget(phase, targets)

        google = GoogleKey.from_env() if {"ingest", "explore"} & set(req.phases) else None
        kid = key_id(google.api_key) if google else None
        ledger = UsageLedger(paths.cache / "usage.sqlite", req.caps)
        osm = OsmStore(paths.osm_store)
        if not paths.osm_store.is_file():
            raise FileNotFoundError(f"no OSM store at {paths.osm_store}: run `cotral osm download` and "
                                    f"`cotral osm build` first")

        if "ingest" in req.phases:
            todo = run.pending("ingest", targets)
            if todo:
                logger.info("Ingest: %d stops", len(todo))
                counts["ingest"] = ingest(
                    run, todo, list(all_stops.values()), osm, RawStore(paths.cache / "places_raw"),
                    lambda: PlacesClient(google.api_key, 20.0, google.referrer), ledger, kid)
                run.add_usage(this_month(), kid, "places", counts["ingest"].get("places_fetched", 0))

        metadata = None
        if "explore" in req.phases:
            lookup_client = StreetViewClient(google.api_key, 20.0, google.referrer)
            metadata = open_metadata_cache(paths.cache, lookup_client.get_metadata)
        ctx = ExploreContext(run, paths, google, kid, req.profile.explorer, all_stops, osm, metadata, ledger) \
            if metadata else None
        scorer = make_scorer(req.profile.scorer, paths) if "score" in req.phases else None

        budget_left = True
        for start in range(0, len(targets), max(req.chunk, 1)):
            chunk = targets[start:start + req.chunk]
            ingested = {r["stop_id"] for r in run.query("SELECT stop_id FROM starts")}
            to_explore = [i for i in run.pending("explore", chunk) if i in ingested]
            if ctx and budget_left and to_explore:
                servers.ensure("explorer")
                c = explore(ctx, to_explore)
                _add(counts, "explore", c)
                budget_left = not c.get("skipped")
                if ctx.stop_event.is_set():
                    raise RuntimeError("exploration stopped (see the log): the explorer server is unreachable")
            to_score = scorable(run, chunk)
            if scorer and to_score:
                servers.ensure("scorer")
                _add(counts, "score", score(run, scorer, chunk))
            if to_explore or to_score:
                path, n = write_results(run)
                logger.info("Results: %s (%d stops). %s", path, n, run.summary())
        path, n = write_results(run)
        counts["results"] = path
        status = "ok"
        logger.info("Done. %s", run.summary())
        return counts
    except KeyboardInterrupt:
        status = "interrupted"
        logger.warning("Interrupted. Re-run the same command to resume; finished stops are kept.")
        raise
    finally:
        servers.stop()
        run.end_invocation(seq, status, counts)
        run.close()


def _add(counts: dict, phase: str, c: dict) -> None:
    total = counts.setdefault(phase, {})
    for k, v in c.items():
        total[k] = total.get(k, 0) + v


def _check_inputs(run: RunStore, stops_file: Path, allow_new: bool) -> None:
    """A run is tied to one GTFS feed: stop ids and positions must mean the same thing in every invocation."""
    digest = sha256_file(stops_file)
    known = run.get_meta("gtfs_stops_sha256")
    if known is None:
        run.set_meta("gtfs_stops_sha256", digest)
    elif known != digest and not allow_new:
        raise ValueError(f"{stops_file} changed since this run started; use a new run, or pass --allow-new-gtfs")


def _load_all_stops(stops_file: Path) -> list[Stop]:
    from ..stops import load_stops

    return load_stops(stops_file)
