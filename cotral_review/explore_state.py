"""State shared by the explore and shape-check routers."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from .config import Settings
from .explore_schemas import ShapeCheck
from .explorations import ExplorationRepository
from .osm_lookup import OsmLookup
from .positions import PositionIndex
from .shapes import ShapeVerdictRepository, load_shape_check


@dataclass
class ExploreState:
    explorations: ExplorationRepository
    shape_check: ShapeCheck | None
    verdicts: ShapeVerdictRepository

    @classmethod
    def load(cls, settings: Settings) -> "ExploreState":
        positions = PositionIndex.load(settings.truth_csv, settings.places_csv)
        return cls(
            explorations=ExplorationRepository(
                settings.agent_runs_dir, positions, OsmLookup(settings.osm_store)),
            shape_check=load_shape_check(settings.shape_check_json),
            verdicts=ShapeVerdictRepository(settings.shape_verdicts_db),
        )


def get_explore_state(request: Request) -> ExploreState:
    return request.app.state.explore


Explore = Annotated[ExploreState, Depends(get_explore_state)]
