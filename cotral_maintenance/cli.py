"""Command line: `uv run cotral --help` (or `python -m cotral_maintenance`).

    cotral inputs check | fetch          the dataset (inputs/dataset.toml): verify, fetch, unzip the GTFS
    cotral osm build | download          the local OSM store, from the dataset's extracts
    cotral models fetch [--profile P]    download a profile's model files (pinned revisions)
    cotral run RUN (--limit N | --stop-id ID ... | --all | --resume) [--profile P]
                                         GTFS -> OSM / Places -> explore -> score -> results.csv
    cotral status RUN                    what a run has done so far
    cotral export RUN                    rewrite RUN/results.csv
    cotral bundle RUN [--media all|stop] one .tar.zst to carry the run to another machine
    cotral unbundle FILE [--replace]     unpack a bundle into the runs directory
    cotral usage                         billed Google requests this month, per API key
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .caches import UsageLedger, key_id, this_month
from .errors import ApiError, CotralMaintenanceError
from .logging_setup import setup_logging
from .settings import DEFAULT_PROFILE, GoogleKey, Paths, load_profile, load_profiles
from .stops import is_cotral_stop, load_stops, sample_order, select_stops

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_ERROR, EXIT_INTERRUPTED = 0, 1, 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cotral", description="Cotral bus stop maintenance pipeline.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", required=True)

    inputs = sub.add_parser("inputs", help="the dataset (inputs/dataset.toml): check it, fetch what is missing")
    inputs.add_argument("action", choices=["check", "fetch"],
                        help="check: every file against its sha256; fetch: download what is missing from its url "
                             "(refused if the bytes differ), then unzip the GTFS feed once")

    osm = sub.add_parser("osm", help="the local OSM store, from the dataset's extracts")
    osm.add_argument("action", choices=["build", "download"],
                     help="build: the store from the extracts; download: replace the extracts with their newest "
                          "copies (for a new dataset: then update the manifest's sha256)")

    models = sub.add_parser("models", help="model files of a profile")
    models.add_argument("action", choices=["fetch", "show"])
    models.add_argument("--profile", default=None, help=f"default: $COTRAL_PROFILE or {DEFAULT_PROFILE}")

    run = sub.add_parser("run", help="run the pipeline on a run directory (created if new)")
    run.add_argument("run_id", help="the run's name: its directory under the runs directory")
    selection = run.add_mutually_exclusive_group(required=True)
    selection.add_argument("--limit", type=int, metavar="N",
                           help="the first N stops of the seeded sample (raising N later extends the same sample)")
    selection.add_argument("--stop-id", action="append", dest="stop_ids", metavar="ID", help="this stop (repeatable)")
    selection.add_argument("--all", action="store_true", help="every stop in scope")
    selection.add_argument("--resume", action="store_true", help="the stops already in the run")
    run.add_argument("--seed", type=int, default=0, help="seed of the sample order (default 0)")
    run.add_argument("--include-shared", action="store_true",
                     help="also stops without an 'f<digits>' id (shared with other operators, depots, legacy)")
    run.add_argument("--profile", default=None, help=f"model profile (default: $COTRAL_PROFILE or {DEFAULT_PROFILE})")
    run.add_argument("--phases", default="ingest,explore,score",
                     help="comma-separated subset of ingest,explore,score (default: all)")
    run.add_argument("--chunk", type=int, default=50, help="stops explored before swapping to the scorer (default 50)")
    run.add_argument("--force", action="append", default=[], choices=["ingest", "explore", "score"],
                     help="redo this phase (and the later ones) for the selected stops; explore is billed")
    run.add_argument("--cap", action="append", default=[], metavar="API=N",
                     help="monthly cap of billed requests per API key: static, tiles, places "
                          "(default: Google's free tiers 10000, 100000, 5000)")
    run.add_argument("--allow-new-gtfs", action="store_true", help="accept a GTFS feed that changed since the run began")
    run.add_argument("--allow-mixed", action="store_true",
                     help="add rows of this code's versions to phases whose rows another version made")

    for name, text in (("status", "what a run has done"), ("export", "rewrite results.csv")):
        p = sub.add_parser(name, help=text)
        p.add_argument("run_id")

    bundle = sub.add_parser("bundle", help="pack a run into one .tar.zst")
    bundle.add_argument("run_id")
    bundle.add_argument("--out", type=Path, help="default: <runs>/<run>.tar.zst")
    bundle.add_argument("--media", choices=["all", "stop", "none"], default="all",
                        help="photos to include: all, only the stop photos, or none (default all)")
    bundle.add_argument("--no-logs", action="store_true")

    unbundle = sub.add_parser("unbundle", help="unpack a bundle into the runs directory")
    unbundle.add_argument("archive", type=Path)
    unbundle.add_argument("--replace", action="store_true", help="update an existing run from the bundle")

    usage = sub.add_parser("usage", help="billed Google requests this month")
    usage.add_argument("--month", default=None)
    return parser


def select(args: argparse.Namespace, paths: Paths):
    if args.resume:
        return None
    stops = load_stops(paths.gtfs / "stops.txt")
    if args.stop_ids:
        return select_stops(stops, args.stop_ids)
    in_scope = stops if args.include_shared else [s for s in stops if is_cotral_stop(s)]
    ordered = sample_order(in_scope, args.seed)
    return ordered if args.all else ordered[: args.limit]


def parse_caps(values: list[str]) -> dict[str, int]:
    caps = {}
    for v in values:
        api, _, n = v.partition("=")
        if api not in ("static", "tiles", "places") or not n.isdigit():
            raise ValueError(f"--cap {v}: expected static=N, tiles=N or places=N")
        caps[api] = int(n)
    return caps


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths.from_env()
    level = getattr(logging, args.log_level)
    if args.command == "run":
        setup_logging(paths.runs / args.run_id / "logs" / "pipeline.log", level)
    else:
        setup_logging(paths.cache / "logs" / "cotral.log", level)
    try:
        return COMMANDS[args.command](args, paths)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except ApiError as error:
        logger.error("Google rejected the request: %s", error)
    except (CotralMaintenanceError, OSError, ValueError, RuntimeError) as error:
        logger.error("%s", error)
    return EXIT_ERROR


def cmd_osm(args, paths: Paths) -> int:
    from .osm_build import build, download

    sources = paths.dataset.of("osm")
    if args.action == "download":
        for entry in download(sources):
            print(json.dumps(entry))
        print("Now update these sources' sha256 (and dates) in the manifest:", paths.dataset_manifest)
    else:
        logger.info("Built %s: %s", paths.osm_store, build(sources, paths.osm_store, paths.gtfs / "stops.txt"))
    return EXIT_OK


def cmd_inputs(args, paths: Paths) -> int:
    from .dataset import fetch

    dataset = paths.dataset
    if args.action == "fetch":
        print(json.dumps(fetch(dataset, paths.gtfs), indent=1))
        return EXIT_OK
    bad = 0
    for source, state in dataset.check():
        bad += state != "ok"
        print(f"{state:12s} {source.role:10s} {source.file}")
    print(f"dataset {dataset.name}: {'all files verified' if not bad else f'{bad} not verified'} ({dataset.manifest})")
    return EXIT_OK if not bad else EXIT_ERROR


def cmd_models(args, paths: Paths) -> int:
    from .servers import fetch

    profile = load_profile(paths, args.profile)
    files = [*profile.explorer.server.files.values(), *profile.scorer.server.files.values(),
             *profile.scorer.readout.values()]
    for f in files:
        path = fetch(f, paths.models) if args.action == "fetch" else f.path(paths.models)
        print(f"{f.repo}@{f.revision[:12]}/{f.file}\t{path}\t{'ok' if path.is_file() else 'missing'}")
    if args.action == "show":
        print(f"profiles in {paths.profiles}: {', '.join(load_profiles(paths.profiles))}")
    return EXIT_OK


def cmd_run(args, paths: Paths) -> int:
    from .pipeline.run import RunRequest, run_pipeline

    phases = tuple(p.strip() for p in args.phases.split(",") if p.strip())
    unknown = set(phases) - {"ingest", "explore", "score"}
    if unknown:
        raise ValueError(f"unknown phases: {', '.join(sorted(unknown))}")
    req = RunRequest(run_id=args.run_id, profile=load_profile(paths, args.profile), stops=select(args, paths),
                     phases=phases, chunk=args.chunk, force=tuple(args.force), caps=parse_caps(args.cap),
                     allow_new_gtfs=args.allow_new_gtfs, allow_mixed=args.allow_mixed)
    counts = run_pipeline(req, paths)
    print(json.dumps(counts, indent=1))
    return EXIT_OK


def cmd_status(args, paths: Paths) -> int:
    from .runstore import RunStore

    with RunStore(paths.runs / args.run_id) as run:
        print(json.dumps({"run": str(run.root), **run.summary(), "versions": run.versions_summary(),
                          "invocations": [dict(r) for r in run.query(
                              "SELECT seq, started_at, finished_at, status, versions, counts FROM invocations "
                              "ORDER BY seq")]},
                         indent=1))
    return EXIT_OK


def cmd_export(args, paths: Paths) -> int:
    from .pipeline.export import write_results
    from .runstore import RunStore

    with RunStore(paths.runs / args.run_id) as run:
        path, n = write_results(run)
    print(f"{path}: {n} stops")
    return EXIT_OK


def cmd_bundle(args, paths: Paths) -> int:
    from .pipeline.bundle import bundle

    out = args.out or paths.runs / f"{args.run_id}.tar.zst"
    path, n = bundle(paths.runs / args.run_id, out, args.media, logs=not args.no_logs)
    print(f"{path}: {n} photos, {path.stat().st_size / 1e6:.1f} MB")
    return EXIT_OK


def cmd_unbundle(args, paths: Paths) -> int:
    from .pipeline.bundle import unbundle

    print(unbundle(args.archive, paths.runs, args.replace))
    return EXIT_OK


def cmd_usage(args, paths: Paths) -> int:
    ledger = UsageLedger(paths.cache / "usage.sqlite")
    key = key_id(GoogleKey.from_env().api_key)
    month = args.month or this_month()
    used = ledger.used(key, month)
    print(json.dumps({"month": month, "key": key, "used": used,
                      "cap": ledger.caps, "left": {k: ledger.caps[k] - used.get(k, 0) for k in ledger.caps}}, indent=1))
    return EXIT_OK


COMMANDS = {"inputs": cmd_inputs, "osm": cmd_osm, "models": cmd_models, "run": cmd_run, "status": cmd_status, "export": cmd_export,
            "bundle": cmd_bundle, "unbundle": cmd_unbundle, "usage": cmd_usage}

if __name__ == "__main__":
    sys.exit(main())
