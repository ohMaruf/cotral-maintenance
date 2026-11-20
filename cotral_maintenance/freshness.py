import logging
import os
import subprocess
from pathlib import Path

from .errors import CotralMaintenanceError

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
FETCH_TIMEOUT_S = 30


class StaleCheckoutError(CotralMaintenanceError):
    """The checkout is behind its remote, or its submodule is not at the pinned commit."""


def _git(*args: str, timeout: float = 10) -> subprocess.CompletedProcess | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    try:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                              timeout=timeout, env=env, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _out(*args: str) -> str | None:
    result = _git(*args)
    return result.stdout.strip() if result is not None and result.returncode == 0 else None


def check_up_to_date() -> None:
    if _out("rev-parse", "--is-inside-work-tree") != "true":
        logger.warning("Freshness check skipped: %s is not a git checkout", REPO)
        return
    _check_branch()
    _check_submodules()


def _check_branch() -> None:
    branch = _out("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch is None:
        logger.warning("Freshness check skipped: detached HEAD (no branch to compare with its remote)")
        return
    upstream = _out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream is None:
        logger.warning("Freshness check skipped: branch %s has no upstream (git branch -u origin/%s)",
                       branch, branch)
        return
    remote = _out("config", f"branch.{branch}.remote") or "origin"
    fetched = _git("fetch", "--quiet", remote, timeout=FETCH_TIMEOUT_S)
    if fetched is None or fetched.returncode != 0:
        reason = "timed out" if fetched is None else (fetched.stderr.strip().splitlines() or ["failed"])[-1]
        logger.warning("Freshness check: cannot fetch %s (%s); comparing with the last fetched %s",
                       remote, reason, upstream)
    counts = _out("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if counts is None:
        logger.warning("Freshness check skipped: cannot compare %s with %s", branch, upstream)
        return
    ahead, behind = (int(n) for n in counts.split())
    if behind:
        state = f"{behind} commit(s) behind" + (f" and {ahead} ahead of (diverged from)" if ahead else "")
        raise StaleCheckoutError(
            f"{branch} is {state} {upstream}: run `git pull` (and `git submodule update inputs`) first, "
            "or pass --allow-stale to run this checkout anyway")
    if ahead:
        logger.warning("Freshness check: %s is %d commit(s) ahead of %s (not pushed)", branch, ahead, upstream)
    else:
        logger.info("Freshness check: %s is up to date with %s", branch, upstream)


def _check_submodules() -> None:
    result = _git("submodule", "status")
    status = result.stdout if result is not None and result.returncode == 0 else ""
    for line in filter(None, status.splitlines()):
        flag, path = line[:1], line[1:].split()[1]
        if flag in "+U":
            raise StaleCheckoutError(
                f"submodule {path} is not at the commit this checkout pins: run `git submodule update {path}` "
                "first, or pass --allow-stale to run anyway")
        if flag == "-":
            logger.warning("Freshness check: submodule %s is not initialised", path)
