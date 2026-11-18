# Review API contract

Contract between the review frontend (`review-ui/`) and its backend-for-frontend
(`cotral_review/`, FastAPI). Both sides implement exactly this; change it here first.

All JSON. Errors use FastAPI's shape: `{"detail": "<message>"}` (422 validation
errors keep FastAPI's default list form). Base path `/api`. The BFF binds to
127.0.0.1 only; in development the Angular dev server proxies `/api` to it
(`review-ui/proxy.conf.json`). In production the BFF serves `review-ui/dist` at `/`.

The explore and shape-check pages have their own contract: `docs/explore-api.md`.

## Data: one run

The app shows ONE run directory of the pipeline (`docs/pipeline.md`, "The run store"),
named by `COTRAL_REVIEW_RUN` (`./start.sh --run runs/<RUN>`, or `cotral_review serve --run`);
a relative path is relative to the repository root. The BFF opens `run.sqlite` read-only
(`mode=ro`) and never writes into the run; its own state (judgments, shape verdicts) lives
in its own SQLite files. It refuses to start, with a message, when the run is missing.

- **stops**: the run's stops that have a `scores` row. Position: the explorer's found position
  (`explorations.lat/lon`), else the start position (`starts`), else GTFS. `imagery_date`:
  `explorations.scan_date`.
- **photos**: the 1-2 `explorations.stop_photos` (sha256s of `media/<2>/<sha256>.jpg`).
- **models**: one, the scorer: key `imajev`, label the `model` of `scores.scorer`.
- **scores**: the `scores` columns; **evidence**: from `scores.answers`, per category.

## Types

```ts
type CategoryKind = "level" | "probability";

interface Category {
  key: string;          // "shelter", "seating", "signage", "lighting", "waiting_area",
                        // "accessibility", "requires_maintenance", "stop_visible"
  label: string;        // "Shelter", ..., "Overall maintenance", "Stop visible"
  kind: CategoryKind;   // "level": 0 (good) .. 4 (missing / severe); "probability": 0 .. 1
  description: string;  // the question asked to the scorer (cotral_maintenance/scorer/questions.py)
}

interface Model {
  key: string;          // "imajev": one model per run, the scorer
  label: string;        // the scorer's model name in the run, e.g. "imajev-4b"
  description: string;  // "Expected level under Imajev's calibrated probabilities"
}

interface Photo {
  view: string;               // "stop_photo_1", "stop_photo_2"
  description: string;        // "From the panorama that confirmed the stop" / "From about 12 m before the stop"
  url: string;                // "/api/stops/f7824/photos/<sha256>.jpg"
  distance_m: number | null;  // null: not recorded
  heading: number | null;     // the camera's, from the run's `photos` row
  copyright: string | null;   // "© Google"; must be displayed with the photo (Street View terms)
}

interface StopSummary {       // what a rater may see before judging: no scores
  stop_id: string;
  name: string;
  lat: number;
  lon: number;
  imagery_date: string | null; // "2025-06" (the exploration's scan_date)
  photos: Photo[];
}

interface StopDetail extends StopSummary {
  // model key -> category key -> value; a model or category may be missing
  scores: Record<string, Record<string, number>>;
  // model key -> category key -> short text, e.g. "unknown 23%, confidence 0.41"
  // ("abstained, " first when the scorer's most likely answer was unknown)
  evidence: Record<string, Record<string, string>>;
}

interface Progress {
  judged: number;     // judgments recorded, skips included
  skipped: number;
  remaining: number;  // unordered pairs of current stops not judged yet
}

interface RunInfo {
  name: string;                       // the run directory's name
  stops: number;
  ingested: Record<string, number>;   // stops by start source: osm, places, gtfs
  explored: Record<string, number>;   // stops by exploration status: found, not_found, no_imagery, error
  scored: number;
  billed: Record<string, number>;     // billed Google requests by API: static, tiles, places
  profiles: { key: string; name: string; description: string }[];  // meta `profile:<key>`, in key order
}

interface ResultRow {                 // one row of results.csv (cotral_maintenance/pipeline/export.py)
  rank: number | null;                // among the stops that need no review; null for the others
  stop_id: string;
  name: string;
  needs_review: boolean;
  review_reason: string;              // "" when none
  shelter: number | null;             // the 8 scores; null until scored
  seating: number | null;
  signage: number | null;
  lighting: number | null;
  waiting_area: number | null;
  accessibility: number | null;
  requires_maintenance: number | null;
  stop_visible: number | null;
  status: string | null;              // the exploration's status; null: not explored yet
  explore_reason: string | null;
  evidence: string | null;            // what identified the stop: cotral_sign, shelter_only, ...
  plate_text: string | null;
  lat: number | null;                 // the found position
  lon: number | null;
  found_from_gtfs_m: number | null;
  position_basis: string | null;
  scan_date: string | null;
  start_source: string | null;        // osm, places, gtfs
  start_lat: number | null;
  start_lon: number | null;
  gtfs_lat: number;
  gtfs_lon: number;
  explorer_model: string | null;
  scorer_model: string | null;
  photos: string[];                   // URLs of the stop photos, served by /api/explorations/{stop_id}/photos/...
}

interface Judgment {
  id: string;
  created_at: string;       // ISO 8601 UTC
  left: string;             // stop ids, as shown on screen
  right: string;
  winner: string | null;    // null = skipped ("can't tell")
  loser: string | null;
  rater: string | null;
  decision_ms: number | null;
}
```

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/health` | `{"status": "ok"}` |
| GET | `/api/catalog` | `{"categories": Category[], "models": Model[]}`, order is display order |
| GET | `/api/stops` | `StopDetail[]`, sorted by stop_id |
| GET | `/api/stops/{stop_id}` | `StopDetail`; 404 if unknown |
| GET | `/api/stops/{stop_id}/photos/{sha}.jpg` | `image/jpeg`; 404 unless `sha` is one of that stop's stop photos |
| GET | `/api/run` | `RunInfo` |
| GET | `/api/results` | `ResultRow[]`: the run's final table, ranked stops first (rank 1 = worst), then the stops that need review; every stop of the run |
| GET | `/api/pairs/next` | `{"pair": {"left": StopSummary, "right": StopSummary} \| null, "progress": Progress}`; `pair` is null when every pair is judged |
| POST | `/api/judgments` | body `{"left": str, "right": str, "winner": str \| null, "rater"?: str \| null, "decision_ms"?: int \| null}` → 201 `{"judgment": Judgment, "left": StopDetail, "right": StopDetail, "progress": Progress}` |
| GET | `/api/judgments` | `Judgment[]`, oldest first |
| GET | `/api/judgments/progress` | `Progress` |

POST `/api/judgments` errors: 404 unknown stop; 409 pair already judged (either
order); 422 invalid body, `left == right`, or `winner` not one of the two.

## Rules

- `/api/pairs/next` never returns a pair that has been judged, in either order,
  by anyone. Left/right order is random. Scores are never included before judging.
- A pair is not reserved when served; the 409 on POST resolves races (the client
  then fetches the next pair).
- Judgments are permanent ground truth for evaluating ranking functions
  (stop embedding + location → real score): a function is right on a judgment when
  it scores `winner` above `loser`.
- A model "agrees" with a judgment when its `requires_maintenance` is higher for
  `winner` than for `loser`; equal values are a tie. `requires_maintenance` is the
  overall verdict category.
- Missing values: a cell with fewer than two model values is never a disagreement;
  stops without a value sort last in either direction.
- Stops have one or two photos. A run with no scored stops has an empty `/api/stops` and no model.
- `/api/results` is computed on every request from the run (stops, explorations and scores).
