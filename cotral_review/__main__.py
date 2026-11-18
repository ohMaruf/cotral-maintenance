"""Command line of the review tool, from the repository root:

    .venv/bin/python -m cotral_review serve --run runs/<RUN> [--port 8765]
    .venv/bin/python -m cotral_review import-jsonl data/comparisons.jsonl
    .venv/bin/python -m cotral_review export --format csv [--out PATH]

serve binds to 127.0.0.1 by default. Needs the review extra (uv sync --extra review).
"""

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, replace
from pathlib import Path

from cotral_maintenance.runstore import RunStoreError

from .config import Settings
from .judgments import COLUMNS, Judgment, JudgmentRepository

logger = logging.getLogger(__name__)

EXPORT_FIELDS = {"left_id": "left", "right_id": "right"}


def read_jsonl(path: Path) -> list[Judgment]:
    """Judgments of the prototype's append-only file (and of `export --format jsonl`)."""
    judgments = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            judgments.append(Judgment(
                id=r["id"], created_at=r["created_at"], left=r["left"], right=r["right"], winner=r.get("winner"),
                loser=r.get("loser"), rater=r.get("rater"), decision_ms=r.get("decision_ms"),
            ))
    return judgments


def export(repo: JudgmentRepository, fmt: str, out) -> int:
    rows = [asdict(j) for j in repo.list()]
    if fmt == "jsonl":
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        writer = csv.DictWriter(out, fieldnames=[EXPORT_FIELDS.get(c, c) for c in COLUMNS], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    base = Settings.from_env()
    parser = argparse.ArgumentParser(prog="cotral_review", description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--database", type=Path, default=base.database, help="SQLite file of the judgments")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", parents=[common], help="run the review server")
    serve.add_argument("--host", default=base.host)
    serve.add_argument("--port", type=int, default=base.port)
    serve.add_argument("--run", type=Path, default=base.run,
                       help="the run directory to show, runs/<RUN> (default: $COTRAL_REVIEW_RUN); "
                            "relative paths are relative to the repository root")
    serve.add_argument("--truth-csv", type=Path, default=base.truth_csv)
    serve.add_argument("--osm-store", type=Path, default=base.osm_store, help="SQLite OSM store")
    serve.add_argument("--shape-check-json", type=Path, default=base.shape_check_json)
    serve.add_argument("--shape-verdicts-db", type=Path, default=base.shape_verdicts_db,
                       help="SQLite file of the shape check verdicts")
    serve.add_argument("--frontend-dist", type=Path, default=base.frontend_dist)
    serve.add_argument("--seed", type=int, default=None, help="seed of the pair selection")

    imp = sub.add_parser("import-jsonl", parents=[common], help="import judgments from a JSONL file; idempotent")
    imp.add_argument("path", type=Path)

    exp = sub.add_parser("export", parents=[common], help="write all judgments, oldest first")
    exp.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    exp.add_argument("--out", type=Path, default=None, help="default: stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        settings = replace(
            Settings.from_env(), run=args.run, truth_csv=args.truth_csv, osm_store=args.osm_store,
            shape_check_json=args.shape_check_json, shape_verdicts_db=args.shape_verdicts_db,
            database=args.database, frontend_dist=args.frontend_dist, host=args.host, port=args.port, seed=args.seed,
        )
        try:
            app = create_app(settings)
        except RunStoreError as error:
            parser.exit(2, f"cotral_review: {error}\n")
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
        return 0

    repo = JudgmentRepository(args.database)
    if args.command == "import-jsonl":
        imported, skipped = repo.import_many(read_jsonl(args.path))
        logger.info("imported %d judgments, skipped %d already present or invalid", imported, skipped)
    else:
        if args.out is None:
            export(repo, args.format, sys.stdout)
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("w", encoding="utf-8", newline="") as f:
                count = export(repo, args.format, f)
            logger.info("exported %d judgments to %s", count, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
