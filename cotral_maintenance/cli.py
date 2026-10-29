"""Command-line entry point: `uv run python -m cotral_maintenance --help`.

One subcommand per pipeline phase. Every phase processes stops sequentially,
can be interrupted at any time, and resumes where it stopped when re-run.
"""

import argparse
import logging
from collections import Counter
from collections.abc import Callable

from .config import Settings
from .downloader import download_stops
from .errors import ApiError, CotralMaintenanceError
from .logging_setup import setup_logging
from .models import Stop, View
from .places import PlacesClient
from .provenance import append_run, git_state, sha256_file, utc_now
from .stops import is_cotral_stop, load_stops, sample_order, select_stops
from .storage import ImageStore
from .streetview import StreetViewClient
from .verification import RawPlacesStore, build_dataset, fetch_stops, write_dataset

logger = logging.getLogger(__name__)

DEFAULT_DISTANCES_M = [0.0, 20.0, 40.0]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    selection = common.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--limit", type=int, metavar="N",
        help="Process the first N stops of the sample. Raising N later extends the same sample.",
    )
    selection.add_argument(
        "--stop-id", action="append", dest="stop_ids", metavar="ID",
        help="Process only this stop (repeatable).",
    )
    selection.add_argument("--all", action="store_true", help="Process every stop in scope.")
    common.add_argument("--seed", type=int, default=0, help="Seed of the sample order (default: 0).")
    common.add_argument(
        "--include-shared", action="store_true",
        help="Also include stops without an 'f<digits>' id (shared, depots, legacy).",
    )
    common.add_argument("--force", action="store_true", help="Redo stops that are already done.")
    common.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    parser = argparse.ArgumentParser(description="Cotral bus stop maintenance pipeline.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "verify-stops", parents=[common],
        help="Phase 1: match stops to Google Maps (Places API) and build the verified-stops dataset.",
    )

    images = commands.add_parser(
        "download-images", parents=[common], help="Download Street View images of stops.",
    )
    images.add_argument(
        "--distance", action="append", type=float, dest="distances", metavar="M",
        help="Shoot from a panorama about M metres from the stop, camera aimed at it "
        "(repeatable, one image each). Default: 0, 20, 40.",
    )
    images.add_argument("--pitch", type=float, default=0.0)
    images.add_argument("--fov", type=float, default=90.0)
    return parser


def select_run_stops(args: argparse.Namespace, stops: list[Stop]) -> list[Stop]:
    if args.stop_ids:
        return select_stops(stops, args.stop_ids)
    in_scope = stops if args.include_shared else [s for s in stops if is_cotral_stop(s)]
    logger.info("%d of %d stops in scope", len(in_scope), len(stops))
    ordered = sample_order(in_scope, args.seed)
    return ordered if args.all else ordered[: args.limit]


def run_verify_stops(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    store = RawPlacesStore(settings.places_raw_dir)
    with PlacesClient(settings.api_key, settings.request_timeout_s) as client:
        try:
            fetched = fetch_stops(stops, client, store, args.force)
        finally:
            # Rebuilt even after an interruption, so the dataset always matches the raw data.
            rows = build_dataset(store)
            write_dataset(rows, settings.verified_stops_file)
            logger.info("Wrote %d rows to %s", len(rows), settings.verified_stops_file)
    verified = sum(row.verified for row in rows)
    return {"fetched": fetched, "dataset_rows": len(rows), "verified": verified}


def run_download_images(args: argparse.Namespace, settings: Settings, stops: list[Stop]) -> dict:
    distances = args.distances or DEFAULT_DISTANCES_M
    views = [View(distance_m=d, pitch=args.pitch, fov=args.fov) for d in distances]
    with StreetViewClient(settings.api_key, settings.request_timeout_s) as client:
        results = download_stops(stops, views, client, ImageStore(settings.images_dir), args.force)
    return dict(Counter(result.outcome.value for result in results))


COMMANDS: dict[str, Callable[[argparse.Namespace, Settings, list[Stop]], dict]] = {
    "verify-stops": run_verify_stops,
    "download-images": run_download_images,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except CotralMaintenanceError as exc:
        logging.basicConfig(format="%(levelname)s: %(message)s")
        logger.error("%s", exc)
        return EXIT_ERROR
    setup_logging(settings.log_file, getattr(logging, args.log_level))

    run = {"command": args.command, "args": vars(args), "started_at": utc_now(), "git": git_state()}
    exit_code, status, counts = EXIT_ERROR, "error", {}
    try:
        run["gtfs_stops_sha256"] = sha256_file(settings.stops_file)
        stops = select_run_stops(args, load_stops(settings.stops_file))
        logger.info("%s: %d stops selected", args.command, len(stops))
        counts = COMMANDS[args.command](args, settings, stops)
        exit_code, status = EXIT_OK, "ok"
        logger.info("Done: %s", counts)
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
            {**run, "finished_at": utc_now(), "status": status, "counts": counts},
        )
    return exit_code
