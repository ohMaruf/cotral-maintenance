#!/usr/bin/env bash
# Set up the GPU server (Linux, NVIDIA, CUDA) for the pipeline. Safe to re-run: every step checks first.
#
#   scripts/setup_remote.sh            everything
#   scripts/setup_remote.sh --no-models  skip the model downloads (~15 GB)
#
# What it does:
#   1. checks the GPU, the CUDA toolkit and the build tools
#   2. installs uv (if missing) and the Python environment (Python 3.14, with the "osm" extra)
#   3. builds llama.cpp's llama-server with CUDA, at the release the pipeline was verified with,
#      into ~/.local/opt/llama.cpp, and links it as ~/.local/bin/llama-server
#   4. downloads the `remote` profile's model files (pinned revisions) into $COTRAL_MODELS (~/models)
#   5. checks the inputs that are not in git (GTFS_COTRAL/, GROUND_TRUTH/, .env)
set -euo pipefail

LLAMA_CPP_TAG="${LLAMA_CPP_TAG:-b11429}"   # the build the pipeline was verified with (media markers, Qwen3.8)
LLAMA_DIR="${LLAMA_DIR:-$HOME/.local/opt/llama.cpp}"
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
if [[ -x "$LLAMA_DIR/build/bin/llama-server" ]] && \
   [[ "$(git -C "$LLAMA_DIR" describe --tags --exact-match 2>/dev/null || true)" == "$LLAMA_CPP_TAG" ]]; then
  log "llama.cpp $LLAMA_CPP_TAG already built"
else
  log "Building llama.cpp $LLAMA_CPP_TAG with CUDA (sm_$ARCH); this takes a few minutes"
  if [[ ! -d "$LLAMA_DIR/.git" ]]; then
    mkdir -p "$(dirname "$LLAMA_DIR")"
    git clone --quiet https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
  fi
  git -C "$LLAMA_DIR" fetch --quiet --tags
  git -C "$LLAMA_DIR" checkout --quiet "$LLAMA_CPP_TAG"
  cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="$ARCH" \
        -DCMAKE_CUDA_COMPILER="$NVCC" -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF >/dev/null
  cmake --build "$LLAMA_DIR/build" --config Release -j "$(nproc)" --target llama-server >/dev/null
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$LLAMA_DIR/build/bin/llama-server" "$HOME/.local/bin/llama-server"
command -v llama-server >/dev/null || log "Add ~/.local/bin to PATH (or set LLAMA_SERVER=$HOME/.local/bin/llama-server in .env)"
log "$("$HOME/.local/bin/llama-server" --version 2>&1 | head -1)"

# 4. Models ----------------------------------------------------------------------------------
if (( models )); then
  log "Model files of the remote profile (Qwen3.8-27B ~10 GB, Imajev-4B ~5 GB)"
  (cd "$ROOT" && uv run cotral models fetch --profile remote)
fi

# 5. Inputs not in git -----------------------------------------------------------------------
missing=()
[[ -f "$ROOT/GTFS_COTRAL/stops.txt" ]] || missing+=("GTFS_COTRAL/")
[[ -f "$ROOT/GROUND_TRUTH/stop_sign_reference.png" ]] || missing+=("GROUND_TRUTH/ (stop_sign_reference.png, lookalikes/)")
grep -q '^MAPS_API_KEY=' "$ROOT/.env" 2>/dev/null || missing+=(".env with MAPS_API_KEY")
if (( ${#missing[@]} )); then
  log "Still to copy from the laptop: ${missing[*]}"
  log "  e.g. rsync -a GTFS_COTRAL GROUND_TRUTH .env <this-server>:$(basename "$ROOT")/"
fi
[[ -f "$ROOT/data/osm/osm.sqlite3" ]] || log "Then build the OSM store: uv run cotral osm download && uv run --extra osm cotral osm build"
log "Done. First run: uv run cotral run first20 --limit 20"
