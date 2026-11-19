# Cotral bus stop maintenance

Finds Cotral bus stops in Google Street View and ranks them by their need of maintenance.

```
GTFS stop ─► ingest ─────────────────► explore ─────────────────────► score ────────────────► results.csv
             OSM (Geofabrik) object,    LLM explorer (Qwen3.8 27B)      decision model (H2O
             else Places, else GTFS:    in Street View: finds and       Lightning 4B) on the stop
             where the search starts    confirms the stop, 1-2 photos   photos -> a condition
```

The pipeline (`cotral_maintenance/`) runs on a Linux server with an NVIDIA GPU; its results are
copied to a laptop and looked at in the review app (`cotral_review/` + `review-ui/`). Every phase
stores each stop as soon as it is done, so a run can be stopped and resumed anywhere.

More detail: [docs/pipeline.md](docs/pipeline.md) (phases, run format, scores, versions),
[docs/review-api.md](docs/review-api.md) (review app API).

## Environments

| Where | Profile | Explorer | Scorer | For |
|---|---|---|---|---|
| Linux + NVIDIA 16 GB | `remote` (default) | Qwen3.8-27B UD-Q2_K_XL, llama.cpp b11429 CUDA | H2O Lightning 4B Q8_0, llama.cpp b11773 CUDA | real runs |
| Linux + NVIDIA 16 GB | `remote-imajev` | same | Imajev-4B Q8_0 + its readout | the previous scorer |
| Mac (Apple silicon) | `local-gguf` | the same Qwen3.8 file, Metal | the same H2O file, Metal | the remote code path, slowly |
| Mac | `local-imajev` | Qwen3.8, Metal | Imajev-4B Q4_K_M, Metal | the previous scorer |
| Mac | `local-smoke` / `local-smoke-gguf` | TurboFieldfare (Gemma 4) | Imajev MLX server / Imajev GGUF | quick checks |
| Mac | - | - | - | the review app |

A profile is picked with `--profile NAME` (or `COTRAL_PROFILE`); profiles live in
[config/profiles.toml](config/profiles.toml). The pipeline starts and stops the model servers itself.

## Inputs

The data the pipeline reads lives in a separate, private repository,
[cotral-maintenance-data](https://github.com/ohMaruf/cotral-maintenance-data), included here as a git
submodule at `inputs/`, pinned to a commit: each commit of the code names the data it runs on.

| What | Where | Needed by |
|---|---|---|
| Cotral GTFS feed, zipped | `inputs/GTFS_COTRAL.zip`, unzipped into `GTFS_COTRAL/` | every run |
| Explorer reference images: `stop_sign_reference.png`, `lookalikes/*.png` (the folder also holds the spreadsheets of verified stop positions the experiments use) | `inputs/GROUND_TRUTH/` | explore |
| `.env` (in no repository: it holds the API key) with `MAPS_API_KEY` (Street View Static, Map Tiles and Places enabled) and, if the key is restricted by referrer, `MAPS_API_REFERRER` | `.env` | ingest, explore |

Other locations can be set in `.env` or the environment: `COTRAL_GTFS`, `COTRAL_ASSETS`, `COTRAL_RUNS`
(default `runs/`), `COTRAL_CACHE` (`data/cache/`), `COTRAL_MODELS` (`~/models`), `COTRAL_OSM_STORE`,
`COTRAL_PROFILES` (see `cotral_maintenance/settings.py`).

```bash
git clone --recurse-submodules https://github.com/ohMaruf/cotral-maintenance.git   # code + inputs/
git submodule update --init inputs                  # in a clone made without --recurse-submodules
unzip -o inputs/GTFS_COTRAL.zip -d GTFS_COTRAL      # on the Mac (setup_remote.sh does it on the server)
```

To update the feed: commit the new `GTFS_COTRAL.zip` in the data repository, then here
`git -C inputs pull origin main` and commit the new `inputs` pointer. An unzipped feed is never replaced
by the setup, because a run is tied to the feed it started with: `rm -rf GTFS_COTRAL`, unzip again, and
start new runs (old runs refuse to continue without `--allow-new-gtfs`).

---

## 1. The GPU server (Linux, NVIDIA, CUDA)

Needs: the NVIDIA driver, the CUDA toolkit (`nvcc`), `git cmake build-essential curl`, about 30 GB of
disk (models 15 GB, OSM 3 GB, llama.cpp builds).

```bash
git clone https://github.com/ohMaruf/cotral-maintenance.git && cd cotral-maintenance
scripts/setup_remote.sh          # uv + Python 3.14, llama.cpp b11429 and b11773 with CUDA, the models, inputs/ + GTFS
```

`setup_remote.sh` is safe to re-run. It builds llama.cpp twice, both with CUDA for the card's compute
capability:

- **b11429** into `~/.local/opt/llama.cpp`, linked as `~/.local/bin/llama-server`, for the explorer;
- **b11773** into `~/.local/opt/llama.cpp-b11773`, for the scorer. This is the first build that answers
  H2O Lightning's decision API itself, and the `remote` profile names it as the scorer's `binary`.

`--no-models` skips the model downloads; `uv run cotral models fetch --profile remote` does them later.

It fetches `inputs/` (the data repository) and unzips the GTFS into `GTFS_COTRAL/` when that is not
there; it says when the zip and the unzipped feed differ. The submodule is fetched over HTTPS
(`.gitmodules`), with the same GitHub credentials the server uses for this repository. The data
repository is private, so that token must be able to read it too: with a fine-grained token, add
`cotral-maintenance-data` to its repositories (Contents: read).

A clone that works over SSH (the laptop, which pushes) can use SSH for `inputs/` too, in its own
config (`.gitmodules` stays HTTPS):

```bash
git config submodule.inputs.url git@github.com:ohMaruf/cotral-maintenance-data.git
git -C inputs remote set-url origin git@github.com:ohMaruf/cotral-maintenance-data.git
```

Copy `.env` from the laptop (the only input in no repository), then build the OSM store once (about 10 minutes):

```bash
# on the laptop
scp .env server:cotral-maintenance/
# on the server
uv run cotral osm download                 # Geofabrik extracts (centro, sud)
uv run --extra osm cotral osm build        # data/osm/osm.sqlite3
```

### Run

```bash
tmux new -s cotral                          # a long run survives a lost SSH session
uv run cotral run first20 --limit 20        # the first 20 stops of the seeded sample, end to end
```

| Command | Does |
|---|---|
| `uv run cotral run RUN --limit N` | the first N stops of the sample (raising N later extends the same sample) |
| `uv run cotral run RUN --stop-id f13457` | given stops (repeatable) |
| `uv run cotral run RUN --resume` | continue a run: only what is not done yet |
| `uv run cotral run RUN --resume --phases score --force score` | score the run's stops again (free) |
| `uv run cotral status RUN` | progress, versions, invocations |
| `uv run cotral usage` | this month's billed Google requests |
| `uv run cotral export RUN` | rewrite `runs/RUN/results.csv` |

Things to know:

- **GPU:** the explorer and the scorer take turns on the GPU, in chunks of stops (`--chunk`, default 50).
  If the explorer server runs out of GPU memory (see `runs/RUN/logs/explorer-server.log`), lower its
  `-c` in the profile, or run one explorer at a time.
- **Budget:** Google requests are capped per API key and month, at the free tiers by default
  (`--cap static=8000` to change). When the budget runs out, the run stops starting new stops.
- **Versions:** a run is one batch. It refuses to mix results from different code or prompt versions;
  `cotral run` says what to do when that happens (see "Versions" in [docs/pipeline.md](docs/pipeline.md)).

### Bring the results to the laptop

```bash
# on the server: one file (--media stop: only the stop photos, much smaller)
uv run cotral bundle first20               # runs/first20.tar.zst
# on the laptop
scp server:cotral-maintenance/runs/first20.tar.zst . && uv run cotral unbundle first20.tar.zst
# or incrementally, while no pipeline writes to the run
rsync -a server:cotral-maintenance/runs/first20/ runs/first20/
```

---

## 2. The Mac: the review app

Needs: [uv](https://docs.astral.sh/uv/) and [fnm](https://github.com/Schniz/fnm) (`brew install uv fnm`).
`start.sh` installs the Python and Node dependencies (Node version from `review-ui/.node-version`).

```bash
./start.sh --run runs/first20              # http://localhost:4200 (BFF on :8765)
./start.sh --run runs/first20 --port 4300 --bff-port 8790    # other ports
./start.sh --prod --run runs/first20       # build once, served by the BFF on :8765
```

A run of an older format is upgraded with `uv run cotral status RUN` (its scores are dropped; re-score
with `uv run cotral run RUN --resume --phases score`).

---

## 3. The Mac: the pipeline with the remote's models (`local-gguf`)

The same models and code path as the server, on Metal, slowly (about 10 minutes per stop explored,
30 s per stop scored on an M5 Pro). The explorer server takes about 13 GB of memory.

Needs two llama.cpp builds:

```bash
# explorer: llama-server build 11429 (Homebrew's llama.cpp 0.6.0 is that build: check `llama-server --version`)
brew install llama.cpp              # or build tag b11429, and set LLAMA_SERVER=/path/to/llama-server in .env

# scorer: build 11773, where the profile expects it. A full clone: a shallow one reports build 1 and its
# web UI step fails; HF_UI_VERSION names the UI assets either way.
git clone https://github.com/ggml-org/llama.cpp ~/.local/opt/llama.cpp-b11773
cd ~/.local/opt/llama.cpp-b11773 && git checkout b11773
HF_UI_VERSION=b11773 cmake -B build -DCMAKE_BUILD_TYPE=Release
HF_UI_VERSION=b11773 cmake --build build --config Release -j --target llama-server
./build/bin/llama-server --version  # commit 7e3eeee
```

Then, with `inputs/` fetched, `GTFS_COTRAL/` unzipped and `.env` in place:

```bash
uv sync --extra osm
uv run cotral osm download && uv run --extra osm cotral osm build      # once
uv run cotral models fetch --profile local-gguf                          # ~15 GB into ~/models
uv run cotral run smoke --profile local-gguf --limit 2
```

Scoring an explored run again with another scorer, for example to compare models, costs no Google
budget: copy the run and re-score the copy.

```bash
cp -R runs/smoke runs/smoke-imajev
uv run cotral run smoke-imajev --resume --profile local-imajev --phases score --force score
```

## 4. The Mac: quick smoke tests (`local-smoke`, `local-smoke-gguf`)

A faster explorer for checking that everything runs end to end: TurboFieldfare (Gemma 4 26B-A4B), a
Swift server in `turbo-fieldfare/` (not in git). Build it and install the model and its image pack
(about 15 GB):

```bash
cd turbo-fieldfare
swift build -c release
swift run -c release TurboFieldfareRepack --output scratch/gemma4.gturbo --overwrite
swift run -c release TurboFieldfareRepack --vision-output scratch/gemma4.vision.gturbo --text-model scratch/gemma4.gturbo
cd ..
```

- `local-smoke-gguf`: TurboFieldfare + Imajev GGUF on llama.cpp (the `llama-server` on the PATH).
- `local-smoke`: TurboFieldfare + Imajev's own MLX server. Set it up with `scripts/setup_imajev_mlx.sh`,
  then set `IMAJEV_HOME` to where it installed.

```bash
uv run cotral run smoke-tf --profile local-smoke-gguf --limit 2
```

---

## Tests

```bash
uv run pytest -q                                              # Python: pipeline, BFF
cd review-ui && eval "$(fnm env)" && fnm use && npm run test:ci   # Angular
```

## Repository

| Path | What |
|---|---|
| `cotral_maintenance/` | the pipeline, `cotral` CLI |
| `cotral_review/`, `review-ui/` | the review app: BFF (FastAPI) and web app (Angular) |
| `config/profiles.toml` | model profiles |
| `scripts/` | server setup, Imajev MLX setup and parity check |
| `docs/` | pipeline, review API, explorer design and versions |
| `experiments/` | scratch experiments, not part of the pipeline |
| `inputs/` | the data repository (submodule): GTFS zip, ground truth |
| `runs/`, `data/` | runs and caches (not in git) |
