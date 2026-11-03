"""Judgment repository on SQLite.

Judgments are permanent ground truth for evaluating ranking functions. "A pair is
judged at most once, in either order" is enforced by a UNIQUE constraint on the
normalised pair, not by application code.

Threading: sync endpoints run in a threadpool, so every operation opens its own
short-lived connection (cheap for SQLite) instead of sharing one across threads.
"""

import logging
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from cotral_maintenance.provenance import utc_now

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
COLUMNS = ("id", "created_at", "left_id", "right_id", "winner", "loser", "rater", "decision_ms")


class DuplicatePair(Exception):
    """The pair has already been judged, in either order."""


@dataclass(frozen=True)
class Judgment:
    id: str
    created_at: str
    left: str
    right: str
    winner: str | None
    loser: str | None
    rater: str | None
    decision_ms: int | None


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the schema to SCHEMA_VERSION; each step runs once, tracked by PRAGMA user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript("""
            CREATE TABLE judgments (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                left_id TEXT NOT NULL,
                right_id TEXT NOT NULL,
                pair_a TEXT NOT NULL,
                pair_b TEXT NOT NULL,
                winner TEXT,
                loser TEXT,
                rater TEXT,
                decision_ms INTEGER,
                UNIQUE (pair_a, pair_b),
                CHECK (pair_a < pair_b),
                CHECK (winner IS NULL OR winner IN (left_id, right_id))
            );
            CREATE INDEX judgments_created_at ON judgments (created_at);
        """)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


class JudgmentRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            _migrate(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success, rolls back on error, and always closes."""
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            with conn:
                yield conn

    def add(self, left: str, right: str, winner: str | None, rater: str | None = None,
            decision_ms: int | None = None, *, id: str | None = None, created_at: str | None = None) -> Judgment:
        """Record one judgment; winner None means skipped. Raises DuplicatePair, or ValueError
        when the stops are equal or the winner is not one of them."""
        if left == right:
            raise ValueError("a stop cannot be compared with itself")
        if winner not in (left, right, None):
            raise ValueError("winner must be one of the two stops, or null to skip")
        judgment = Judgment(
            id=id or uuid.uuid4().hex, created_at=created_at or utc_now(), left=left, right=right,
            winner=winner, loser=None if winner is None else (right if winner == left else left),
            rater=rater or None, decision_ms=decision_ms,
        )
        pair_a, pair_b = pair_key(left, right)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO judgments (id, created_at, left_id, right_id, pair_a, pair_b, winner, loser, "
                    "rater, decision_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (judgment.id, judgment.created_at, left, right, pair_a, pair_b, winner, judgment.loser,
                     judgment.rater, decision_ms),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicatePair(f"pair {pair_a}/{pair_b} has already been judged") from error
        return judgment

    def list(self) -> list[Judgment]:
        """All judgments, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM judgments ORDER BY created_at, rowid"
            ).fetchall()
        return [Judgment(*row) for row in rows]

    def pairs(self) -> set[tuple[str, str]]:
        """Normalised pairs judged so far."""
        with self._connect() as conn:
            return set(conn.execute("SELECT pair_a, pair_b FROM judgments"))

    def counts(self) -> tuple[int, int]:
        """(judged, skipped)."""
        with self._connect() as conn:
            judged, skipped = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(winner IS NULL), 0) FROM judgments"
            ).fetchone()
        return judged, skipped

    def import_many(self, judgments: Iterable[Judgment]) -> tuple[int, int]:
        """Insert judgments, skipping ids or pairs already present: (imported, skipped)."""
        imported = skipped = 0
        for j in judgments:
            try:
                self.add(j.left, j.right, j.winner, j.rater, j.decision_ms, id=j.id, created_at=j.created_at)
                imported += 1
            except (DuplicatePair, ValueError):
                skipped += 1
        return imported, skipped
