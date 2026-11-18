"""Caches shared by every run on a machine: Street View metadata, and the ledger of billed Google requests.

Both are SQLite files in the cache directory, safe for the explorer's parallel workers. Neither
travels with a run: a run records the usage it caused in its own store, and the photos it used.

The ledger keeps runs inside a monthly cap per API key (Google's free tiers are per billing
account and calendar month: 10,000 Static Street View images, 100,000 Map Tiles tiles). A stop
is started only after reserving the most it could bill; when it ends, the reservation is
replaced by what it actually billed. Keys are stored as a fingerprint, never in clear.
"""

import hashlib
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .errors import NoImageryError, ServerError
from .models import PanoMetadata

FREE_PER_MONTH = {"static": 10_000, "tiles": 100_000, "places": 5_000}


def key_id(api_key: str) -> str:
    return "k" + hashlib.sha256(api_key.encode()).hexdigest()[:12]


def this_month(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


class _Db:
    def __init__(self, path: Path, schema: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(schema)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class MetadataCache(_Db):
    """Street View metadata lookups (free, but slow), by rounded position and radius. None = no imagery there."""

    def __init__(self, path: Path, lookup: Callable[[float, float, float], PanoMetadata]) -> None:
        super().__init__(path, "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, pano_id TEXT, lat REAL, "
                               "lon REAL, date TEXT, copyright TEXT)")
        self.lookup = lookup

    def get(self, lat: float, lon: float, radius: float) -> PanoMetadata | None:
        key = f"{lat:.6f},{lon:.6f},{radius:.0f}"
        with self._lock:
            row = self._conn.execute("SELECT pano_id, lat, lon, date, copyright FROM metadata WHERE key = ?",
                                     (key,)).fetchone()
        if row is not None:
            return PanoMetadata(row[0], row[1], row[2], row[3], row[4] or "") if row[0] else None
        value: PanoMetadata | None = None
        for attempt in (1, 2):
            try:
                value = self.lookup(lat, lon, radius)
                break
            except NoImageryError:
                break
            except ServerError:  # transient on Google's side: retry once, then don't cache
                if attempt == 2:
                    return None
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?, ?, ?, ?, ?)",
                               (key, value.pano_id if value else None, value.lat if value else None,
                                value.lon if value else None, value.date if value else None,
                                value.copyright if value else None))
        return value

    def save(self) -> None:
        """Kept for the session's interface: every lookup is already stored."""


@dataclass(frozen=True)
class Reservation:
    key_id: str
    month: str
    amounts: dict[str, int]


class BudgetExhausted(Exception):
    pass


class UsageLedger(_Db):
    """Billed requests per key, month and API, against a monthly cap; reservations for work in flight."""

    def __init__(self, path: Path, caps: dict[str, int] | None = None) -> None:
        super().__init__(path, "CREATE TABLE IF NOT EXISTS usage (month TEXT, key_id TEXT, api TEXT, used INTEGER, "
                               "PRIMARY KEY (month, key_id, api))")
        self.caps = {**FREE_PER_MONTH, **(caps or {})}
        self._reserved: dict[tuple[str, str, str], int] = {}

    def used(self, key: str, month: str | None = None) -> dict[str, int]:
        month = month or this_month()
        with self._lock:
            rows = self._conn.execute("SELECT api, used FROM usage WHERE month = ? AND key_id = ?",
                                      (month, key)).fetchall()
        return {api: 0 for api in self.caps} | dict(rows)

    def remaining(self, key: str, month: str | None = None) -> dict[str, int]:
        month = month or this_month()
        used = self.used(key, month)
        with self._lock:
            return {api: cap - used.get(api, 0) - self._reserved.get((month, key, api), 0)
                    for api, cap in self.caps.items()}

    def reserve(self, key: str, amounts: dict[str, int]) -> Reservation:
        """Reserve the most a unit of work can bill, or raise BudgetExhausted."""
        month = this_month()
        left = self.remaining(key, month)
        short = {api: (n, left.get(api, 0)) for api, n in amounts.items() if n > left.get(api, 0)}
        if short:
            raise BudgetExhausted(", ".join(f"{api}: needs up to {n}, {max(m, 0)} left in {month}"
                                            for api, (n, m) in short.items()))
        with self._lock:
            for api, n in amounts.items():
                self._reserved[(month, key, api)] = self._reserved.get((month, key, api), 0) + n
        return Reservation(key, month, dict(amounts))

    def settle(self, reservation: Reservation, billed: dict[str, int]) -> None:
        """Replace a reservation by what was actually billed (in the month it was reserved in)."""
        with self._lock:
            for api, n in reservation.amounts.items():
                k = (reservation.month, reservation.key_id, api)
                self._reserved[k] = max(self._reserved.get(k, 0) - n, 0)
            for api, n in billed.items():
                if n > 0:
                    self._conn.execute(
                        "INSERT INTO usage VALUES (?, ?, ?, ?) ON CONFLICT (month, key_id, api) "
                        "DO UPDATE SET used = used + excluded.used", (reservation.month, reservation.key_id, api, n))

    def record(self, key: str, api: str, n: int) -> None:
        """Usage that was not reserved (e.g. Places searches, counted as they happen)."""
        if n > 0:
            self.settle(Reservation(key, this_month(), {}), {api: n})


def open_metadata_cache(cache_dir: Path, lookup: Callable[[float, float, float], PanoMetadata]) -> MetadataCache:
    return MetadataCache(cache_dir / "streetview_metadata.sqlite", lookup)


def import_json_metadata(json_path: Path, cache: MetadataCache) -> int:
    """Load an old metadata.json cache (data/agent_runs/cache) into the SQLite one."""
    import json

    data = json.loads(json_path.read_text())
    with cache._lock, closing(cache._conn.cursor()) as cur:
        cur.executemany("INSERT OR IGNORE INTO metadata VALUES (?, ?, ?, ?, ?, ?)",
                        [(k, v["pano_id"] if v else None, v["lat"] if v else None, v["lon"] if v else None,
                          v.get("date") if v else None, v.get("copyright") if v else None) for k, v in data.items()])
    return len(data)
