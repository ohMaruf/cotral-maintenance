"""Pydantic models of the explore and shape-check endpoints; see docs/explore-api.md."""

from typing import Any, Literal

from pydantic import BaseModel, Field

LatLon = tuple[float, float]
PositionKind = Literal["gtfs", "places", "verified", "estimate"]
ShapeVerdictValue = Literal["on_route", "off_route", "unclear"]
BudgetUnit = Literal["images", "sweeps", "photos"]


class Position(BaseModel):
    kind: PositionKind
    lat: float
    lon: float
    label: str
    error_m: float | None


UNVERSIONED = "unversioned"
StartKind = Literal["osm_ref", "osm_nearest", "places", "gtfs"]


class Harness(BaseModel):
    """The explorer harness that produced a run (`record.harness`); see docs/explore-harness-versions.md."""

    version: str  # "0.6.0"; "unversioned" for runs recorded before versioning
    git_commit: str | None = None
    git_dirty: bool | None = None
    prompt_sha256: str | None = None
    explorer_model: str | None = None
    confirmer_model: str | None = None


class HarnessVersion(BaseModel):
    version: str
    runs: int


class ExplorationSummary(BaseModel):
    run_id: str
    stop_id: str
    name: str
    outcome: str  # the exploration's status: found, not_found, no_imagery, error; unknown ones are passed through
    outcome_reason: str | None
    model: str | None
    turns: int
    seconds: float
    scan_date: str | None
    photos: int
    max_photos: int
    budget_unit: BudgetUnit  # what the budget counts: images (the only unit the pipeline writes)
    budget_used: int
    budget_max: int
    zooms_used: int  # 0 for runs without a zoom budget
    confirms_used: int
    billed_used: int | None = None  # Street View images actually fetched (cache hits are free); None without a search
    stop_photos_used: int = 0  # photos the harness took of the found stop
    harness: Harness
    billed_static: int  # requests actually sent to Google (cache hits excluded)
    billed_tiles: int
    tiles_used: int | None = None  # tiles paid for, of tiles_max; None without a search
    tiles_max: int | None = None
    start_kind: str | None = None  # StartKind of the start position (`record.starts[0].kind`); unknown kinds pass through
    events: int  # tool calls of the run (`Exploration.event_list` also holds the model's thoughts)
    err_gtfs_m: float | None
    err_found_m: float | None
    started_at: str
    finished_at: str


class ExplorationPhoto(BaseModel):
    index: int
    url: str
    pano_id: str
    lat: float
    lon: float
    date: str | None
    heading: float
    fov: float
    pitch: float
    along_m: float
    right_m: float
    toward: str  # aimed, sweep_ahead, sweep_behind, zoom, look_from, stop_photo, ...; unknown values pass through
    opening: bool
    copyright: str | None
    width: int | None = None  # pixels; None for runs that did not record them
    height: int | None = None
    shot: int = 0  # the sweep a sweep photo belongs to; 0 for zooms, confirmations and old runs
    parent: int | None = None  # the photo index a zoom was taken from
    source: Literal["static", "tiles"] = "static"  # the Street View Static API, or Map Tiles
    tiles: int = 0  # tiles paid for this view
    billed: bool | None = None  # fetched (billed) from Google rather than from the cache; None when not recorded


class RawExchange(BaseModel):
    request: Any
    response: Any


class ExplorationEvent(BaseModel):
    seq: int
    kind: str  # thought, a tool name, tool_error; unknown kinds are rendered generically
    summary: str
    error: str | None
    photos: list[int]
    photos_used: int
    budget_used: int  # in the run's budget_unit, this event included
    raw: RawExchange


class ExplorationCandidate(BaseModel):
    index: int
    kind: str
    lat: float
    lon: float
    along_m: float
    right_m: float
    status: str
    evidence: str | None
    basis: str
    checklist: dict[str, str]
    confirmer_note: str = ""  # what the independent confirmer said the object is; "" when none
    confirm_photo: int | None = None  # ExplorationPhoto.index of the confirmation photo


class AlongLimits(BaseModel):
    along_from: float
    along_to: float


class OsmFeature(BaseModel):
    """A stop-like OSM object near a stop (the local OSM store); `kind` may be a value not known yet."""

    id: str
    kind: str
    lat: float
    lon: float
    ref: str
    name: str
    operator: str


class Exploration(ExplorationSummary):
    positions: list[Position]
    osm_features: list[OsmFeature]  # within 200 m of the GTFS position
    limits: AlongLimits
    path: list[LatLon]
    candidates: list[ExplorationCandidate]
    report: str | None
    photo_list: list[ExplorationPhoto]
    event_list: list[ExplorationEvent]
    transcript: list[Any]  # `transcripts.lines`, parsed: the explorer's conversation, raw
    stop_photos: list[int] = []  # ExplorationPhoto.index of the harness's photos of the found stop; [] if not found
    close_up: int | None = None  # ExplorationPhoto.index of the confirming zoom of a found run


class ShapeArrow(BaseModel):
    lat: float
    lon: float
    bearing: float


class ShapeRoute(BaseModel):
    shape: str
    trips: int
    points: list[LatLon]
    arrows: list[ShapeArrow]
    truth_m: float
    truth_side: Literal["right", "left"]
    gtfs_m: float
    prev: list[str]
    next: list[str]
    matched: list[list[LatLon]] | None
    truth_path_m: float | None
    truth_path_side: Literal["right", "left"] | None


class Neighbour(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class ShapeStop(BaseModel):
    id: str
    name: str
    offset_m: float
    flags: list[str] = Field(min_length=1)  # ShapeFlag; unknown flags are passed through
    has_sign: str
    comments: str
    gtfs: LatLon
    truth: LatLon
    places: LatLon | None
    osm_features: list[OsmFeature]
    routes: list[ShapeRoute]
    neighbours: list[Neighbour]


class ShapeCheck(BaseModel):
    generated_at: str
    min_offset_m: float
    stops: list[ShapeStop]


class ShapeVerdict(BaseModel):
    stop_id: str
    verdict: ShapeVerdictValue | None
    note: str
    rater: str | None
    updated_at: str


class ShapeVerdictIn(BaseModel):
    verdict: ShapeVerdictValue | None
    note: str = Field(max_length=2000)
    rater: str | None = Field(default=None, max_length=80)
