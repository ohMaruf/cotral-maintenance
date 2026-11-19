"""The dataset a run reads, described by a manifest (inputs/dataset.toml): every input file, its role, where it
came from and its sha256.

The files live next to the manifest, in the data repository (a git submodule at inputs/, large files in Git LFS),
so the exact bytes a result came from stay retrievable. A file that is missing is fetched from its `url` and
accepted only if its sha256 matches: a "latest" URL that has moved on is refused, never silently used.

    cotral inputs check     every file against its sha256
    cotral inputs fetch     fetch what is missing, then unzip the GTFS feed into GTFS_COTRAL/ (once)

Roles: gtfs (the operator's feed, zipped), osm (OpenStreetMap extracts covering the network), sign (the
explorer's reference image of the operator's stop sign), lookalike (signs it must not take for one),
reference (ground truth for experiments, not read by the pipeline).
"""

import hashlib
import logging
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .errors import CotralMaintenanceError

logger = logging.getLogger(__name__)

ROLES = ("gtfs", "osm", "sign", "lookalike", "reference")
GTFS_FILES = ("agency.txt", "calendar.txt", "routes.txt", "shapes.txt", "stop_times.txt", "stops.txt", "trips.txt")
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


class DatasetError(CotralMaintenanceError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Source:
    role: str
    file: str
    sha256: str
    path: Path
    url: str | None = None
    info: dict = field(default_factory=dict)  # data_date, retrieved, license, md5, description

    def state(self) -> str:
        """ok, missing, lfs-pointer (the file is a Git LFS pointer: `git lfs pull` not run) or mismatch."""
        if not self.path.is_file():
            return "missing"
        with self.path.open("rb") as f:
            if f.read(len(LFS_POINTER)) == LFS_POINTER:
                return "lfs-pointer"
        return "ok" if sha256_file(self.path) == self.sha256 else "mismatch"


@dataclass(frozen=True)
class Dataset:
    name: str
    manifest: Path
    sources: tuple[Source, ...]
    description: str = ""

    @classmethod
    def load(cls, manifest: Path) -> "Dataset":
        if not manifest.is_file():
            raise DatasetError(f"no dataset manifest at {manifest}: fetch the data repository "
                               f"(git submodule update --init inputs), or set COTRAL_DATASET")
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
        sources = []
        for i, s in enumerate(raw.get("source", [])):
            missing = {"role", "file", "sha256"} - s.keys()
            if missing:
                raise DatasetError(f"{manifest}: source {i + 1} lacks {', '.join(sorted(missing))}")
            if s["role"] not in ROLES:
                raise DatasetError(f"{manifest}: source {s['file']}: role must be one of {', '.join(ROLES)}")
            info = {k: v for k, v in s.items() if k not in ("role", "file", "sha256", "url")}
            sources.append(Source(s["role"], s["file"], s["sha256"].lower(), manifest.parent / s["file"], s.get("url"),
                                  info))
        dataset = cls(raw.get("name", manifest.parent.name), manifest, tuple(sources), raw.get("description", ""))
        if len(dataset.of("gtfs")) != 1:
            raise DatasetError(f"{manifest}: needs exactly one gtfs source")
        return dataset

    def of(self, role: str) -> list[Source]:
        return [s for s in self.sources if s.role == role]

    @property
    def sign(self) -> Path:
        signs = self.of("sign")
        if not signs:
            raise DatasetError(f"{self.manifest}: no sign source (the explorer's reference image)")
        return signs[0].path

    @property
    def lookalikes(self) -> list[Path]:
        return [s.path for s in self.of("lookalike")]

    def identity(self) -> dict:
        """What the dataset is, for a run's versions: its name and every pipeline input's sha256."""
        return {"name": self.name, "sources": {s.file: s.sha256 for s in self.sources if s.role != "reference"}}

    def check(self) -> list[tuple[Source, str]]:
        return [(s, s.state()) for s in self.sources]


def fetch(dataset: Dataset, gtfs_dir: Path, timeout_s: float = 60.0) -> dict:
    """Make every source present and verified (download what is missing from its url), then unzip the GTFS feed
    into `gtfs_dir` if it is not there. Raises DatasetError with what to do when a source cannot be had."""
    report: dict[str, str] = {}
    problems = []
    for source in dataset.sources:
        state = source.state()
        if state == "missing" and source.url:
            state = _download(source, timeout_s)
        report[source.file] = state
        if state == "lfs-pointer":
            problems.append(f"{source.file} is a Git LFS pointer: install git-lfs, then "
                            f"`git -C {dataset.manifest.parent} lfs pull`")
        elif state == "mismatch":
            problems.append(f"{source.file} differs from its sha256 in the manifest"
                            + (" (its URL serves other bytes now: use the data repository's copy)" if source.url else ""))
        elif state == "missing":
            problems.append(f"{source.file} is missing and has no url")
    if problems:
        raise DatasetError("dataset " + dataset.name + ":\n  " + "\n  ".join(problems))
    report["gtfs_dir"] = unzip_gtfs(dataset.of("gtfs")[0].path, gtfs_dir)
    return report


def _download(source: Source, timeout_s: float) -> str:
    source.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = source.path.with_name(source.path.name + ".part")
    logger.info("Downloading %s", source.url)
    try:
        with requests.get(source.url, stream=True, timeout=timeout_s) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    except requests.RequestException as error:
        tmp.unlink(missing_ok=True)
        logger.error("%s: %s", source.url, error)
        return "missing"
    if sha256_file(tmp) != source.sha256:
        tmp.unlink()
        return "mismatch"
    tmp.replace(source.path)
    return "ok"


def unzip_gtfs(zip_path: Path, gtfs_dir: Path) -> str:
    """Unzip the feed into `gtfs_dir`, flat, once. An unzipped feed is never replaced (a run is tied to the feed it
    started with); when it differs from the zip, that is reported."""
    with zipfile.ZipFile(zip_path) as z:
        members = {Path(n).name: n for n in z.namelist() if n.endswith(".txt") and not Path(n).name.startswith(".")}
        missing = set(GTFS_FILES) - members.keys()
        if missing:
            raise DatasetError(f"{zip_path.name} lacks {', '.join(sorted(missing))}")
        if (gtfs_dir / "stops.txt").is_file():
            if z.read(members["stops.txt"]) == (gtfs_dir / "stops.txt").read_bytes():
                return "kept"
            return (f"kept, differs from {zip_path.name}: to switch feed, remove {gtfs_dir} and fetch again "
                    f"(and start new runs)")
        tmp = gtfs_dir.with_name(gtfs_dir.name + ".partial")
        tmp.mkdir(parents=True, exist_ok=True)
        for name, member in members.items():
            (tmp / name).write_bytes(z.read(member))
    tmp.replace(gtfs_dir)
    return "unzipped"
