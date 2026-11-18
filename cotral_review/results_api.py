"""Routes of the results page: the run's summary and its final table."""

import json

from fastapi import APIRouter

from cotral_maintenance.pipeline.export import rows
from cotral_maintenance.runstore import RunStore

from . import schemas
from .explorations import photo_url
from .state import State

router = APIRouter(prefix="/api")

PROFILE_PREFIX = "profile:"


def profiles_of(run: RunStore) -> list[schemas.Profile]:
    found = []
    for r in run.query("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key", (f"{PROFILE_PREFIX}%",)):
        value = json.loads(r["value"])
        found.append(schemas.Profile(
            key=r["key"].removeprefix(PROFILE_PREFIX), name=value.get("name", ""),
            description=value.get("description", "")))
    return sorted(found, key=lambda p: (len(p.key), p.key))


@router.get("/run")
def get_run(state: State) -> schemas.RunInfo:
    run = state.run
    return schemas.RunInfo(name=run.root.name, **run.summary(), profiles=profiles_of(run))


@router.get("/results")
def get_results(state: State) -> list[schemas.ResultRow]:
    """Every stop of the run: ranked ones first, then those a person must look at."""
    run = state.run
    photos = {r["stop_id"]: json.loads(r["stop_photos"])
              for r in run.query("SELECT stop_id, stop_photos FROM explorations")}
    return [
        schemas.ResultRow(**d, photos=[photo_url(d["stop_id"], f"{sha}.jpg") for sha in photos.get(d["stop_id"], [])])
        for d in rows(run)
    ]
