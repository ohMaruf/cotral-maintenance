"""The run's final table: one row per stop, from its GTFS record to its maintenance scores.

Written to <run>/results.csv. Stops are ranked by `condition`, worst first (0 bad .. 1 good: the mean
of the conditions that apply; a missing shelter or bench has none and is listed in `missing`) among
those scored with the stop visible; every other stop is listed after them with `needs_review` set and the reason, so a
person can check what the pipeline could not.
"""

import csv
import io
import json
import math

from ..fileutils import write_atomic
from ..geo import distance_m
from ..runstore import SCORE_COLUMNS, RunStore, media_path
from ..scorer.questions import missing

VISIBLE_MIN = 0.5
COLUMNS = ("rank", "stop_id", "name", "needs_review", "review_reason", *SCORE_COLUMNS, "missing", "status", "evidence",
           "plate_text", "lat", "lon", "found_from_gtfs_m", "position_basis", "scan_date", "start_source",
           "start_lat", "start_lon", "gtfs_lat", "gtfs_lon", "stop_photos", "explore_reason", "explorer_model",
           "scorer_model")


def rows(run: RunStore) -> list[dict]:
    out = []
    for r in run.query("""
        SELECT s.stop_id, s.name, s.gtfs_lat, s.gtfs_lon, st.source AS start_source, st.lat AS start_lat,
               st.lon AS start_lon, e.status, e.reason AS explore_reason, e.lat, e.lon, e.evidence, e.plate_text,
               e.position_basis, e.scan_date, e.stop_photos, e.explorer, sc.scorer,
               """ + ", ".join(f"sc.{c}" for c in SCORE_COLUMNS) + """
        FROM stops s LEFT JOIN starts st USING (stop_id) LEFT JOIN explorations e USING (stop_id)
        LEFT JOIN scores sc USING (stop_id) ORDER BY s.position"""):
        d = dict(r)
        photos = json.loads(d.pop("stop_photos") or "[]")
        d["stop_photos"] = ";".join(str(media_path(run.root, p).relative_to(run.root)) for p in photos)
        d["explorer_model"] = json.loads(d.pop("explorer"))["model"] if d.get("explorer") else None
        d["scorer_model"] = json.loads(d.pop("scorer"))["model"] if d.get("scorer") else None
        if d["lat"] is not None:
            d["found_from_gtfs_m"] = round(distance_m(d["gtfs_lat"], d["gtfs_lon"], d["lat"], d["lon"]), 1)
        d["missing"] = ";".join(missing(d)) if d["condition"] is not None else None
        d["needs_review"], d["review_reason"] = _review(d)
        out.append(d)
    ranked = sorted((d for d in out if not d["needs_review"]), key=lambda d: d["condition"])
    for i, d in enumerate(ranked, 1):
        d["rank"] = i
    return ranked + [d for d in out if d["needs_review"]]


def _review(d: dict) -> tuple[bool, str]:
    if d["status"] is None:
        return True, "not explored yet"
    if d["status"] != "found":
        text = {"not_found": "the explorer did not find the stop", "no_imagery": "no recent Street View",
                "error": "the search failed"}.get(d["status"], d["status"])
        reason = (d.get("explore_reason") or "").removeprefix("the explorer ended: ")
        return True, f"{text} ({reason})" if reason and d["status"] != "no_imagery" else text
    if d["condition"] is None:
        return True, "not scored yet"
    if d["stop_visible"] is not None and d["stop_visible"] < VISIBLE_MIN:
        return True, "the scorer does not see the stop in its photos"
    return False, ""


def write_results(run: RunStore) -> tuple[str, int]:
    data = rows(run)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for d in data:
        writer.writerow({k: ("" if v is None or (isinstance(v, float) and math.isnan(v)) else v)
                         for k, v in d.items()})
    path = run.root / "results.csv"
    write_atomic(path, buffer.getvalue().encode("utf-8"))
    return str(path), len(data)
