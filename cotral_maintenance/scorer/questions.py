import math

from ..geo import bearing_deg, distance_m
from .imajev import Question

PRESENT_MIN = 0.5
ELEMENT_LEVELS = [
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
ELEMENTS = {
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
    rated = [values[k] for k in CONDITIONS if values.get(k) is not None]
    return round(sum(rated) / len(rated), 4) if rated else None


def missing(values: dict) -> list[str]:
    return [name for name in (*ELEMENTS, "lamp")
            if values.get(present(name)) is not None and values[present(name)] < PRESENT_MIN]


def values(answers: dict) -> dict[str, float | None]:
    out = {}
    for name, a in answers.items():
        if a is None:
            out[name] = None
        elif a["type"] == "score":
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
WIDE_FOV = 90
WIDE_DISTANCE_M = (10.0, 60.0)


def frame_x(photo: dict, stop_lat: float, stop_lon: float) -> float | None:
    off = (bearing_deg(photo["lat"], photo["lon"], stop_lat, stop_lon) - photo["heading"] + 180) % 360 - 180
    if abs(off) >= 90:
        return None
    return 0.5 + math.tan(math.radians(off)) / (2 * math.tan(math.radians(photo["fov"] / 2)))


def describe_photo(i: int, photo: dict, stop_lat: float, stop_lon: float, same_camera_as: int | None = None) -> str:
    d = distance_m(photo["lat"], photo["lon"], stop_lat, stop_lon)
    x = frame_x(photo, stop_lat, stop_lon)
    view = "wide view" if photo["fov"] >= WIDE_FOV else "close view"
    where = ("not in the frame" if x is None or not 0 <= x <= 1 else
             "near the left edge" if x < 0.2 else "left of centre" if x < 0.4 else
             "in the centre" if x <= 0.6 else "right of centre" if x <= 0.8 else "near the right edge")
    camera = (f"the same camera position as Photo {same_camera_as}, about {d:.0f} m from the stop" if same_camera_as
              else f"camera about {d:.0f} m from the stop")
    return (f"Photo {i}: {view}, {photo['fov']:.0f} degree field of view, {camera}, facing it; the stop is {where} "
            f"of the frame")


def describe_photos(photos: list[dict], stop_lat: float, stop_lon: float) -> list[str]:
    out = []
    for i, p in enumerate(photos, 1):
        earlier = next((j for j, q in enumerate(photos[:i - 1], 1)
                        if p.get("pano_id") and q.get("pano_id") == p["pano_id"]), None)
        out.append(describe_photo(i, p, stop_lat, stop_lon, earlier))
    return out


def lamp_photos(stop_photos: list[dict], wide: list[dict], stop_lat: float, stop_lon: float) -> list[dict]:
    def usable(p: dict) -> bool:
        x = frame_x(p, stop_lat, stop_lon)
        lo, hi = WIDE_DISTANCE_M
        return (p["fov"] >= WIDE_FOV and x is not None and 0.15 <= x <= 0.85
                and lo <= distance_m(p["lat"], p["lon"], stop_lat, stop_lon) <= hi)

    def turn(p: dict, q: dict) -> float:
        return abs((p["heading"] - q["heading"] + 180) % 360 - 180)

    candidates = [p for p in wide if usable(p)]
    for close in stop_photos:
        same = sorted((w for w in candidates if w.get("pano_id") and w["pano_id"] == close.get("pano_id")),
                      key=lambda w: turn(w, close))
        if same:
            return [close, same[0]]
    if candidates:
        return [stop_photos[0], min(candidates, key=lambda w: turn(w, stop_photos[0]))]
    return stop_photos


def questions(lamp: bool = True, others: bool = True) -> list[Question]:
    qs = []
    for name, (ask, what) in ELEMENTS.items() if others else ():
        qs.append(Question(present(name), "noul", ask))
        qs.append(Question(name, "score", f"Condition of {what}? If there is none, answer unknown.", ELEMENT_LEVELS))
    if others:
        qs += [Question(name, "score", f"State of {what}?", levels) for name, (what, levels) in AREAS.items()]
    if lamp:
        qs.append(Question(LAMP, "noul", LAMP_INSTRUCTIONS, LAMP_CRITERIA))
    if others:
        qs.append(Question(VISIBLE, "noul",
                           "Is the bus stop (its sign, shelter or stop markings) visible in the photos?"))
    return qs


def state(stop_name: str, evidence: str | None, photos: list[str]) -> dict:
    several = len(photos) > 1
    return {
        "task": f"{'These photos show' if several else 'This photo shows'} a Cotral bus stop in Lazio, Italy, "
                "from Google Street View. Judge the stop's state for maintenance"
                + (", using every photo. " if several else ". ") + "A stop on the far side of the road is a "
                "different stop: ignore it.",
        "stop_name": stop_name,
        "how_the_stop_was_identified": EVIDENCE_TEXT.get(evidence or "", "a bus stop seen in Street View"),
        "photos": photos,
        **({"same_stop": "All the photos show the same bus stop, from different camera positions and with different "
                         "fields of view. The same sign, pole, lamp or shelter appears large in a close view and small "
                         "in a wide view, at another place in the frame: match them across the photos, and use the "
                         "wide view to see what a close view cuts off (the top of a pole, what stands beside the "
                         "stop)."} if several else {}),
        "photo_artifacts": "The photos are cut from panoramas taken from a moving car. Blur, stitching seams, objects "
                           "that look sliced or doubled, blurred faces and number plates, and parts of the camera car "
                           "are artifacts of the camera, not damage at the stop: ignore them.",
    }
