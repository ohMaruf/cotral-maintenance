// Hand-written mirror of docs/review-api.md. Change the contract first.

export type CategoryKind = 'level' | 'probability';

export interface Category {
  key: string;
  label: string;
  kind: CategoryKind;
  description: string;
}

export interface Model {
  key: string;
  label: string;
  description: string;
}

export interface Catalog {
  categories: Category[];
  models: Model[];
}

export interface Photo {
  view: string;
  description: string;
  url: string;
  distance_m: number | null;
  heading: number | null;
  /** Must be displayed with the photo (Street View terms). */
  copyright: string | null;
}

export interface StopSummary {
  stop_id: string;
  name: string;
  lat: number;
  lon: number;
  /** "2025-06" */
  imagery_date: string | null;
  photos: Photo[];
}

/** model key -> category key -> value; a model or category may be missing. */
export type ScoreMap = Record<string, Record<string, number>>;
/** model key -> category key -> one-sentence reason. */
export type EvidenceMap = Record<string, Record<string, string>>;

export interface StopDetail extends StopSummary {
  scores: ScoreMap;
  evidence: EvidenceMap;
}

export interface Progress {
  judged: number;
  skipped: number;
  remaining: number;
}

/** A profile of the run (meta `profile:<key>`). */
export interface RunProfile {
  key: string;
  name: string;
  description: string;
}

/** What the run holds and spent; see docs/review-api.md. */
export interface RunInfo {
  name: string;
  stops: number;
  /** Stops by start source: osm, places, gtfs. */
  ingested: Record<string, number>;
  /** Stops by exploration status: found, not_found, no_imagery, error. */
  explored: Record<string, number>;
  scored: number;
  /** Billed Google requests by API: static, tiles, places. */
  billed: Record<string, number>;
  profiles: RunProfile[];
}

/** One row of the run's results table; the scores are null until the stop is scored. */
export interface ResultRow {
  /** Among the stops that need no review; null for the others. */
  rank: number | null;
  stop_id: string;
  name: string;
  needs_review: boolean;
  /** Empty when none. */
  review_reason: string;
  /** 0 (nothing to do) .. 1: the mean of the needs; what ranked rows are ordered by. */
  priority: number | null;
  shelter: number | null;
  seating: number | null;
  waiting_area: number | null;
  accessibility: number | null;
  /** Probability that a street lamp stands at the stop. */
  lighting: number | null;
  stop_visible: number | null;
  /** The exploration's status; null: not explored yet. */
  status: string | null;
  explore_reason: string | null;
  /** What identified the stop: cotral_sign, shelter_only, ... */
  evidence: string | null;
  plate_text: string | null;
  lat: number | null;
  lon: number | null;
  found_from_gtfs_m: number | null;
  position_basis: string | null;
  scan_date: string | null;
  start_source: string | null;
  start_lat: number | null;
  start_lon: number | null;
  gtfs_lat: number;
  gtfs_lon: number;
  explorer_model: string | null;
  scorer_model: string | null;
  /** URLs of the stop photos (one or two). */
  photos: string[];
}

export interface Judgment {
  id: string;
  created_at: string;
  left: string;
  right: string;
  winner: string | null;
  loser: string | null;
  rater: string | null;
  decision_ms: number | null;
}

export interface Pair {
  left: StopSummary;
  right: StopSummary;
}

export interface NextPairResponse {
  pair: Pair | null;
  progress: Progress;
}

export interface JudgmentRequest {
  left: string;
  right: string;
  winner: string | null;
  rater?: string | null;
  decision_ms?: number | null;
}

export interface JudgmentResponse {
  judgment: Judgment;
  left: StopDetail;
  right: StopDetail;
  progress: Progress;
}

// ---------------------------------------------------------------------------
// Explore and Shapes: hand-written mirror of docs/explore-api.md.

export type LatLon = [number, number];

export type PositionKind = 'gtfs' | 'places' | 'verified' | 'estimate';

export interface Position {
  kind: PositionKind;
  lat: number;
  lon: number;
  label: string;
  /** Distance to the verified position; null without one (and for "verified"). */
  error_m: number | null;
}

/** The exploration's status in the run store. */
export type Outcome = 'found' | 'not_found' | 'no_imagery' | 'error';

export type BudgetUnit = 'images' | 'sweeps' | 'photos';

export type StartKind = 'osm_ref' | 'osm_nearest' | 'places' | 'gtfs';

/** The explorer harness of a run; see docs/explore-harness-versions.md. */
export interface Harness {
  /** E.g. "0.6.0"; "unversioned" for runs recorded before versioning. */
  version: string;
  git_commit: string | null;
  git_dirty: boolean | null;
  prompt_sha256: string | null;
  explorer_model: string | null;
  confirmer_model: string | null;
}

/** A harness version present among the runs, with its number of runs. */
export interface HarnessVersion {
  version: string;
  runs: number;
}

export interface ExplorationSummary {
  /** The stop id: one exploration per stop of the run. */
  run_id: string;
  stop_id: string;
  name: string;
  /** Unknown outcomes are passed through. */
  outcome: Outcome | (string & {});
  /** E.g. "the explorer ended: outcome". */
  outcome_reason: string | null;
  model: string | null;
  /** Model turns of the exploration. */
  turns: number;
  /** Wall time of the exploration. */
  seconds: number;
  /** The found stop's panorama date, "2025-06". */
  scan_date: string | null;
  photos: number;
  /** Oldest runs: the photo budget (14); sweep runs: the sweep cap (12); images runs: 14. Prefer the budget_* fields. */
  max_photos: number;
  /** What the budget counts: "images" (billed Street View images), "sweeps" (two photos each) or "photos" (oldest runs). */
  budget_unit: BudgetUnit;
  budget_used: number;
  budget_max: number;
  zooms_used: number;
  confirms_used: number;
  /** Street View images actually fetched from Google (cache hits are free); null unless an images run. */
  billed_used: number | null;
  /** Photos the harness took of the found stop; 0 for runs before the images format. */
  stop_photos_used: number;
  /** The harness that produced the run; version "unversioned" when the record has none. */
  harness: Harness;
  /** Requests actually sent to Google (cache hits excluded). */
  billed_static: number;
  billed_tiles: number;
  /** Map Tiles paid for, of the per-stop tile budget; null for runs without one. */
  tiles_used: number | null;
  tiles_max: number | null;
  /** Kind of the start position: "osm_ref", "osm_nearest", "places", "gtfs"; unknown kinds pass through. */
  start_kind: StartKind | (string & {}) | null;
  events: number;
  /** GTFS position -> verified. */
  err_gtfs_m: number | null;
  /** The submitted position -> verified; null if not found or no truth. */
  err_found_m: number | null;
  started_at: string;
  finished_at: string;
}

export interface ExplorationPhoto {
  /** 1-based, order taken. */
  index: number;
  url: string;
  pano_id: string;
  lat: number;
  lon: number;
  date: string | null;
  heading: number;
  fov: number;
  pitch: number;
  /** Along the bus's path from the start (+ ahead in the direction of travel). */
  along_m: number;
  /** From the path's centre line (+ right of travel). */
  right_m: number;
  /**
   * Oldest runs: "forward", "backward", "across", "target", "confirm". Sweep runs: "sweep_ahead",
   * "sweep_behind", "zoom", "confirm". Images runs: "sweep_ahead", "sweep_behind", "zoom",
   * "stop_photo" (taken by the harness of the found stop). Harness 0.5+: "aimed" (the opening photo aimed at an
   * OSM start); 0.6+: "look_from" (a narrow view of a candidate from another panorama).
   */
  toward: string;
  /** Pixels; null for old runs. */
  width: number | null;
  height: number | null;
  /** The sweep a sweep photo belongs to (sweep runs: both photos share it; images runs: one photo); 0 otherwise. */
  shot: number;
  /** For a zoom: the index of the photo it was taken from. */
  parent: number | null;
  /** One of the two photos the harness takes before the model's first turn. */
  opening: boolean;
  /** Must be displayed with the photo when present. */
  copyright: string | null;
  /** Fetched (billed) from Google rather than the cache; null when the record does not say. */
  billed: boolean | null;
  /** The Street View Static API, or Map Tiles (zoom and look_from views of harness 0.6+). */
  source: 'static' | 'tiles';
  /** Tiles paid for this view; 0 for Static photos. */
  tiles: number;
}

/** "thought" and "tool_error" are special; the others are tool names. Unknown kinds render generically. */
export type EventKind =
  | 'thought'
  | 'begin'
  | 'look'
  | 'sweep'
  | 'zoom'
  | 'look_from'
  | 'confirm'
  | 'mark_candidate'
  | 'mark_clear'
  | 'mark_hidden'
  | 'answer_checklist'
  | 'find_other_scans'
  | 'show_map'
  | 'note'
  | 'submit_found'
  | 'tool_error'
  | (string & {});

export interface ExplorationEvent {
  /** 1-based, the exact order of the run. */
  seq: number;
  kind: EventKind;
  /** First line of the tool's result (or "ERROR: ..."), or the model's text. */
  summary: string;
  /** The tool's error message when the call was refused. */
  error: string | null;
  /** Indexes of the photos taken at this event (begin: two). */
  photos: number[];
  /** Photos taken so far, this event included; drives the map's fading of later photos. */
  photos_used: number;
  /** Budget spent so far in the run's `budget_unit` (images, sweeps or photos), this event included. */
  budget_used: number;
  /** Tool: request = arguments, response = full result text. Thought: request null, response the text. */
  raw: { request: unknown; response: unknown };
}

export interface ExplorationCandidate {
  index: number;
  /** "sign", "shelter", ... */
  kind: string;
  lat: number;
  lon: number;
  along_m: number;
  right_m: number;
  /** "spotted", "awaiting_checklist", "confirmed", "rejected". */
  status: string;
  /** When confirmed: "cotral_sign", "other_stop_sign", "shelter_only", "road_marking". */
  evidence: string | null;
  /** "single_ray_sidewalk", "triangulated". */
  basis: string;
  /** Feature -> "yes" | "no" | "unsure"; empty before the checklist. */
  checklist: Record<string, string>;
  /** What the independent confirmer said the object is; empty for old runs and unconfirmed candidates. */
  confirmer_note: string;
  /** Index of the confirmation photo. */
  confirm_photo: number | null;
}

export interface Exploration extends ExplorationSummary {
  positions: Position[];
  /** Every OSM stop-like object within 200 m of the GTFS position. */
  osm_features: OsmFeature[];
  /** The searched stretch, metres along the path. */
  limits: { along_from: number; along_to: number };
  /** The bus's path (snapped to roads), in travel order. */
  path: LatLon[];
  candidates: ExplorationCandidate[];
  /** The model's closing words, when its last turn made no tool call. */
  report: string | null;
  photo_list: ExplorationPhoto[];
  event_list: ExplorationEvent[];
  /** The explorer's conversation as stored in the run, raw. */
  transcript: unknown[];
  /** Indexes of the harness's photos of the found stop (images runs); [] otherwise. They feed the next stage. */
  stop_photos: number[];
  /** Index of the confirming zoom of a found images run. */
  close_up: number | null;
}

export interface ShapeArrow {
  lat: number;
  lon: number;
  bearing: number;
}

export interface ShapeRoute {
  shape: string;
  trips: number;
  points: LatLon[];
  arrows: ShapeArrow[];
  truth_m: number;
  truth_side: 'right' | 'left';
  gtfs_m: number;
  prev: string[];
  next: string[];
  /** The shape snapped onto OSM roads, in travel order; several pieces where no route connects; null if not snapped. */
  matched: LatLon[][] | null;
  /** Verified position -> snapped path. */
  truth_path_m: number | null;
  truth_path_side: 'right' | 'left' | null;
}

/** Why a stop is in the shape check. Unknown flags are shown as-is. */
export type ShapeFlag = 'moved' | 'left_of_path' | 'far_from_path' | 'on_detour';

export type OsmFeatureKind = 'bus_stop' | 'platform' | 'stop_position' | 'shelter' | 'bus_station';

/** A stop-like OSM object from the local OSM store; a hint, never matched to a stop by id. */
export interface OsmFeature {
  /** "n123" node, "w456" way (shown at its centre). */
  id: string;
  kind: OsmFeatureKind | (string & {});
  lat: number;
  lon: number;
  /** May be empty. */
  ref: string;
  name: string;
  operator: string;
}

export interface ShapeNeighbour {
  id: string;
  name: string;
  lat: number;
  lon: number;
}

export interface ShapeStop {
  id: string;
  name: string;
  offset_m: number;
  /** At least one. */
  flags: (ShapeFlag | (string & {}))[];
  /** "yes" | "no" | "" */
  has_sign: string;
  comments: string;
  gtfs: LatLon;
  truth: LatLon;
  places: LatLon | null;
  osm_features: OsmFeature[];
  routes: ShapeRoute[];
  neighbours: ShapeNeighbour[];
}

export interface ShapeCheck {
  generated_at: string;
  min_offset_m: number;
  stops: ShapeStop[];
}

export type ShapeVerdictValue = 'on_route' | 'off_route' | 'unclear';

export interface ShapeVerdict {
  stop_id: string;
  /** null: only a note so far. */
  verdict: ShapeVerdictValue | null;
  note: string;
  rater: string | null;
  updated_at: string;
}

export interface ShapeVerdictRequest {
  verdict: ShapeVerdictValue | null;
  note: string;
  rater?: string | null;
}
