import json
import re
import shutil
from pathlib import Path

from ..errors import CotralMaintenanceError
from ..runstore import DB_NAME, RunStore, media_path

SHA = re.compile(r"\b[0-9a-f]{64}\b")
RANK = {"found": 3, "not_found": 2, "no_imagery": 2, "error": 1}
STOP_TABLES = ("starts", "explorations", "photos", "transcripts", "scores")
WITH_INVOCATION = ("starts", "explorations", "scores")


class MergeError(CotralMaintenanceError):
    pass


def merge(target: Path, sources: list[Path]) -> dict:
    if target.exists():
        raise MergeError(f"{target} already exists: merge into a new run")
    if len(sources) < 2:
        raise MergeError("merge needs at least two runs")
    for s in sources:
        if not (s / DB_NAME).is_file():
            raise MergeError(f"no run at {s}")
        RunStore(s).close()
    try:
        return _merge(target, sources)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _merge(target: Path, sources: list[Path]) -> dict:
    with RunStore(target, create=True) as run:
        c = run._conn
        gtfs, winner, order, seqs = None, {}, [], {}
        for n, source in enumerate(sources):
            c.execute(f"ATTACH DATABASE ? AS s{n}", (str((source / DB_NAME).resolve()),))
        for n, source in enumerate(sources):
            s = f"s{n}"
            digest = c.execute(f"SELECT value FROM {s}.meta WHERE key = 'gtfs_stops_sha256'").fetchone()
            if digest is not None:
                if gtfs is not None and digest[0] != gtfs:
                    raise MergeError(f"{source.name} was made from another GTFS feed")
                gtfs = digest[0]
            status = dict(c.execute(f"SELECT stop_id, status FROM {s}.explorations").fetchall())
            for (stop_id,) in c.execute(f"SELECT stop_id FROM {s}.stops ORDER BY position"):
                if stop_id not in winner:
                    order.append(stop_id)
                rank = RANK.get(status.get(stop_id), 0)
                if stop_id not in winner or rank >= winner[stop_id][1]:
                    winner[stop_id] = (n, rank)
        with run.transaction():
            for n, source in enumerate(sources):
                s = f"s{n}"
                for row in c.execute(f"SELECT * FROM {s}.invocations ORDER BY seq").fetchall():
                    old = dict(row)
                    args = json.loads(old["args"])
                    args["merged_from"] = source.name
                    cur = c.execute("INSERT INTO invocations (started_at, finished_at, status, host, args, git, counts, "
                                    "versions) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (old["started_at"], old["finished_at"], old["status"], old["host"],
                                     json.dumps(args), old["git"], old["counts"], old["versions"]))
                    seqs[(n, old["seq"])] = cur.lastrowid
                for key, value in c.execute(f"SELECT key, value FROM {s}.meta").fetchall():
                    if key.startswith("profile:"):
                        new = seqs.get((n, int(key.split(":")[1])))
                        if new is not None:
                            c.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"profile:{new}", value))
                for v in c.execute(f"SELECT * FROM {s}.versions").fetchall():
                    c.execute("INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?)",
                              (v["version"], v["phase"], v["detail"], seqs.get((n, v["first_invocation"]))))
                for u in c.execute(f"SELECT * FROM {s}.usage").fetchall():
                    c.execute("INSERT INTO usage VALUES (?, ?, ?, ?) ON CONFLICT (month, key_id, api) DO UPDATE SET "
                              "count = count + excluded.count", (u["month"], u["key_id"], u["api"], u["count"]))
            if gtfs is not None:
                c.execute("INSERT OR REPLACE INTO meta VALUES ('gtfs_stops_sha256', ?)", (gtfs,))
            c.execute("INSERT OR REPLACE INTO meta VALUES ('merged_from', ?)", (json.dumps([s.name for s in sources]),))
            for position, stop_id in enumerate(order):
                n = winner[stop_id][0]
                s = f"s{n}"
                stop = dict(c.execute(f"SELECT * FROM {s}.stops WHERE stop_id = ?", (stop_id,)).fetchone())
                c.execute("INSERT INTO stops (stop_id, position, name, gtfs_lat, gtfs_lon, services) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (stop_id, position, stop["name"], stop["gtfs_lat"], stop["gtfs_lon"], stop["services"]))
                for table in STOP_TABLES:
                    for row in c.execute(f"SELECT * FROM {s}.{table} WHERE stop_id = ?", (stop_id,)).fetchall():
                        row = dict(row)
                        if table in WITH_INVOCATION and row.get("invocation") is not None:
                            row["invocation"] = seqs.get((n, row["invocation"]))
                        columns = ", ".join(row)
                        marks = ", ".join("?" for _ in row)
                        c.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))
        for n in range(len(sources)):
            c.execute(f"DETACH DATABASE s{n}")
        copied = missing = 0
        for stop_id in order:
            source = sources[winner[stop_id][0]]
            for sha in _media_of(run, stop_id):
                src, dst = media_path(source, sha), media_path(target, sha)
                if dst.exists():
                    continue
                if not src.is_file():
                    missing += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
        found = sum(1 for _, rank in winner.values() if rank == RANK["found"])
        from .export import write_results
        write_results(run)
    return {"stops": len(order), "found": found, "photos": copied, "missing_photos": missing,
            "from": {sources[n].name: sum(1 for w, _ in winner.values() if w == n) for n in range(len(sources))}}


def _media_of(run: RunStore, stop_id: str) -> set[str]:
    shas: set[str] = set()
    for table in ("photos", "explorations", "scores"):
        for row in run.query(f"SELECT * FROM {table} WHERE stop_id = ?", (stop_id,)):
            for value in dict(row).values():
                if isinstance(value, str):
                    shas |= set(SHA.findall(value))
    return shas
