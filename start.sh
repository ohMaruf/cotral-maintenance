#!/usr/bin/env zsh
# Start the review app: the BFF (FastAPI) and the web app (Angular).
#
#   ./start.sh          development: BFF on :8765, Angular dev server on :4200
#                       (live reload; /api is proxied to the BFF)
#   ./start.sh --prod   build the web app once and let the BFF serve it on :8765
#
# Dependencies are installed when missing or out of date. Ctrl-C stops everything.
# Extra arguments after the mode go to `cotral_review serve`, e.g. --database PATH.
emulate -L zsh
setopt err_exit no_unset pipe_fail

ROOT=${0:A:h}
UI=$ROOT/review-ui
BFF_PORT=8765   # must match review-ui/proxy.conf.json
UI_PORT=4200

mode=dev
if [[ ${1:-} == --prod ]]; then mode=prod; shift; fi
if [[ ${1:-} == (-h|--help) ]]; then sed -n '2,9p' $0; exit 0; fi

log() { print -P "%B[start]%b $*" }
die() { print -P "%F{red}[start]%f $*" >&2; exit 1 }

(( $+commands[uv] )) || die "uv is not installed (https://docs.astral.sh/uv/)"
(( $+commands[fnm] )) || die "fnm is not installed (brew install fnm)"

port_free() { ! lsof -iTCP:$1 -sTCP:LISTEN -t >/dev/null 2>&1 }
port_free $BFF_PORT || die "port $BFF_PORT is already in use"
[[ $mode == prod ]] || port_free $UI_PORT || die "port $UI_PORT is already in use"

log "Python dependencies"
uv sync --quiet --extra review --project $ROOT

log "Node $(<$UI/.node-version) via fnm"
eval "$(fnm env --shell zsh)"
cd $UI
fnm use --install-if-missing --silent-if-unchanged
# Reinstall when package-lock.json is newer than the last install.
if [[ ! -f node_modules/.package-lock.json || package-lock.json -nt node_modules/.package-lock.json ]]; then
  log "npm ci"
  npm ci --no-audit --no-fund
fi

typeset -a pids
cleanup() {
  trap - INT TERM EXIT
  (( ${#pids} )) && kill $pids 2>/dev/null
  wait 2>/dev/null
  return 0
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

serve_bff() {
  (cd $ROOT && exec $ROOT/.venv/bin/python -m cotral_review serve --port $BFF_PORT "$@") &
  local bff_pid=$!
  pids+=($bff_pid)
  repeat 60; do
    curl -fs http://127.0.0.1:$BFF_PORT/api/health >/dev/null 2>&1 && return 0
    kill -0 $bff_pid 2>/dev/null || die "the BFF exited during startup"
    sleep 0.5
  done
  die "the BFF did not become healthy on :$BFF_PORT"
}

if [[ $mode == prod ]]; then
  log "Building the web app"
  npm run build
  serve_bff "$@"
  log "Review app at http://127.0.0.1:$BFF_PORT  (API docs: /docs)"
  wait $pids[1]
else
  serve_bff "$@"
  log "BFF at http://127.0.0.1:$BFF_PORT  (API docs: /docs)"
  log "Web app at http://127.0.0.1:$UI_PORT"
  # stdin from /dev/null: a background job must never wait on a terminal prompt.
  npm start -- --host 127.0.0.1 --port $UI_PORT </dev/null &
  pids+=($!)
  # Stop as soon as either process exits, so a crash is not hidden.
  while kill -0 $pids[1] 2>/dev/null && kill -0 $pids[2] 2>/dev/null; do sleep 1; done
  log "a process exited, stopping"
fi
