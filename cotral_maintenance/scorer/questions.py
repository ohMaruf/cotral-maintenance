"""What the scorer is asked about a found stop, on the explorer's 1-2 stop photos (Imajev: at most 8 questions).

The explorer only reports a stop it has confirmed, so the stop itself is not asked about: the
sign (or shelter, or markings) is what it confirmed, recorded as the exploration's `evidence`.
The scorer judges what is around it:
  - shelter, seating, waiting_area, accessibility: 0 (good) .. 4 on a 0-4 scale, the expected
    level under the model's probabilities. For shelter and seating, level 4 includes "missing":
    a stop without them needs maintenance.
  - lighting: the probability that a street lamp stands at the stop. Its pole is enough, even when
    the lamp at the top is out of the photo; poles that carry overhead wires are not lamps.
  - stop_visible: the probability that the photos show the stop at all. When they don't, the other
    answers describe something else and the stop goes to a person.
`priority` (computed, not asked) combines the needs into one number to rank the stops by.
"""

from .imajev import Question

ELEMENT_LEVELS = [
    "Present and in good condition",
    "Present, minor issues: dirt, faded paint, light wear",
    "Present, moderate wear or damage that should be fixed",
    "Present, significant damage or deficiency",
    "Missing, broken or unusable",
]
AREA_LEVELS = [
    "Good: no maintenance needed",
    "Minor issues: dirt, litter, light wear",
    "Moderate problems that should be fixed",
    "Significant problems",
    "Severe: unsafe or unusable",
]
ELEMENTS = {
    "shelter": "the bus shelter (a covered structure where passengers wait)",
    "seating": "seating for waiting passengers (benches or seats)",
}
AREAS = {
    "waiting_area": "the waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown "
                    "vegetation, standing space)",
    "accessibility": "accessibility (a proper raised platform or kerb, step-free access, even surfaces, no obstacles "
                     "for wheelchairs or prams)",
}
SCORES = (*ELEMENTS, *AREAS)  # 0 good .. 4 severe / missing
LIGHTING = "lighting"  # probability that there is a street lamp
VISIBLE = "stop_visible"
LIGHTING_INSTRUCTIONS = (
    "Is there a street lamp at the bus stop: a lighting pole standing on the stop's side of the road, within "
    "about 15 m of the stop, or a light in its shelter?")
LIGHTING_CRITERIA = {
    "true": "a street lamp pole (a pole with a lamp head or arm, typically metal or concrete, standing alone by the "
            "road) is near the stop; the pole alone is enough, even if its top and the lamp are cut off by the photo",
    "false": "no lamp pole near the stop. Poles that carry overhead electric or telephone wires (wooden or concrete "
             "poles with cables running between them, insulators, transformers) are NOT street lamps, unless a lamp "
             "is mounted on them",
}


def priority(values: dict[str, float | None]) -> float | None:
    """The stop's need for maintenance, 0 (nothing to do) .. 1: the mean of the needs, each scaled to 0-1
    (a 0-4 level / 4, and the absence of a street lamp). None when nothing was scored."""
    needs = [values[k] / 4 for k in SCORES if values.get(k) is not None]
    if values.get(LIGHTING) is not None:
        needs.append(1 - values[LIGHTING])
    return round(sum(needs) / len(needs), 4) if needs else None


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
    qs = [Question(name, "score", f"State of {what}?", ELEMENT_LEVELS) for name, what in ELEMENTS.items()]
    qs += [Question(name, "score", f"State of {what}?", AREA_LEVELS) for name, what in AREAS.items()]
    qs.append(Question(LIGHTING, "noul", LIGHTING_INSTRUCTIONS, LIGHTING_CRITERIA))
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
