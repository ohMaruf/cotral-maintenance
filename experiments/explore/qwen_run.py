"""Explore with the local Qwen3.8-27B (Unsloth UD-Q2_K_XL GGUF on llama-server) as the LLM.

The same harness as the Claude Code runs (setup.py builds the identical session); only the loop differs:
Chat Completions with function tools, run here. Built around what the model and the server do (measured,
docs/explore-harness-versions.md, 0.11):
  - points on photos are on Qwen's native 0-1000 grid (it located a sign within 3 px that way)
  - photos go inside the tool results (the chat template renders them there), with the text they belong to
  - every turn must be a tool call (tool_choice required: the server constrains the output, so no
    malformed replies); the run ends on an outcome, a stall, a repeated failing call or the turn cap
  - thinking on, effort low (about 100 tokens a turn at about 6 tokens/s), and the thinking kept in the
    history (preserve_thinking, the template's default) so every request only extends the cached prompt:
    a hybrid DeltaNet model can't roll its cache back, and a changed prefix would re-read the whole run
  - the explorer and the confirmer each keep their own server slot, so a confirmation doesn't evict the
    explorer's cache
  - Qwen's recommended sampling for thinking: temperature 1.0, top_p 0.95, top_k 20

Start the server first (experiments/explore/qwen_server.sh), then, from the repository root:
    .venv/bin/python experiments/explore/qwen_run.py f7824 f13457 f9388 [--confirmer qwen|haiku]
"""

import argparse
import base64
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_dry_run import LEDGER, PROMPT, ROOT, RUNS, harness, summarise  # noqa: E402
from confirmer import ClaudeCodeConfirmer, QwenConfirmer  # noqa: E402
from setup import LOOKALIKES, REFERENCE, build_session  # noqa: E402

from cotral_maintenance.explorer.drawing import draw_map  # noqa: E402
from cotral_maintenance.explorer.quota import MonthlyLedger  # noqa: E402
from cotral_maintenance.explorer.session import GRID, MAX_IMAGES, MAX_TILES, Session, ToolError  # noqa: E402

MODEL = "qwen3.8-27b"  # the server's --alias
RUNTIME = "llama.cpp llama-server, Qwen3.8-27B-UD-Q2_K_XL.gguf + mmproj-F16.gguf"
EXPLORER_SLOT, CONFIRMER_SLOT = 0, 1
SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0}
TEMPLATE = {"reasoning_effort": "low", "preserve_thinking": True}
MAX_TOKENS = 3000  # thinking + the call; a reply cut off here is retried
MAX_TURNS = 90
MAX_INVALID = 3  # failed requests or cut-off replies in a row
MAX_REPEATS = 4  # the same failing call this many times in a row
STALL_NUDGE, STALL_END = 4, 8  # turns in a row that change nothing: a nudge, then the end
REFERENCE_PX = 640


def fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


NUM = {"type": "number"}
INT = {"type": "integer"}
POINT = (f"x, y: a point on the photo on a 0-{GRID} grid (0,0 top left, {GRID},{GRID} bottom right), "
         "whatever the photo's size")
TOOLS = [
    fn("begin", "Start the search. Returns the briefing, the reference Cotral sign, the look-alikes, the two opening "
       "photos and the state. Call it once, first.", {}, []),
    fn("sweep", "Costs 1 image. One wide photo (fov 110) from the panorama nearest from_m metres along the path. "
       "facing 'ahead': from straight ahead along the road round to straight right. facing 'behind': from straight "
       "right round to straight back.",
       {"from_m": NUM, "facing": {"type": "string", "enum": ["ahead", "behind"]}}, ["from_m", "facing"]),
    fn("zoom", f"Costs about 2-4 tiles. A sharp close-up centred on a point of a photo, from the same panorama. "
       f"{POINT}. fov 5-20 degrees (10 is a good start). The harness judges every zoom at once and, when needed, "
       f"looks from another panorama too.", {"photo": INT, "x": NUM, "y": NUM, "fov": NUM}, ["photo", "x", "y", "fov"]),
    fn("look_from", "Costs about 2-4 tiles. A close-up of a candidate from ANOTHER panorama: a new viewpoint.",
       {"candidate": INT}, ["candidate"]),
    fn("mark_candidate", f"Free. Mark something that may be the stop on a photo: point where it meets the ground. "
       f"{POINT}. kind: sign, shelter, pole_with_panel, bench, road_marking, people_waiting. same_as: the candidate "
       f"this is a second view of (from another panorama), else leave it out.",
       {"photo": INT, "x": NUM, "y": NUM,
        "kind": {"type": "string", "enum": ["sign", "shelter", "pole_with_panel", "bench", "road_marking",
                                            "people_waiting"]}, "same_as": INT}, ["photo", "x", "y", "kind"]),
    fn("mark_clear", f"Free. In a sweep photo the right-hand sidewalk is clearly visible with nothing stop-like from "
       f"the camera up to a point: point at the FARTHEST clearly visible spot of that sidewalk. {POINT}.",
       {"photo": INT, "x": NUM, "y": NUM}, ["photo", "x", "y"]),
    fn("mark_hidden", f"Free. Part of the right-hand sidewalk can't be seen at a point. {POINT}.",
       {"photo": INT, "x": NUM, "y": NUM,
        "reason": {"type": "string", "enum": ["vehicle", "vegetation", "glare", "blur", "dirty_lens", "dark",
                                              "other"]}}, ["photo", "x", "y", "reason"]),
    fn("confirm", "Ask the confirmer again about a candidate you marked yourself on a close view.",
       {"candidate": INT}, ["candidate"]),
    fn("submit_found", "End the search: the stop is this CONFIRMED candidate.", {"candidate": INT}, ["candidate"]),
    fn("find_other_scans", "Free. Look for panoramas of other drives (other dates, the other carriageway) around "
       "at_m.", {"at_m": NUM}, ["at_m"]),
    fn("show_map", "Free. A drawn map of the search so far and the state.", {}, []),
]
SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


def check(name: str, args: dict) -> str | None:
    """Why a call doesn't match its tool's schema, in words the model can act on, or None."""
    schema = SCHEMAS.get(name)
    if schema is None:
        return f"there is no tool {name}; the tools are: {', '.join(SCHEMAS)}"
    missing = [k for k in schema["required"] if args.get(k) is None]
    if missing:
        return f"missing argument {', '.join(missing)}; {name} needs {', '.join(schema['required'])}"
    for k, v in args.items():
        spec = schema["properties"].get(k)
        if spec is None:
            return f"{name} has no argument {k}; its arguments are {', '.join(schema['properties']) or 'none'}"
        if v is None:
            continue
        if spec.get("type") in ("number", "integer") and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"{k} must be a number"
        if "enum" in spec and v not in spec["enum"]:
            return f"{k} must be one of {', '.join(spec['enum'])}"
    return None


def call(session: Session, name: str, args: dict):
    """Run one tool on the session."""
    def num(k, default=None):
        v = args.get(k, default)
        return None if v is None else float(v)

    def whole(k):
        return None if args.get(k) is None else int(args[k])

    if name == "begin":
        result = session.begin()
        refs = [REFERENCE, *sorted(LOOKALIKES.glob("*.png"))]
        return type(result)("REFERENCE (the first image): the Cotral bus stop sign. LOOK-ALIKES (the next images): "
                            "blue road signs that are NOT bus stops. Then the two opening photos.\n\n" + result.text,
                            refs + result.images)
    if name == "sweep":
        return session.sweep(num("from_m"), args["facing"])
    if name == "zoom":
        return session.zoom(whole("photo"), num("x"), num("y"), num("fov", 10.0))
    if name == "look_from":
        return session.look_from(whole("candidate"))
    if name == "mark_candidate":
        return session.mark_candidate(whole("photo"), num("x"), num("y"), args["kind"], whole("same_as"))
    if name == "mark_clear":
        return session.mark_clear(whole("photo"), num("x"), num("y"))
    if name == "mark_hidden":
        return session.mark_hidden(whole("photo"), num("x"), num("y"), args["reason"])
    if name == "confirm":
        return session.confirm(whole("candidate"))
    if name == "submit_found":
        return session.submit_found(whole("candidate"))
    if name == "find_other_scans":
        return session.find_other_scans(num("at_m"))
    if name == "show_map":
        return session.show_map(draw_map)
    raise ToolError(f"unknown tool {name}")


def image_part(path: Path, max_px: int | None = None) -> dict:
    img = Image.open(path).convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()}}


def tool_content(text: str, images: list[Path], session: Session) -> list[dict] | str:
    """A tool result with its photos in it, each labelled as the text calls it."""
    if not images:
        return text
    content = [{"type": "text", "text": text}]
    for path in images:
        index = next((p.index for p in session.photos if session._file(p) == path), None)
        content += [{"type": "text", "text": f"PHOTO {index}:" if index else f"{path.stem}:"},
                    image_part(path, None if index else REFERENCE_PX)]
    return content


def progress(session: Session) -> tuple:
    """What a useful turn changes: photos, candidates and their status, the sidewalk bookkeeping."""
    return (len(session.photos), tuple((c.status, len(c.views)) for c in session.candidates),
            tuple(session.state), session.outcome is not None)


def explore(session: Session, base_url: str, log) -> str:
    """The loop. Returns why it ended."""
    messages = [{"role": "system", "content": PROMPT.read_text()},
                {"role": "user", "content": f"Find bus stop {session.world.stop.stop_id}. Start with begin()."}]
    invalid = repeats = stalled = 0
    last_failure = None
    for turn in range(1, MAX_TURNS + 1):
        if session.outcome is not None:
            return "outcome"
        body = {"model": MODEL, "messages": messages, "tools": TOOLS, "tool_choice": "required",
                "max_tokens": MAX_TOKENS, "id_slot": EXPLORER_SLOT, "cache_prompt": True,
                "chat_template_kwargs": TEMPLATE, "seed": turn * 10 + invalid, **SAMPLING}
        started = time.monotonic()
        try:
            response = requests.post(f"{base_url}/chat/completions", json=body, timeout=1800)
        except requests.RequestException as error:
            return f"server unreachable: {error}"
        seconds = round(time.monotonic() - started, 1)
        if response.status_code != 200:
            invalid += 1
            log({"turn": turn, "seconds": seconds, "error": f"HTTP {response.status_code}: {response.text[:500]}"})
            if "context" in response.text.lower() and "exceed" in response.text.lower():
                return "context full"
            if invalid >= MAX_INVALID:
                return "invalid replies"
            continue
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        log({"turn": turn, "seconds": seconds, "finish": choice.get("finish_reason"), "usage": data.get("usage"),
             "timings": {k: data.get("timings", {}).get(k) for k in ("cache_n", "prompt_n", "predicted_n")},
             "reasoning": message.get("reasoning_content"), "content": message.get("content"),
             "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]} for c in calls]})
        if not calls:  # cut off before the call (tool_choice required makes any finished reply a call)
            invalid += 1
            if invalid >= MAX_INVALID:
                return "invalid replies"
            continue
        invalid = 0
        messages.append({"role": "assistant", "content": message.get("content") or "",
                         "reasoning_content": message.get("reasoning_content") or "", "tool_calls": calls})
        before = progress(session)
        failed = None
        for c in calls:
            name = c["function"]["name"]
            images: list[Path] = []
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                problem = check(name, args) if isinstance(args, dict) else "the arguments must be a JSON object"
                if problem:
                    raise ToolError(problem)
                result = call(session, name, args)
                text, images = result.text, list(result.images)
            except (ToolError, KeyError, TypeError, ValueError) as error:
                text = f"ERROR: {error}"
                failed = (name, c["function"]["arguments"])
                session.log_error(name, {"raw": c["function"]["arguments"]}, str(error))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": tool_content(text, images, session)})
            log({"turn": turn, "tool": name, "result": text[:4000], "images": [p.name for p in images]})
            if session.outcome is not None:
                break
        repeats = repeats + 1 if failed is not None and failed == last_failure else (1 if failed else 0)
        last_failure = failed
        if repeats >= MAX_REPEATS:
            return "stuck repeating a failing call"
        stalled = 0 if progress(session) != before else stalled + 1
        if stalled >= STALL_END:
            return "stalled"
        nudge = None
        if repeats >= 2:
            nudge = "That call failed again with the same error. Read the error, fix the arguments or do something else."
        elif stalled == STALL_NUDGE:
            nudge = ("The last turns changed nothing. Take one of the BEST NEXT SWEEPS, examine a corner, or zoom on "
                     "something stop-like you haven't zoomed on.")
        if nudge:  # appended to the last tool result, so the history stays an exact extension of the cached prompt
            last = messages[-1]
            last["content"] = (last["content"] + f"\n\nHARNESS: {nudge}" if isinstance(last["content"], str)
                               else [*last["content"], {"type": "text", "text": f"HARNESS: {nudge}"}])
    return "turn cap"


def run_stop(stop_id: str, base_url: str, confirmer: str) -> dict:
    run_dir = RUNS / f"{stop_id}_{datetime.now(UTC):%Y%m%dT%H%M%S}"
    run_dir.mkdir(parents=True)
    confirmer_model = MODEL if confirmer == "qwen" else "haiku"
    config = {"stop_id": stop_id, "model": MODEL, "confirmer_model": confirmer_model, "runtime": RUNTIME,
              "sampling": SAMPLING, "template": TEMPLATE, "harness": harness(MODEL, confirmer_model)}
    (run_dir / "config.json").write_text(json.dumps(config, indent=1))
    lookalikes = sorted(LOOKALIKES.glob("*.png"))

    def make_confirmer(log_dir: Path):
        if confirmer == "qwen":
            return QwenConfirmer(base_url, MODEL, REFERENCE, lookalikes, log_dir, CONFIRMER_SLOT)
        return ClaudeCodeConfirmer("haiku", REFERENCE, lookalikes, ROOT, log_dir)

    session = build_session(run_dir, config, make_confirmer)
    log_file = (run_dir / "qwen_transcript.jsonl").open("w")

    def log(entry: dict) -> None:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log_file.flush()

    started = time.monotonic()
    try:
        ended = explore(session, base_url, log)
    finally:
        log_file.close()
    session.finish(f"the explorer ended: {ended}")
    summary = summarise(stop_id, run_dir, 0, time.monotonic() - started)
    summary["ended"] = ended
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stops", nargs="+")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--confirmer", choices=("qwen", "haiku"), default="qwen")
    args = parser.parse_args()
    ledger = MonthlyLedger(LEDGER)
    for stop_id in args.stops:
        left = ledger.remaining()
        if not left.covers(MAX_IMAGES, MAX_TILES):
            print(f"Stopping before {stop_id}: the free tier of {left.month} is nearly used. Resume next month.")
            return 0
        summary = run_stop(stop_id, args.base_url, args.confirmer)
        billed = summary.get("billed_requests") or {}
        ledger.add(summary["run_dir"], billed.get("static", 0), billed.get("tiles", 0))
        print(json.dumps({k: v for k, v in summary.items() if k != "report"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
