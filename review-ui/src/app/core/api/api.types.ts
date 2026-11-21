export type CategoryKind = 'condition' | 'probability';

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

  copyright: string | null;
}

export interface StopSummary {
  stop_id: string;
  name: string;
  lat: number;
  lon: number;

  imagery_date: string | null;
  photos: Photo[];
}

export type ScoreMap = Record<string, Record<string, number>>;

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

export interface RunProfile {
  key: string;
  name: string;
  description: string;
}

export interface RunInfo {
  name: string;
  stops: number;

  ingested: Record<string, number>;

  explored: Record<string, number>;
  scored: number;

  billed: Record<string, number>;
  profiles: RunProfile[];
}

export interface ResultRow {
  rank: number | null;
  stop_id: string;
  name: string;
  needs_review: boolean;

  review_reason: string;

  condition: number | null;

  has_shelter: number | null;

  shelter: number | null;

  has_seating: number | null;

  seating: number | null;

  waiting_area: number | null;

  accessibility: number | null;

  has_lamp: number | null;
  stop_visible: number | null;

  missing: string[] | null;

  status: string | null;
  explore_reason: string | null;

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

export type LatLon = [number, number];

export type PositionKind = 'gtfs' | 'places' | 'verified' | 'estimate';

export interface Position {
  kind: PositionKind;
  lat: number;
  lon: number;
  label: string;

  error_m: number | null;
}

export type Outcome = 'found' | 'not_found' | 'no_imagery' | 'error';

export type BudgetUnit = 'images' | 'sweeps' | 'photos';

export type StartKind = 'osm_ref' | 'osm_nearest' | 'places' | 'gtfs';

export interface Harness {
  version: string;
  git_commit: string | null;
  git_dirty: boolean | null;
  prompt_sha256: string | null;
  explorer_model: string | null;
  confirmer_model: string | null;
}

export interface HarnessVersion {
  version: string;
  runs: number;
}

export interface ExplorationSummary {
  run_id: string;
  stop_id: string;
  name: string;

  outcome: Outcome | (string & {});

  outcome_reason: string | null;
  model: string | null;

  turns: number;

  seconds: number;

  scan_date: string | null;
  photos: number;

  max_photos: number;

  budget_unit: BudgetUnit;
  budget_used: number;
  budget_max: number;
  zooms_used: number;
  confirms_used: number;

  billed_used: number | null;

  stop_photos_used: number;

  harness: Harness;

  billed_static: number;
  billed_tiles: number;

  tiles_used: number | null;
  tiles_max: number | null;

  start_kind: StartKind | (string & {}) | null;
  events: number;

  err_gtfs_m: number | null;

  err_found_m: number | null;
  started_at: string;
  finished_at: string;
}

export interface ExplorationPhoto {
  index: number;
  url: string;
  pano_id: string;
  lat: number;
  lon: number;
  date: string | null;
  heading: number;
  fov: number;
  pitch: number;

  along_m: number;

  right_m: number;

  toward: string;

  width: number | null;
  height: number | null;

  shot: number;

  parent: number | null;

  opening: boolean;

  copyright: string | null;

  billed: boolean | null;

  source: 'static' | 'tiles';

  tiles: number;
}

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
  | 'harness_submit'
  | 'tool_error'
  | (string & {});

export interface ExplorationEvent {
  seq: number;
  kind: EventKind;

  summary: string;

  error: string | null;

  photos: number[];

  photos_used: number;

  budget_used: number;

  raw: { request: unknown; response: unknown };
}

export interface ExplorationCandidate {
  index: number;

  kind: string;
  lat: number;
  lon: number;
  along_m: number;
  right_m: number;

  status: string;

  evidence: string | null;

  basis: string;

  checklist: Record<string, string>;

  confirmer_note: string;

  confirm_photo: number | null;
}

export interface Exploration extends ExplorationSummary {
  positions: Position[];

  osm_features: OsmFeature[];

  limits: { along_from: number; along_to: number };

  path: LatLon[];
  candidates: ExplorationCandidate[];

  report: string | null;
  photo_list: ExplorationPhoto[];
  event_list: ExplorationEvent[];

  transcript: unknown[];

  stop_photos: number[];

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

  matched: LatLon[][] | null;

  truth_path_m: number | null;
  truth_path_side: 'right' | 'left' | null;
}

export type ShapeFlag = 'moved' | 'left_of_path' | 'far_from_path' | 'on_detour';

export type OsmFeatureKind = 'bus_stop' | 'platform' | 'stop_position' | 'shelter' | 'bus_station';

export interface OsmFeature {
  id: string;
  kind: OsmFeatureKind | (string & {});
  lat: number;
  lon: number;

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

  flags: (ShapeFlag | (string & {}))[];

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
