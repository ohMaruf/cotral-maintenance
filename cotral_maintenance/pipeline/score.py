"""Phase 3, score: Imajev judges the maintenance state of each found stop from its 1-2 stop photos.

Only stops the explorer found are scored: their stop photos are what the scorer reads. A stop not
found (or without imagery) gets no score; it stays in the results with its search outcome, for a
person to check.
"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..runstore import SCORE_COLUMNS, RunStore
from ..scorer import questions as Q
from ..scorer.backends import LlamaCppReadout, Scorer, ScorerError, SystemOne
from ..scorer.imajev import Calibration, Engine
from ..servers import fetch
from ..settings import ModelSpec, Paths

logger = logging.getLogger(__name__)

STOPS_IN_FLIGHT = 2  # stops scored at once; each sends its prompts concurrently


def make_scorer(spec: ModelSpec, paths: Paths) -> Scorer:
    describe = spec.describe()
    if spec.dialect == "llamacpp-readout":
        if "readout" not in spec.readout:
            raise ScorerError("the llamacpp-readout scorer needs [scorer.readout] readout = {repo, revision, file}")
        readout = fetch(spec.readout["readout"], paths.models)
        calibration = Calibration.load(fetch(spec.readout["calibration"], paths.models)) \
            if "calibration" in spec.readout else None
        return LlamaCppReadout(spec.server.url, readout, Engine(calibration, spec.rotations), describe,
                               parallel=spec.concurrency)
    return SystemOne(spec.server.url, describe)


def scorable(run: RunStore, stop_ids: list[str]) -> list[str]:
    """The stops among `stop_ids` the explorer found with at least one stop photo, and not scored yet."""
    wanted = set(stop_ids)
    rows = run.query("SELECT e.stop_id FROM explorations e JOIN stops s USING (stop_id) "
                     "LEFT JOIN scores sc USING (stop_id) WHERE e.status = 'found' AND e.stop_photos != '[]' "
                     "AND sc.stop_id IS NULL ORDER BY s.position")
    return [r["stop_id"] for r in rows if r["stop_id"] in wanted]


def score_stop(run: RunStore, scorer: Scorer, stop_id: str) -> None:
    stop = run.stop(stop_id)
    exploration = run.exploration(stop_id)
    photos = exploration["stop_photos"][:2]
    data = [run.media(sha).read_bytes() for sha in photos]
    qs = Q.questions()
    t0 = time.monotonic()
    answers = scorer.answer(qs, Q.state(stop["name"], exploration["evidence"], len(data)), data)
    seconds = time.monotonic() - t0
    values = {}
    for name in SCORE_COLUMNS:
        a = answers.get(name)
        values[name] = None if a is None else round(a["score"] if a["type"] == "score" else a["noul"], 4)
    run.put_score({"stop_id": stop_id, "photos": photos, "scorer": scorer.describe(), **values, "answers": answers,
                   "seconds": round(seconds, 2)})


def score(run: RunStore, scorer: Scorer, stop_ids: list[str],
          on_done: Callable[[str, str], None] | None = None) -> dict:
    todo = scorable(run, stop_ids)
    counts = {"scored": 0, "failed": 0}
    with ThreadPoolExecutor(STOPS_IN_FLIGHT, thread_name_prefix="score") as pool:
        futures = {pool.submit(score_stop, run, scorer, i): i for i in todo}
        for n, future in enumerate(as_completed(futures), 1):
            stop_id = futures[future]
            try:
                future.result()
                counts["scored"] += 1
                status = "scored"
            except (ScorerError, OSError, ValueError, KeyError) as error:
                counts["failed"] += 1
                status = f"failed: {error}"
                logger.error("Scoring %s failed: %s", stop_id, error)
            logger.info("[%d/%d] %s: %s", n, len(todo), stop_id, status)
            if on_done:
                on_done(stop_id, status)
    return counts
