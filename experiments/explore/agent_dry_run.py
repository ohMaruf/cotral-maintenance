"""Dry-run the explorer with a Claude Code model as the LLM, sandboxed to our tools only.

For each stop: a run directory data/agent_runs/<stop>_<time>/, then a headless
Claude Code session (`claude -p`) that has NO built-in tools, no user settings,
hooks or CLAUDE.md, and only the MCP server experiments/explore/agent_server.py.
Its system prompt is experiments/explore/agent_prompt.md. No API key is used: it
runs on the Claude Code login. Photos are rendered from Map Tiles (billed per
tile, cached in data/tiles/): at most 12 sweeps, 30 zooms and 6 confirmations per
stop. Each confirmation is a fresh, tool-less `claude -p` call (confirmer.py).

Written per run: config.json, mcp.json, transcript.jsonl (the model's whole
session, stream-json), record.json (every tool call, photo and the outcome, from
the server), photos/, maps/, confirmer/ (each confirmer call), and summary.json
(the outcome scored against the verified position, which the explorer never sees).

Usage, from the repository root:
    .venv/bin/python experiments/explore/agent_dry_run.py f13457 [f9388 ...] [--model haiku]
        [--confirmer-model haiku]
"""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.explorer import HARNESS_VERSION
from cotral_maintenance.explorer.quota import MonthlyLedger
from cotral_maintenance.explorer.session import MAX_IMAGES, MAX_TILES
from cotral_maintenance.geo import distance_m

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data/agent_runs"
SERVER = ROOT / "experiments/explore/agent_server.py"
PROMPT = ROOT / "experiments/explore/agent_prompt.md"
TRUTH = ROOT / "data/ground_truth_manual.csv"
LEDGER = ROOT / "data/agent_runs/usage.json"  # billed requests per month, against Google's free tiers
TIMEOUT_S = 45 * 60
CHILD_ENV_DROP = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET",
                  "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED"}


def harness(model: str, confirmer_model: str) -> dict:
    """What produced a run: the harness version, the code (git commit, uncommitted changes) and the prompt."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    return {"version": HARNESS_VERSION, "git_commit": git("rev-parse", "HEAD"),
            "git_dirty": bool(git("status", "--porcelain")),
            "prompt_sha256": hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
            "explorer_model": model, "confirmer_model": confirmer_model}


def run_stop(stop_id: str, model: str, confirmer_model: str) -> dict:
    run_dir = RUNS / f"{stop_id}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    run_dir.mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps({"stop_id": stop_id, "model": model,
                                                     "confirmer_model": confirmer_model,
                                                     "harness": harness(model, confirmer_model)}, indent=1))
    mcp = {"mcpServers": {"explorer": {
        "type": "stdio", "command": str(ROOT / ".venv/bin/python"), "args": [str(SERVER)],
        "env": {"EXPLORER_RUN_DIR": str(run_dir)},
    }}}
    (run_dir / "mcp.json").write_text(json.dumps(mcp, indent=1))
    command = [
        "claude", "-p", f"Find bus stop {stop_id}. Start with begin().",
        "--model", model,
        "--tools", "",  # no built-in tools at all
        "--strict-mcp-config", "--mcp-config", str(run_dir / "mcp.json"),
        "--allowedTools", "mcp__explorer__*",
        "--system-prompt-file", str(PROMPT),
        "--setting-sources", "",  # no user/project settings, hooks or CLAUDE.md
        "--no-session-persistence",
        "--output-format", "stream-json", "--verbose",
    ]
    # The child runs on the Claude Code login: no API key, and none of this session's internal variables.
    env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}
    started = time.monotonic()
    with (run_dir / "transcript.jsonl").open("w") as out, (run_dir / "claude.stderr").open("w") as err:
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=out, stderr=err, timeout=TIMEOUT_S).returncode
    summary = summarise(stop_id, run_dir, code, time.monotonic() - started)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def summarise(stop_id: str, run_dir: Path, code: int, seconds: float) -> dict:
    record = json.loads((run_dir / "record.json").read_text()) if (run_dir / "record.json").is_file() else {}
    outcome = record.get("outcome") or {"status": "unfinished"}
    truth = {r["stop_id"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(TRUTH.open(encoding="utf-8"))}
    events = record.get("events", [])
    transcript = run_dir / "transcript.jsonl"  # Claude Code runs only (Qwen runs log qwen_transcript.jsonl)
    lines = [json.loads(line) for line in transcript.read_text().splitlines() if line.strip()] \
        if transcript.is_file() else []
    final = next((x for x in reversed(lines) if x.get("type") == "result"), {})
    summary = {
        "stop_id": stop_id, "run_dir": str(run_dir.relative_to(ROOT)), "exit_code": code,
        "seconds": round(seconds), "status": outcome.get("status"), "reason": outcome.get("reason"),
        "evidence": outcome.get("evidence"), "photos": len(record.get("photos", [])),
        "used": (record.get("budget") or {}).get("used"), "billed_requests": record.get("billed_requests"),
        "harness": (record.get("harness") or {}).get("version"), "tool_calls": len(events),
        "tool_errors": sum(1 for e in events if e.get("error")), "num_turns": final.get("num_turns"),
        "report": final.get("result"),
    }
    if stop_id in truth:
        t = truth[stop_id]
        stop = record.get("stop") or {}
        if stop:
            summary["err_gtfs_m"] = round(distance_m(stop["lat"], stop["lon"], *t), 1)
        if outcome.get("lat") is not None:
            summary["err_found_m"] = round(distance_m(outcome["lat"], outcome["lon"], *t), 1)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stops", nargs="+")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--confirmer-model", default=None, help="the fresh confirmer call's model (default: --model)")
    args = parser.parse_args()
    ledger = MonthlyLedger(LEDGER)
    for stop_id in args.stops:
        left = ledger.remaining()
        if not left.covers(MAX_IMAGES, MAX_TILES):
            print(f"Stopping before {stop_id}: the free tier of {left.month} has {left.static} Static images and "
                  f"{left.tiles} tiles left, less than one stop may need ({MAX_IMAGES} and {MAX_TILES}). "
                  f"Resume next month.")
            return 0
        summary = run_stop(stop_id, args.model, args.confirmer_model or args.model)
        billed = summary.get("billed_requests") or {}
        ledger.add(summary["run_dir"], billed.get("static", 0), billed.get("tiles", 0))
        print(json.dumps({k: v for k, v in summary.items() if k != "report"}))
        print(f"report: {summary.get('report')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
