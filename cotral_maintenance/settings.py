"""Where things live and which models run: paths from the environment, model profiles from config/profiles.toml.

Paths (defaults relative to the repository root; override with environment variables or .env):
  COTRAL_DATASET     inputs/dataset.toml      the dataset manifest (dataset.py): the GTFS zip, the OSM extracts, the
                                              explorer's reference images, with their sha256 (inputs/: the data
                                              repository, a git submodule)
  COTRAL_GTFS        GTFS_COTRAL              the GTFS feed, unzipped from the dataset (`cotral inputs fetch`)
  COTRAL_OSM_STORE   data/osm/osm.sqlite3     the OSM store built from the dataset's extracts (`cotral osm build`)
  COTRAL_CACHE       data/cache               caches shared by runs (metadata, photos, tiles, Places, usage)
  COTRAL_RUNS        runs                     one directory per run
  COTRAL_MODELS      ~/models                 model files downloaded from Hugging Face
  COTRAL_PROFILES    config/profiles.toml
Google: MAPS_API_KEY (required for ingest and explore), MAPS_API_REFERRER (optional).
"""

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "remote"


@dataclass(frozen=True)
class Paths:
    gtfs: Path
    osm_store: Path
    dataset_manifest: Path
    cache: Path
    runs: Path
    models: Path
    profiles: Path

    @classmethod
    def from_env(cls) -> "Paths":
        load_dotenv(ROOT / ".env")

        def p(var: str, default: str | Path) -> Path:
            value = Path(os.environ.get(var) or default).expanduser()
            return value if value.is_absolute() else ROOT / value

        return cls(gtfs=p("COTRAL_GTFS", "GTFS_COTRAL"), osm_store=p("COTRAL_OSM_STORE", "data/osm/osm.sqlite3"),
                   dataset_manifest=p("COTRAL_DATASET", "inputs/dataset.toml"),
                   cache=p("COTRAL_CACHE", "data/cache"), runs=p("COTRAL_RUNS", "runs"),
                   models=p("COTRAL_MODELS", Path.home() / "models"),
                   profiles=p("COTRAL_PROFILES", "config/profiles.toml"))

    @property
    def dataset(self) -> "Dataset":
        from .dataset import Dataset

        return Dataset.load(self.dataset_manifest)

    @property
    def reference_sign(self) -> Path:
        return self.dataset.sign

    @property
    def lookalikes(self) -> list[Path]:
        return self.dataset.lookalikes


@dataclass(frozen=True)
class GoogleKey:
    api_key: str
    referrer: str | None

    @classmethod
    def from_env(cls) -> "GoogleKey":
        load_dotenv(ROOT / ".env")
        key = os.environ.get("MAPS_API_KEY")
        if not key:
            raise ConfigError("MAPS_API_KEY is not set (environment or .env)")
        return cls(key, os.environ.get("MAPS_API_REFERRER") or None)


@dataclass(frozen=True)
class ModelFile:
    repo: str
    revision: str
    file: str

    def path(self, models: Path) -> Path:
        return models / self.repo.replace("/", "--") / self.revision[:12] / self.file


@dataclass(frozen=True)
class ServerSpec:
    kind: str  # llama-server, command, external
    port: int
    files: dict[str, ModelFile] = field(default_factory=dict)
    args: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    health: str = "/health"
    base_url: str | None = None
    binary: str = "llama-server"

    @property
    def url(self) -> str:
        return (self.base_url or f"http://127.0.0.1:{self.port}").rstrip("/")


@dataclass(frozen=True)
class ModelSpec:
    """One side of a profile: the explorer or the scorer."""

    role: str
    dialect: str
    model: str
    server: ServerSpec
    concurrency: int = 1
    sampling: dict = field(default_factory=dict)
    template: dict = field(default_factory=dict)
    request: dict = field(default_factory=dict)  # backend-specific OpenAI request fields
    max_tokens: int = 3000
    rotations: int = 4
    readout: dict[str, ModelFile] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)  # the profile entry as written, recorded with every result

    def describe(self) -> dict:
        return {"role": self.role, "dialect": self.dialect, "model": self.model, "profile_entry": self.raw}


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    explorer: ModelSpec
    scorer: ModelSpec


EXPLORER_DIALECTS = ("llamacpp", "strict")
SCORER_DIALECTS = ("llamacpp-readout", "systemone", "llamacpp-systemone")


def load_profiles(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise ConfigError(f"no profiles file at {path}")
    return tomllib.loads(path.read_text()).get("profiles", {})


def _merge(base: dict, over: dict) -> dict:
    """`over` on top of `base`, table by table; a table with `inherit = false` replaces the inherited one whole."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and v.get("inherit") is False:
            out[k] = {key: copy.deepcopy(x) for key, x in v.items() if key != "inherit"}
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _resolve(profiles: dict[str, dict], name: str, seen: tuple[str, ...] = ()) -> dict:
    if name not in profiles:
        raise ConfigError(f"no profile {name!r}; profiles: {', '.join(sorted(profiles))}")
    if name in seen:
        raise ConfigError(f"profile inheritance loops: {' -> '.join((*seen, name))}")
    entry = profiles[name]
    parent = entry.get("inherit")
    return _merge(_resolve(profiles, parent, (*seen, name)), entry) if parent else entry


def _file(value: dict) -> ModelFile:
    try:
        return ModelFile(value["repo"], value["revision"], value["file"])
    except KeyError as error:
        raise ConfigError(f"a model file needs repo, revision and file: {value}") from error


def _server(value: dict) -> ServerSpec:
    kind = value.get("kind", "external")
    if kind not in ("llama-server", "command", "external"):
        raise ConfigError(f"unknown server kind {kind!r}")
    return ServerSpec(kind=kind, port=int(value.get("port", 8080)),
                      files={k: _file(v) for k, v in value.get("files", {}).items()},
                      args=tuple(value.get("args", ())), command=tuple(value.get("command", ())),
                      cwd=value.get("cwd"), env=dict(value.get("env", {})), health=value.get("health", "/health"),
                      base_url=value.get("base_url"), binary=_binary(value.get("binary")))


def _binary(configured: str | None) -> str:
    """A server's own `binary` (a llama.cpp build it needs), else $LLAMA_SERVER, else llama-server on the PATH."""
    if configured:
        return os.path.expanduser(configured)
    return os.environ.get("LLAMA_SERVER", "llama-server")


def _model(role: str, value: dict, dialects: tuple[str, ...]) -> ModelSpec:
    dialect = value.get("dialect")
    if dialect not in dialects:
        raise ConfigError(f"{role}: dialect must be one of {', '.join(dialects)}, got {dialect!r}")
    return ModelSpec(role=role, dialect=dialect, model=value["model"], server=_server(value.get("server", {})),
                     concurrency=int(value.get("concurrency", 1)), sampling=dict(value.get("sampling", {})),
                     template=dict(value.get("template", {})), request=dict(value.get("request", {})),
                     max_tokens=int(value.get("max_tokens", 3000)),
                     rotations=int(value.get("rotations", 4)),
                     readout={k: _file(v) for k, v in value.get("readout", {}).items()}, raw=value)


def load_profile(paths: Paths, name: str | None = None) -> Profile:
    name = name or os.environ.get("COTRAL_PROFILE") or DEFAULT_PROFILE
    entry = _resolve(load_profiles(paths.profiles), name)
    return Profile(name=name, description=entry.get("description", ""),
                   explorer=_model("explorer", entry["explorer"], EXPLORER_DIALECTS),
                   scorer=_model("scorer", entry["scorer"], SCORER_DIALECTS))
