"""Shape check: the generated stops file and the stored verdicts on it."""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from cotral_maintenance.provenance import utc_now

from .explore_schemas import ShapeCheck, ShapeVerdict, ShapeVerdictValue

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
COLUMNS = ("stop_id", "verdict", "note", "rater", "updated_at")


def load_shape_check(path: Path) -> ShapeCheck | None:
    """The shape check file validated against the contract; None when it has not been generated."""
    if not path.is_file():
        logger.info("no shape check at %s", path)
        return None
    return ShapeCheck.model_validate_json(path.read_text(encoding="utf-8"))


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the schema to SCHEMA_VERSION; each step runs once, tracked by PRAGMA user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.execute("""
            CREATE TABLE shape_verdicts (
                stop_id TEXT PRIMARY KEY,
                verdict TEXT CHECK (verdict IS NULL OR verdict IN ('on_route', 'off_route', 'unclear')),
                note TEXT NOT NULL,
                rater TEXT,
                updated_at TEXT NOT NULL
            )
        """)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


class ShapeVerdictRepository:
    """One verdict per stop, last write wins. Short-lived connection per operation (see judgments.py)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            _migrate(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            with conn:
                yield conn

    def put(self, stop_id: str, verdict: ShapeVerdictValue | None, note: str, rater: str | None) -> ShapeVerdict:
        """Replace the stop's verdict."""
        row = ShapeVerdict(stop_id=stop_id, verdict=verdict, note=note, rater=rater or None, updated_at=utc_now())
        with self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO shape_verdicts ({', '.join(COLUMNS)}) VALUES (?, ?, ?, ?, ?)",
                (row.stop_id, row.verdict, row.note, row.rater, row.updated_at),
            )
        return row

    def list(self) -> list[ShapeVerdict]:
        """All verdicts, sorted by stop id."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM shape_verdicts ORDER BY stop_id").fetchall()
        return [ShapeVerdict(**dict(zip(COLUMNS, row))) for row in rows]
