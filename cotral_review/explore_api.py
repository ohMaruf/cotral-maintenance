"""Routes of the explore page: exploration runs and their photos."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import explore_schemas as schemas
from .explore_state import Explore
from .explorations import UnknownLayout, UnknownRun

router = APIRouter(prefix="/api/explorations")


@router.get("")
def list_explorations(state: Explore, harness: str | None = None) -> list[schemas.ExplorationSummary]:
    """All runs by id; `?harness=0.6.0` keeps the runs of that harness version ("unversioned" for the old ones)."""
    return state.explorations.list(harness)


@router.get("/harness-versions")
def list_harness_versions(state: Explore) -> list[schemas.HarnessVersion]:
    """The harness versions present, newest first ("unversioned" last), with their run counts."""
    return state.explorations.harness_versions()


@router.get("/{run_id}")
def get_exploration(run_id: str, state: Explore) -> schemas.Exploration:
    try:
        return state.explorations.get(run_id)
    except UnknownRun as error:
        raise HTTPException(404, f"unknown exploration {run_id}") from error
    except UnknownLayout as error:
        raise HTTPException(422, str(error)) from error


@router.get("/{run_id}/photos/{file}", response_class=FileResponse, responses={200: {"content": {"image/jpeg": {}}}})
def get_exploration_photo(run_id: str, file: str, state: Explore) -> FileResponse:
    try:
        path = state.explorations.photo_path(run_id, file)
    except (UnknownRun, UnknownLayout) as error:
        raise HTTPException(404, f"unknown photo {file}") from error
    if path is None:
        raise HTTPException(404, f"unknown photo {file}")
    # Photos never change once downloaded.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
