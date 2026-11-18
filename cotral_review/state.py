"""State of the app shared by the routers: the run, the scored stops and the judgments."""

import random
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from cotral_maintenance.runstore import RunStore

from .config import Settings
from .judgments import JudgmentRepository
from .stops import StopIndex


@dataclass
class AppState:
    settings: Settings
    run: RunStore
    stops: StopIndex
    judgments: JudgmentRepository
    rng: random.Random


def get_state(request: Request) -> AppState:
    return request.app.state.review


State = Annotated[AppState, Depends(get_state)]
