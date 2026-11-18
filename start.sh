#!/usr/bin/env zsh
# Start the review app: the BFF (FastAPI) and the web app (Angular).
#
#   ./start.sh --run runs/<RUN>          development: BFF on :8765, Angular dev server on :4200
#                                        (live reload; /api is proxied to the BFF)
#   ./start.sh --prod --run runs/<RUN>   build the web app once and let the BFF serve it on :8765
#   --port N       the port to open in the browser (dev: the web app, default 4200; prod: the BFF, 8765)
#   --bff-port N   the BFF's port in development (default 8765)
#
# --run is the run directory to show (relative to the repository root); it falls back to
# $COTRAL_REVIEW_RUN. Dependencies are installed when missing or out of date. Ctrl-C stops everything.
# Other arguments after the mode go to `cotral_review serve`, e.g. --database PATH.
emulate -L zsh
setopt err_exit no_unset pipe_fail

ROOT=${0:A:h}
UI=$ROOT/review-ui
BFF_PORT=${COTRAL_REVIEW_PORT:-8765}
UI_PORT=4200

mode=dev
if [[ ${1:-} == --prod ]]; then mode=prod; shift; fi
if [[ ${1:-} == (-h|--help) ]]; then sed -n '2,12p' $0; exit 0; fi

log() { print -P "%B[start]%b $*" }
die() { print -P "%F{red}[start]%f $*" >&2; exit 1 }

typeset -a bff_args
while (( $# )); do
  case $1 in
    --run) (( $# > 1 )) || die "--run needs a run directory, e.g. --run runs/<RUN>"
           export COTRAL_REVIEW_RUN=$2; shift 2 ;;
    --run=*) export COTRAL_REVIEW_RUN=${1#--run=}; shift ;;
    --port|--bff-port)
           (( $# > 1 )) && [[ $2 == <1-65535> ]] || die "$1 needs a port number"
           if [[ $1 == --bff-port || $mode == prod ]]; then BFF_PORT=$2; else UI_PORT=$2; fi
           shift 2 ;;
    --port=*|--bff-port=*)
           value=${1#*=}; [[ $value == <1-65535> ]] || die "${1%%=*} needs a port number"
           if [[ $1 == --bff-port=* || $mode == prod ]]; then BFF_PORT=$value; else UI_PORT=$value; fi
           shift ;;
    *) bff_args+=($1); shift ;;
  esac
done
set -- $bff_args
[[ -n ${COTRAL_REVIEW_RUN:-} ]] || die "no run to show: ./start.sh --run runs/<RUN>"
run_dir=$COTRAL_REVIEW_RUN; [[ $run_dir == /* ]] || run_dir=$ROOT/$run_dir
[[ -f $run_dir/run.sqlite ]] || die "no run at $run_dir (missing run.sqlite)"

(( $+commands[uv] )) || die "uv is not installed (https://docs.astral.sh/uv/)"
(( $+commands[fnm] )) || die "fnm is not installed (brew install fnm)"

port_free() { ! lsof -iTCP:$1 -sTCP:LISTEN -t >/dev/null 2>&1 }
port_free $BFF_PORT || die "port $BFF_PORT is already in use"
[[ $mode == prod ]] || port_free $UI_PORT || die "port $UI_PORT is already in use"

log "Python dependencies"
uv sync --quiet --inexact --extra review --project $ROOT  # --inexact: keep other extras (agent, osm)

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
  # /api goes to the BFF on whatever port it got (proxy.conf.json holds only the default).
  proxy=$(mktemp -t cotral-proxy).json
  print -r -- "{\"/api\": {\"target\": \"http://127.0.0.1:$BFF_PORT\", \"secure\": false, \"changeOrigin\": false}}" > $proxy
  # stdin from /dev/null: a background job must never wait on a terminal prompt.
  npm start -- --host 127.0.0.1 --port $UI_PORT --proxy-config $proxy </dev/null &
  pids+=($!)
  # Stop as soon as either process exits, so a crash is not hidden.
  while kill -0 $pids[1] 2>/dev/null && kill -0 $pids[2] 2>/dev/null; do sleep 1; done
  log "a process exited, stopping"
fi
