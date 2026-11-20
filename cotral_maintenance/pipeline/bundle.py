import json
import tarfile
from pathlib import Path

from ..runstore import DB_NAME, LOGS_DIR, RunStore, media_path

MEDIA_CHOICES = ("all", "stop", "none")


def media_to_ship(run: RunStore, media: str) -> list[str]:
    if media == "none":
        return []
    if media == "all":
        return sorted({r["media"] for r in run.query("SELECT media FROM photos")}
                      | _stop_photos(run))
    return sorted(_stop_photos(run))


def _stop_photos(run: RunStore) -> set[str]:
    shas = set()
    for r in run.query("SELECT stop_photos FROM explorations UNION ALL SELECT photos FROM scores"):
        shas.update(json.loads(r[0] or "[]"))
    return shas


def bundle(root: Path, out: Path, media: str = "all", logs: bool = True) -> tuple[Path, int]:
    if media not in MEDIA_CHOICES:
        raise ValueError(f"media must be one of {MEDIA_CHOICES}")
    store = RunStore(root)
    try:
        shas = media_to_ship(store, media)
    finally:
        store.close()
    name = root.name
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with tarfile.open(tmp, "w:zst") as tar:
        tar.add(root / DB_NAME, arcname=f"{name}/{DB_NAME}")
        for extra in ("results.csv",):
            if (root / extra).is_file():
                tar.add(root / extra, arcname=f"{name}/{extra}")
        if logs and (root / LOGS_DIR).is_dir():
            tar.add(root / LOGS_DIR, arcname=f"{name}/{LOGS_DIR}")
        for sha in shas:
            path = media_path(root, sha)
            if path.is_file():
                tar.add(path, arcname=f"{name}/{path.relative_to(root)}")
    tmp.replace(out)
    return out, len(shas)


def unbundle(archive: Path, runs: Path, replace: bool = False) -> Path:
    with tarfile.open(archive, "r:*") as tar:
        names = {m.name.split("/", 1)[0] for m in tar.getmembers()}
        if len(names) != 1:
            raise ValueError(f"{archive} is not a run bundle (top-level entries: {sorted(names)})")
        name = names.pop()
        target = runs / name
        if (target / DB_NAME).exists() and not replace:
            raise FileExistsError(f"{target} exists; pass --replace to update it from the bundle")
        runs.mkdir(parents=True, exist_ok=True)
        for leftover in (target / f"{DB_NAME}-wal", target / f"{DB_NAME}-shm"):
            leftover.unlink(missing_ok=True)
        tar.extractall(runs, filter="data")
    RunStore(target).close()
    return target
