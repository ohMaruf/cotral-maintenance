"""The confirmer: a fresh LLM call that judges one narrow photo of a candidate (design doc §3).

It has seen nothing of the search, so it can't be talked into "this must be it". It
answers a checklist, each item yes / no / unsure; code decides (`verdict`). The model
behind it is pluggable: anything that takes the photo and returns the answers.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

STOP_FEATURES = {
    "fermata_or_bus_text": "the word FERMATA or BUS written on a sign or panel",
    "cotral_logo": "the white Cotral logo on a navy panel",
    "timetable": "a timetable panel on a pole or in a shelter",
    "plate": "a small plate with a stop id or number, under or on a stop sign",
    "shelter": "a bus shelter (roof on posts, often with a bench) at the kerb",
    "road_marking": "BUS written on the road, or a yellow zig-zag stop marking",
}
BUS_PICTOGRAM = {"bus_pictogram": "a pictogram of a bus (alone it is NOT enough: bus-lane signs have one)"}
# Far away, a Cotral sign's text and logo are a few pixels: it can still be recognised by its design.
DESIGN = {"same_design_as_reference": "a panel with the same design as the REFERENCE Cotral sign: dark navy (not the "
                                      "bright blue of road signs), taller than wide, a block of white text at the top "
                                      "and a white wordmark at the bottom, on its own pole; answer even if the text "
                                      "itself is too small to read"}
LOOKALIKE_FEATURES = {
    "walking_figure": "a walking figure (pedestrian crossing sign)",
    "arrows": "arrows (lane, direction or mandatory-direction signs)",
    "letter_p": "a letter P (parking)",
    "wheelchair": "a wheelchair symbol",
    "plain_blue_square": "a plain blue square or rectangle with no stop text",
    "street_name": "a street name plate",
}
# Not part of the verdict: whether another viewpoint is needed before the spot can be dismissed.
ANGLE = {"could_be_stop_from_another_angle": "something that could be a stop seen badly from here: a sign panel "
                                             "seen edge on or from behind, a glass or roofed structure, a bench, a "
                                             "pole with something on top, partly hidden by a tree, a car or a railing"}
FEATURES = {**STOP_FEATURES, **BUS_PICTOGRAM, **DESIGN, **LOOKALIKE_FEATURES, **ANGLE}
ANSWERS = ("yes", "no", "unsure")


class ConfirmerError(Exception):
    """The confirmer gave no usable answer."""


@dataclass
class Checklist:
    answers: dict[str, str]
    plate_text: str = ""
    note: str = ""
    raw: str = field(default="", repr=False)


Confirmer = Callable[[Path], Checklist]


@dataclass(frozen=True)
class Verdict:
    confirmed: bool
    reason: str
    evidence: str = ""


def verdict(answers: dict[str, str]) -> Verdict:
    """Confirmed when no look-alike feature is 'yes' and at least one stop feature (the bus pictogram
    doesn't count) is 'yes'; or, weaker evidence, when the panel has the reference sign's design and none of
    its readable features is a clear 'no' (too small to read is 'unsure')."""
    lookalike = [k for k in LOOKALIKE_FEATURES if answers.get(k) == "yes"]
    stop_like = [k for k in STOP_FEATURES if answers.get(k) == "yes"]
    if lookalike:
        return Verdict(False, f"look-alike features seen: {', '.join(lookalike)}")
    if not stop_like and answers.get("same_design_as_reference") == "yes" \
            and all(answers.get(k) != "no" for k in ("fermata_or_bus_text", "cotral_logo")):
        return Verdict(True, "the panel has the Cotral sign's design (its text is too small to read)",
                       "cotral_sign_by_design")
    if not stop_like:
        return Verdict(False, "no stop feature seen" + (
            " (a bus pictogram alone is not enough: bus-lane signs have one)"
            if answers.get("bus_pictogram") == "yes" else ""))
    evidence = ("cotral_sign" if answers.get("cotral_logo") == "yes"
                else "other_stop_sign" if any(answers.get(k) == "yes" for k in ("fermata_or_bus_text", "plate",
                                                                                 "timetable"))
                else "shelter_only" if answers.get("shelter") == "yes" else "road_marking")
    return Verdict(True, f"stop features seen: {', '.join(stop_like)}", evidence)


def instructions() -> str:
    """The checklist as the confirmer is asked it; the answer is one JSON object."""
    lines = [f'- "{k}": {v}' for k, v in FEATURES.items()]
    return ("Answer from the CANDIDATE photo only, comparing it with the reference sign and the look-alikes. "
            "For each feature answer \"yes\", \"no\" or \"unsure\". Say yes only when you can actually see it; "
            "when the photo is too blurry or small to tell, say unsure.\n" + "\n".join(lines) +
            '\nAlso give "plate_text" (the stop id on the plate, if you can read it, else "") and "note" (one short '
            "sentence: what the object is).\nReply with ONE JSON object with exactly these keys and nothing else.")


def parse(text: str) -> Checklist:
    """The checklist from the model's reply: the last JSON object in it, every feature answered."""
    objects = re.findall(r"\{.*?\}", text, flags=re.S)
    for candidate in reversed(objects):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        answers = {k: str(data.get(k, "")).strip().lower() for k in FEATURES}
        bad = [k for k, v in answers.items() if v not in ANSWERS]
        if bad:
            raise ConfirmerError(f"features missing or not yes/no/unsure: {', '.join(bad)}")
        return Checklist(answers, str(data.get("plate_text") or "").strip(), str(data.get("note") or "").strip(),
                         text)
    raise ConfirmerError("no JSON object in the reply")
