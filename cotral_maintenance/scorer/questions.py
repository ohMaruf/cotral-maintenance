"""What the scorer is asked about a found stop, on the explorer's 1-2 stop photos (Imajev: at most 8 questions).

The explorer only reports a stop it has confirmed, so the stop itself is not asked about: the
sign (or shelter, or markings) is what it confirmed, recorded as the exploration's `evidence`.
The scorer judges what is around it. Every value is 0 (bad) .. 1 (good):
  - has_shelter, has_seating, has_lamp: the probability that the element is there. Cotral puts a
    shelter or a bench at some stops and not at others, so a missing element is not a defect: it
    has no condition, and is listed in `missing` (below 0.5).
  - shelter, seating: the condition of the element, only when it is there (else None). Asked on a
    0 (unusable) .. 4 (good) scale; the value is the expected level / 4.
  - waiting_area, accessibility: always there, rated the same way.
  - stop_visible: the probability that the photos show the stop at all. When they don't, the other
    answers describe something else and the stop goes to a person.
`condition` (computed, not asked) is the mean of the conditions that apply; stops are ranked by it,
worst first. A lamp's condition cannot be judged from daytime photos, so lighting is presence only.
"""

from .imajev import Question

PRESENT_MIN = 0.5
ELEMENT_LEVELS = [  # worst first: the level is the condition
    "Broken, damaged so that it cannot be used",
    "Significant damage or deficiency",
    "Moderate wear or damage that should be fixed",
    "Minor issues: dirt, faded paint, light wear",
    "Good condition",
]
AREA_LEVELS = [
    "Severe: unsafe or unusable",
    "Significant problems",
    "Moderate problems that should be fixed",
    "Minor issues: dirt, litter, light wear",
    "Good: no maintenance needed",
]
ACCESS_LEVELS = [
    "Inaccessible: no pavement or platform, passengers wait on the roadside, verge or ditch",
    "Poor: a narrow or broken surface, no kerb, steps or obstacles in the way",
    "Partial: a surface to wait on, but no raised kerb or no step-free path to it",
    "Mostly accessible: a raised kerb or platform and step-free access, with minor obstacles",
    "Fully accessible: a raised platform or kerb at bus floor height, step-free, even and unobstructed",
]
ELEMENTS = {  # name: (presence question, what to rate)
    "shelter": ("Is there a bus shelter (a covered structure where passengers wait) at the stop?",
                "the bus shelter at the stop"),
    "seating": ("Is there seating for waiting passengers (a bench or seats, also inside a shelter) at the stop?",
                "the seating (bench or seats) at the stop"),
}
AREAS = {
    "waiting_area": ("the waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown "
                     "vegetation, standing space)", AREA_LEVELS),
    "accessibility": ("accessibility of the stop for passengers, including wheelchair users and prams",
                      ACCESS_LEVELS),
}
LAMP = "has_lamp"
VISIBLE = "stop_visible"
CONDITIONS = (*ELEMENTS, *AREAS)
LAMP_INSTRUCTIONS = "Is there a street lamp at the bus stop, within about 20 m of it, or a light in its shelter?"
LAMP_CRITERIA = {
    "true": "a street lamp is near the stop: a slender metal or concrete pole with a lamp head or a curved arm. The "
            "pole alone is enough, even when its top and the lamp are cut off by the photo",
    "false": "no street lamp near the stop. Wooden or concrete poles that only carry overhead electric or telephone "
             "wires are not street lamps",
}


def present(name: str) -> str:
    return f"has_{name}"


def condition(values: dict[str, float | None]) -> float | None:
    """The stop's condition, 0 (bad) .. 1 (good): the mean of the conditions that apply (a missing shelter or
    seating has none). None when nothing was rated."""
    rated = [values[k] for k in CONDITIONS if values.get(k) is not None]
    return round(sum(rated) / len(rated), 4) if rated else None


def missing(values: dict) -> list[str]:
    """The elements the stop lacks: shelter, seating, lamp (presence below 0.5)."""
    return [name for name in (*ELEMENTS, "lamp")
            if values.get(present(name)) is not None and values[present(name)] < PRESENT_MIN]


def values(answers: dict) -> dict[str, float | None]:
    """The score columns from the scorer's answers."""
    out = {}
    for name, a in answers.items():
        if a is None:
            out[name] = None
        elif a["type"] == "score":  # expected level / top level
            out[name] = round(a["score"] / max(float(k) for k in a["probabilities"]), 4)
        else:
            out[name] = round(a["noul"], 4)
    for name in ELEMENTS:
        if out.get(present(name)) is not None and out[present(name)] < PRESENT_MIN:
            out[name] = None
    out["condition"] = condition(out)
    return out


EVIDENCE_TEXT = {
    "cotral_sign": "a Cotral bus stop sign",
    "cotral_sign_by_design": "a sign with the design of a Cotral bus stop sign (its text too small to read)",
    "other_stop_sign": "a bus stop sign of another operator",
    "shelter_only": "a bus shelter, without a sign",
    "road_marking": "bus stop markings on the road",
}
PHOTO_ROLES = (
    "taken from the Street View panorama the stop was confirmed from, facing the stop",
    "taken from a panorama about 12 m before the stop, facing it, as a passenger arriving would see it",
)


def questions() -> list[Question]:
    qs = []
    for name, (ask, what) in ELEMENTS.items():
        qs.append(Question(present(name), "noul", ask))
        qs.append(Question(name, "score", f"Condition of {what}? If there is none, answer unknown.", ELEMENT_LEVELS))
    qs += [Question(name, "score", f"State of {what}?", levels) for name, (what, levels) in AREAS.items()]
    qs.append(Question(LAMP, "noul", LAMP_INSTRUCTIONS, LAMP_CRITERIA))
    qs.append(Question(VISIBLE, "noul", "Is the bus stop (its sign, shelter or stop markings) visible in the photos?"))
    return qs


def state(stop_name: str, evidence: str | None, n_photos: int) -> dict:
    return {
        "task": f"{'These photos show' if n_photos > 1 else 'This photo shows'} a Cotral bus stop in Lazio, Italy, "
                "from Google Street View. Judge the stop's state for maintenance, using every photo. A stop on the "
                "far side of the road is a different stop: ignore it.",
        "stop_name": stop_name,
        "how_the_stop_was_identified": EVIDENCE_TEXT.get(evidence or "", "a bus stop seen in Street View"),
        "photos": [f"Photo {i}: {role}" for i, role in enumerate(PHOTO_ROLES[:n_photos], 1)],
        "photo_artifacts": "The photos are cut from panoramas taken from a moving car. Blur, stitching seams, objects "
                           "that look sliced or doubled, blurred faces and number plates, and parts of the camera car "
                           "are artifacts of the camera, not damage at the stop: ignore them.",
    }
