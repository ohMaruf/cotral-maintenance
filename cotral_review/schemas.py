"""Pydantic models of the API; see docs/review-api.md."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Category(BaseModel):
    key: str
    label: str
    kind: Literal["level", "probability"]
    description: str


class Model(BaseModel):
    key: str
    label: str
    description: str


class Catalog(BaseModel):
    categories: list[Category]
    models: list[Model]


class Photo(BaseModel):
    view: str
    description: str
    url: str
    distance_m: float | None
    heading: float | None
    copyright: str | None


class StopSummary(BaseModel):
    stop_id: str
    name: str
    lat: float
    lon: float
    imagery_date: str | None
    photos: list[Photo]


class StopDetail(StopSummary):
    scores: dict[str, dict[str, float]]
    evidence: dict[str, dict[str, str]]


class Progress(BaseModel):
    judged: int
    skipped: int
    remaining: int


class Pair(BaseModel):
    left: StopSummary
    right: StopSummary


class NextPair(BaseModel):
    pair: Pair | None
    progress: Progress


class Judgment(BaseModel):
    id: str
    created_at: str
    left: str
    right: str
    winner: str | None
    loser: str | None
    rater: str | None
    decision_ms: int | None


class JudgmentIn(BaseModel):
    left: str
    right: str
    winner: str | None
    rater: str | None = Field(default=None, max_length=80)
    decision_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_pair(self) -> "JudgmentIn":
        if self.left == self.right:
            raise ValueError("a stop cannot be compared with itself")
        if self.winner not in (self.left, self.right, None):
            raise ValueError("winner must be one of the two stops, or null to skip")
        return self


class JudgmentCreated(BaseModel):
    judgment: Judgment
    left: StopDetail
    right: StopDetail
    progress: Progress


class Health(BaseModel):
    status: Literal["ok"] = "ok"
