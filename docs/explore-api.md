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

| Setting (`Settings` field) | Default | Written by |
|---|---|---|
| `agent_runs_dir` | `data/agent_runs` | `experiments/explore/agent_dry_run.py`: one directory per run, `<stop_id>_<UTC time>/` (the `cache/` directory is not a run) |
| `truth_csv` | `data/ground_truth_manual.csv` | `experiments/explore/ground_truth.py` (`stop_id, lat, lon, ...`) |
| `osm_store` | `data/osm/osm.sqlite3` | `experiments/explore/build_osm_store.py` (read with `cotral_maintenance.osm_store.OsmStore`) |
| `places_csv` | `data/stops_corrected.csv` | phase 1; rows with `coord_source == "places"` (`stop_id, stop_lat, stop_lon`) |
| `shape_check_json` | `data/shape_check/stops.json` | `experiments/explore/shape_check.py` |
| `shape_verdicts_db` | `data/shape_verdicts.sqlite3` | the BFF (verdicts) |

Any of these may be missing; see each endpoint. Exploration records are read **on
every request** (no startup cache): runs are added while the app is open, and a
debugging view must never show stale data. The other files are read at startup.

Exploration records are explorer-specific. The BFF turns each into the `Exploration`
shape below through an adapter chosen by the record's layout. Today there is one: the
LLM explorer (`cotral_maintenance/explorer/`, run by `agent_dry_run.py`). A run
directory holds:
- `record.json` (`"layout": "agent-explorer/1"`), written by the explorer's tool server
  after every tool call: the stop, the snapped path, starting positions, hints,
  panoramas, `photos`, `candidates`, `events` (one per tool call, in order, with
  `tool`, `args`, `result` text or `error`, `photos` taken, `photos_used`, and in newer
  runs `sweeps_used`) and
  `outcome` (`null` while the run is going on);
- `photos/` (the photos, named in `record.photos[].file`);
- `transcript.jsonl`: the model's session as Claude Code `stream-json` lines; its
  `assistant` messages hold the model's text (its reasoning) and `tool_use` blocks in
  order; the final `{"type": "result"}` line holds the model's report;
- `config.json` (`stop_id`, `model`), `summary.json` (written when the run ends).
Three generations of the record exist under the same layout; the BFF reads all of them.
**Oldest** runs spend photos (`max_photos` 14; photos `toward` is `forward`/`backward`/`across`/`target`/
`confirm`; the checklist comes from the `answer_checklist` tool; no `budget`). **Sweep** runs carry a
`budget` without a `unit` (`{sweeps, zooms, confirms, used: {...}}`): a `sweep` takes two wide photos
of one panorama (`toward` `sweep_ahead`/`sweep_behind`, same `shot`) and only sweeps count against
the budget (events carry `sweeps_used`); `zoom` photos (`parent` = the photo zoomed into) and
`confirm` photos are capped separately. **Images** runs carry `budget.unit == "images"`
(`{unit, images: 12, stop_photos: 2, confirms: 6, used: {images, sweeps, zooms, stop_photos,
confirms, billed}}`): the budget is billed Street View Static API images (max 14 per stop: 12 for
the explorer, 2 kept back for the stop photos). A `sweep` is ONE 640x640 photo (`toward`
`sweep_ahead` or `sweep_behind`, its own `shot`), a `zoom` is one image, `confirm` takes no photo (the
confirmer judges the zoom the candidate was marked on: `confirm_photo`). On `submit_found` the harness
takes photos of the stop (`toward` `stop_photo`; the record's `outcome.stop_photos` lists the files and
`outcome.close_up` the confirming zoom), which feed the next pipeline stage. Photos carry `billed`
(fetched from Google rather than the cache); events carry `budget_used` directly. The BFF hides the
differences: when `budget.unit` is present it is used generically (`budget_unit` = the unit,
`budget_used` = `used[unit]`, `budget_max` = `budget[unit]`), else sweeps, else photos. The record's
`shared` stretches (where the bus drives a road twice) are not exposed yet.
**Harness 0.6+** (see `docs/explore-harness-versions.md`) adds `record.harness`
(`{version, git_commit, git_dirty, prompt_sha256, explorer_model, confirmer_model}`, also in
`config.json`, which the BFF falls back to), `record.billed_requests` (`{static, tiles}`: requests
actually sent to Google, cache hits excluded), `budget.tiles` and `budget.used.tiles`/`look_froms`,
photo `source` (`static`|`tiles`) and `tiles` (tiles paid for the view), the photo `toward` values
`aimed` (opening photo aimed at an OSM start) and `look_from` (a narrow view of a candidate from
another panorama; the matching event kind is `look_from`), and `starts[0].kind` (`osm_ref`,
`osm_nearest`, `places`, `gtfs`). Records without `harness` are version `"unversioned"`.
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

type Outcome = "found" | "not_found" | "no_imagery" | "failed" | "running";  // running: no outcome yet

interface Harness {
  version: string;            // "0.6.0"; "unversioned" for runs recorded before versioning
  git_commit: string | null;
  git_dirty: boolean | null;
  prompt_sha256: string | null;
  explorer_model: string | null;
  confirmer_model: string | null;
}

interface ExplorationSummary {
  run_id: string;             // run directory name, e.g. "f9388_20261107T161806"; [A-Za-z0-9_.-]+
  stop_id: string;
  name: string;
  outcome: Outcome | string;  // unknown outcomes are passed through
  outcome_reason: string | null;  // e.g. "photo budget used"
  model: string | null;       // the model id from the transcript (e.g. "claude-haiku-5-5"), else config.json's
  photos: number;             // photos taken
  max_photos: number;         // oldest runs: the photo budget (14); sweep runs: the sweep cap (12); images runs: 14
  budget_unit: "images" | "sweeps" | "photos";  // budget.unit; "sweeps" for a unit-less `budget`; else "photos"
  budget_used: number;        // used[unit] / photos taken (oldest); show as "5/12 images"
  budget_max: number;         // budget[unit] / max_photos (oldest)
  billed_used: number | null; // images actually fetched from Google (cache hits are free); null unless images run
  stop_photos_used: number;   // stop photos the harness took of the found stop; 0 before the new format
  harness: Harness;           // version "unversioned" when the record has none
  billed_static: number | null;  // record.billed_requests.static: Static requests sent to Google; null when not recorded
  billed_tiles: number | null;   // record.billed_requests.tiles
  tiles_used: number | null;  // budget.used.tiles; null for runs without a tile budget
  tiles_max: number | null;   // budget.tiles (42 in 0.6)
  start_kind: "osm_ref" | "osm_nearest" | "places" | "gtfs" | string | null;  // record.starts[0].kind; unknown kinds pass through
  zooms_used: number;         // 0 for old runs
  confirms_used: number;      // 0 for old runs
  events: number;
  err_gtfs_m: number | null;  // GTFS position -> verified
  err_found_m: number | null; // the submitted position -> verified; null if not found or no truth
  started_at: string | null;  // ISO 8601
  finished_at: string | null; // when the record was last saved after the outcome was set; null while running
}

interface ExplorationPhoto {
  index: number;              // 1-based, order taken; "PHOTO N" in the results
  url: string;                // "/api/explorations/f9388_20261107T161806/photos/03_<pano>_12.0_90_0.jpg"
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
  toward: string;             // oldest: "forward", "backward", "across", "target", "confirm";
                              // sweep runs: "sweep_ahead", "sweep_behind", "zoom", "confirm";
                              // images runs: "sweep_ahead", "sweep_behind", "zoom", "stop_photo";
                              // 0.5+: "aimed" (opening photo aimed at the start); 0.6+: "look_from"
  billed: boolean | null;     // fetched from Google (billed) vs cache; null when the record does not say
  width: number | null;       // pixels; null for old runs
  height: number | null;
  shot: number;               // the sweep a sweep photo belongs to (sweep runs: both photos of a sweep share it; images runs: one photo per shot); 0 otherwise
  parent: number | null;      // zoom: the photo index it was taken from
  opening: boolean;           // one of the two photos the harness takes before the model's first turn
  copyright: string | null;   // shown with the photo when present
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
  report: string | null;      // the model's final report, when the run has ended
  photo_list: ExplorationPhoto[]; // by index
  event_list: ExplorationEvent[]; // by seq
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
| GET | `/api/explorations?harness=0.6.0` | `ExplorationSummary[]`, sorted by `run_id`; `[]` if the directory is missing. Optional `harness`: only the runs of that harness version (`unversioned` for runs without one; an unknown version gives `[]`) |
| GET | `/api/explorations/harness-versions` | `{version: string, runs: number}[]`: the versions present with their run counts, newest first (numeric per dotted part), `unversioned` last |
| GET | `/api/explorations/{run_id}` | `Exploration`; 404 if unknown; 422 if the record has a layout no adapter reads |
| GET | `/api/explorations/{run_id}/photos/{file}` | `image/jpeg`; 404 unless `file` is a photo of that run and exists |
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
  the transcript: a `thought` comes before the tool call it led to. The record's events
  are matched to the transcript's `tool_use` blocks in order (tool name
  `mcp__explorer__<kind>`); a `tool_use` with no record event (refused before it reached
  the explorer) becomes a `tool_error` event with the transcript's error text. Without
  a transcript (a run being written), the record's events alone are listed.
- `photos_used` never decreases and equals the photos taken so far; `budget_used` never decreases either.
- A run is listed as soon as its `record.json` exists, also while it is going on
  (`outcome: "running"`); reloading shows its progress.
- Run ids and photo file names are validated (`[A-Za-z0-9_.-]+`) and resolved
  inside their directory; anything else is 404.
- Photos never change once downloaded: `Cache-Control: public, max-age=86400`.
- Street View copyright, when the record carries it, is displayed with the photo.
