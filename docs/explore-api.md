# Explore and shape-check API contract

Extends the review app (`docs/review-api.md`: same BFF `cotral_review/`, same Angular
app `review-ui/`, same error shape, base path `/api`). Two debugging pages:

- **Explore** (`/explore`): replays a Street View exploration run step by step, in
  the exact order it happened: every photo, every model decision, the raw model
  request and response, and a map of where each photo was taken and where it looked.
- **Shapes** (`/shapes`): the visual check of GTFS shapes, and of the shapes
  snapped onto OSM roads, against verified stop positions (formerly the standalone `data/shape_check/index.html`), with verdicts
  stored by the BFF instead of the browser.

Both sides implement exactly this; change it here first.

## Data on disk (read by the BFF)

The explorations come from the one run the app shows (`docs/review-api.md`, "Data: one run";
`docs/pipeline.md`, "The run store"), opened read-only. One exploration per stop of the run,
its `run_id` is the `stop_id`.

| Source | What |
|---|---|
| `run.sqlite`: `explorations` | status, reason, found position, scan date, models, harness, billing, turns, seconds, and `record` |
| `run.sqlite`: `stops`, `starts` | name, GTFS position, start position (OSM, Places or GTFS) |
| `run.sqlite`: `photos`, `transcripts` | every photo taken; the explorer's conversation, one JSON object per line |
| `media/<2>/<sha256>.jpg` | the photos, content-addressed |

Other files (`Settings` fields; any may be missing, see each endpoint):

| Setting | Default | Written by |
|---|---|---|
| `truth_csv` | `data/ground_truth_manual.csv` | `experiments/explore/ground_truth.py` (`stop_id, lat, lon, ...`); optional: without it no `verified` position and no errors |
| `osm_store` | `data/osm/osm.sqlite3` | `experiments/explore/build_osm_store.py` (read with `cotral_maintenance.osm_store.OsmStore`) |
| `shape_check_json` | `data/shape_check/stops.json` | `experiments/explore/shape_check.py`; unrelated to runs |
| `shape_verdicts_db` | `data/shape_verdicts.sqlite3` | the BFF (verdicts) |

Explorations are read **on every request** (no startup cache). The other files are read at startup.

`explorations.record` is JSON of layout `"agent-explorer/1"` (written by the explorer's
session, `cotral_maintenance/explorer/session.py`): the stop, the snapped `path`, `starts`,
`photos`, `candidates`, `events` (one per tool call, in order, with `tool`, `args`, `result`
text or `error`, `photos` taken, `photos_used`, `budget_used`), `budget`
(`{unit: "images", images, stop_photos, tiles, confirms, used: {...}}`) and `outcome`. In the
run store every photo `file` and the paths in `events[].photos`, `outcome.stop_photos` and
`outcome.close_up` are media sha256s. A stop that was never searched (`no_imagery`, `error`)
has a record with an `outcome` only: its exploration has no photos, events, candidates or path.
The BFF takes the status, reason, billing, turns, seconds, models, harness and scan date from
the row's columns, and the rest from the record when it is there.

`transcripts.lines` is the explorer's conversation as written by the pipeline: JSON lines with
`turn`, and per model turn `reasoning`, `content`, `tool_calls`, `usage`, `timings`; per tool
call `tool`, `result`, `images`; per confirmation `confirm`, `attempt`, `photo`, `status`.
The BFF interleaves the model's reasoning and text (`thought` events) with the record's tool
events: tool lines are matched to the record's events in order by tool name. The whole
transcript is also returned as `transcript`.

The frontend must render an event of an unknown `kind` generically (summary + raw
JSON), never fail on it.

## Types

```ts
type LatLon = [number, number];               // [lat, lon]

type PositionKind = "gtfs" | "places" | "verified" | "estimate";

interface Position {
  kind: PositionKind;
  lat: number;
  lon: number;
  label: string;              // "GTFS", "Places", "OpenStreetMap", "Verified", "Explorer estimate"
  error_m: number | null;     // distance to the verified position; null without one (and for "verified")
}

// ---------- Explore ----------

type Outcome = "found" | "not_found" | "no_imagery" | "error";  // the exploration's status

interface Harness {
  version: string;            // `harness.version`, "0.11.1"
  git_commit: string | null;  // `harness.git.commit`
  git_dirty: boolean | null;  // `harness.git.dirty`
  prompt_sha256: string | null;
  explorer_model: string | null;   // `explorer.model`
  confirmer_model: string | null;  // `explorer.confirmer`, e.g. "same model, fresh call"
}

interface ExplorationSummary {
  run_id: string;             // = stop_id: one exploration per stop of the run
  stop_id: string;
  name: string;
  outcome: Outcome | string;  // `explorations.status`; unknown outcomes are passed through
  outcome_reason: string | null;  // `explorations.reason`, e.g. "the explorer ended: outcome"
  model: string | null;       // `explorations.explorer.model`, e.g. "qwen3.8-27b"
  turns: number;              // model turns
  seconds: number;            // wall time of the exploration
  scan_date: string | null;   // the found stop's panorama date, "YYYY-MM"
  photos: number;             // photos taken
  max_photos: number;         // the record's cap (14)
  budget_unit: "images" | "sweeps" | "photos";  // "images" (the only unit the pipeline writes)
  budget_used: number;        // budget.used.images; show as "5/12 images"; 0 without a search
  budget_max: number;         // budget.images; 0 without a search
  billed_used: number | null; // images actually fetched from Google (cache hits are free); null without a search
  stop_photos_used: number;   // stop photos the harness took of the found stop
  harness: Harness;           // from `explorations.harness`: version, prompt hash, git commit/dirty
  billed_static: number;      // `explorations.billed_static`: Static requests sent to Google
  billed_tiles: number;       // `explorations.billed_tiles`
  tiles_used: number | null;  // budget.used.tiles; null without a search
  tiles_max: number | null;   // budget.tiles (42 in 0.6)
  start_kind: "osm_ref" | "osm_nearest" | "places" | "gtfs" | string | null;  // record.starts[0].kind; unknown kinds pass through
  zooms_used: number;         // 0 for old runs
  confirms_used: number;      // 0 for old runs
  events: number;
  err_gtfs_m: number | null;  // GTFS position -> verified
  err_found_m: number | null; // the submitted position -> verified; null if not found or no truth
  started_at: string;         // ISO 8601
  finished_at: string;
}

interface ExplorationPhoto {
  index: number;              // 1-based, order taken; "PHOTO N" in the results
  url: string;                // "/api/explorations/f7824/photos/<sha256>.jpg"
  pano_id: string;
  lat: number;                // camera (panorama) position
  lon: number;
  date: string | null;        // panorama capture "YYYY-MM"
  heading: number;            // compass degrees the camera looked at
  fov: number;                // horizontal field of view, degrees
  pitch: number;
  along_m: number;            // along the bus's path from the start (+ ahead in the direction of travel)
  right_m: number;            // from the path's centre line (+ right of travel)
  source: "static" | "tiles"; // Street View Static API or Map Tiles; "static" when not recorded
  tiles: number;              // tiles paid for this view; 0 for Static photos
  toward: string;             // "aimed" (opening photo aimed at the start), "sweep_ahead", "sweep_behind",
                              // "zoom", "look_from", "stop_photo"; unknown values pass through
  billed: boolean | null;     // fetched from Google (billed) vs cache; null when the record does not say
  width: number | null;       // pixels
  height: number | null;
  shot: number;               // the sweep a sweep photo belongs to; 0 otherwise
  parent: number | null;      // zoom: the photo index it was taken from
  opening: boolean;           // one of the two photos the harness takes before the model's first turn
  copyright: string | null;   // "© Google" (every photo is Street View); shown with the photo
}

type EventKind =
  | "thought"                 // the model's own text between tool calls (from the transcript)
  | "begin" | "look" | "sweep" | "zoom" | "confirm" | "mark_candidate" | "mark_clear" | "mark_hidden"
  | "answer_checklist" | "find_other_scans" | "show_map" | "note" | "submit_found"
  | "tool_error"              // a call rejected before it reached the explorer (e.g. bad argument types)
  | string;

interface ExplorationEvent {
  seq: number;                // 1-based, the exact order of the run
  kind: EventKind;
  summary: string;            // first line of the tool's result (or "ERROR: ..."), or the model's text
  error: string | null;       // the tool's error message when the call was refused
  photos: number[];           // ExplorationPhoto.index of every photo taken at this event (begin: two)
  photos_used: number;        // photos taken so far, this event included (drives the map's fading)
  budget_used: number;        // in the run's budget_unit (the record's budget_used, else sweeps_used), this event included
  raw: { request: unknown; response: unknown };  // tool: request = args, response = full result text;
                                                  // thought: request = null, response = the text
}

interface ExplorationCandidate {
  index: number;
  kind: string;               // "sign", "shelter", ...
  lat: number;
  lon: number;
  along_m: number;
  right_m: number;
  status: string;             // "spotted", "awaiting_checklist", "confirmed", "rejected"
  evidence: string | null;    // when confirmed: "cotral_sign", "other_stop_sign", "shelter_only", "road_marking"
  basis: string;              // "single_ray_sidewalk", "triangulated"
  checklist: Record<string, string>;  // feature -> "yes" / "no" / "unsure" (empty before the checklist)
  confirmer_note: string;     // what the independent confirmer said the object is; "" for old runs / unconfirmed
  confirm_photo: number | null;  // ExplorationPhoto.index of the confirmation photo
}

interface Exploration extends ExplorationSummary {
  positions: Position[];      // gtfs always; places when Google has the stop; verified and estimate (the
                              // submitted position) when known
  osm_features: OsmFeature[]; // every OSM stop-like object within 200 m of the GTFS position
  limits: { along_from: number; along_to: number };  // the searched stretch, metres along the path
  path: LatLon[];             // the bus's path (snapped to roads), in travel order
  candidates: ExplorationCandidate[];
  report: string | null;      // the model's last text (transcript), when it said anything after its last tool call
  photo_list: ExplorationPhoto[]; // by index
  event_list: ExplorationEvent[]; // by seq
  transcript: unknown[];      // `transcripts.lines`, parsed: the explorer's conversation, raw
  stop_photos: number[];      // ExplorationPhoto.index of the stop photos of a found images run; [] otherwise
  close_up: number | null;    // ExplorationPhoto.index of the confirming zoom of a found images run
}

// ---------- Shapes ----------

interface ShapeRoute {
  shape: string;              // GTFS shape_id
  trips: number;              // trips of this shape serving the stop
  points: LatLon[];           // the shape within 1.2 km of the stop, in travel order
  arrows: { lat: number; lon: number; bearing: number }[];  // direction of travel marks
  truth_m: number;            // verified position -> shape
  truth_side: "right" | "left";   // side of travel the verified position is on
  gtfs_m: number;             // GTFS position -> shape
  prev: string[];             // previous stop ids on this shape
  next: string[];
  matched: LatLon[][] | null; // the shape snapped onto OSM roads (route_paths.py), in travel order;
                              // several pieces where no drivable route connects; null if not snapped
  truth_path_m: number | null;          // verified position -> snapped path
  truth_path_side: "right" | "left" | null;
}

type ShapeFlag = "moved" | "left_of_path" | "far_from_path" | "on_detour";
// moved: the verifier moved the stop >= min_offset_m; left_of_path: verified position left of the
// snapped main path by > 3 m (stops are always on the right); far_from_path: > 25 m from it;
// on_detour: on a loop or out-and-back stretch of the path. Unknown flags must be shown as-is.

type OsmFeatureKind = "bus_stop" | "platform" | "stop_position" | "shelter" | "bus_station";

interface OsmFeature {        // a stop-like OSM object (the local OSM store); OSM rarely carries Cotral ids,
                              // so these are hints, never matched to the stop by id
  id: string;                 // "n123" node, "w456" way (shown at its centre)
  kind: OsmFeatureKind | string;
  lat: number;
  lon: number;
  ref: string;                // may be empty
  name: string;
  operator: string;
}

interface ShapeStop {
  id: string;
  name: string;
  offset_m: number;           // verifier's correction, GTFS -> verified
  flags: ShapeFlag[];         // why the stop is in the check; at least one
  has_sign: string;           // "yes" | "no" | ""
  comments: string;
  gtfs: LatLon;
  truth: LatLon;
  places: LatLon | null;
  osm_features: OsmFeature[]; // within 200 m of the verified position
  routes: ShapeRoute[];       // most trips first
  neighbours: { id: string; name: string; lat: number; lon: number }[];
}

interface ShapeCheck {
  generated_at: string;
  min_offset_m: number;       // threshold of the "moved" flag
  stops: ShapeStop[];         // largest offset first
}

type ShapeVerdictValue = "on_route" | "off_route" | "unclear";

interface ShapeVerdict {
  stop_id: string;
  verdict: ShapeVerdictValue | null;  // null: only a note so far
  note: string;
  rater: string | null;
  updated_at: string;         // ISO 8601 UTC
}
```

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/explorations?harness=0.6.0` | `ExplorationSummary[]`, in the run's stop order. Optional `harness`: only the runs of that harness version (`unversioned` for runs without one; an unknown version gives `[]`) |
| GET | `/api/explorations/harness-versions` | `{version: string, runs: number}[]`: the versions present with their run counts, newest first (numeric per dotted part), `unversioned` last |
| GET | `/api/explorations/{stop_id}` | `Exploration`; 404 if the stop has no exploration; 422 if its record does not match its layout |
| GET | `/api/explorations/{stop_id}/photos/{sha}.jpg` | `image/jpeg`; 404 unless `sha` is a photo of that stop (its `photos` rows, or its stop photos) and the file exists |
| GET | `/api/shape-check` | `ShapeCheck`; 404 `{"detail": "...run experiments/explore/shape_check.py"}` if the file is missing |
| GET | `/api/shape-check/verdicts` | `ShapeVerdict[]`, sorted by `stop_id` |
| PUT | `/api/shape-check/verdicts/{stop_id}` | body `{"verdict": ShapeVerdictValue \| null, "note": str, "rater"?: str \| null}` → 200 `ShapeVerdict` |
| GET | `/api/shape-check/verdicts.csv` | `text/csv`, attachment `shape_check_verdicts.csv` |

PUT errors: 404 if `stop_id` is not in the shape check; 422 invalid body (unknown
verdict, note over 2000 characters). PUT replaces the stop's verdict (last write
wins) and sets `updated_at`.

CSV columns, one row per shape-check stop in `ShapeCheck.stops` order, verdict
columns empty when not judged: `stop_id, offset_m, verdict, note, closest_shape_m,
has_osm, rater, updated_at, flags` (`flags`: the stop's flags joined by `;`; `closest_shape_m`: smallest `truth_m` over the routes,
empty without routes; `has_osm`: 1 if an OSM stop-like object is within 30 m of the verified position, else 0).
The first six match the old page's export,
so its CSV can be imported by the frontend (one PUT per row with a verdict or note).

## Rules

- Events are in the order they happened. Thoughts and tool calls are interleaved as in
  the transcript: a `thought` comes before the tool calls of its turn. A tool line of
  the transcript takes the next record event when the tool name matches; record events the
  transcript does not account for are added at the end (and without a transcript, the
  record's events alone are listed).
- `photos_used` never decreases and equals the photos taken so far; `budget_used` never decreases either.
- The stop id is looked up in the run (a parameter, never a path): an unknown id is 404. A photo name
  must be `<64 lowercase hex>.jpg` and the hash one of that stop's photos; anything else is 404.
  Files are served from the run's `media/` only.
- Photos never change: `Cache-Control: public, max-age=86400`.
- Street View copyright is displayed with the photo.
