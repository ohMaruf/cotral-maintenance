"""Score bus stops with Gemma 4 26B-A4B (TurboFieldfare) to compare against Clef.

Same stops, photos, wording and categories as phase 3 (cotral_maintenance.scoring):
one request per stop with all its photos and all questions together.

Structured output only. The TurboFieldfare server has no constrained decoding
(response_format json_schema is refused), so the answer must come through one
function tool, submit_assessment, whose arguments are checked against the schema
here. A response with no tool call, with free text, or with arguments that do not
match the schema is rejected and retried; after --attempts failures the stop is
recorded as failed, never parsed from prose.

Gemma gives no probabilities, so scores are integer levels 0-4 rather than Clef's
expected levels, and classifiable is 1.0 or 0.0 (sign visible or not).

Needs a running server, from turbo-fieldfare/:
    .build/release/TurboFieldfareServer --model scratch/gemma4.gturbo

Usage, from the repository root:
    .venv/bin/python experiments/gemma/score_stops.py [--limit 10]
"""

import argparse
import base64
import csv
import json
import sys
import time
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.scoring import (  # noqa: E402
    AREA_LEVELS, AREAS, ELEMENT_LEVELS, ELEMENTS, QUESTIONS, StopScores, VIEW_ROLES,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL = "gemma-4-26b-a4b-it"
TOOL = "submit_assessment"
LEVELED = [*ELEMENTS, *AREAS, "requires_maintenance"]


def level_text(levels: list[str]) -> str:
    return "; ".join(f"{i} = {text}" for i, text in enumerate(levels))


def build_tool() -> dict:
    # Flat on purpose: nested objects in tool arguments came back as calls the
    # server's Gemma tool-call parser rejects as malformed.
    properties = {}
    for name in LEVELED:
        levels = ELEMENT_LEVELS if name in ELEMENTS else AREA_LEVELS
        properties[f"{name}_level"] = {
            "type": "integer",
            "description": f"{QUESTIONS[name]['instructions']} Levels: {level_text(levels)}.",
        }
        properties[f"{name}_evidence"] = {
            "type": "string",
            "description": f"One short sentence: what in which photo supports {name}_level.",
        }
    properties["sign_visible"] = {"type": "boolean", "description": QUESTIONS["classifiable"]["instructions"]}
    properties["sign_evidence"] = {
        "type": "string", "description": "One short sentence: where the sign is, or why none is seen.",
    }
    return {
        "type": "function",
        "function": {
            "name": TOOL,
            "description": "Submit the maintenance assessment of the bus stop. This is the only way to answer.",
            "parameters": {"type": "object", "properties": properties, "required": list(properties)},
        },
    }


KEYS = list(build_tool()["function"]["parameters"]["properties"])


def validate(args: object) -> list[str]:
    """Schema check of the tool arguments; returns the problems, empty when valid."""
    if not isinstance(args, dict):
        return ["arguments are not an object"]
    problems = [f"unexpected key {k!r}" for k in args if k not in KEYS]
    problems += [f"missing key {k!r}" for k in KEYS if k not in args]
    for key, value in args.items():
        if key.endswith("_evidence") and not isinstance(value, str):
            problems.append(f"{key}: not a string")
        elif key.endswith("_level") and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4):
            problems.append(f"{key}: {value!r} is not an integer in 0-4")
        elif key == "sign_visible" and not isinstance(value, bool):
            problems.append(f"{key}: not a boolean")
    return problems


def build_messages(manifest: dict, stop_dir: Path) -> list[dict]:
    views = [image["view"] for image in manifest["images"]]
    system = "\n\n".join([
        f"These {len(views)} street-level photos cover the sidewalk where a Cotral bus stop is mapped. The mapped "
        "position can be tens of metres off, so the stop may appear in any of them. Find it and judge it using all "
        "photos together. A stop on the far side of the road is a different stop: ignore it.",
        "Cotral is the regional bus operator of Lazio, Italy. Its stops are marked by a blue sign on a pole, "
        "sometimes with a timetable panel, and may have a shelter and seating.",
        "The photos are cut from Google Street View panoramas taken from a moving car. Blur, stitching seams, "
        "vertical objects that look sliced, bent or doubled, blurred faces and number plates, and parts of the "
        "camera car at the bottom are artifacts of the camera, not damage at the stop. Do not let them affect any "
        "score.",
        f"Answer only by calling {TOOL} exactly once. Write no text outside the tool call.",
    ])
    content: list[dict] = [{"type": "text", "text": f"Stop name: {manifest['stop']['name']}"}]
    for i, image in enumerate(manifest["images"], 1):
        data = base64.b64encode((stop_dir / image["file"]).read_bytes()).decode()
        content.append({"type": "text", "text": f"Photo {i}: {VIEW_ROLES.get(image['view'], image['view'])}"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
    questions = [f"- {name}: {QUESTIONS[name]['instructions']}" for name in [*LEVELED, "classifiable"]]
    content.append({"type": "text", "text": "Assess the stop and call the tool with:\n" + "\n".join(questions)})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def ask(base_url: str, messages: list[dict], tool: dict, attempt: int, timeout: float) -> tuple[dict, dict | None, list[str]]:
    """One request. Returns (response, arguments or None, problems)."""
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": [tool],
        "tool_choice": "auto",
        # Greedy first; later attempts sample so a retry can differ.
        "temperature": 0 if attempt == 1 else 0.3,
        "seed": attempt,
        "max_completion_tokens": 1500,
    }
    response = requests.post(f"{base_url}/chat/completions", json=body, timeout=timeout)
    if response.status_code != 200:
        # e.g. 500 structured_output_failure: the server could not parse the model's tool call.
        return {"status": response.status_code, "body": response.text}, None, [f"HTTP {response.status_code}: {response.text[:300]}"]
    data = response.json()
    message = data["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    problems = []
    if (message.get("content") or "").strip():
        problems.append("free text outside the tool call")
    if len(calls) != 1 or calls[0]["function"]["name"] != TOOL:
        problems.append(f"expected one {TOOL} call, got {[c['function']['name'] for c in calls]}")
        return data, None, problems
    try:
        args = json.loads(calls[0]["function"]["arguments"])
    except json.JSONDecodeError as exc:
        return data, None, [*problems, f"arguments are not JSON: {exc}"]
    problems += validate(args)
    return data, (args if not problems else None), problems


def score_row(record: dict) -> StopScores:
    args = record["arguments"]
    return StopScores(
        stop_id=record["stop"]["stop_id"],
        stop_name=record["stop"]["name"],
        imagery_date=record["imagery_date"],
        **{name: float(args[f"{name}_level"]) for name in LEVELED},
        classifiable=1.0 if args["sign_visible"] else 0.0,
        image_count=len(record["images"]),
        latency_s=record["latency_s"],
        scored_at=record["scored_at"],
    )


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def write_comparison(gemma: list[StopScores], clef_csv: Path, out: Path) -> None:
    if not clef_csv.exists():
        return
    clef = {row["stop_id"]: row for row in csv.DictReader(clef_csv.open(encoding="utf-8"))}
    header = ["stop_id", "stop_name"]
    for name in [*LEVELED, "classifiable"]:
        header += [f"{name}_clef", f"{name}_gemma", f"{name}_diff"]
    rows = []
    for g in gemma:
        c = clef.get(g.stop_id)
        if c is None:
            continue
        row = {"stop_id": g.stop_id, "stop_name": g.stop_name}
        for name in [*LEVELED, "classifiable"]:
            cv, gv = float(c[name]), getattr(g, name)
            row |= {f"{name}_clef": cv, f"{name}_gemma": gv, f"{name}_diff": round(gv - cv, 3)}
        rows.append(row)
    write_csv(out, header, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, default=ROOT / "images")
    parser.add_argument("--raw", type=Path, default=HERE / "scores_raw")
    parser.add_argument("--out", type=Path, default=HERE / "stop_scores.csv")
    parser.add_argument("--clef", type=Path, default=ROOT / "data/stop_scores.csv")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--force", action="store_true", help="rescore stops already in --raw")
    args = parser.parse_args()

    args.raw.mkdir(parents=True, exist_ok=True)
    tool = build_tool()
    stop_dirs = sorted(p for p in args.images.iterdir() if (p / "stop.json").is_file())[: args.limit]
    for index, stop_dir in enumerate(stop_dirs, 1):
        raw_path = args.raw / f"{stop_dir.name}.json"
        if raw_path.exists() and not args.force:
            continue
        manifest = json.loads((stop_dir / "stop.json").read_text())
        messages = build_messages(manifest, stop_dir)
        attempts = []
        start = time.perf_counter()
        for attempt in range(1, args.attempts + 1):
            t0 = time.perf_counter()
            response, parsed, problems = ask(args.base_url, messages, tool, attempt, args.timeout)
            attempts.append({"response": response, "problems": problems, "latency_s": round(time.perf_counter() - t0, 2)})
            if parsed is not None:
                break
            print(f"  {stop_dir.name} attempt {attempt} rejected: {problems}", file=sys.stderr)
        latency = time.perf_counter() - start
        record = {
            "stop": manifest["stop"],
            "model": {"id": MODEL, "runtime": "TurboFieldfare"},
            "imagery_date": manifest["imagery_date"],
            "images": [image["file"] for image in manifest["images"]],
            "tool": tool,
            "arguments": parsed,
            "attempts": attempts,
            "latency_s": round(latency, 2),
            "scored_at": datetime.now(UTC).isoformat(),
        }
        raw_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        usage = attempts[-1]["response"].get("usage") or {}
        status = "ok" if parsed else "FAILED"
        levels = " ".join(f"{n[:6]}={parsed[f'{n}_level']}" for n in LEVELED) if parsed else ""
        sign = f"sign={parsed['sign_visible']}" if parsed else ""
        print(f"[{index}/{len(stop_dirs)}] {stop_dir.name} {status} {levels} {sign} "
              f"{latency:.1f}s ({usage.get('prompt_tokens')} in, {usage.get('completion_tokens')} out, "
              f"{len(attempts)} attempt(s))")

    records = [json.loads(p.read_text()) for p in sorted(args.raw.glob("*.json"))]
    rows = [score_row(r) for r in records if r["arguments"] is not None]
    write_csv(args.out, [f.name for f in fields(StopScores)], [asdict(r) for r in rows])
    write_comparison(rows, args.clef, HERE / "comparison.csv")
    failed = [r["stop"]["stop_id"] for r in records if r["arguments"] is None]
    print(f"Wrote {len(rows)} rows to {args.out}" + (f"; failed: {failed}" if failed else ""))


if __name__ == "__main__":
    main()
