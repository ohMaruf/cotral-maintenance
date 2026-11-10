"""The confirmer for dry runs: a fresh, tool-less headless Claude Code call per candidate.

It sees the reference Cotral sign, the look-alikes and the candidate photo, nothing of
the search, and answers the checklist of cotral_maintenance/explorer/confirmer.py as
structured output (--json-schema). Runs on the Claude Code login, like the explorer.
"""

import base64
import io
import json
import os
import subprocess
from pathlib import Path

from PIL import Image

from cotral_maintenance.explorer.confirmer import ANSWERS, FEATURES, Checklist, ConfirmerError, instructions, parse

TIMEOUT_S = 180
MAX_REFERENCE_PX = 800
CHILD_ENV_DROP = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET",
                  "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED",
                  "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}
SYSTEM = ("You check photos of possible bus stops in Lazio, Italy, taken from Google Street View. You are strict and "
          "honest: you report only what you can actually see in the candidate photo.")
SCHEMA = {
    "type": "object",
    "properties": {**{k: {"type": "string", "enum": list(ANSWERS), "description": v} for k, v in FEATURES.items()},
                   "plate_text": {"type": "string"}, "note": {"type": "string"}},
    "required": [*FEATURES, "plate_text", "note"],
    "additionalProperties": False,
}


def _image_block(path: Path, max_px: int | None = None) -> dict:
    img = Image.open(path).convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buffer.getvalue()).decode()}}


class ClaudeCodeConfirmer:
    def __init__(self, model: str, reference: Path, lookalikes: list[Path], cwd: Path, log_dir: Path) -> None:
        self.model = model
        self.cwd = cwd
        self.log_dir = log_dir
        self.frozen = [
            {"type": "text", "text": "REFERENCE: the Cotral bus stop sign (navy panel, 'FERMATA', white Cotral logo, "
                                     "plate with the stop id)."},
            _image_block(reference, MAX_REFERENCE_PX),
            {"type": "text", "text": "LOOK-ALIKES: blue road signs that are NOT bus stops (pedestrian crossing, "
                                     "lanes, bus-lane signs with a bus pictogram, parking, directions)."},
            *(_image_block(p, MAX_REFERENCE_PX) for p in lookalikes),
        ]
        self.calls = 0

    def __call__(self, photo: Path) -> Checklist:
        self.calls += 1
        content = [*self.frozen, {"type": "text", "text": "CANDIDATE photo:"}, _image_block(photo),
                   {"type": "text", "text": instructions()}]
        message = {"type": "user", "message": {"role": "user", "content": content}}
        command = ["claude", "-p", "--model", self.model, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                   "--no-session-persistence", "--input-format", "stream-json", "--output-format", "stream-json",
                   "--verbose", "--json-schema", json.dumps(SCHEMA), "--system-prompt", SYSTEM]
        env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}
        try:
            run = subprocess.run(command, input=json.dumps(message) + "\n", capture_output=True, text=True, env=env,
                                 cwd=self.cwd, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as error:
            raise ConfirmerError("the confirmer timed out") from error
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / f"confirm_{self.calls:02d}_{photo.stem}.jsonl").write_text(run.stdout + run.stderr)
        result = next((json.loads(line) for line in reversed(run.stdout.splitlines())
                       if line.strip().startswith("{") and '"type":"result"' in line.replace(" ", "")), None)
        if result is None or result.get("is_error"):
            raise ConfirmerError(f"the confirmer call failed (exit {run.returncode})")
        structured = result.get("structured_output")
        return parse(json.dumps(structured) if isinstance(structured, dict) else str(result.get("result") or ""))


class QwenConfirmer:
    """The same checklist from the local Qwen3.8 server (llama-server, OpenAI-compatible). The answer comes as one
    function call (tool_choice required: the server constrains the output to the schema), checked by the same
    parser. It keeps its own server slot, so the frozen part (instructions, reference, look-alikes) stays cached
    and the explorer's cache is never evicted; thinking on, effort low."""

    TOOL = "submit_checklist"

    def __init__(self, base_url: str, model: str, reference: Path, lookalikes: list[Path], log_dir: Path,
                 slot: int, attempts: int = 3, timeout_s: float = 900.0) -> None:
        import requests  # only the local runs need it

        self.requests = requests
        self.base_url = base_url
        self.model = model
        self.log_dir = log_dir
        self.slot = slot
        self.attempts = attempts
        self.timeout_s = timeout_s
        self.frozen = [
            {"type": "text", "text": "REFERENCE: the Cotral bus stop sign (navy panel, 'FERMATA', white Cotral logo, "
                                     "plate with the stop id)."},
            _openai_image(reference, 640),
            {"type": "text", "text": "LOOK-ALIKES: blue road signs that are NOT bus stops (pedestrian crossing, "
                                     "lanes, bus-lane signs with a bus pictogram, parking, directions)."},
            *(_openai_image(p, 640) for p in lookalikes),
        ]
        self.tool = {"type": "function", "function": {
            "name": self.TOOL, "description": "Submit the checklist for the CANDIDATE photo.",
            "parameters": {"type": "object", "properties": {
                **{k: {"type": "string", "enum": list(ANSWERS), "description": v} for k, v in FEATURES.items()},
                "plate_text": {"type": "string", "description": "the stop id on the plate if readable, else empty"},
                "note": {"type": "string", "description": "a few words: what the object is"}},
                "required": [*FEATURES, "plate_text", "note"]}}}
        self.calls = 0

    def __call__(self, photo: Path) -> Checklist:
        self.calls += 1
        messages = [
            {"role": "system", "content": SYSTEM + f" Answer by calling {self.TOOL} once."},
            {"role": "user", "content": [*self.frozen, {"type": "text", "text": instructions()},
                                         {"type": "text", "text": "CANDIDATE photo:"}, _openai_image(photo)]},
        ]
        problems = []
        for attempt in range(1, self.attempts + 1):
            body = {"model": self.model, "messages": messages, "tools": [self.tool], "tool_choice": "required",
                    "id_slot": self.slot, "cache_prompt": True, "max_tokens": 3000, "seed": attempt,
                    "chat_template_kwargs": {"reasoning_effort": "low"},
                    "temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
            response = self.requests.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout_s)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir / f"confirm_{self.calls:02d}_{attempt}_{photo.stem}.json").write_text(response.text)
            if response.status_code != 200:
                problems.append(f"HTTP {response.status_code}")
                continue
            calls = response.json()["choices"][0]["message"].get("tool_calls") or []
            if len(calls) != 1 or calls[0]["function"]["name"] != self.TOOL:
                problems.append("no single checklist call")
                continue
            try:
                return parse(calls[0]["function"]["arguments"])
            except ConfirmerError as error:
                problems.append(str(error))
        raise ConfirmerError("; ".join(problems))


def _openai_image(path: Path, max_px: int | None = None) -> dict:
    img = Image.open(path).convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()}}
