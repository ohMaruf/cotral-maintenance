"""State shared by the explore and shape-check routers."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from cotral_maintenance.runstore import RunStore

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
    def load(cls, settings: Settings, run: RunStore) -> "ExploreState":
        return cls(
            explorations=ExplorationRepository(
                run, PositionIndex.load(settings.truth_csv), OsmLookup(settings.osm_store)),
            shape_check=load_shape_check(settings.shape_check_json),
            verdicts=ShapeVerdictRepository(settings.shape_verdicts_db),
        )


def get_explore_state(request: Request) -> ExploreState:
    return request.app.state.explore


Explore = Annotated[ExploreState, Depends(get_explore_state)]
