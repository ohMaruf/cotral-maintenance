"""The explorer and the confirmer as LLM calls, on any OpenAI-compatible chat server.

Two dialects, because servers differ in what they accept:
  llamacpp  llama-server. Every turn must be a tool call (tool_choice "required": the server
            constrains the output, so no malformed replies); each explorer and confirmer keeps its
            own server slot (id_slot) and the cached prompt (cache_prompt); thinking is controlled
            by chat_template_kwargs; photos go inside the tool results.
  strict    a plain OpenAI server that refuses unknown fields (TurboFieldfare): tool_choice "auto"
            (a reply without a call is answered with a reminder), no slots or template controls, and
            images only in user messages, so a tool result's photos follow it as a user message.

The loop keeps the history an exact extension of the previous request, so the server's prompt cache
is reused every turn. Reasoning is disabled at the server and deliberately never retained in the
history; harness nudges are appended to the last tool result.
"""

import base64
import io
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import requests
from PIL import Image

from .confirmer import ANSWERS, FEATURES, Checklist, ConfirmerError, instructions, parse
from .session import GRID, ScanReply, Session, ToolError

MAX_TURNS = 45  # successes took 3-13 turns (one 43) in test-nvfp4-5; failures ran to 50+ turns and overflowed a
                # 49k context (f9388). 45 turns at ~900 tokens each stay under it.
MAX_INVALID = 3  # failed requests or replies without a call, in a row
MAX_REPEATS = 4  # the same failing call this many times in a row
STALL_NUDGE, STALL_END = 4, 8  # turns in a row that change nothing: a nudge, then the end
REFERENCE_PX = 640
REQUEST_TIMEOUT_S = 1800.0
STRICT_FIELDS = ("temperature", "top_p", "top_k", "seed", "repetition_penalty")


@dataclass
class ChatClient:
    """One chat server, in one dialect."""

    base_url: str
    model: str
    dialect: str  # llamacpp | strict
    sampling: dict = field(default_factory=dict)
    template: dict = field(default_factory=dict)
    max_tokens: int = 3000
    session: requests.Session = field(default_factory=requests.Session)
    request: dict = field(default_factory=dict)  # optional backend-specific OpenAI fields

    def complete(self, messages: list[dict], tools: list[dict], slot: int | None, seed: int,
                 template: dict | None = None) -> tuple[int, dict | str, float]:
        """(HTTP status, JSON body or error text, seconds)."""
        body: dict = {**self.request, "model": self.model, "messages": messages, "max_tokens": self.max_tokens,
                      "seed": seed}
        if tools:
            body["tools"] = tools
        if self.dialect == "llamacpp":
            if tools:
                body["tool_choice"] = "required"
            body.update(self.sampling)
            body["chat_template_kwargs"] = template if template is not None else self.template
            body["cache_prompt"] = True
            if slot is not None:
                body["id_slot"] = slot
        else:
            if tools:
                body["tool_choice"] = "auto"
            body.update({k: v for k, v in self.sampling.items() if k in STRICT_FIELDS})
        started = time.monotonic()
        try:
            r = self.session.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as error:
            return 0, str(error), time.monotonic() - started
        seconds = time.monotonic() - started
        if r.status_code != 200:
            return r.status_code, r.text[:2000], seconds
        return 200, r.json(), seconds

    @property
    def images_in_tool_results(self) -> bool:
        return self.dialect == "llamacpp"


def image_part(path: Path, max_px: int | None = None) -> dict:
    img = Image.open(path).convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()}}


# ---------------------------------------------------------------------------------------------- tools

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
    fn("sweep", "Costs 1 image. One wide photo (fov 110) of the right-hand sidewalk around at_m metres along the "
       "path, from a panorama about 15 m before it, looking at it: away from the start, or back towards it when the "
       "stretch is BLOCKED from that side. Sweeps aim inside the SEARCH RING around the start, which widens every 2 "
       "sweeps.", {"at_m": NUM}, ["at_m"]),
    fn("zoom", f"Costs about 2-4 tiles. A sharp close-up centred on a point of a photo, from the same panorama. "
       f"{POINT}. fov 5-20 degrees (10 is a good start). what: the stop-like thing you SEE at that point, in a few "
       f"words (e.g. 'dark panel on a thin pole by the gate', 'shelter roof behind the parked van'). The harness judges "
       f"every zoom at once and, when needed, looks from another panorama too.",
       {"photo": INT, "x": NUM, "y": NUM, "fov": NUM, "what": {"type": "string"}}, ["photo", "x", "y", "fov", "what"]),
    fn("look_from", "Costs about 2-4 tiles. A close-up of a candidate from ANOTHER panorama: a new viewpoint.",
       {"candidate": INT}, ["candidate"]),
    fn("mark_candidate", f"Free. Mark something that may be the stop on a photo: point where it meets the ground. "
       f"{POINT}. kind: sign, shelter, pole_with_panel, bench, road_marking, people_waiting. same_as: the candidate "
       f"this is a second view of (from another panorama), else leave it out.",
       {"photo": INT, "x": NUM, "y": NUM,
        "kind": {"type": "string", "enum": ["sign", "shelter", "pole_with_panel", "bench", "road_marking",
                                            "people_waiting"]}, "same_as": INT}, ["photo", "x", "y", "kind"]),
    fn("confirm", "Ask the confirmer about a candidate you marked yourself on a close view it has not "
       "judged yet (the same photo always gets the same answer).",
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


def call(session: Session, name: str, args: dict, references: list[Path], draw_map: Callable):
    """Run one tool on the session."""
    def num(k, default=None):
        v = args.get(k, default)
        return None if v is None else float(v)

    def whole(k):
        return None if args.get(k) is None else int(args[k])

    if name == "begin":
        result = session.begin()
        return type(result)("REFERENCE (the first image): the Cotral bus stop sign. LOOK-ALIKES (the next images): "
                            "blue road signs that are NOT bus stops. Then " + ("the map and " if session.aerial
                                                                              else "") +
                            "the two opening photos.\n\n" + result.text,
                            references + result.images)
    if name == "sweep":
        return session.sweep(num("at_m"))
    if name == "zoom":
        return session.zoom(whole("photo"), num("x"), num("y"), num("fov", 10.0), what=str(args.get("what") or ""))
    if name == "look_from":
        return session.look_from(whole("candidate"))
    if name == "mark_candidate":
        return session.mark_candidate(whole("photo"), num("x"), num("y"), args["kind"], whole("same_as"))
    if name == "confirm":
        return session.confirm(whole("candidate"))
    if name == "submit_found":
        return session.submit_found(whole("candidate"))
    if name == "find_other_scans":
        return session.find_other_scans(num("at_m"))
    if name == "show_map":
        return session.show_map(draw_map)
    raise ToolError(f"unknown tool {name}")


def _photo_parts(images: list[Path], session: Session) -> list[dict]:
    parts = []
    for path in images:
        index = next((p.index for p in session.photos if session._file(p) == path), None)
        if path == session.aerial:  # at full size: its labels are small
            parts += [{"type": "text", "text": "MAP:"}, image_part(path)]
            continue
        parts += [{"type": "text", "text": f"PHOTO {index}:" if index else f"{path.stem}:"},
                  image_part(path, None if index else REFERENCE_PX)]
    return parts


def progress(session: Session) -> tuple:
    """What a useful turn changes: photos, candidates and their status, the sidewalk bookkeeping."""
    return (len(session.photos), tuple((c.status, len(c.views)) for c in session.candidates),
            tuple(session.state), session.outcome is not None)


@dataclass
class Explorer:
    client: ChatClient
    prompt: str
    references: list[Path]  # the reference sign, then the look-alikes
    draw_map: Callable
    slot: int | None = None
    should_stop: Callable[[], bool] = lambda: False

    def run(self, session: Session, log: Callable[[dict], None]) -> tuple[str, int]:
        """The loop. Returns why it ended and the number of turns."""
        messages: list[dict] = [{"role": "system", "content": self.prompt},
                                {"role": "user", "content": f"Find bus stop {session.world.stop.stop_id}. "
                                                            "Start with begin()."}]
        invalid = repeats = stalled = 0
        last_failure = None
        turn = 0
        for turn in range(1, MAX_TURNS + 1):
            if session.outcome is not None:
                return "outcome", turn - 1
            if self.should_stop():
                return "interrupted", turn - 1
            status, data, seconds = self.client.complete(messages, TOOLS, self.slot, seed=turn * 10 + invalid)
            if status != 200:
                invalid += 1
                log({"turn": turn, "seconds": round(seconds, 1), "error": f"HTTP {status}: {str(data)[:500]}"})
                if status == 0 and invalid >= MAX_INVALID:
                    return f"server unreachable: {str(data)[:200]}", turn
                text = str(data).lower()  # llama-server: "exceeds the available context"; vLLM: "maximum context length"
                if "context" in text and ("exceed" in text or "maximum context length" in text):
                    return "context full", turn
                if invalid >= MAX_INVALID:
                    return "invalid replies", turn
                continue
            choice = data["choices"][0]
            message = choice["message"]
            calls = message.get("tool_calls") or []
            timings = data.get("timings") or {}
            log({"turn": turn, "seconds": round(seconds, 1), "finish": choice.get("finish_reason"),
                 "usage": data.get("usage"),
                 "timings": {k: timings.get(k) for k in ("cache_n", "prompt_n", "predicted_n")},
                 "reasoning": message.get("reasoning_content"), "content": message.get("content"),
                 "tool_calls": [{"name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                                for c in calls]})
            if not calls:
                invalid += 1
                if self.client.dialect == "strict":  # tool_choice can't be forced: answer, and remind
                    content = message.get("content") or ""
                    if content.strip().lower().rstrip(".") == "done":
                        return "the explorer said done", turn
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": "Act through the tools: reply with exactly one tool "
                                                                "call."})
                if invalid >= MAX_INVALID:
                    return "invalid replies", turn
                continue
            invalid = 0
            assistant = {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            messages.append(assistant)
            before = progress(session)
            failed = None
            pending_photos: list[dict] = []
            for c in calls:
                name = c["function"]["name"]
                images: list[Path] = []
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                    problem = check(name, args) if isinstance(args, dict) else "the arguments must be a JSON object"
                    if problem:
                        raise ToolError(problem)
                    result = call(session, name, args, self.references, self.draw_map)
                    text, images = result.text, list(result.images)
                except (ToolError, KeyError, TypeError, ValueError) as error:
                    text = f"ERROR: {error}"
                    failed = (name, c["function"]["arguments"])
                    session.log_error(name, {"raw": c["function"]["arguments"]}, str(error))
                if images and self.client.images_in_tool_results:
                    content: list[dict] | str = [{"type": "text", "text": text}, *_photo_parts(images, session)]
                else:
                    content = text + (f"\n({len(images)} photos: in the next message)" if images else "")
                    pending_photos += _photo_parts(images, session)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": content})
                log({"turn": turn, "tool": name, "result": text[:4000], "images": [p.name for p in images]})
                if session.outcome is not None:
                    break
            if pending_photos:
                messages.append({"role": "user", "content": [{"type": "text", "text": "Photos from the tool results:"},
                                                             *pending_photos]})
            repeats = repeats + 1 if failed is not None and failed == last_failure else (1 if failed else 0)
            last_failure = failed
            if repeats >= MAX_REPEATS:
                return "stuck repeating a failing call", turn
            spent = session.exhausted()
            if spent:  # nothing more can be confirmed: the model can't stop by itself (every turn is a tool call)
                return spent, turn
            stalled = 0 if progress(session) != before else stalled + 1
            if stalled >= STALL_END:
                return "stalled", turn
            nudge = None
            if repeats >= 2:
                nudge = "That call failed again with the same error. Read the error, fix the arguments or do " \
                        "something else."
            elif stalled == STALL_NUDGE:
                nudge = "The last turns changed nothing."
            if nudge:  # appended to the last message, so the history stays an extension of the cached prompt
                last = messages[-1]
                last["content"] = (last["content"] + f"\n\nHARNESS: {nudge}" if isinstance(last["content"], str)
                                   else [*last["content"], {"type": "text", "text": f"HARNESS: {nudge}"}])
        return ("outcome" if session.outcome is not None else "turn cap"), turn


class LlmConfirmer:
    """The checklist judge: a fresh call per candidate photo that has seen nothing of the search. With llamacpp the
    answer is one constrained function call on the confirmer's own slot (so the frozen part, instructions, reference
    and look-alikes, stays cached and the explorer's cache is never evicted); with strict, one JSON object in text."""

    TOOL = "submit_checklist"
    SYSTEM = ("You check photos of possible bus stops in Lazio, Italy, taken from Google Street View. You are strict "
              "and honest: you report only what you can actually see in the candidate photo.")

    def __init__(self, client: ChatClient, reference: Path, lookalikes: list[Path], log: Callable[[dict], None],
                 slot: int | None = None, attempts: int = 3) -> None:
        self.client = client
        self.log = log
        self.slot = slot
        self.attempts = attempts
        self.frozen = [
            {"type": "text", "text": "REFERENCE: the Cotral bus stop sign (navy panel, 'FERMATA', white Cotral logo, "
                                     "plate with the stop id)."},
            image_part(reference, REFERENCE_PX),
            {"type": "text", "text": "LOOK-ALIKES: blue road signs that are NOT bus stops (pedestrian crossing, "
                                     "lanes, bus-lane signs with a bus pictogram, parking, directions)."},
            *(image_part(p, REFERENCE_PX) for p in lookalikes),
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
        constrained = self.client.dialect == "llamacpp"
        system = self.SYSTEM + (f" Answer by calling {self.TOOL} once." if constrained else "")
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": [*self.frozen, {"type": "text", "text": instructions()},
                                                 {"type": "text", "text": "CANDIDATE photo:"}, image_part(photo)]}]
        problems = []
        for attempt in range(1, self.attempts + 1):
            status, data, seconds = self.client.complete(
                messages, [self.tool] if constrained else [], self.slot, seed=attempt,
                template={"reasoning_effort": "low"} if constrained else None)
            self.log({"confirm": self.calls, "attempt": attempt, "photo": photo.name, "status": status,
                      "seconds": round(seconds, 1), "reply": data if status == 200 else str(data)[:1000]})
            if status != 200:
                problems.append(f"HTTP {status}")
                continue
            message = data["choices"][0]["message"]
            try:
                if constrained:
                    calls = message.get("tool_calls") or []
                    if len(calls) != 1 or calls[0]["function"]["name"] != self.TOOL:
                        raise ConfirmerError("no single checklist call")
                    return parse(calls[0]["function"]["arguments"])
                return parse(message.get("content") or "")
            except ConfirmerError as error:
                problems.append(str(error))
        raise ConfirmerError("; ".join(problems))


SCAN_PROMPT = ("PHOTO: a street-level photo of a roadside. 1) Is a Cotral bus stop sign like the REFERENCE anywhere "
               "in it? It can be small, far away, blurry, partly hidden or seen at an angle; the panel is the same on "
               "both sides. 2) Where does something stand in front of the roadside, between the camera and where a "
               "sign pole would stand, big enough to hide a sign: a tree or its foliage, a hedge or bush, a parked "
               "van, truck or bus, a kiosk, another sign or its pole? Only what stands between the camera and the kerb: a "
               "wall, fence, hedge or building BEHIND the sidewalk hides nothing. Reply with JSON only: "
               '{"sign": true, "x": X, "y": Y, "cover": [[X_FROM, X_TO], ...]} with X, Y the centre of the sign and '
               "X_FROM, X_TO the left and right edges of each thing in front, on a 0-1000 grid of the photo (0,0 top "
               'left, 1000,1000 bottom right); "sign": false and no x, y when there is no sign; "cover": [] when '
               "nothing could hide one.")


class LlmScanner:
    def __init__(self, client: ChatClient, reference: Path, log: Callable[[dict], None], slot: int | None = None,
                 attempts: int = 2) -> None:
        self.client = client
        self.log = log
        self.slot = slot
        self.attempts = attempts
        self.reference = image_part(reference)
        self.calls = 0

    def __call__(self, piece: Path) -> ScanReply:
        self.calls += 1
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "REFERENCE: the Cotral bus stop sign."}, self.reference,
            {"type": "text", "text": SCAN_PROMPT}, image_part(piece)]}]
        for attempt in range(1, self.attempts + 1):
            status, data, seconds = self.client.complete(messages, [], self.slot, seed=attempt)
            self.log({"scan": self.calls, "attempt": attempt, "piece": piece.name, "status": status,
                      "seconds": round(seconds, 1), "reply": data if status == 200 else str(data)[:1000]})
            if status != 200:
                continue
            answer = parse_scan(data["choices"][0]["message"].get("content") or "")
            if answer is not None:
                return answer
        return ScanReply()


def parse_scan(text: str) -> ScanReply | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(j, dict):
        return None
    cover = [(_on_grid(c[0]), _on_grid(c[1])) for c in j.get("cover") or []
             if isinstance(c, (list, tuple)) and len(c) == 2 and all(_is_num(v) for v in c)]
    if j.get("sign") is False:
        return ScanReply(None, cover)
    if j.get("sign") is True and all(_is_num(j.get(k)) for k in ("x", "y")):
        return ScanReply((_on_grid(j["x"]), _on_grid(j["y"])), cover)
    return None


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _on_grid(v: float) -> float:
    return float(min(max(v, 0), GRID))
