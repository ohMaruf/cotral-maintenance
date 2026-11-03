"""Command-line entry point: `uv run python -m cotral_maintenance --help`.

Runs the pipeline phases in order on the same selection of stops:
  Phase 1: check stops against Google Maps (Places API), build the corrected-stops dataset.
  Phase 2: download Street View images of the stops that dataset confirms, at its positions.
  Phase 3: score the downloaded stops with Clef, build the scores dataset.

Every phase processes stops sequentially, can be interrupted at any time, and
resumes where it stopped when re-run.
"""

import argparse
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from .config import Settings
from .downloader import download_stops
from .errors import ApiError, CotralMaintenanceError
from .fileutils import RawStore, write_dataset
from .logging_setup import setup_logging
from .models import Stop
from .panoramas import VIEWS
from .places import PlacesClient
from .provenance import append_run, git_state, sha256_file, utc_now
from .scoring import ClefScorer, StopScores, score_stops
from .scoring import build_dataset as build_scores_dataset
from .stops import find_pairs, is_cotral_stop, load_stops, sample_order, select_stops
from .storage import ImageStore
from .streetview import StreetViewClient
from .verification import (
    CONFIRMED,
    GONE,
    CorrectedStop,
    build_dataset,
    fetch_stops,
    load_corrected_stops,
)

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def run_phase1_verify_stops(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    store = RawStore(settings.places_raw_dir)
    with PlacesClient(settings.api_key, settings.request_timeout_s, settings.referrer) as client:
        try:
            fetched = fetch_stops(stops, client, store, 1 in args.force)
        finally:
            # Rebuilt even after an interruption, so the dataset always matches the raw data.
            rows = build_dataset(load_stops(settings.stops_file), store)
            write_dataset(rows, CorrectedStop, settings.corrected_stops_file)
            logger.info("Wrote %d rows to %s", len(rows), settings.corrected_stops_file)
    return {"fetched": fetched, **Counter(row.status.value for row in rows)}


def run_phase2_download_images(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    corrected = load_corrected_stops(settings.corrected_stops_file)
    targets = [corrected[s.stop_id][0] for s in stops if corrected[s.stop_id][1] in CONFIRMED]
    logger.info("%d of %d selected stops are confirmed, the others are skipped", len(targets), len(stops))
    pairs = find_pairs(targets, [stop for stop, status in corrected.values() if status not in GONE])
    with StreetViewClient(settings.api_key, settings.request_timeout_s, settings.referrer) as client:
        results = download_stops(targets, VIEWS, client, ImageStore(settings.images_dir), 2 in args.force, pairs)
    return dict(Counter(result.outcome.value for result in results))


def run_phase3_score_stops(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    images = ImageStore(settings.images_dir)
    store = RawStore(settings.scores_raw_dir)
    corrected = load_corrected_stops(settings.corrected_stops_file)
    downloaded = [
        corrected[s.stop_id][0] for s in stops
        if corrected[s.stop_id][1] in CONFIRMED and images.manifest_path(s.stop_id).is_file()
    ]
    pending = [s for s in downloaded if 3 in args.force or not store.has(s.stop_id)]
    logger.info("%d of %d selected stops have images, %d to score", len(downloaded), len(stops), len(pending))
    scored = 0
    try:
        if pending:
            scored = score_stops(pending, ClefScorer(), images, store)
    finally:
        # Rebuilt even after an interruption, so the dataset always matches the raw data.
        rows = build_scores_dataset(store)
        write_dataset(rows, StopScores, settings.stop_scores_file)
        logger.info("Wrote %d rows to %s", len(rows), settings.stop_scores_file)
    return {"scored": scored, "failed": len(pending) - scored, "dataset_rows": len(rows)}


@dataclass(frozen=True)
class Phase:
    number: int
    name: str
    run: Callable[[argparse.Namespace, Settings, list[Stop]], dict]


PHASES = (
    Phase(1, "check and correct stops (Places API)", run_phase1_verify_stops),
    Phase(2, "download images (Street View)", run_phase2_download_images),
    Phase(3, "score stops (Clef)", run_phase3_score_stops),
)
LAST_PHASE = PHASES[-1].number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cotral bus stop maintenance pipeline. "
        + " ".join(f"Phase {p.number}: {p.name}." for p in PHASES)
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--limit", type=int, metavar="N",
        help="Process the first N stops of the sample. Raising N later extends the same sample.",
    )
    selection.add_argument(
        "--stop-id", action="append", dest="stop_ids", metavar="ID",
        help="Process only this stop (repeatable).",
    )
    selection.add_argument("--all", action="store_true", help="Process every stop in scope.")
    parser.add_argument("--seed", type=int, default=0, help="Seed of the sample order (default: 0).")
    parser.add_argument(
        "--include-shared", action="store_true",
        help="Also include stops without an 'f<digits>' id (shared, depots, legacy).",
    )
    parser.add_argument(
        "--start-phase", type=int, choices=[p.number for p in PHASES], default=PHASES[0].number,
        metavar="N", help="Start at phase N, using the output of the earlier phases as it is.",
    )
    parser.add_argument(
        "--stop-after-phase", type=int, choices=[p.number for p in PHASES], default=LAST_PHASE,
        metavar="N", help=f"Stop after phase N (default: {LAST_PHASE}, the last phase).",
    )
    parser.add_argument(
        "--force", type=int, action="append", choices=[p.number for p in PHASES], default=[], metavar="N",
        help="Redo the stops phase N has already done (repeatable). Phases 1 and 2 are billed.",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def select_run_stops(args: argparse.Namespace, stops: list[Stop]) -> list[Stop]:
    if args.stop_ids:
        return select_stops(stops, args.stop_ids)
    in_scope = stops if args.include_shared else [s for s in stops if is_cotral_stop(s)]
    logger.info("%d of %d stops in scope", len(in_scope), len(stops))
    ordered = sample_order(in_scope, args.seed)
    return ordered if args.all else ordered[: args.limit]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start_phase > args.stop_after_phase:
        parser.error("--start-phase is after --stop-after-phase")
    try:
        settings = Settings.from_env()
    except CotralMaintenanceError as exc:
        logging.basicConfig(format="%(levelname)s: %(message)s")
        logger.error("%s", exc)
        return EXIT_ERROR
    setup_logging(settings.log_file, getattr(logging, args.log_level))

    run = {"args": vars(args), "started_at": utc_now(), "git": git_state()}
    exit_code, status, phase_counts = EXIT_ERROR, "error", {}
    try:
        run["gtfs_stops_sha256"] = sha256_file(settings.stops_file)
        stops = select_run_stops(args, load_stops(settings.stops_file))
        logger.info("%d stops selected", len(stops))
        for phase in PHASES[args.start_phase - 1 : args.stop_after_phase]:
            logger.info("Phase %d: %s", phase.number, phase.name)
            phase_counts[phase.number] = phase.run(args, settings, stops)
            logger.info("Phase %d done: %s", phase.number, phase_counts[phase.number])
        exit_code, status = EXIT_OK, "ok"
    except KeyboardInterrupt:
        exit_code, status = EXIT_INTERRUPTED, "interrupted"
        logger.warning("Interrupted. Re-run the same command to resume; finished stops are kept.")
    except ApiError as exc:
        logger.error("API rejected the request: %s", exc)
    except (CotralMaintenanceError, OSError) as exc:
        logger.error("%s", exc)
    finally:
        append_run(
            settings.runs_log,
            {**run, "finished_at": utc_now(), "status": status, "phases": phase_counts},
        )
    return exit_code
