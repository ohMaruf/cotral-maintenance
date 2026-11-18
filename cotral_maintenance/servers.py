"""Model servers: fetch their files, start them, wait until they answer, stop them.

On the 16 GB GPU the explorer (Qwen3.8-27B) and the scorer (Imajev-4B) don't fit together with
the explorer's KV cache, so the pipeline runs one at a time: explore a chunk of stops with the
explorer server up, stop it, score the chunk with the scorer server up, and so on. A server of
kind "external" is someone else's: it is only checked, never started or stopped.
"""

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import requests

from .errors import ConfigError, CotralMaintenanceError
from .settings import ROOT, ModelFile, ServerSpec

logger = logging.getLogger(__name__)

START_TIMEOUT_S = 900.0  # a 10 GB model from a cold disk, plus warm-up


class ModelServerError(CotralMaintenanceError):
    pass


def fetch(file: ModelFile, models: Path) -> Path:
    """The local path of a model file, downloaded at its pinned revision if missing."""
    path = file.path(models)
    if path.is_file():
        return path
    from huggingface_hub import hf_hub_download

    logger.info("Downloading %s/%s @ %s", file.repo, file.file, file.revision[:12])
    downloaded = hf_hub_download(file.repo, file.file, revision=file.revision, local_dir=path.parent.parent / "dl")
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(downloaded).replace(path)
    return path


def _expand(value: str, spec: ServerSpec, files: dict[str, Path]) -> str:
    out = value.replace("{port}", str(spec.port))
    for key, path in files.items():
        out = out.replace(f"{{file:{key}}}", str(path))
    while "{env:" in out:
        start = out.index("{env:")
        end = out.index("}", start)
        var = out[start + 5:end]
        if not os.environ.get(var):
            raise ConfigError(f"{var} is not set (used by a server command)")
        out = out[:start] + os.environ[var] + out[end + 1:]
    return out


def healthy(spec: ServerSpec) -> bool:
    try:
        return requests.get(spec.url + spec.health, timeout=5).status_code == 200
    except requests.RequestException:
        return False


class ManagedServer:
    """A model server for the time of a `with` block (or a check of an external one)."""

    def __init__(self, name: str, spec: ServerSpec, models: Path, log_path: Path) -> None:
        self.name = name
        self.spec = spec
        self.models = models
        self.log_path = log_path
        self.process: subprocess.Popen | None = None

    def command(self) -> tuple[list[str], dict[str, str], Path]:
        files = {k: fetch(f, self.models) for k, f in self.spec.files.items()}
        if self.spec.kind == "llama-server":
            binary = shutil.which(self.spec.binary) or self.spec.binary
            argv = [binary, *(_expand(a, self.spec, files) for a in self.spec.args)]
        else:
            argv = [_expand(a, self.spec, files) for a in self.spec.command]
        cwd = Path(_expand(self.spec.cwd, self.spec, files)) if self.spec.cwd else ROOT
        cwd = cwd if cwd.is_absolute() else ROOT / cwd
        env = {**os.environ, **{k: _expand(v, self.spec, files) for k, v in self.spec.env.items()}}
        return argv, env, cwd

    def __enter__(self) -> "ManagedServer":
        if self.spec.kind == "external":
            if not healthy(self.spec):
                raise ModelServerError(f"{self.name}: no server answering at {self.spec.url}{self.spec.health}")
            return self
        if healthy(self.spec):
            raise ModelServerError(f"{self.name}: something already answers on port {self.spec.port}; stop it first "
                              f"(or declare the server kind = \"external\")")
        argv, env, cwd = self.command()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("ab")
        logger.info("Starting the %s server: %s", self.name, " ".join(argv))
        try:
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError as error:
            raise ModelServerError(f"{self.name}: cannot start {argv[0]} ({error})") from error
        finally:
            log.close()
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ModelServerError(f"{self.name} server exited with code {self.process.returncode}; "
                                  f"see {self.log_path}")
            if healthy(self.spec):
                logger.info("The %s server is ready at %s", self.name, self.spec.url)
                return self
            time.sleep(2.0)
        self.stop()
        raise ModelServerError(f"{self.name} server not ready after {START_TIMEOUT_S:.0f} s; see {self.log_path}")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        os.killpg(self.process.pid, signal.SIGTERM)
        try:
            self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
        logger.info("Stopped the %s server", self.name)

    def __exit__(self, *exc: object) -> None:
        self.stop()
