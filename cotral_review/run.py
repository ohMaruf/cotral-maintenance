"""The run being reviewed, opened read-only: the BFF never writes into a run."""

import sqlite3
import threading
from pathlib import Path

from cotral_maintenance.runstore import DB_NAME, SCHEMA_VERSION, RunStore, RunStoreError

from .config import repo_path


class ReadOnlyRunStore(RunStore):
    """A `RunStore` on `mode=ro`: the reads of `RunStore` (and `pipeline.export.rows`) work, writes fail.

    `RunStore.__init__` creates directories and switches the journal mode, both writes, so it is not called.
    """

    def __init__(self, root: Path) -> None:
        db = root / DB_NAME
        if not db.is_file():
            raise RunStoreError(f"no run at {root} (missing {DB_NAME})")
        self.root = root
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            self._conn.close()
            raise RunStoreError(f"{db} has schema {version}; this code reads {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def open_run(path: Path | None) -> ReadOnlyRunStore:
    """Raises RunStoreError with a message fit for the user when there is no run to show."""
    if path is None:
        raise RunStoreError("no run to show: pass --run runs/<RUN> (or set COTRAL_REVIEW_RUN)")
    return ReadOnlyRunStore(repo_path(path).resolve())
