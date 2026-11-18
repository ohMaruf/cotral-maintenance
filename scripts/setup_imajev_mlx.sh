#!/usr/bin/env bash
# Install Imajev's reference server (MLX, Apple silicon) for the `local-smoke` profile's scorer.
#
#   scripts/setup_imajev_mlx.sh          then: export IMAJEV_HOME=~/models/imajev-src (the script prints it)
#
# Imajev (github.com/mohit67890/imajev, Apache-2.0) runs in its own Python environment: it pins
# mlx-vlm 0.7.1, which this project does not use. Everything is pinned:
#   code     mohit67890/imajev @ 318e8da (the commit the client in cotral_maintenance/scorer was ported from)
#   adapter  mohit67890/imajev-4b @ 27d4e54 (LoRA + decision readout + calibration)
#   base     Qwen/Qwen3.5-4B @ 851bf6e (~9 GB, in the Hugging Face cache)
set -euo pipefail

IMAJEV_HOME="${IMAJEV_HOME:-$HOME/models/imajev-src}"
CODE_COMMIT=318e8dad55c12a1c6faddbec5f30489d2ee529ff
ADAPTER_REV=27d4e54fc11efeea2ea4d10e910643440d2333b5
BASE_REV=851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a

log() { printf '\033[1m[imajev]\033[0m %s\n' "$*"; }
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
command -v hf >/dev/null || { echo "the hf CLI is required (uv tool install huggingface_hub)" >&2; exit 1; }

if [[ ! -d "$IMAJEV_HOME/.git" ]]; then
  log "Cloning the Imajev code into $IMAJEV_HOME"
  git clone --quiet https://github.com/mohit67890/imajev "$IMAJEV_HOME"
fi
git -C "$IMAJEV_HOME" fetch --quiet origin "$CODE_COMMIT" 2>/dev/null || true
git -C "$IMAJEV_HOME" checkout --quiet "$CODE_COMMIT"

log "Python environment (3.12, mlx-vlm 0.7.1)"
uv venv --quiet --allow-existing -p 3.12 "$IMAJEV_HOME/.venv"
uv pip install --quiet -p "$IMAJEV_HOME/.venv/bin/python" -e "$IMAJEV_HOME[serve,mlx]"

log "Adapter mohit67890/imajev-4b @ ${ADAPTER_REV:0:7}"
hf download mohit67890/imajev-4b --revision "$ADAPTER_REV" --local-dir "$IMAJEV_HOME/adapters/imajev-4b" >/dev/null

log "Base model Qwen/Qwen3.5-4B @ ${BASE_REV:0:7} (~9 GB, skipped if cached)"
SNAPSHOT="$(hf download Qwen/Qwen3.5-4B --revision "$BASE_REV" --quiet)"
cat > "$IMAJEV_HOME/artifacts/model-local.json" <<JSON
{"repo": "Qwen/Qwen3.5-4B", "revision": "$BASE_REV", "path": "$SNAPSHOT"}
JSON

log "Done. Add to your shell or .env:  export IMAJEV_HOME=$IMAJEV_HOME"
log "The pipeline starts the server itself (profile local-smoke); to start it by hand:"
log "  cd \$IMAJEV_HOME && PYTHONPATH=src:scripts .venv/bin/python scripts/playground/server.py \\"
log "    --model-bundle artifacts/model-local.json --adapter adapters/imajev-4b/mlx --rotations 4 \\"
log "    --calibration adapters/imajev-4b/calibration-rot4.json --model-name imajev-4b --port 8765"
