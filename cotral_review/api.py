"""The FastAPI app: routers over a stop index and a judgment repository."""

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse

from . import schemas
from .catalog import CATEGORIES, models_for, photo_description
from .config import Settings
from .judgments import DuplicatePair, JudgmentRepository
from .judgments import Judgment as JudgmentRow
from .pairs import next_pair, remaining
from .stops import Stop, StopIndex, load_index

logger = logging.getLogger(__name__)

NO_FRONTEND = (
    "<h1>Cotral review API</h1><p>The frontend is not built. Run <code>npm run build</code> in "
    "<code>review-ui/</code>, or start the Vite dev server (<code>npm run dev</code>, port 5173). "
    "API docs: <a href='/docs'>/docs</a>.</p>"
)


@dataclass
class AppState:
    settings: Settings
    stops: StopIndex
    judgments: JudgmentRepository
    rng: random.Random


def get_state(request: Request) -> AppState:
    return request.app.state.review


State = Annotated[AppState, Depends(get_state)]


def summary_of(stop: Stop) -> schemas.StopSummary:
    return schemas.StopSummary(
        stop_id=stop.stop_id, name=stop.name, lat=stop.lat, lon=stop.lon, imagery_date=stop.imagery_date,
        photos=[
            schemas.Photo(
                view=p.view, description=photo_description(p.view),
                url=f"/api/stops/{stop.stop_id}/photos/{p.file}",
                distance_m=p.distance_m, heading=p.heading, copyright=p.copyright,
            )
            for p in stop.photos
        ],
    )


def detail_of(stop: Stop) -> schemas.StopDetail:
    return schemas.StopDetail(**summary_of(stop).model_dump(), scores=stop.scores, evidence=stop.evidence)


def judgment_of(row: JudgmentRow) -> schemas.Judgment:
    return schemas.Judgment(**vars(row))


def progress_of(state: AppState) -> schemas.Progress:
    judged, skipped = state.judgments.counts()
    return schemas.Progress(
        judged=judged, skipped=skipped, remaining=remaining(state.stops.ids(), state.judgments.pairs()),
    )


def require_stop(state: AppState, stop_id: str) -> Stop:
    stop = state.stops.get(stop_id)
    if stop is None:
        raise HTTPException(404, f"unknown stop {stop_id}")
    return stop


api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> schemas.Health:
    return schemas.Health()


@api.get("/catalog")
def catalog(state: State) -> schemas.Catalog:
    return schemas.Catalog(
        categories=[schemas.Category(**vars(c)) for c in CATEGORIES],
        models=[schemas.Model(**vars(m)) for m in models_for(state.stops.models)],
    )


@api.get("/stops")
def list_stops(state: State) -> list[schemas.StopDetail]:
    return [detail_of(s) for s in state.stops.all()]


@api.get("/stops/{stop_id}")
def get_stop(stop_id: str, state: State) -> schemas.StopDetail:
    return detail_of(require_stop(state, stop_id))


@api.get("/stops/{stop_id}/photos/{file}", response_class=FileResponse, responses={200: {"content": {"image/jpeg": {}}}})
def get_photo(stop_id: str, file: str, state: State) -> FileResponse:
    stop = require_stop(state, stop_id)
    if stop.photo(file) is None:
        raise HTTPException(404, f"unknown photo {file}")
    root = state.settings.images_dir.resolve()
    path = (root / stop_id / file).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, f"unknown photo {file}")
    # Photos never change once downloaded.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@api.get("/pairs/next")
def get_next_pair(state: State) -> schemas.NextPair:
    pair = next_pair(state.stops.ids(), state.judgments.pairs(), state.rng)
    progress = progress_of(state)
    if pair is None:
        return schemas.NextPair(pair=None, progress=progress)
    # Summaries only: scores are shown after the judgment, never before.
    left, right = (summary_of(state.stops.get(i)) for i in pair)
    return schemas.NextPair(pair=schemas.Pair(left=left, right=right), progress=progress)


@api.post("/judgments", status_code=201)
def create_judgment(body: schemas.JudgmentIn, state: State) -> schemas.JudgmentCreated:
    left, right = require_stop(state, body.left), require_stop(state, body.right)
    rater = (body.rater or "").strip() or None
    try:
        row = state.judgments.add(body.left, body.right, body.winner, rater, body.decision_ms)
    except DuplicatePair as error:
        raise HTTPException(409, str(error)) from error
    logger.info("judgment %s: %s vs %s -> %s", row.id, row.left, row.right, row.winner)
    return schemas.JudgmentCreated(
        judgment=judgment_of(row), left=detail_of(left), right=detail_of(right), progress=progress_of(state),
    )


@api.get("/judgments")
def list_judgments(state: State) -> list[schemas.Judgment]:
    return [judgment_of(row) for row in state.judgments.list()]


@api.get("/judgments/progress")
def get_progress(state: State) -> schemas.Progress:
    return progress_of(state)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend at /, falling back to index.html for client-side routes."""

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "not found")
        root, index = dist.resolve(), dist.resolve() / "index.html"
        if not index.is_file():
            return HTMLResponse(NO_FRONTEND)
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app; loads the stops once."""
    settings = settings or Settings.from_env()
    app = FastAPI(title="Cotral review", docs_url="/docs", openapi_url="/api/openapi.json")
    app.state.review = AppState(
        settings=settings,
        stops=load_index(settings.images_dir, settings.score_sources, settings.gemma_raw_dir),
        judgments=JudgmentRepository(settings.database),
        rng=random.Random(settings.seed),
    )
    app.include_router(api)
    mount_frontend(app, settings.frontend_dist)
    return app
