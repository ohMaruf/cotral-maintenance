import hashlib
import json
from importlib.metadata import PackageNotFoundError, version as package_version

from .provenance import _git, git_state

INGEST_VERSION = 1
SCORER_VERSION = 5
_NOT_OUTPUT = {"port", "concurrency"}


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
            "osm_store": {k: osm_meta.get(k) for k in ("build_version", "extracts_sha256", "region")}}


def explore_detail(harness: dict, explorer: dict) -> dict:
    return {"phase": "explore", "harness": {k: v for k, v in harness.items() if k != "git"}, "explorer": explorer}


def scorer_prompts_sha256() -> str:
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
