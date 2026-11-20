import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .provenance import utc_now

SCHEMA_VERSION = 4
DB_NAME = "run.sqlite"
MEDIA_DIR = "media"
LOGS_DIR = "logs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                -- JSON
);

-- The stops of the run, in the order they are processed.
CREATE TABLE IF NOT EXISTS stops (
    stop_id   TEXT PRIMARY KEY,
    position  INTEGER NOT NULL,        -- order in the run's selection
    name      TEXT NOT NULL,
    gtfs_lat  REAL NOT NULL,
    gtfs_lon  REAL NOT NULL,
    services  TEXT NOT NULL            -- JSON: [{shape_id, trips, previous, next}], most trips first
);

-- Phase 1, ingest: where the search starts, from OSM, else Places, else GTFS.
CREATE TABLE IF NOT EXISTS starts (
    stop_id      TEXT PRIMARY KEY REFERENCES stops(stop_id),
    source       TEXT NOT NULL CHECK (source IN ('osm', 'places', 'gtfs')),
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    osm          TEXT,                 -- JSON: {osm_id, kind, how, from_gtfs_m, ref, name}, when OSM matched
    places       TEXT,                 -- JSON: {status, reason, lat, lon, offset_m, place_id, ...}, when Places was asked
    ingested_at  TEXT NOT NULL,
    version      TEXT,                 -- what produced the row: versions.version (NULL: before versions)
    invocation   INTEGER               -- invocations.seq
);

-- Phase 2, explore: the search for the stop in Street View.
CREATE TABLE IF NOT EXISTS explorations (
    stop_id         TEXT PRIMARY KEY REFERENCES stops(stop_id),
    status          TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'no_imagery', 'error')),
    reason          TEXT,              -- why it ended (not_found, error)
    lat             REAL,              -- the stop's position, when found
    lon             REAL,
    position_basis  TEXT,
    evidence        TEXT,
    plate_text      TEXT,
    scan_date       TEXT,
    stop_photos     TEXT NOT NULL,     -- JSON: [sha256, ...] the 1-2 photos of the found stop, for scoring
    explorer        TEXT NOT NULL,     -- JSON: the explorer and confirmer models (profile entry, files, revisions)
    harness         TEXT NOT NULL,     -- JSON: harness version, prompt sha256, git
    billed_static   INTEGER NOT NULL,
    billed_tiles    INTEGER NOT NULL,
    turns           INTEGER NOT NULL,
    seconds         REAL NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    version         TEXT,              -- versions.version (NULL: before versions)
    invocation      INTEGER,           -- invocations.seq
    record          TEXT NOT NULL      -- JSON: the session record (world, photos, candidates, events, outcome);
                                       -- photo `file`s are media sha256s
);

-- Every photo an exploration took, in order.
CREATE TABLE IF NOT EXISTS photos (
    stop_id  TEXT NOT NULL REFERENCES stops(stop_id),
    idx      INTEGER NOT NULL,         -- the photo number the explorer saw
    media    TEXT NOT NULL,            -- sha256 -> media/<2>/<sha256>.jpg
    toward   TEXT NOT NULL,            -- opening_ahead/behind, sweep_ahead/behind, zoom, look_from, stop_photo
    pano_id  TEXT NOT NULL,
    date     TEXT,
    heading  REAL NOT NULL,
    fov      REAL NOT NULL,
    pitch    REAL NOT NULL,
    width    INTEGER NOT NULL,
    height   INTEGER NOT NULL,
    lat      REAL NOT NULL,            -- of the camera
    lon      REAL NOT NULL,
    PRIMARY KEY (stop_id, idx)
);

-- The explorer's conversation, one JSON object per line (turns, tool results, timings).
CREATE TABLE IF NOT EXISTS transcripts (
    stop_id  TEXT PRIMARY KEY REFERENCES stops(stop_id),
    lines    TEXT NOT NULL
);

-- Phase 3, score: what is around each found stop, from its stop photos (the stop itself was confirmed by the explorer).
CREATE TABLE IF NOT EXISTS scores (
    stop_id        TEXT PRIMARY KEY REFERENCES stops(stop_id),
    photos         TEXT NOT NULL,   -- JSON: [sha256, ...] the photos scored
    scorer         TEXT NOT NULL,   -- JSON: model, files, revisions, rotations, calibration
    condition      REAL,            -- 0 bad .. 1 good: the mean of the conditions below that apply; ranked by, worst first
    has_shelter    REAL,            -- probability that the element is there (0-1); below 0.5 it is missing
    shelter        REAL,            -- 0 unusable .. 1 good, only when the element is there (else NULL)
    has_seating    REAL,
    seating        REAL,
    waiting_area   REAL,            -- 0 severe .. 1 good
    accessibility  REAL,            -- 0 inaccessible .. 1 fully accessible
    has_lamp       REAL,            -- probability that a street lamp stands at the stop (0-1)
    stop_visible   REAL,            -- probability that the photos show the stop (0-1)
    answers        TEXT NOT NULL,   -- JSON: per question, probabilities, unknown probability, confidence
    seconds        REAL NOT NULL,
    scored_at      TEXT NOT NULL,
    version        TEXT,            -- versions.version (NULL: before versions)
    invocation     INTEGER          -- invocations.seq
);

-- Billed Google requests made by this run (the cross-run ledger lives in the cache).
CREATE TABLE IF NOT EXISTS usage (
    month   TEXT NOT NULL,
    key_id  TEXT NOT NULL,             -- a fingerprint of the API key, never the key
    api     TEXT NOT NULL,             -- static, tiles, places
    count   INTEGER NOT NULL,
    PRIMARY KEY (month, key_id, api)
);

-- One row per invocation of the pipeline on this run.
CREATE TABLE IF NOT EXISTS invocations (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT,                 -- ok, interrupted, error
    host         TEXT NOT NULL,        -- JSON: hostname, platform, gpu
    args         TEXT NOT NULL,        -- JSON
    git          TEXT NOT NULL,        -- JSON
    counts       TEXT,                 -- JSON: per phase
    versions     TEXT                  -- JSON: {package, ingest, explore, score}: the versions it ran with
);

-- What produced the rows: one per phase and version (cotral_maintenance/versions.py). `detail` is what the
-- version is the hash of: prompt hashes, phase constants, model files and revisions, inputs.
CREATE TABLE IF NOT EXISTS versions (
    version           TEXT PRIMARY KEY,   -- first 12 hex of the sha256 of the canonical JSON of detail
    phase             TEXT NOT NULL,      -- ingest, explore, score
    detail            TEXT NOT NULL,      -- JSON
    first_invocation  INTEGER             -- invocations.seq that first used it
);
"""

SCORE_COLUMNS = ("condition", "has_shelter", "shelter", "has_seating", "seating", "waiting_area", "accessibility",
                 "has_lamp", "stop_visible")
MIGRATIONS = {
    1: "DROP TABLE scores;",
    2: "DROP TABLE IF EXISTS scores;",
    3: "DROP TABLE IF EXISTS scores;",
}
NEW_COLUMNS = {"starts": {"version": "TEXT", "invocation": "INTEGER"},
               "explorations": {"version": "TEXT", "invocation": "INTEGER"}, "invocations": {"versions": "TEXT"}}
PHASE_TABLES = {"ingest": "starts", "explore": "explorations", "score": "scores"}


class RunStoreError(Exception):
    pass


def media_path(root: Path, sha: str) -> Path:
    return root / MEDIA_DIR / sha[:2] / f"{sha}.jpg"


class RunStore:
    def __init__(self, root: Path, create: bool = False) -> None:
        self.root = root
        db = root / DB_NAME
        if not create and not db.is_file():
            raise RunStoreError(f"no run at {root} (missing {DB_NAME})")
        root.mkdir(parents=True, exist_ok=True)
        (root / MEDIA_DIR).mkdir(exist_ok=True)
        (root / LOGS_DIR).mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            if version not in MIGRATIONS:
                raise RunStoreError(f"{db} has schema {version}; this code reads {SCHEMA_VERSION}")
            for step in range(version, SCHEMA_VERSION):
                self._conn.executescript(MIGRATIONS[step])
            self._add_columns()
            self._conn.executescript(SCHEMA)
            self._backfill_explore_versions()
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.stamp: dict[str, tuple[str, int]] = {}

    def _add_columns(self) -> None:
        for table, columns in NEW_COLUMNS.items():
            have = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    def _backfill_explore_versions(self) -> None:
        from .versions import explore_detail, fingerprint

        rows = self._conn.execute("SELECT stop_id, harness, explorer FROM explorations WHERE version IS NULL").fetchall()
        for r in rows:
            detail = explore_detail(json.loads(r["harness"]), json.loads(r["explorer"]))
            v = fingerprint(detail)
            self._conn.execute("INSERT OR IGNORE INTO versions (version, phase, detail) VALUES (?, 'explore', ?)",
                               (v, _json(detail)))
            self._conn.execute("UPDATE explorations SET version = ? WHERE stop_id = ?", (v, r["stop_id"]))


    def add_version(self, version: str, detail: dict, invocation: int | None) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR IGNORE INTO versions (version, phase, detail, first_invocation) VALUES (?, ?, ?, ?)",
                      (version, detail["phase"], _json(detail), invocation))

    def versions_in(self, phase: str, stop_ids: Iterable[str] | None = None) -> dict[str | None, int]:
        rows = self.query(f"SELECT stop_id, version FROM {PHASE_TABLES[phase]}")
        wanted = None if stop_ids is None else set(stop_ids)
        out: dict[str | None, int] = {}
        for r in rows:
            if wanted is None or r["stop_id"] in wanted:
                out[r["version"]] = out.get(r["version"], 0) + 1
        return out

    def version_details(self) -> dict[str, dict]:
        return {r["version"]: {"phase": r["phase"], "first_invocation": r["first_invocation"],
                               "detail": json.loads(r["detail"])}
                for r in self.query("SELECT * FROM versions ORDER BY phase, first_invocation")}

    def versions_summary(self) -> dict:
        out = {}
        for phase in PHASE_TABLES:
            counts = {v or "unknown": n for v, n in self.versions_in(phase).items()}
            out[phase] = {"rows": counts, "mixed": len(counts) > 1}
        return out

    def _stamp(self, phase: str, row: dict) -> tuple:
        version, invocation = self.stamp.get(phase, (None, None))
        return row.get("version", version), row.get("invocation", invocation)

    @property
    def logs_dir(self) -> Path:
        return self.root / LOGS_DIR

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("PRAGMA journal_mode=DELETE")
            self._conn.close()
            self._closed = True

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()


    def set_meta(self, key: str, value: object) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, _json(value)))

    def get_meta(self, key: str, default: object = None) -> Any:
        rows = self.query("SELECT value FROM meta WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default


    def put_media(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = media_path(self.root, sha)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return sha

    def media(self, sha: str) -> Path:
        return media_path(self.root, sha)


    def add_stops(self, stops: list[dict]) -> int:
        with self.transaction() as c:
            start = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM stops").fetchone()[0]
            added = 0
            for s in stops:
                cur = c.execute(
                    "INSERT OR IGNORE INTO stops (stop_id, position, name, gtfs_lat, gtfs_lon, services) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (s["stop_id"], start + added, s["name"], s["gtfs_lat"], s["gtfs_lon"], _json(s["services"])))
                added += cur.rowcount
            return added

    def stop_ids(self) -> list[str]:
        return [r["stop_id"] for r in self.query("SELECT stop_id FROM stops ORDER BY position")]

    def pending(self, phase: str, stop_ids: Iterable[str] | None = None) -> list[str]:
        table = {"ingest": "starts", "explore": "explorations", "score": "scores"}[phase]
        rows = self.query(f"SELECT s.stop_id FROM stops s LEFT JOIN {table} t USING (stop_id) "
                          f"WHERE t.stop_id IS NULL ORDER BY s.position")
        ids = [r["stop_id"] for r in rows]
        if stop_ids is not None:
            wanted = set(stop_ids)
            ids = [i for i in ids if i in wanted]
        return ids

    def forget(self, phase: str, stop_ids: Iterable[str]) -> None:
        tables = {"ingest": ["scores", "transcripts", "photos", "explorations", "starts"],
                  "explore": ["scores", "transcripts", "photos", "explorations"],
                  "score": ["scores"]}[phase]
        with self.transaction() as c:
            for stop_id in stop_ids:
                for table in tables:
                    c.execute(f"DELETE FROM {table} WHERE stop_id = ?", (stop_id,))


    def put_start(self, row: dict) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO starts (stop_id, source, lat, lon, osm, places, ingested_at, version, "
                      "invocation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (row["stop_id"], row["source"], row["lat"], row["lon"], _json_or_none(row.get("osm")),
                       _json_or_none(row.get("places")), row.get("ingested_at") or utc_now(),
                       *self._stamp("ingest", row)))

    def start(self, stop_id: str) -> dict | None:
        rows = self.query("SELECT * FROM starts WHERE stop_id = ?", (stop_id,))
        return _decode(rows[0], ("osm", "places")) if rows else None

    def stop(self, stop_id: str) -> dict:
        rows = self.query("SELECT * FROM stops WHERE stop_id = ?", (stop_id,))
        if not rows:
            raise RunStoreError(f"stop {stop_id} is not in the run")
        return _decode(rows[0], ("services",))

    def put_exploration(self, row: dict, photos: list[dict], transcript: list[dict]) -> None:
        with self.transaction() as c:
            stop_id = row["stop_id"]
            for table in ("scores", "transcripts", "photos", "explorations"):
                c.execute(f"DELETE FROM {table} WHERE stop_id = ?", (stop_id,))
            c.execute(
                "INSERT INTO explorations (stop_id, status, reason, lat, lon, position_basis, evidence, plate_text, "
                "scan_date, stop_photos, explorer, harness, billed_static, billed_tiles, turns, seconds, started_at, "
                "finished_at, record, version, invocation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stop_id, row["status"], row.get("reason"), row.get("lat"), row.get("lon"), row.get("position_basis"),
                 row.get("evidence"), row.get("plate_text"), row.get("scan_date"), _json(row.get("stop_photos", [])),
                 _json(row["explorer"]), _json(row["harness"]), row["billed_static"], row["billed_tiles"],
                 row["turns"], row["seconds"], row["started_at"], row["finished_at"], _json(row["record"]),
                 *self._stamp("explore", row)))
            c.executemany(
                "INSERT INTO photos (stop_id, idx, media, toward, pano_id, date, heading, fov, pitch, width, height, "
                "lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(stop_id, p["idx"], p["media"], p["toward"], p["pano_id"], p.get("date"), p["heading"], p["fov"],
                  p["pitch"], p["width"], p["height"], p["lat"], p["lon"]) for p in photos])
            c.execute("INSERT INTO transcripts (stop_id, lines) VALUES (?, ?)",
                      (stop_id, "\n".join(json.dumps(t, ensure_ascii=False) for t in transcript)))

    def exploration(self, stop_id: str) -> dict | None:
        rows = self.query("SELECT * FROM explorations WHERE stop_id = ?", (stop_id,))
        return _decode(rows[0], ("stop_photos", "explorer", "harness", "record")) if rows else None

    def put_score(self, row: dict) -> None:
        with self.transaction() as c:
            c.execute(
                f"INSERT OR REPLACE INTO scores (stop_id, photos, scorer, {', '.join(SCORE_COLUMNS)}, answers, "
                f"seconds, scored_at, version, invocation) VALUES (?, ?, ?, {', '.join('?' * len(SCORE_COLUMNS))}, ?, ?, ?, ?, ?)",
                (row["stop_id"], _json(row["photos"]), _json(row["scorer"]), *(row.get(k) for k in SCORE_COLUMNS),
                 _json(row["answers"]), row["seconds"], row.get("scored_at") or utc_now(), *self._stamp("score", row)))


    def add_usage(self, month: str, key_id: str, api: str, count: int) -> None:
        if count <= 0:
            return
        with self.transaction() as c:
            c.execute("INSERT INTO usage (month, key_id, api, count) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT (month, key_id, api) DO UPDATE SET count = count + excluded.count",
                      (month, key_id, api, count))

    def begin_invocation(self, host: dict, args: dict, git: dict, versions: dict | None = None) -> int:
        with self.transaction() as c:
            cur = c.execute("INSERT INTO invocations (started_at, host, args, git, versions) VALUES (?, ?, ?, ?, ?)",
                            (utc_now(), _json(host), _json(args), _json(git), _json_or_none(versions)))
            return int(cur.lastrowid)

    def set_invocation_versions(self, seq: int, versions: dict) -> None:
        with self.transaction() as c:
            c.execute("UPDATE invocations SET versions = ? WHERE seq = ?", (_json(versions), seq))

    def end_invocation(self, seq: int, status: str, counts: dict) -> None:
        with self.transaction() as c:
            c.execute("UPDATE invocations SET finished_at = ?, status = ?, counts = ? WHERE seq = ?",
                      (utc_now(), status, _json(counts), seq))

    def summary(self) -> dict:
        one = lambda sql: self.query(sql)[0][0]  # noqa: E731
        return {
            "stops": one("SELECT COUNT(*) FROM stops"),
            "ingested": dict(self.query("SELECT source, COUNT(*) FROM starts GROUP BY source")),
            "explored": dict(self.query("SELECT status, COUNT(*) FROM explorations GROUP BY status")),
            "scored": one("SELECT COUNT(*) FROM scores"),
            "billed": {f"{r['api']}": r["n"] for r in self.query("SELECT api, SUM(count) AS n FROM usage GROUP BY api")},
        }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_or_none(value: object) -> str | None:
    return None if value is None else _json(value)


def _decode(row: sqlite3.Row, json_columns: tuple[str, ...]) -> dict:
    out = dict(row)
    for k in json_columns:
        if out.get(k) is not None:
            out[k] = json.loads(out[k])
    return out
