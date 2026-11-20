import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..runstore import SCORE_COLUMNS, RunStore
from ..scorer import questions as Q
from ..scorer.backends import LlamaCppReadout, LlamaCppSystemOne, Scorer, ScorerError, SystemOne
from ..scorer.imajev import Calibration, Engine
from ..servers import fetch
from ..settings import ModelSpec, Paths

logger = logging.getLogger(__name__)

STOPS_IN_FLIGHT = 2


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
    if spec.dialect == "llamacpp-systemone":
        return LlamaCppSystemOne(spec.server.url, describe)
    return SystemOne(spec.server.url, describe)


def scorable(run: RunStore, stop_ids: list[str]) -> list[str]:
    wanted = set(stop_ids)
    rows = run.query("SELECT e.stop_id FROM explorations e JOIN stops s USING (stop_id) "
                     "LEFT JOIN scores sc USING (stop_id) WHERE e.status = 'found' AND e.stop_photos != '[]' "
                     "AND sc.stop_id IS NULL ORDER BY s.position")
    return [r["stop_id"] for r in rows if r["stop_id"] in wanted]


PHOTO_COLUMNS = "media, toward, pano_id, heading, fov, lat, lon"


def score_stop(run: RunStore, scorer: Scorer, stop_id: str) -> None:
    stop = run.stop(stop_id)
    exploration = run.exploration(stop_id)
    lat, lon = exploration["lat"], exploration["lon"]
    taken = {r["media"]: dict(r) for r in run.query(f"SELECT {PHOTO_COLUMNS} FROM photos WHERE stop_id = ? ORDER BY idx",
                                                    (stop_id,))}
    stop_photos = [taken[sha] for sha in exploration["stop_photos"][:2]]
    wide = [p for p in taken.values() if p["toward"] != "stop_photo"]
    t0 = time.monotonic()
    answers = {}
    for qs, photos in ((Q.questions(lamp=False), stop_photos),
                       (Q.questions(others=False), Q.lamp_photos(stop_photos, wide, lat, lon))):
        texts = Q.describe_photos(photos, lat, lon)
        data = [run.media(ph["media"]).read_bytes() for ph in photos]
        for name, a in scorer.answer(qs, Q.state(stop["name"], exploration["evidence"], texts), data).items():
            answers[name] = {**a, "photos": [ph["media"] for ph in photos], "photo_texts": texts}
    seconds = time.monotonic() - t0
    values = Q.values(answers)
    values = {c: values.get(c) for c in SCORE_COLUMNS}
    run.put_score({"stop_id": stop_id, "photos": exploration["stop_photos"][:2], "scorer": scorer.describe(), **values,
                   "answers": answers, "seconds": round(seconds, 2)})


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
