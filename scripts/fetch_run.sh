#!/usr/bin/env bash
# Copy a run from the GPU server to this machine, incrementally, safe while the pipeline is still writing to it.
#
#   scripts/fetch_run.sh RUN              copy runs/RUN from the server into runs/RUN here
#   scripts/fetch_run.sh RUN --every 300  ... and again every 300 s, until Ctrl-C (follow a run in progress)
#   scripts/fetch_run.sh --list           the runs on the server
#
# Then: ./start.sh --run runs/RUN
#
# Server and path: COTRAL_REMOTE (default iseng@matrix.diag.uniroma1.it) and COTRAL_REMOTE_DIR (default
# ~/maruf/cotral-maintenance), in the environment or in .env.
#
# How: the database is copied as a consistent snapshot, taken on the server with SQLite's backup API (a plain
# copy of run.sqlite while the pipeline writes could be torn); then the photos, logs and results.csv are synced
# with rsync (only what is new is sent). The snapshot is taken before the photos are synced, so every photo it
# refers to is there. One SSH connection is shared by all steps (one password or key prompt).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
from_env_file() { [[ -f "$ROOT/.env" ]] && sed -n "s/^$1=//p" "$ROOT/.env" | tail -1; true; }
REMOTE="${COTRAL_REMOTE:-$(from_env_file COTRAL_REMOTE)}"
REMOTE_DIR="${COTRAL_REMOTE_DIR:-$(from_env_file COTRAL_REMOTE_DIR)}"
REMOTE="${REMOTE:-iseng@matrix.diag.uniroma1.it}"
REMOTE_DIR="${REMOTE_DIR:-~/maruf/cotral-maintenance}"
LOCAL_RUNS="$ROOT/runs"

log() { printf '\033[1m[fetch]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[fetch]\033[0m %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

run="" every=0 list=0
while (( $# )); do
  case "$1" in
    --every) [[ "${2:-}" =~ ^[0-9]+$ ]] || die "--every needs seconds"; every="$2"; shift 2 ;;
    --list) list=1; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) [[ -z "$run" ]] || die "one run at a time"; run="$1"; shift ;;
  esac
done
[[ $list -eq 1 || -n "$run" ]] || usage 2
[[ -z "$run" || "$run" =~ ^[A-Za-z0-9._-]+$ ]] || die "run names are letters, digits, . _ -"

# One shared SSH connection for every step.
ctl="$(mktemp -d)"
trap 'ssh -o ControlPath="$ctl/s" -O exit "$REMOTE" 2>/dev/null || true; rm -rf "$ctl"' EXIT
SSH=(ssh -o ControlMaster=auto -o ControlPath="$ctl/s" -o ControlPersist=600)
"${SSH[@]}" -o ConnectTimeout=20 "$REMOTE" true || die "cannot connect to $REMOTE"

if (( list )); then
  "${SSH[@]}" "$REMOTE" "cd $REMOTE_DIR/runs 2>/dev/null && for d in */; do [ -f \"\$d/run.sqlite\" ] && \
    printf '%-24s %s\n' \"\${d%/}\" \"\$(du -sh \"\$d\" | cut -f1)\"; done" || die "no runs/ in $REMOTE_DIR"
  exit 0
fi

fetch() {
  local remote_run="$REMOTE_DIR/runs/$run" local_run="$LOCAL_RUNS/$run"
  local snap=".fetch-snapshot.sqlite"
  # 1. a consistent snapshot of the database, on the server (Python's sqlite3: no sqlite3 CLI needed there)
  "${SSH[@]}" "$REMOTE" "cd $remote_run 2>/dev/null || { echo 'no run $run in $REMOTE_DIR/runs' >&2; exit 3; }
    python3 - <<'PY'
import sqlite3
src = sqlite3.connect('file:run.sqlite?mode=ro', uri=True)
dst = sqlite3.connect('$snap')
src.backup(dst)
dst.close(); src.close()
PY" || die "snapshot of $run on $REMOTE failed"
  mkdir -p "$local_run"
  # 2. the photos, logs and results (only what is new), then the snapshot as run.sqlite
  rsync -az --partial -e "${SSH[*]}" --exclude 'run.sqlite' --exclude 'run.sqlite-*' --exclude "$snap" \
    --exclude 'work/' "$REMOTE:$remote_run/" "$local_run/"
  rsync -az -e "${SSH[*]}" "$REMOTE:$remote_run/$snap" "$local_run/$snap.part"
  rm -f "$local_run/run.sqlite-wal" "$local_run/run.sqlite-shm"
  mv "$local_run/$snap.part" "$local_run/run.sqlite"
  "${SSH[@]}" "$REMOTE" "rm -f $remote_run/$snap" || true
  log "$run: $(du -sh "$local_run" | cut -f1) in runs/$run ($(date '+%H:%M:%S'))"
  local status
  if status="$(cd "$ROOT" && uv run --quiet cotral status "$run" 2>/dev/null)"; then
    python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print("  stops", d["stops"], "| explored", d["explored"], "| scored", d["scored"], "| billed", d["billed"])' \
      "$status" 2>/dev/null || true
  fi
}

fetch
while (( every > 0 )); do
  sleep "$every"
  fetch
done
log "Look at it: ./start.sh --run runs/$run"
