# The pipeline: GTFS records in, ranked maintenance scores out

```
GTFS stop ──► ingest ──────────────────► explore ───────────────────────► score ───────────► results.csv
              OSM (Geofabrik) object,     LLM explorer in Street View:     Imajev on the 1-2
              else Places, else GTFS:     finds the stop, confirms it,     stop photos: 7 scores
              where the search starts     keeps 1-2 photos of it           (0-4) + stop visible
```

One command runs it all, resumable at any point: `uv run cotral run RUN --limit 20`.
Each phase stores every stop as soon as it is done; re-running the same command continues.

| Phase | Reads | Runs on | Billed |
|---|---|---|---|
| ingest | GTFS (`stops.txt`, `trips.txt`, `stop_times.txt`), OSM store, Places | CPU | Places Nearby Search, only for stops OSM has no object for |
| explore | the start and the GTFS shape snapped to OSM roads | GPU (explorer) | Street View Static images (≤ 22 per stop), Map Tiles (≤ 60 per stop) |
| score | the explorer's stop photos | GPU (scorer) | nothing |

The explorer and the scorer are different models and the 16 GB GPU holds one at a time, so stops
go in chunks (`--chunk`, default 50): explore a chunk, swap the server, score it, write
`results.csv`, next chunk. The pipeline starts and stops the servers itself.

## Models: profiles

`config/profiles.toml` holds the profiles; `--profile` picks one (default `remote`, or `$COTRAL_PROFILE`).
Swapping a model = another profile or an edit, and a restart. Every result records the profile entry
that produced it.

| Profile | Explorer | Scorer | For |
|---|---|---|---|
| `remote` | Qwen3.8-27B UD-Q2_K_XL (Unsloth GGUF), llama.cpp CUDA, 2 stops at once | Imajev-4B Q8_0 GGUF, llama.cpp CUDA | the Linux server, 16 GB NVIDIA |
| `local-smoke` | TurboFieldfare (Gemma 4 26B-A4B) | Imajev-4B MLX, Imajev's reference server | quick checks on the Mac |
| `local-smoke-gguf` | TurboFieldfare | Imajev-4B Q4_K_M GGUF, llama.cpp Metal | the Mac without the MLX server |
| `local-gguf` | Qwen3.8 GGUF on Metal | Imajev GGUF on Metal | the remote code path, slowly, on the Mac |

The explorer speaks one of two dialects: `llamacpp` (llama-server: forced tool calls, a server slot per
explorer and per confirmer so their prompt caches survive, thinking budget) or `strict` (plain OpenAI
servers that refuse unknown fields, such as TurboFieldfare). The scorer is `llamacpp-readout` (an Imajev
GGUF on llama-server with `--embeddings --pooling last`: the trained decision readout, which the GGUF does
not carry, is applied here to the last hidden state) or `systemone` (Imajev's own server).

## On the GPU server (Linux, NVIDIA, CUDA)

```bash
git clone <this repo> cotral-maintenance && cd cotral-maintenance
scripts/setup_remote.sh            # uv, Python 3.14, llama.cpp built with CUDA, the models
# inputs that are not in git: copy them from the laptop
rsync -a GTFS_COTRAL GROUND_TRUTH .env server:cotral-maintenance/
uv run cotral osm download && uv run --extra osm cotral osm build    # once, ~10 min
uv run cotral run first20 --limit 20                                 # the first end-to-end run
```

`.env` needs `MAPS_API_KEY` (Street View Static, Map Tiles and Places enabled); `MAPS_API_REFERRER`
if the key is restricted by referrer. `GROUND_TRUTH/stop_sign_reference.png` and `GROUND_TRUTH/lookalikes/`
are the explorer's reference images.

Long runs: start them in `tmux` (or `nohup`); Ctrl-C (or losing the session) loses only the stops in
flight. `uv run cotral status RUN` shows progress; `uv run cotral usage` the month's Google usage.

### Google budget

Every Street View and Places request is counted per API key and calendar month in
`data/cache/usage.sqlite`. A stop is started only if the month's remaining budget covers the most it
could bill (22 Static images, 60 tiles); when it ends, what it actually billed is recorded. The caps
default to Google's free tiers (10,000 Static images, 100,000 tiles, 5,000 Places searches a month)
and can be changed per run: `--cap static=8000`. When the budget runs out the run stops starting
stops, scores what was explored, and can be resumed next month.

## Moving a run to the laptop

A run is one directory, `runs/RUN/`, with nothing in it that depends on the machine:

```
runs/RUN/
  run.sqlite            stops, starts, explorations, photos, transcripts, scores, usage, invocations
  media/ab/<sha256>.jpg every photo, content-addressed
  results.csv           the ranked table
  logs/                 the pipeline's and the servers' logs
```

Either:

```bash
# one file (on the server, then copy it):
uv run cotral bundle RUN                 # runs/RUN.tar.zst; --media stop: stop photos only (much smaller)
uv run cotral unbundle RUN.tar.zst       # on the laptop, into runs/
# or incrementally, while no pipeline writes to the run:
rsync -a server:cotral-maintenance/runs/RUN/ runs/RUN/
```

Then the review app reads it: `./start.sh --run runs/RUN`.

## The run store (`cotral_maintenance/runstore.py`, schema version 1)

SQLite, one row per stop and phase. JSON columns are UTF-8 JSON text. Photos are referenced by the
sha256 of their bytes; the file is `media/<first 2 hex>/<sha256>.jpg`.

| Table | Key | What |
|---|---|---|
| `meta` | key | `gtfs_stops_sha256`; `profile:<invocation>` (the profile used by each invocation) |
| `stops` | stop_id | `position` (run order), `name`, `gtfs_lat`, `gtfs_lon`, `services` JSON `[{shape_id, trips, previous[], next[]}]` |
| `starts` | stop_id | `source` (`osm` / `places` / `gtfs`), `lat`, `lon`, `osm` JSON `{osm_id, kind, how, from_gtfs_m, ref, name, operator}`, `places` JSON `{status, reason, lat, lon, offset_m, place_id, ...}` |
| `explorations` | stop_id | `status` (`found` / `not_found` / `no_imagery` / `error`), `reason`, `lat`, `lon`, `position_basis`, `evidence`, `plate_text`, `scan_date`, `stop_photos` JSON `[sha256]` (1-2), `explorer` JSON, `harness` JSON, `billed_static`, `billed_tiles`, `turns`, `seconds`, `started_at`, `finished_at`, `record` JSON |
| `photos` | stop_id, idx | every photo of the search: `media`, `toward` (`opening_before`, `opening_after`, `sweep_ahead`, `sweep_behind`, `zoom`, `look_from`, `stop_photo`), `pano_id`, `date`, `heading`, `fov`, `pitch`, `width`, `height`, `lat`, `lon` (camera) |
| `transcripts` | stop_id | `lines`: JSON lines, the explorer's turns, tool results, confirmer calls |
| `scores` | stop_id | `photos` JSON `[sha256]`, `scorer` JSON, `shelter`, `seating`, `signage`, `lighting`, `waiting_area`, `accessibility`, `requires_maintenance` (0 good .. 4 missing / severe), `stop_visible` (0-1), `answers` JSON (per question: probabilities, `unknown_probability`, `confidence`, `abstained`) |
| `usage` | month, key_id, api | billed requests this run made |
| `invocations` | seq | each `cotral run`: times, status, host (GPU), args, git, counts |

`explorations.record` is the explorer session's record (layout `agent-explorer/1`, see
`cotral_maintenance/explorer/session.py`, `Session.record`): `stop`, `limits`, `budget`, `path`,
`starts`, `hints`, `others`, `previous`, `next`, `shared`, `panoramas`, `cells`, `photos`,
`candidates`, `events`, `outcome`, where every photo `file` (and every path in `events[].photos`,
`outcome.stop_photos`, `outcome.close_up`) is a media sha256.

## Measured

See the commit history and `docs/explore-harness-versions.md` for the explorer; the scorer's
llama.cpp path is checked against Imajev's reference server with `scripts/check_imajev_parity.py`.
