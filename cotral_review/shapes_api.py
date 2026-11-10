"""Routes of the shapes page: the shape check and its verdicts."""

import csv
import io

from fastapi import APIRouter, HTTPException, Response

from cotral_maintenance.geo import distance_m

from . import explore_schemas as schemas
from .explore_state import Explore, ExploreState

router = APIRouter(prefix="/api/shape-check")

NOT_GENERATED = "no shape check yet: run experiments/explore/shape_check.py"
CSV_COLUMNS = ("stop_id", "offset_m", "verdict", "note", "closest_shape_m", "has_osm", "rater", "updated_at", "flags")
OSM_NEAR_M = 30.0


def require_shape_check(state: ExploreState) -> schemas.ShapeCheck:
    if state.shape_check is None:
        raise HTTPException(404, NOT_GENERATED)
    return state.shape_check


def has_osm_near_truth(stop: schemas.ShapeStop) -> bool:
    """True if an OSM stop-like object is within OSM_NEAR_M of the verified position."""
    return any(distance_m(*stop.truth, f.lat, f.lon) <= OSM_NEAR_M for f in stop.osm_features)


def verdicts_csv(check: schemas.ShapeCheck, verdicts: list[schemas.ShapeVerdict]) -> str:
    """One row per shape-check stop, in order; verdict columns empty when not judged."""
    by_stop = {v.stop_id: v for v in verdicts}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for stop in check.stops:
        verdict = by_stop.get(stop.id)
        writer.writerow({
            "stop_id": stop.id, "offset_m": stop.offset_m,
            "verdict": verdict.verdict or "" if verdict else "", "note": verdict.note if verdict else "",
            "closest_shape_m": min((r.truth_m for r in stop.routes), default=""),
            "has_osm": int(has_osm_near_truth(stop)),
            "rater": verdict.rater or "" if verdict else "", "updated_at": verdict.updated_at if verdict else "",
            "flags": ";".join(stop.flags),
        })
    return out.getvalue()


@router.get("")
def get_shape_check(state: Explore) -> schemas.ShapeCheck:
    return require_shape_check(state)


@router.get("/verdicts")
def list_verdicts(state: Explore) -> list[schemas.ShapeVerdict]:
    return state.verdicts.list()


@router.get("/verdicts.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def export_verdicts(state: Explore) -> Response:
    body = verdicts_csv(require_shape_check(state), state.verdicts.list())
    return Response(
        body, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=shape_check_verdicts.csv"},
    )


@router.put("/verdicts/{stop_id}")
def put_verdict(stop_id: str, body: schemas.ShapeVerdictIn, state: Explore) -> schemas.ShapeVerdict:
    if all(stop.id != stop_id for stop in require_shape_check(state).stops):
        raise HTTPException(404, f"unknown stop {stop_id}")
    return state.verdicts.put(stop_id, body.verdict, body.note, body.rater)
