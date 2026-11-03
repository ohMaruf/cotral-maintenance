# Review API contract

Contract between the review frontend (`review-ui/`) and its backend-for-frontend
(`cotral_review/`, FastAPI). Both sides implement exactly this; change it here first.

All JSON. Errors use FastAPI's shape: `{"detail": "<message>"}` (422 validation
errors keep FastAPI's default list form). Base path `/api`. The BFF binds to
127.0.0.1 only; in development the Angular dev server proxies `/api` to it
(`review-ui/proxy.conf.json`). In production the BFF serves `review-ui/dist` at `/`.

## Types

```ts
type CategoryKind = "level" | "probability";

interface Category {
  key: string;          // "shelter", "seating", "signage", "lighting", "waiting_area",
                        // "accessibility", "requires_maintenance", "classifiable"
  label: string;        // "Shelter", ..., "Overall maintenance", "Sign visible"
  kind: CategoryKind;   // "level": 0 (good) .. 4 (missing / severe); "probability": 0 .. 1
  description: string;  // the question asked to the models
}

interface Model {
  key: string;          // "clef", "gemma"
  label: string;        // "Clef", "Gemma"
  description: string;  // e.g. "Probability-weighted expected level" / "Integer level, structured tool call"
}

interface Photo {
  view: string;               // "sweep_1"
  description: string;        // "About 24 m before the mapped stop position"
  url: string;                // "/api/stops/f00077/photos/sweep_1_640x640.jpg"
  distance_m: number | null;
  heading: number | null;
  copyright: string | null;   // must be displayed with the photo (Street View terms)
}

interface StopSummary {       // what a rater may see before judging: no scores
  stop_id: string;
  name: string;
  lat: number;
  lon: number;
  imagery_date: string | null; // "2025-06"
  photos: Photo[];
}

interface StopDetail extends StopSummary {
  // model key -> category key -> value; a model or category may be missing
  scores: Record<string, Record<string, number>>;
  // model key -> category key -> one-sentence reason (only models that give one)
  evidence: Record<string, Record<string, string>>;
}

interface Progress {
  judged: number;     // judgments recorded, skips included
  skipped: number;
  remaining: number;  // unordered pairs of current stops not judged yet
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
| GET | `/api/stops/{stop_id}/photos/{file}` | `image/jpeg`; 404 unless `file` is in that stop's manifest |
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
- Stops may have fewer than four photos.
