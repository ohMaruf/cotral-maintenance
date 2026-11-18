"""What the scorer is asked about a found stop: 8 questions (Imajev's limit), on the explorer's 1-2 stop photos.

Seven maintenance scores on a 0-4 scale (the expected level under the model's probabilities) and
whether the stop is visible at all. For shelter, seating, signage and lighting, level 4 includes
"missing": a stop without them needs maintenance. `stop_visible` guards the rest: when the photos
do not show the stop, the scores describe something else and the stop goes to a person.
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
    "signage": "the bus stop sign (a sign on a pole, possibly with a timetable panel)",
    "lighting": "lighting at the stop (street lamps near the waiting area, or lights in the shelter)",
}
AREAS = {
    "waiting_area": "the waiting area (pavement or platform surface, cleanliness, litter, weeds, overgrown "
                    "vegetation, standing space)",
    "accessibility": "accessibility (a proper raised platform or kerb, step-free access, even surfaces, no obstacles "
                     "for wheelchairs or prams)",
}
SCORES = (*ELEMENTS, *AREAS, "requires_maintenance")
VISIBLE = "stop_visible"

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
    qs.append(Question(
        "requires_maintenance", "score",
        "Overall, how much does this bus stop require maintenance or improvement? Count missing facilities and "
        "anything else visible at the stop (road surface, graffiti, vandalism, litter, drainage, vegetation, hazards).",
        AREA_LEVELS))
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
