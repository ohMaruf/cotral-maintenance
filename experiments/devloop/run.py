import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from claude_client import child_env

PROMPT = ROOT / "cotral_maintenance" / "explorer" / "prompt.md"


def explore(stop: str, args, out: Path) -> dict:
    folder = out / stop
    folder.mkdir(parents=True, exist_ok=True)
    config = {"mcpServers": {"explorer": {
        "command": "uv", "args": ["run", "--extra", "agent", "python", str(HERE / "server.py")],
        "cwd": str(ROOT),
        "env": {"DEVLOOP_STOP": stop, "DEVLOOP_SOURCE_RUN": args.source_run, "DEVLOOP_OUT": str(out),
                "DEVLOOP_MAX_TURNS": str(args.max_turns), "DEVLOOP_VISION_MODEL": args.vision_model}}}}
    (folder / "mcp.json").write_text(json.dumps(config, indent=1))
    command = ["claude", "-p", "--model", args.model, "--mcp-config", str(folder / "mcp.json"), "--strict-mcp-config",
               "--setting-sources", "", "--tools", "", "--allowedTools", "mcp__explorer__*",
               "--no-session-persistence", "--output-format", "stream-json", "--verbose",
               "--max-turns", str(args.max_turns + 10), "--system-prompt", PROMPT.read_text(),
               f"Find bus stop {stop}. Start with begin()."]
    with (folder / "agent.jsonl").open("w") as transcript:
        subprocess.run(command, stdout=transcript, stderr=subprocess.STDOUT, env=child_env(), cwd=ROOT,
                       timeout=args.timeout)
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()] \
        if (out / "results.jsonl").is_file() else []
    return next((r for r in reversed(rows) if r["stop"] == stop), {"stop": stop, "status": "no result"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Explore stops locally: a headless Claude Code agent drives the "
                                                 "harness over MCP; confirmer and scanner through claude -p.")
    parser.add_argument("stops", nargs="+")
    parser.add_argument("--source-run", required=True, help="the run whose ingested stops and starts are used")
    parser.add_argument("--tag", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--model", default="haiku", help="the explorer")
    parser.add_argument("--vision-model", default="haiku", help="the confirmer and the scanner")
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    out = ROOT / "data" / "devloop" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.parallel) as pool:
        results = list(pool.map(lambda s: explore(s, args, out), args.stops))
    for r in results:
        print(json.dumps(r))
    print(f"details: {out}")


if __name__ == "__main__":
    main()
