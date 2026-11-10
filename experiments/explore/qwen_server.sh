#!/usr/bin/env bash
# The local Qwen3.8-27B server for qwen_run.py (llama.cpp llama-server, Metal).
# Files, from huggingface.co/unsloth/Qwen3.8-27B-GGUF: Qwen3.8-27B-UD-Q2_K_XL.gguf (9.8 GB), mmproj-F16.gguf (0.9 GB).
# Measured on an M5 with 24 GB: about 15 GB resident, about 60 tokens/s reading, 6 tokens/s writing.
#  - 2 slots of 48k: slot 0 the explorer, slot 1 the confirmer (each keeps its own cached prompt)
#  - KV cache in q8_0 (only 16 of the 64 layers have attention; the rest are DeltaNet with a fixed state)
#  - thinking capped at 300 tokens: at effort low it still ran to 900+ tokens a turn (3 minutes), mostly
#    working out geometry the harness now gives it; at the cap the server closes the thinking with a nudge
#  - MTP speculative decoding was tried: 70% of drafts accepted, no faster on this quant, so off
set -euo pipefail
MODELS="${QWEN_MODELS:-$HOME/models/qwen3.8-27b}"
exec llama-server \
  -m "$MODELS/Qwen3.8-27B-UD-Q2_K_XL.gguf" --mmproj "$MODELS/mmproj-F16.gguf" \
  --alias qwen3.8-27b --host 127.0.0.1 --port "${QWEN_PORT:-8080}" \
  -c 98304 -np 2 -ngl 99 -fa on --cache-type-k q8_0 --cache-type-v q8_0 \
  --jinja --reasoning-format deepseek \
  --reasoning-budget 300 --reasoning-budget-message " Enough thinking: act now with one tool call."
