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
    "fermata_or_bus_text": "the word FERMATA or BUS written on a sign or panel (unsure when the text is too small "
                           "to read)",
    "cotral_logo": "the white Cotral logo on a navy panel (unsure when it is too small to make out)",
    "timetable": "a timetable panel on a pole or in a shelter",
    "plate": "a small plate with a stop id or number, under or on a stop sign",
    "shelter": "a bus shelter (roof on posts, often with a bench) at the kerb",
    "road_marking": "BUS written on the road, or a yellow zig-zag stop marking",
}
BUS_PICTOGRAM = {"bus_pictogram": "a pictogram of a bus (alone it is NOT enough: bus-lane signs have one)"}
# Far away, a Cotral sign's text and logo are a few pixels: it can still be recognised by its design.
DESIGN = {"same_design_as_reference": "a panel with the same design as the REFERENCE Cotral sign: dark navy (not the "
                                      "bright blue of road signs; in poor light or faded it can look grey, black or "
                                      "washed-out blue), taller than wide, a block of white text at the top and a white "
                                      "wordmark at the bottom, on its own pole; answer even if the text itself is too "
                                      "small to read",
          "text_readable": "the text on the panel is large and sharp enough to read (answer no when it is too small, "
                           "far or blurry to read)"}
LOOKALIKE_FEATURES = {
    "walking_figure": "a walking figure (pedestrian crossing sign)",
    "arrows": "arrows (lane, direction or mandatory-direction signs)",
    "letter_p": "a letter P (parking)",
    "wheelchair": "a wheelchair symbol",
    "plain_blue_square": "a plain blue square or rectangle with no stop text",
    "street_name": "a street name plate",
    "prohibition_disc": "a red circle or red-bordered disc (no entry, no parking, no stopping, speed limit) or a red "
                        "triangle (warning)",
    "private_plate": "a private-road, property, house-number, field-number or advertising plate",
    "narrow_track": "the pole stands at a narrow lane, dirt track, driveway, field entrance or footpath, not at a road "
                    "wide enough for a large coach",
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
    """Confirmed when the Cotral logo is seen with FERMATA or the Cotral design (whatever else is in view); or when
    no look-alike feature is 'yes' and a stop feature is 'yes' (a plate counts only with another
    stop feature: house-number and field plates look like stop plates; the bus pictogram never counts); or, weaker
    evidence, when the panel has the reference sign's design and its text is not readable (a readable text that is
    neither FERMATA nor the Cotral logo means another sign)."""
    lookalike = [k for k in LOOKALIKE_FEATURES if answers.get(k) == "yes"]
    # A close view at a busy stop often holds several signs: the Cotral logo with FERMATA or the Cotral design is
    # specific enough to win over a road sign beside it (f4156, 0.11.1: the stop, with a parking sign, rejected).
    cotral = answers.get("cotral_logo") == "yes" and "yes" in (answers.get("fermata_or_bus_text"),
                                                              answers.get("same_design_as_reference"))
    if lookalike and cotral:
        return Verdict(True, f"the Cotral sign is seen (also in view: {', '.join(lookalike)})", "cotral_sign")
    if lookalike:
        return Verdict(False, f"look-alike features seen: {', '.join(lookalike)}")
    stop_like = [k for k in STOP_FEATURES if answers.get(k) == "yes"]
    core = [k for k in stop_like if k != "plate"]
    if not core and answers.get("same_design_as_reference") == "yes":
        read_as_other = answers.get("text_readable") == "yes" and all(
            answers.get(k) == "no" for k in ("fermata_or_bus_text", "cotral_logo"))
        if not read_as_other:
            return Verdict(True, "the panel has the Cotral sign's design (its text is too small to read)",
                           "cotral_sign_by_design")
        return Verdict(False, "the panel's text is readable and is neither FERMATA nor the Cotral logo")
    if not core:
        return Verdict(False, "no stop feature seen" + (
            " (a plate alone is not enough: house-number and field plates look the same)" if stop_like else "") + (
            " (a bus pictogram alone is not enough: bus-lane signs have one)"
            if answers.get("bus_pictogram") == "yes" else ""))
    evidence = ("cotral_sign" if answers.get("cotral_logo") == "yes"
                else "other_stop_sign" if any(answers.get(k) == "yes" for k in ("fermata_or_bus_text", "timetable"))
                else "shelter_only" if answers.get("shelter") == "yes" else "road_marking")
    return Verdict(True, f"stop features seen: {', '.join(stop_like)}", evidence)


def instructions() -> str:
    """The checklist as the confirmer is asked it; the answer is one JSON object."""
    lines = [f'- "{k}": {v}' for k, v in FEATURES.items()]
    return ("Answer from the CANDIDATE photo only, comparing it with the reference sign and the look-alikes. "
            "For each feature answer \"yes\", \"no\" or \"unsure\". Say yes only when you can actually see it; "
            "when the photo is too blurry or small to tell, say unsure: \"no\" means you can see clearly that it is "
            "not there.\n" + "\n".join(lines) +
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
