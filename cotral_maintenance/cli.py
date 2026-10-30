"""Command-line entry point: `uv run python -m cotral_maintenance --help`.

Runs the pipeline phases in order on the same selection of stops:
  Phase 1: verify stops against Google Maps (Places API), build the verified-stops dataset.
  Phase 2: download Street View images of the stops.

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
from .logging_setup import setup_logging
from .models import Stop
from .panoramas import VIEWS
from .places import PlacesClient
from .provenance import append_run, git_state, sha256_file, utc_now
from .stops import is_cotral_stop, load_stops, sample_order, select_stops
from .storage import ImageStore
from .streetview import StreetViewClient
from .verification import RawPlacesStore, build_dataset, fetch_stops, write_dataset

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def run_phase1_verify_stops(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    store = RawPlacesStore(settings.places_raw_dir)
    with PlacesClient(settings.api_key, settings.request_timeout_s, settings.referrer) as client:
        try:
            fetched = fetch_stops(stops, client, store, args.force)
        finally:
            # Rebuilt even after an interruption, so the dataset always matches the raw data.
            rows = build_dataset(store)
            write_dataset(rows, settings.verified_stops_file)
            logger.info("Wrote %d rows to %s", len(rows), settings.verified_stops_file)
    verified = sum(row.verified for row in rows)
    return {"fetched": fetched, "dataset_rows": len(rows), "verified": verified}


def run_phase2_download_images(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    with StreetViewClient(settings.api_key, settings.request_timeout_s, settings.referrer) as client:
        results = download_stops(stops, VIEWS, client, ImageStore(settings.images_dir), args.force)
    return dict(Counter(result.outcome.value for result in results))


@dataclass(frozen=True)
class Phase:
    number: int
    name: str
    run: Callable[[argparse.Namespace, Settings, list[Stop]], dict]


PHASES = (
    Phase(1, "verify stops (Places API)", run_phase1_verify_stops),
    Phase(2, "download images (Street View)", run_phase2_download_images),
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
        "--stop-after-phase", type=int, choices=[p.number for p in PHASES], default=LAST_PHASE,
        metavar="N", help=f"Run phases 1..N only (default: {LAST_PHASE}, all phases).",
    )
    parser.add_argument("--force", action="store_true", help="Redo stops that are already done.")
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
    args = build_parser().parse_args(argv)
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
        for phase in PHASES[: args.stop_after_phase]:
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
