"""What produced each result: one version per phase, so a run's rows can be grouped and never mixed by mistake.

Every phase row (starts, explorations, scores) carries the `version` that made it: the first 12 hex of the
sha256 of a canonical JSON of what decides the phase's output:

  ingest   INGEST_VERSION, the OSM store (its build time, region, extracts), the GTFS stops.txt sha256
  explore  the harness (HARNESS_VERSION, the prompt's sha256) and the explorer models (files, revisions,
           sampling, server arguments)
  score    SCORER_VERSION, the sha256 of the prompts Imajev reads (header, questions, state template) and the
           scorer model (files, revisions, readout, calibration, rotations)

The details are kept in the run's `versions` table; each invocation records the versions it ran with, the
package version and the git commit (with a sha256 of the uncommitted diff, when there is one). The git commit
is not part of a version: a commit that does not change a phase must not split the phase's rows. A code change
that does change a phase's output without touching a prompt bumps the phase's constant.
"""

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version as package_version

from .provenance import _git, git_state

INGEST_VERSION = 1  # bump when the ingest logic changes its output (start choice, OSM matching, Places use)
SCORER_VERSION = 5  # bump when scoring changes beyond the prompts: answer -> value mapping, gating, condition,
# which photos each question reads
_NOT_OUTPUT = {"port", "concurrency"}  # settings that change speed, not results


def fingerprint(detail: dict) -> str:
    return hashlib.sha256(_canonical(detail).encode()).hexdigest()[:12]


def _canonical(value) -> str:
    return json.dumps(_strip(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _NOT_OUTPUT}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def pipeline() -> dict:
    """The code: package version and git state (commit, dirty, sha256 of the diff against HEAD)."""
    try:
        pkg = package_version("cotral-maintenance")
    except PackageNotFoundError:
        pkg = None
    git = git_state()
    if git.get("dirty"):
        diff = _git("diff", "HEAD") or ""
        git["diff_sha256"] = hashlib.sha256(diff.encode()).hexdigest()
    return {"package": pkg, "git": git}


def ingest_detail(osm_meta: dict, gtfs_stops_sha256: str) -> dict:
    return {"phase": "ingest", "ingest_version": INGEST_VERSION, "gtfs_stops_sha256": gtfs_stops_sha256,
            "osm_store": {k: osm_meta.get(k) for k in ("built_at", "region", "extracts")}}


def explore_detail(harness: dict, explorer: dict) -> dict:
    """`harness` as stored with each exploration (its `git` is left out), `explorer` the model description."""
    return {"phase": "explore", "harness": {k: v for k, v in harness.items() if k != "git"}, "explorer": explorer}


def scorer_prompts_sha256() -> str:
    """The sha256 of every prompt text the scorer sends, for a placeholder stop with a close and a wide photo."""
    from .scorer import questions as Q
    from .scorer.imajev import Engine

    close = {"pano_id": "a", "heading": 0.0, "fov": 60.0, "lat": 42.0, "lon": 12.0}
    wide = {**close, "fov": 110.0}
    texts = Q.describe_photos([close, wide], 42.0002, 12.0)
    prompts = Engine(None, rotations=1).prompts(Q.questions(), Q.state("<stop>", "<evidence>", texts))
    return hashlib.sha256("\n\0\n".join(p.text for p in prompts).encode()).hexdigest()


def score_detail(scorer: dict) -> dict:
    return {"phase": "score", "scorer_version": SCORER_VERSION, "prompts_sha256": scorer_prompts_sha256(),
            "scorer": scorer}
