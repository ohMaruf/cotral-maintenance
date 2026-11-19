#!/usr/bin/env bash
# Set up the GPU server (Linux, NVIDIA, CUDA) for the pipeline. Safe to re-run: every step checks first.
#
#   scripts/setup_remote.sh            everything
#   scripts/setup_remote.sh --no-models  skip the model downloads (~15 GB)
#
# What it does:
#   1. checks the GPU, the CUDA toolkit and the build tools
#   2. installs uv (if missing) and the Python environment (Python 3.14, with the "osm" extra)
#   3. builds llama.cpp's llama-server with CUDA, twice:
#        b11429 (the explorer, Qwen3.8: verified) into ~/.local/opt/llama.cpp, linked as ~/.local/bin/llama-server
#        b11773 (the scorer, H2O Lightning: the first build that answers /v1/systemone) into
#        ~/.local/opt/llama.cpp-b11773, which the `remote` profile's scorer names as its binary
#   4. downloads the `remote` profile's model files (pinned revisions) into $COTRAL_MODELS (~/models)
#   5. fetches inputs/, the data repository (a private git submodule: the GTFS zip, GROUND_TRUTH/), and
#      unzips the Cotral GTFS feed, inputs/GTFS_COTRAL.zip, into GTFS_COTRAL/ when it is not there
#   6. checks the input that is not in git: .env (the Google API key)
set -euo pipefail

LLAMA_CPP_TAG="${LLAMA_CPP_TAG:-b11429}"   # the build the pipeline was verified with (media markers, Qwen3.8)
LLAMA_DIR="${LLAMA_DIR:-$HOME/.local/opt/llama.cpp}"
DECISIONS_TAG="b11773"   # H2O Lightning's decision API in llama-server; the model card's commit 7e3eeee04
DECISIONS_DIR="$HOME/.local/opt/llama.cpp-$DECISIONS_TAG"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
models=1
[[ "${1:-}" == "--no-models" ]] && models=0

log() { printf '\033[1m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

# 1. GPU and tools ---------------------------------------------------------------------------
command -v nvidia-smi >/dev/null || die "nvidia-smi not found: install the NVIDIA driver"
log "GPU: $(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)"
NVCC="$(command -v nvcc || true)"
[[ -z "$NVCC" && -x /usr/local/cuda/bin/nvcc ]] && NVCC=/usr/local/cuda/bin/nvcc
[[ -n "$NVCC" ]] || die "nvcc not found: install the CUDA toolkit (e.g. apt install nvidia-cuda-toolkit, or CUDA from NVIDIA)"
log "CUDA: $("$NVCC" --version | tail -1)"
for tool in git cmake g++ curl; do
  command -v "$tool" >/dev/null || die "$tool not found (apt install git cmake build-essential curl)"
done
# The GPU's compute capability, e.g. 8.9 -> 89: building for it alone keeps the build short.
ARCH="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '.')"

# 2. Python ----------------------------------------------------------------------------------
if ! command -v uv >/dev/null; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
log "Python environment"
(cd "$ROOT" && uv sync --extra osm)

# 3. llama.cpp with CUDA ---------------------------------------------------------------------
# A full clone: llama.cpp counts commits for its build number, and a shallow clone calls itself build 1 (and then
# fails to fetch its web UI assets). HF_UI_VERSION names the UI assets of the tag in any case.
build_llama() {
  local tag="$1" dir="$2"
  if [[ -x "$dir/build/bin/llama-server" ]] && \
     [[ "$(git -C "$dir" describe --tags --exact-match 2>/dev/null || true)" == "$tag" ]]; then
    log "llama.cpp $tag already built in $dir"
    return
  fi
  log "Building llama.cpp $tag with CUDA (sm_$ARCH) in $dir; this takes a few minutes"
  if [[ ! -d "$dir/.git" ]]; then
    mkdir -p "$(dirname "$dir")"
    if [[ -d "$LLAMA_DIR/.git" && "$dir" != "$LLAMA_DIR" ]]; then
      git clone --quiet --reference "$LLAMA_DIR" https://github.com/ggml-org/llama.cpp "$dir"
    else
      git clone --quiet https://github.com/ggml-org/llama.cpp "$dir"
    fi
  fi
  git -C "$dir" fetch --quiet --tags
  git -C "$dir" checkout --quiet "$tag"
  HF_UI_VERSION="$tag" cmake -S "$dir" -B "$dir/build" -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="$ARCH" \
        -DCMAKE_CUDA_COMPILER="$NVCC" -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF >/dev/null
  HF_UI_VERSION="$tag" cmake --build "$dir/build" --config Release -j "$(nproc)" --target llama-server >/dev/null
}
build_llama "$LLAMA_CPP_TAG" "$LLAMA_DIR"
build_llama "$DECISIONS_TAG" "$DECISIONS_DIR"
log "scorer: $("$DECISIONS_DIR/build/bin/llama-server" --version 2>&1 | head -1)"
mkdir -p "$HOME/.local/bin"
ln -sf "$LLAMA_DIR/build/bin/llama-server" "$HOME/.local/bin/llama-server"
command -v llama-server >/dev/null || log "Add ~/.local/bin to PATH (or set LLAMA_SERVER=$HOME/.local/bin/llama-server in .env)"
log "$("$HOME/.local/bin/llama-server" --version 2>&1 | head -1)"

# 4. Models ----------------------------------------------------------------------------------
if (( models )); then
  log "Model files of the remote profile (Qwen3.8-27B ~10 GB, H2O Lightning 4B ~5 GB)"
  (cd "$ROOT" && uv run cotral models fetch --profile remote)
fi

# 5. Inputs: the data repository and the Cotral GTFS feed -------------------------------------------
# inputs/ is https://github.com/ohMaruf/cotral-maintenance-data, private, at the commit this checkout pins,
# fetched over HTTPS with the same GitHub credentials as this repository: a token that can read both repositories
# (stored once by `git config --global credential.helper store` and the first fetch, or by `gh auth login`).
log "Inputs: the data repository (inputs/)"
git -C "$ROOT" submodule update --init inputs \
  || die "inputs/: cannot fetch https://github.com/ohMaruf/cotral-maintenance-data.git. The server's GitHub token
  must be able to read it (a fine-grained token: add the repository to it), then re-run"
# The GTFS zip is in the data repository (the feed's download server is not reachable from everywhere); it is
# unzipped once.
# An unzipped feed is never replaced: a run is tied to the feed it started with (`cotral run` checks stops.txt's
# sha256). When the zip has a newer feed, this says so; remove GTFS_COTRAL/ and re-run to switch, and start new runs.
GTFS_ZIP="$ROOT/inputs/GTFS_COTRAL.zip"
GTFS_DIR="$ROOT/GTFS_COTRAL"
if [[ -f "$GTFS_DIR/stops.txt" ]]; then
  if [[ -f "$GTFS_ZIP" ]] && ! (cd "$ROOT" && uv run python - "$GTFS_ZIP" "$GTFS_DIR/stops.txt" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z, open(sys.argv[2], "rb") as f:
    sys.exit(0 if z.read("stops.txt") == f.read() else 1)
PY
  ); then
    log "GTFS: inputs/GTFS_COTRAL.zip differs from GTFS_COTRAL/ (kept). To switch feed: rm -rf GTFS_COTRAL and re-run"
  else
    log "GTFS: GTFS_COTRAL/ is there"
  fi
elif [[ -f "$GTFS_ZIP" ]]; then
  (cd "$ROOT" && uv run python - "$GTFS_ZIP" "$GTFS_DIR" <<'PY'
import sys, zipfile
from pathlib import Path
need = {"agency.txt", "calendar.txt", "routes.txt", "shapes.txt", "stop_times.txt", "stops.txt", "trips.txt"}
out = Path(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as z:
    files = {Path(n).name: n for n in z.namelist() if n.endswith(".txt") and "/." not in n}
    missing = need - files.keys()
    if missing:
        sys.exit(f"GTFS_COTRAL.zip lacks {', '.join(sorted(missing))}")
    tmp = out.with_name(out.name + ".partial")
    tmp.mkdir(exist_ok=True)
    for name, member in files.items():  # flat, whether the zip has a folder or not
        (tmp / name).write_bytes(z.read(member))
    tmp.rename(out)
print(f"{sum(1 for _ in open(out / 'stops.txt', encoding='utf-8-sig')) - 1} stops")
PY
  ) | { read -r n; log "GTFS: inputs/GTFS_COTRAL.zip unzipped into GTFS_COTRAL/ ($n)"; } || die "GTFS: unzipping inputs/GTFS_COTRAL.zip failed"
  [[ -f "$GTFS_DIR/stops.txt" ]] || die "GTFS: unzipping inputs/GTFS_COTRAL.zip failed"
else
  die "GTFS: no inputs/GTFS_COTRAL.zip and no GTFS_COTRAL/"
fi

# 6. .env, not in git -------------------------------------------------------------------------
missing=()
grep -q '^MAPS_API_KEY=' "$ROOT/.env" 2>/dev/null || missing+=(".env with MAPS_API_KEY")
if (( ${#missing[@]} )); then
  log "Still to copy from the laptop: ${missing[*]}"
  log "  e.g. scp .env <this-server>:$(basename "$ROOT")/"
fi
[[ -f "$ROOT/data/osm/osm.sqlite3" ]] || log "Then build the OSM store: uv run cotral osm download && uv run --extra osm cotral osm build"
log "Done. First run: uv run cotral run first20 --limit 20"
