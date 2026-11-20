"""One search: the explorer's tools, the bookkeeping, and the record (design doc §6).

The session owns the state; each tool method returns a ToolResult (text, and the
photos to show). Every call is appended to the record in order, so a run can be
replayed exactly. Images come from `fetch_image` (the Street View Static API: one
billed request per image) and are cached on disk by panorama, heading, fov, pitch and
size, so re-running a stop costs nothing twice.

Budget, per stop: MAX_IMAGES Static API images and MAX_TILES Map Tiles tiles (both billed per request);
metadata lookups are free and not counted.
  - sweep: one wide Static image from a panorama, ahead-right (or behind-right) of travel: broad looks.
  - zoom: a narrow, full-resolution view of a spot of a photo, from the same panorama, rendered from
    tiles (2-4 each, priced before fetching); a narrow Static image once the tiles run out.
  - look_from: the same kind of narrow view of a candidate, from ANOTHER panorama: a new viewpoint
    when the sign can't be seen clearly (edge on, hidden, too far).
  - confirm: no image; a fresh confirmer call judges the close view the candidate was marked on.
  - STOP_PHOTOS images are kept back: when a stop is submitted, the harness photographs
    it and its surroundings for the next stage of the pipeline.
"""

import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from ..provenance import utc_now
from . import HARNESS_VERSION
from .confirmer import LOOKALIKE_FEATURES, Confirmer, ConfirmerError, verdict
from .geometry import Camera, angle_diff, compass, ray_point, ray_to_sidewalk, triangulate, unit
from ..caches import MetadataCache
from .world import CELL_M, Panorama, World, find_panoramas, shared_stretches

MAX_IMAGES = 22  # billed Static API images per stop, the stop photos included (10,000 free a month: see quota.py)
STOP_PHOTOS = 2  # kept back for photographing a found stop
OPENING_OFFSETS_M = (35.0, 28.0, 21.0, 14.0)  # the two opening sweeps: ahead-right from this far before the start,
# behind-right from this far after it, the farthest with a panorama and no corner in between. The stretch around the
# start is in front of both cameras (0.12.0 photos converged on it from 11 m and missed a sign 4 m behind one of
# them, f8520); signs face the arriving buses, so the first sees their faces.
OPENING_PANO_M = 10.0  # a panorama this close to the wanted point of the path
BEND_DEG = 30.0  # a turn of the path this sharp is a corner: no view sees round it
BEND_SPAN_M = 10.0
CORNER_M = 12.0  # the sidewalk this far either side of a corner must be seen close for the corner to count as examined
EXPLORE_IMAGES = MAX_IMAGES - STOP_PHOTOS
MAX_CONFIRMS = 30  # confirmer calls (not Google requests): every close view is judged
CORNER_REACH_M = 40.0  # a sweep facing a corner this close makes the harness look round it
CORNER_STEP_M = 6.0  # ... from panoramas about this far past and before it
SECOND_VIEW_SPAN_M = 3.0  # an automatic second view frames the first view's sight line with this margin either side
SECOND_VIEW_RANGE = (0.6, 1.6)  # ... from this much to this much of the estimated distance: a single view's distance
                                # was 10 m short at f4156 (0.11.1), and its second view missed the sign
SECOND_VIEW_FOV = 30.0
# The search spreads out evenly from the start: a sweep standing more than this much farther out than the other side
# has been looked at is refused (0.16.0 NVFP4 swept ahead out to +436 m before one sweep behind found f306 at -44 m).
BALANCE_M = 40.0
LOOKED_SHARE = 0.7  # a side counts as looked at out to where this share of its sidewalk has been seen
MAX_CALLS = 100
IMAGE_SIZE = (640, 640)  # the Static API's maximum
SWEEP_FOV = 110.0
SWEEP_TURNS = {"ahead": 50.0, "behind": 130.0}  # image centre, degrees right of travel: -5..105 or 75..185
MAX_TILES = 60  # Map Tiles tiles per stop, for zooms and new viewpoints (100,000 free a month: see quota.py)
ZOOM_SIZE = (512, 512)  # a tile view: about 45 px per degree at fov 10
ZOOM_FOV = (5.0, 20.0)
DEFAULT_ZOOM_FOV = 10.0
CLOSE_VIEWS = ("zoom", "look_from")
LOOK_FROM_MAX_M = 40.0
OSM_SNAP_M = 15.0  # a sight line passing this close to an OSM start is taken to end there
STOP_CONTEXT_FOV = (50.0, 60.0)  # the found stop: from the confirming panorama, from a second one
STOP_PHOTO_BACK_M = 12.0  # the second stop photo: from about this far before the stop, looking at it
SIGN_M = 0.6  # width of a stop sign panel
SIGN_HEIGHT_M = 2.2  # height of a stop sign panel's centre above the sidewalk
READABLE_PX = 12.0  # a sign this wide in a sweep counts as seen close
SPOT_PX = 5.0  # ... this wide, as glimpsed: enough to notice and zoom on, not to judge
NEARBY_STOP_M = 15.0
BEARING_SPAN_M = 8.0  # direction of travel averaged over this much path each way
STATES = ("not_looked", "glimpsed", "surveyed_clear", "seen_close", "hidden", "unscanned")
# Where the stop is, by distance from the start, per start source (rings: up to 10 m, 25, 50, 100, 400).
# Measured on the 504 verified stops (osm_match.py): OSM matched, and GTFS where OSM has no match.
SPREAD = {
    "osm": ((10, 0.55), (25, 0.19), (50, 0.12), (100, 0.07), (400, 0.07)),
    "places": ((10, 0.38), (25, 0.22), (50, 0.20), (100, 0.14), (400, 0.06)),
    "gtfs": ((10, 0.18), (25, 0.22), (50, 0.31), (100, 0.18), (400, 0.11)),
}
HINT_WEIGHT = {"bus_stop": 0.3, "platform": 0.3, "shelter": 0.3, "stop_position": 0.2, "bus_station": 0.1}
HINT_SIGMA_M = 8.0
SEEN_FACTOR = {"seen_close": 0.1, "surveyed_clear": 0.4, "glimpsed": 0.6}  # likelihood left after each
CANDIDATE_KINDS = ("sign", "shelter", "pole_with_panel", "bench", "road_marking", "people_waiting")
# Points on photos are given on a 0-1000 grid over the image, whatever its size: the scale Qwen-VL models are
# trained to point in (Qwen3.8 located a sign within 3 px this way), and easier than pixels for any model.
GRID = 1000

FetchImage = Callable[[str, float, float, float, int, int], bytes]  # pano, heading, fov, pitch, width, height


class TileSource(Protocol):
    """Narrow views from Map Tiles (tileviews.TileViews), priced before they are fetched."""

    def plan(self, pano_id: str, heading: float, pitch: float, fov: float, width: int, height: int,
             paid: Iterable[tuple]) -> tuple[float, float, set[tuple]]: ...

    def render(self, pano_id: str, heading: float, pitch: float, fov: float, width: int, height: int) -> bytes: ...


class ToolError(Exception):
    """The call is invalid; the message tells the explorer why."""


@dataclass
class ToolResult:
    text: str
    images: list[Path] = field(default_factory=list)
    done: bool = False


@dataclass
class Photo:
    index: int
    pano_id: str
    date: str
    along: float  # of the panorama
    offset: float
    heading: float
    fov: float
    pitch: float
    toward: str  # opening_before, opening_after, sweep_ahead, sweep_behind, zoom, look_from, stop_photo
    file: str
    lat: float
    lon: float
    width: int = IMAGE_SIZE[0]
    height: int = IMAGE_SIZE[1]
    shot: int = 0  # the sweep number (0 for other photos)
    parent: int | None = None  # the photo a zoom was taken from
    billed: bool = True  # False when it came from the cache
    source: str = "static"  # "static" (Street View Static API) or "tiles" (Map Tiles)
    tiles: int = 0  # tiles paid for this view (a tile is paid once per stop)


@dataclass
class Candidate:
    index: int
    kind: str
    views: list[tuple[int, float, float]]  # (photo index, bearing, elevation)
    lat: float
    lon: float
    along: float
    offset: float
    status: str = "spotted"  # spotted, confirmed, rejected
    checklist: dict[str, str] = field(default_factory=dict)
    plate_text: str = ""
    evidence: str = ""
    basis: str = "single_ray_sidewalk"
    confirmer_note: str = ""
    confirm_photo: int | None = None


class Session:
    def __init__(self, world: World, run_dir: Path, image_cache: Path, metadata: MetadataCache,
                 fetch_image: FetchImage, confirmer: Confirmer | None = None,
                 tiles: TileSource | None = None, harness: dict | None = None) -> None:
        self.world = world
        self.run_dir = run_dir
        self.image_cache = image_cache
        self.metadata = metadata
        self.fetch_image = fetch_image
        self.confirmer = confirmer
        self.tile_source = tiles
        self.harness = {"version": HARNESS_VERSION, **(harness or {})}
        self.tiles_paid: set[tuple] = set()
        self.photos: list[Photo] = []
        self.candidates: list[Candidate] = []
        self.sweeps = 0
        self.confirms = 0
        self.calls = 0
        self.judged: set[int] = set()  # close views the confirmer has answered on
        self.balance_m = BALANCE_M  # inf switches the even-spread rule off (geometry tests)
        self.outcome: dict | None = None
        self.events: list[dict] = []
        cells = world.cells()
        self.cells = cells
        self.state = ["not_looked" if world.scanned(a) else "unscanned" for a in cells]
        self._sidewalk = [world.path.sidewalk(a) for a in cells]
        self.bends = self._find_bends()
        self.corners_done: set[float] = set()
        self.prior = self._prior()
        self.shared = shared_stretches(world.path, *world.limits)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "photos").mkdir(exist_ok=True)
        self.started_at = utc_now()

    @property
    def explore_used(self) -> int:
        """Static images the explorer has used (the stop photos are kept back)."""
        return sum(1 for p in self.photos if p.source == "static" and p.toward != "stop_photo")

    @property
    def billed(self) -> int:
        return sum(1 for p in self.photos if p.billed)

    # ------------------------------------------------------------------ tools

    def begin(self) -> ToolResult:
        """The briefing and the two opening sweeps (taken by the harness), with the start in front of both."""
        if self.photos:
            raise ToolError("begin() was already called")
        pair = self._opening()
        text = "\n\n".join([self._briefing(), *(self._opening_caption(p) for p in pair), self._state()])
        return self._log("begin", {}, ToolResult(text, [self._file(p) for p in pair]))

    def sweep(self, from_m: float, facing: str | None = None, scan: str | None = None) -> ToolResult:
        """A wide photo looking AWAY from the start along the route: ahead from a + position, back from a - one, so
        every sweep shows new ground. (`facing` is only for tests and experiments; the explorer can't choose it.)"""
        facing = facing or ("behind" if from_m < 0 else "ahead")
        args = {"from_m": from_m, "facing": facing, "scan": scan}
        self._count_call()
        if facing not in SWEEP_TURNS:
            raise ToolError(f"facing must be one of {', '.join(SWEEP_TURNS)}")
        photo = self._sweep(from_m, facing, scan)
        lines = [self._sweep_caption(photo)]
        corner, extra = self._complete_corner(photo)
        if extra:
            lines.append(f"CORNER {_m(corner)}: this sweep faces a corner, and no view sees round one, so the harness "
                         f"also looked at it from both sides:")
            lines += [self._sweep_caption(e) for e in extra]
        text = "\n".join(lines) + "\n\n" + self._state()
        return self._log("sweep", args, ToolResult(text, [self._file(q) for q in [photo, *extra]]))

    def zoom(self, photo: int, x: float, y: float, fov: float = DEFAULT_ZOOM_FOV, what: str | None = None) -> ToolResult:
        """`what`: the stop-like thing the explorer sees at the point (required from the explorer; None only for
        direct calls). Kept with the zoom for review, never shown to the confirmer."""
        args = {"photo": photo, "x": x, "y": y, "fov": fov, "what": what}
        self._count_call()
        if not ZOOM_FOV[0] <= fov <= ZOOM_FOV[1]:
            raise ToolError(f"fov must be between {ZOOM_FOV[0]:.0f} and {ZOOM_FOV[1]:.0f}")
        if what is not None and not names_a_stop_like_thing(what):
            raise ToolError(f"what={what!r} names nothing stop-like. Zoom only on something you can see in the photo "
                            f"that could be a stop: a sign, panel, pole, plate, shelter, bench, road marking or people "
                            f"waiting, and say what it is. If you see nothing like that, sweep elsewhere.")
        p = self._photo(photo)
        px, py = self._pixel(p, x, y)
        camera = self._camera(p)
        heading, pitch = camera.bearing_of(px), max(-30.0, min(45.0, camera.elevation_of(py)))
        z = self._narrow(self._pano(p.pano_id), heading, pitch, fov, "zoom", along=p.along, parent=p.index)
        shown = [z]
        text = (f"PHOTO {z.index}: zoom ×{p.fov / fov:.0f} into photo {p.index} at ({x:.0f}, {y:.0f})"
                + (f" on '{what}'" if what else "") + ", same panorama "
                f"({_m(p.along)}), {self._narrow_note(z)}.\n" + self._examine(z, shown) + "\n\n" + self._state())
        return self._log("zoom", args, ToolResult(text, [self._file(q) for q in shown]))

    def look_from(self, candidate: int, from_m: float | None = None, fov: float = DEFAULT_ZOOM_FOV) -> ToolResult:
        """A narrow view of a candidate from another panorama: a new viewpoint."""
        args = {"candidate": candidate, "from_m": from_m, "fov": fov}
        self._count_call()
        if not ZOOM_FOV[0] <= fov <= ZOOM_FOV[1]:
            raise ToolError(f"fov must be between {ZOOM_FOV[0]:.0f} and {ZOOM_FOV[1]:.0f}")
        c = self._candidate(candidate)
        target = self.world.frame.to_xy(c.lat, c.lon)
        used = {self._photo(i).pano_id for i, _, _ in c.views}
        if from_m is not None:
            pano = self._nearest_pano(from_m, None)
            if pano.pano_id in used:
                raise ToolError(f"candidate {candidate} was already seen from the panorama nearest {_m(from_m)}; "
                                f"pick a position further away")
        else:
            pano = self._other_viewpoint(c, target, used)
        heading = compass(target[0] - self._xy(pano)[0], target[1] - self._xy(pano)[1])
        along = self.world.path.along_near(self._xy(pano), c.along, 60.0)
        v = self._narrow(pano, heading, 0.0, fov, "look_from", along=along)
        d = math.dist(self._xy(pano), target)
        text = (f"PHOTO {v.index}: candidate {candidate} seen from another panorama ({_m(along)}, {d:.0f} m from its "
                f"estimated position), {self._narrow_note(v)}. It is aimed at the ESTIMATED position, so the object may "
                f"be off centre. If you see it: mark_candidate on this photo with same_as={candidate} (two panoramas "
                f"triangulate its position).\n" + self._rejudge(c, v) + "\n\n" + self._state())
        return self._log("look_from", args, ToolResult(text, [self._file(v)]))

    def mark_candidate(self, photo: int, x: float, y: float, kind: str, same_as: int | None = None) -> ToolResult:
        args = {"photo": photo, "x": x, "y": y, "kind": kind, "same_as": same_as}
        self._count_call()
        if kind not in CANDIDATE_KINDS:
            raise ToolError(f"kind must be one of {', '.join(CANDIDATE_KINDS)}")
        p = self._photo(photo)
        px, py = self._pixel(p, x, y)
        bearing, point, basis = self._candidate_point(p, px, py)
        elevation = self._camera(p).elevation_of(py)
        if same_as is not None:
            c = self._candidate(same_as)
            if any(self._photo(v[0]).pano_id == p.pano_id for v in c.views):
                raise ToolError(f"candidate {same_as} already has a view from this panorama; a second view must come "
                                "from another panorama")
            c.views.append((photo, bearing, elevation))
            self._place_candidate(c)
            text = f"Candidate {c.index}: added the view from photo {photo}. " + self._describe(c)
        else:
            along, offset, _ = self.world.path.locate(point)
            lat, lon = self.world.latlon(point)
            c = Candidate(len(self.candidates) + 1, kind, [(photo, bearing, elevation)], lat, lon, along, offset,
                          basis=basis)
            self.candidates.append(c)
            text = f"Candidate {c.index} ({kind}): " + self._describe(c)
            if offset < -2:
                text += (" WARNING: this is LEFT of the path; the stop is always on the right-hand sidewalk"
                         " of travel. Check you clicked the right object.")
            text += (f" Next: confirm({c.index})." if p.toward in CLOSE_VIEWS else
                     f" To confirm it, zoom on it first and mark it on the zoom (same panorama: a new candidate).")
        return self._log("mark_candidate", args, ToolResult(text + "\n\n" + self._state()))

    def confirm(self, candidate: int) -> ToolResult:
        """No image: the confirmer judges the zoom photo the candidate was last marked on."""
        args = {"candidate": candidate}
        self._count_call()
        c = self._candidate(candidate)
        if c.status == "confirmed":
            raise ToolError(f"candidate {candidate} is already confirmed")
        if self.confirms >= MAX_CONFIRMS:
            raise ToolError(f"all {MAX_CONFIRMS} confirmations are used")
        if self.confirmer is None:
            raise ToolError("no confirmer is configured")
        zooms = [i for i, _, _ in c.views if self._photo(i).toward in CLOSE_VIEWS]
        if not zooms:
            raise ToolError(f"candidate {candidate} was marked on a wide photo only; the confirmer needs a close view: "
                            f"zoom on it and mark it on the zoom photo")
        fresh = [i for i in zooms if i not in self.judged]
        if not fresh:  # the same photo gets the same answer: asking again only spends confirmations
            raise ToolError(f"photo {zooms[-1]} was already judged by the confirmer; for a new judgement take a new "
                            f"close view (zoom closer, or look_from({candidate}))")
        photo = self._photo(fresh[-1])
        try:
            checklist = self.confirmer(self._file(photo))
        except ConfirmerError as error:
            text = (f"The confirmer gave no usable answer on photo {photo.index} ({error}); candidate {candidate} is "
                    f"still spotted, you may call confirm again.")
            return self._log("confirm", args, ToolResult(text + "\n\n" + self._state()))
        self.confirms += 1
        self.judged.add(photo.index)
        result = verdict(checklist.answers)
        c.checklist, c.plate_text, c.confirmer_note = checklist.answers, checklist.plate_text, checklist.note
        c.confirm_photo = photo.index
        c.status = "confirmed" if result.confirmed else "rejected"
        c.evidence = result.evidence
        yes = [k for k, v in checklist.answers.items() if v == "yes"]
        unsure = [k for k, v in checklist.answers.items() if v == "unsure"]
        text = (f"An independent confirmer judged photo {photo.index} (candidate {candidate}).\n"
                f"Confirmer: \"{checklist.note}\". Yes: {', '.join(yes) or 'none'}. Unsure: {', '.join(unsure) or 'none'}."
                + (f" Plate: {checklist.plate_text}." if checklist.plate_text else "")
                + f"\nCandidate {candidate} {c.status.upper()}: {result.reason}.")
        if result.confirmed:
            text += f" Evidence: {c.evidence}. " + self._describe(c)
            if len({self._photo(v[0]).pano_id for v in c.views}) < 2:
                text += (" Tip: marking it in a photo from another panorama (mark_candidate with same_as) makes the"
                         " position triangulated, more accurate. Then submit_found.")
        elif unsure:
            text += " If it was too small or blurry to judge, a closer zoom (smaller fov, or from a nearer panorama) can be marked and confirmed as a new candidate."
        return self._log("confirm", args, ToolResult(text + "\n\n" + self._state()))

    def find_other_scans(self, at_m: float) -> ToolResult:
        args = {"at_m": at_m}
        self._count_call()
        before = {p.pano_id for p in self.world.panoramas}
        self.world.panoramas = find_panoramas(self.world, self.metadata, at=at_m)
        new = [p for p in self.world.panoramas if p.pano_id not in before]
        text = (f"{len(new)} new panoramas near {_m(at_m)}: "
                + "; ".join(f"{_m(p.along)} {_side(p.offset)} scan {p.date}" for p in new)) if new else \
            f"No other panoramas from 2024 onwards near {_m(at_m)}."
        return self._log("find_other_scans", args, ToolResult(text))

    def show_map(self, draw: Callable[["Session", Path], Path]) -> ToolResult:
        """The debug map (drawn by `draw`, see drawing.py) and the state."""
        self._count_call()
        out = draw(self, self.run_dir / "maps" / f"map_{len(self.events) + 1:03d}.png")
        return self._log("show_map", {}, ToolResult(self._state(), [out]))

    def note(self, text: str) -> ToolResult:
        self._count_call()
        return self._log("note", {"text": text}, ToolResult("Noted."))

    def submit_found(self, candidate: int) -> ToolResult:
        args = {"candidate": candidate}
        self._count_call()
        c = self._candidate(candidate)
        if c.status != "confirmed":
            raise ToolError(f"candidate {candidate} is {c.status}, not confirmed; confirm it first")
        target = self.world.frame.to_xy(c.lat, c.lon)
        # A sign next to another stop (often the same name, the other direction or a shared pole) is accepted unless
        # its plate reads the other stop's id: a plate is often unreadable, and that doesn't mean the stop isn't found
        # (f2164, 0.14.0). The outcome names the neighbour, for review.
        near = [o for o in self.world.others if math.dist(target, self.world.frame.to_xy(o.lat, o.lon)) <= NEARBY_STOP_M]
        for o in near:
            if o.ref and plate_matches(c.plate_text, o.ref) and not plate_matches(c.plate_text, self.world.stop.stop_id):
                raise ToolError(f"candidate {candidate}'s plate reads {c.plate_text!r}: the sign of {o.label}, not of "
                                f"this stop")
        stop_photos = self._photograph_stop(c)
        self.outcome = {"status": "found", "candidate": c.index, "lat": c.lat, "lon": c.lon,
                        "position_basis": c.basis, "evidence": c.evidence, "plate_text": c.plate_text,
                        "scan_date": self._photo(c.views[0][0]).date,
                        "close_up": self._photo(c.confirm_photo).file if c.confirm_photo else None,
                        "stop_photos": [p.file for p in stop_photos],
                        "near_other_stop": near[0].label if near else None,
                        "plate_matches": plate_matches(c.plate_text, self.world.stop.stop_id)}
        text = f"Submitted. The search is over: found. The harness took {len(stop_photos)} photos of the stop."
        return self._log("submit_found", args, ToolResult(text, [self._file(p) for p in stop_photos], done=True))

    def exhausted(self) -> str | None:
        """Why nothing more can be found, or None. No confirmed candidate, and no way to get one: confirmations
        used up, or no image or tile left for a close view and no unjudged close view to confirm. The search then
        ends (0.11.1 runs spent up to 40 turns on free calls after this point: a model can't be asked to stop when
        every turn must be a tool call)."""
        if self.outcome is not None or any(c.status == "confirmed" for c in self.candidates):
            return None
        if self.confirmer is not None and self.confirms >= MAX_CONFIRMS:
            return "budget spent: all confirmations used"
        can_look = self.explore_used < EXPLORE_IMAGES or (self.tile_source is not None
                                                          and len(self.tiles_paid) + 2 <= MAX_TILES)
        unjudged = any(i not in self.judged and self._photo(i).toward in CLOSE_VIEWS
                       for c in self.candidates if c.status == "spotted" for i, _, _ in c.views)
        if not can_look and not unjudged:
            return "budget spent: no images or tiles left"
        return None

    def finish(self, reason: str) -> None:
        """Called by the runner when the explorer stops without submitting."""
        if self.outcome is None:
            self.outcome = {"status": "not_found", "reason": reason}
            self.save()

    # ------------------------------------------------------------ bookkeeping

    def _count_call(self) -> None:
        if self.outcome is not None:
            raise ToolError(f"the search is over ({self.outcome['status']})")
        self.calls += 1
        if self.calls > MAX_CALLS:
            self.outcome = {"status": "not_found", "reason": "call cap"}
            raise ToolError("call cap reached: the search is over (not_found)")

    def _spend(self) -> None:
        if self.explore_used >= EXPLORE_IMAGES:
            raise ToolError(f"all {EXPLORE_IMAGES} images are used; you can still mark and confirm on the photos you "
                            "have")

    def _travel_bearing(self, along: float) -> float:
        a = self.world.path.point(along - BEARING_SPAN_M)
        b = self.world.path.point(along + BEARING_SPAN_M)
        if math.dist(a, b) < 1.0:
            return self.world.path.bearing(along)
        return compass(b[0] - a[0], b[1] - a[1])

    def _sweep(self, from_m: float, facing: str, scan: str | None) -> Photo:
        self._spend()
        pano = self._nearest_pano(from_m, scan)
        along = self.world.path.along_near(self._xy(pano), from_m, 30.0)  # on the pass that was asked for
        heading = (self._travel_bearing(along) + SWEEP_TURNS[facing]) % 360
        self._refuse_if_unbalanced(along)
        self._refuse_if_nothing_new(Camera(self._xy(pano), heading, SWEEP_FOV, 0.0, *IMAGE_SIZE), along, facing)
        self.sweeps += 1
        photo = self._shoot(pano, heading, SWEEP_FOV, 0.0, f"sweep_{facing}", along=along, shot=self.sweeps)
        self._mark_seen_close(photo)
        return photo

    def looked_out_to(self, side: int) -> float:
        """How far from the start (metres along the path) one side (+1 ahead, -1 behind) has been looked at: the
        farthest distance within which LOOKED_SHARE of its sidewalk is seen close or glimpsed (unscanned and hidden
        count as done: nothing more can be seen there). inf when the side is done to its limit."""
        cells = sorted((abs(a), st) for a, st in zip(self.cells, self.state, strict=True) if a * side > 0)
        reach, looked = 0.0, 0
        for n, (d, st) in enumerate(cells, 1):
            looked += st != "not_looked"
            if looked / n >= LOOKED_SHARE:
                reach = d
        return math.inf if cells and reach >= cells[-1][0] - CELL_M else reach

    def _refuse_if_unbalanced(self, along: float) -> None:
        side = 1 if along >= 0 else -1
        other = self.looked_out_to(-side)
        if abs(along) > other + self.balance_m:
            name, sign = ("behind" if side > 0 else "ahead"), -side
            raise ToolError(f"the search spreads out evenly from the start: {name} it is looked at only out to "
                            f"{_m(sign * other)}, so no sweep stands farther out than {_m(side * (other + self.balance_m))} "
                            f"here yet. Sweep {name} first.")

    def _refuse_if_nothing_new(self, camera: Camera, along: float, facing: str) -> None:
        """A sweep that would show no sidewalk not already seen close or glimpsed is refused before it is taken: it
        costs an image and a turn for nothing (f306, 0.14.0: two sweeps repeated the opening photos, the model wrote
        "this is the same view as photo 1"). Its stretch is named, and the wide photos that already show it."""
        if self._seen_by(camera, along):
            return
        shown = [i for i, p in enumerate(self._sidewalk) if camera.column_of(p) is not None
                 and math.dist(p, camera.position) <= 80 and abs(self.cells[i] - along) <= 120]
        if not shown:
            raise ToolError(f"a sweep {facing} from {_m(along)} would show no right-hand sidewalk within 80 m")
        lo, hi = sorted((self.cells[shown[0]], self.cells[shown[-1]]))
        mid = self._sidewalk[shown[len(shown) // 2]]
        earlier = [q.index for q in self.photos if q.fov == SWEEP_FOV and self._camera(q).column_of(mid) is not None]
        raise ToolError(f"a sweep {facing} from {_m(along)} would show nothing new: the sidewalk from {_m(lo)} to "
                        f"{_m(hi)} is already seen close or glimpsed" + (f" (photos {', '.join(map(str, earlier[-3:]))})"
                                                                         if earlier else "") +
                        ". Zoom on something in those photos, or sweep where the sidewalk is not looked at yet.")

    def _narrow(self, pano: Panorama, heading: float, pitch: float, fov: float, toward: str, along: float,
                parent: int | None = None) -> Photo:
        """A narrow view: from tiles while the tile budget allows, else a narrow Static image."""
        if self.tile_source is not None:
            h, pt, new = self.tile_source.plan(pano.pano_id, heading, pitch, fov, *ZOOM_SIZE, self.tiles_paid)
            if len(self.tiles_paid) + len(new) <= MAX_TILES:
                self.tiles_paid |= new
                return self._shoot(pano, h, fov, pt, toward, along=along, parent=parent, source="tiles",
                                   tiles=len(new))
        if self.explore_used >= EXPLORE_IMAGES:
            raise ToolError(f"no tiles and no images left for a close view ({len(self.tiles_paid)} of {MAX_TILES} "
                            f"tiles, {EXPLORE_IMAGES} of {EXPLORE_IMAGES} images used)")
        return self._shoot(pano, heading, fov, pitch, toward, along=along, parent=parent)

    def _judge(self, photo: Photo):
        """The confirmer's checklist on a close view, or None (no confirmer, none left, no usable answer)."""
        if self.confirmer is None or self.confirms >= MAX_CONFIRMS:
            return None
        try:
            checklist = self.confirmer(self._file(photo))
        except ConfirmerError:
            return None
        self.confirms += 1
        self.judged.add(photo.index)
        return checklist

    def _examine(self, view: Photo, shown: list[Photo]) -> str:
        """Every close view is judged, so nothing the explorer zoomed on goes unexamined. A stop: a confirmed
        candidate. A look-alike: closed. Anything that could be a stop seen badly (from behind, edge on, hidden): a
        second view from another panorama, judged too, before it can be dismissed."""
        checklist = self._judge(view)
        if checklist is None:
            return ("Not judged automatically (no confirmations left, or no usable answer): if it may be the stop, "
                    "mark_candidate on this photo and confirm.")
        result = verdict(checklist.answers)
        bearing, point, basis = self._candidate_point(view, view.width / 2, view.height / 2)
        along, offset, _ = self.world.path.locate(point)
        lat, lon = self.world.latlon(point)
        c = Candidate(len(self.candidates) + 1, "seen", [(view.index, bearing, view.pitch)], lat, lon, along, offset,
                      basis=basis)
        self._record_judgement(c, view, checklist, result)
        if result.confirmed:
            self.candidates.append(c)
            return (f"JUDGED by the confirmer: \"{checklist.note}\". Candidate {c.index} CONFIRMED ({c.evidence}), "
                    f"{self._describe(c)} submit_found({c.index}); look_from({c.index}) first triangulates its position.")
        a = checklist.answers
        lookalike = [k for k in LOOKALIKE_FEATURES if a.get(k) == "yes"]
        design = a.get("same_design_as_reference")
        maybe = a.get("could_be_stop_from_another_angle") in ("yes", "unsure") or a.get("shelter") == "unsure" or \
            design in ("yes", "unsure") or any(a.get(k) == "yes" for k in ("fermata_or_bus_text", "cotral_logo"))
        # A close view often holds several signs: a look-alike beside a panel with the Cotral design doesn't close it
        # (f4156, 0.11.1: the real sign behind a tree, an arrow sign in the same frame).
        core = any(a.get(k) == "yes" for k in ("fermata_or_bus_text", "cotral_logo", "timetable", "shelter"))
        if (lookalike and design != "yes" and not core) or not maybe:
            return f"JUDGED by the confirmer: not a stop (\"{checklist.note}\")."
        self.candidates.append(c)
        target = self.world.frame.to_xy(c.lat, c.lon)
        try:
            pano = self._other_viewpoint(c, target, {view.pano_id})
            heading, fov = self._frame_sight_line(self._camera(view).position, bearing, target, pano)
            second = self._narrow(pano, heading, 0.0, fov, "look_from",
                                  along=self.world.path.along_near(self._xy(pano), c.along, 60.0))
        except ToolError as error:
            c.status = "spotted"
            return (f"JUDGED by the confirmer: \"{checklist.note}\": it could be a stop seen badly from here, but no "
                    f"second view could be taken ({error}). Candidate {c.index} stays open: look at it from elsewhere.")
        shown.append(second)
        return (f"JUDGED by the confirmer: \"{checklist.note}\": it could be a stop seen badly from here, so the "
                f"harness looked at it from another panorama: PHOTO {second.index}, {self._narrow_note(second)}.\n"
                + self._rejudge(c, second))

    def _rejudge(self, c: Candidate, view: Photo) -> str:
        """Judge a candidate's view from another panorama. It can confirm the candidate, never reject it: it is aimed
        at an estimated position and may not show the object at all (f4156, 0.11.1: a bench and an arrow sign in the
        second view rejected the real stop)."""
        checklist = self._judge(view)
        if checklist is None:
            return f"Not judged automatically: confirm({c.index}) after marking it on this photo."
        result = verdict(checklist.answers)
        if c.status == "confirmed" and not result.confirmed:
            return f"Second view judged: \"{checklist.note}\" (candidate {c.index} stays confirmed)."
        if result.confirmed:
            self._record_judgement(c, view, checklist, result)
            return (f"Second view JUDGED by the confirmer: \"{checklist.note}\". Candidate {c.index} CONFIRMED "
                    f"({c.evidence}). submit_found({c.index}).")
        c.status = "spotted"
        return (f"Second view judged: \"{checklist.note}\". That does not settle it (the view may have missed the "
                f"object): candidate {c.index} stays open.")

    def _record_judgement(self, c: Candidate, view: Photo, checklist, result) -> None:
        c.checklist, c.plate_text, c.confirmer_note = checklist.answers, checklist.plate_text, checklist.note
        c.confirm_photo = view.index
        c.status = "confirmed" if result.confirmed else "rejected"
        c.evidence = result.evidence

    def _complete_corner(self, photo: Photo) -> tuple[float | None, list[Photo]]:
        """When a sweep faces a corner, look round it: from just past it looking back, and from just before it
        looking ahead. The explorer can't cut a corner; the harness never leaves one half-seen."""
        sign = 1 if photo.toward == "sweep_ahead" else -1
        ahead = [b for b, _ in self.bends if b not in self.corners_done and 0 < sign * (b - photo.along) <= CORNER_REACH_M]
        if not ahead:
            return None, []
        corner = min(ahead, key=lambda b: abs(b - photo.along))
        self.corners_done.add(corner)
        done = {(q.pano_id, q.toward) for q in self.photos}
        shots = []
        for wanted, facing, chord in ((corner + CORNER_STEP_M, "behind", (0.0, 8.0)),
                                      (corner - CORNER_STEP_M, "ahead", (-8.0, 0.0))):
            if self.explore_used >= EXPLORE_IMAGES:
                break
            try:
                pano = self._nearest_pano(wanted, None)
            except ToolError:
                continue
            if (pano.pano_id, f"sweep_{facing}") in done:
                continue
            along = self.world.path.along_near(self._xy(pano), wanted, 20.0)
            a, b = self.world.path.point(along + chord[0]), self.world.path.point(along + chord[1])
            heading = (compass(b[0] - a[0], b[1] - a[1]) + SWEEP_TURNS[facing]) % 360
            self.sweeps += 1
            shot = self._shoot(pano, heading, SWEEP_FOV, 0.0, f"sweep_{facing}", along=along, shot=self.sweeps)
            self._mark_seen_close(shot)
            done.add((pano.pano_id, shot.toward))
            shots.append(shot)
        return corner, shots

    def _frame_sight_line(self, origin, bearing: float, target, pano: Panorama) -> tuple[float, float]:
        """(heading, fov) for a view from `pano` of the stretch of a first view's sight line where the object can be:
        a single view's bearing is precise, its distance is not."""
        d0 = max(math.dist(origin, target), 1.0)
        here = self._xy(pano)
        ends = [ray_point(origin, bearing, d0 * k) for k in SECOND_VIEW_RANGE]
        bearings = [compass(e[0] - here[0], e[1] - here[1]) for e in ends]
        spread = angle_diff(bearings[1], bearings[0])
        middle = (bearings[0] + spread / 2) % 360
        margin = math.degrees(math.atan(SECOND_VIEW_SPAN_M / max(math.dist(here, target), 1.0)))
        fov = max(ZOOM_FOV[0], min(SECOND_VIEW_FOV, abs(spread) + 2 * margin))
        if abs(spread) + 2 * margin > SECOND_VIEW_FOV:  # too long a stretch to frame: centre on the estimate
            middle = compass(target[0] - here[0], target[1] - here[1])
        return middle, fov

    def _narrow_note(self, p: Photo) -> str:
        paid = (f"{p.tiles} tile{'s' if p.tiles != 1 else ''} ({MAX_TILES - len(self.tiles_paid)} left)"
                if p.source == "tiles" else "1 Static image (no tiles left)")
        return f"heading {p.heading:.0f}°, pitch {p.pitch:.0f}°, fov {p.fov:.0f}°, {p.width}x{p.height}, cost {paid}"

    def _other_viewpoint(self, c: Candidate, target, used: set[str]) -> Panorama:
        """The best other panorama for a candidate: close to it, at least a few metres away, and before it in the
        direction of travel (stop signs face the buses arriving), else after it."""
        close = [p for p in self.world.panoramas if p.pano_id not in used
                 and 5.0 <= math.dist(self._xy(p), target) <= LOOK_FROM_MAX_M]
        if not close:
            raise ToolError(f"no other panorama within {LOOK_FROM_MAX_M:.0f} m of candidate {c.index}; try "
                            f"find_other_scans near {_m(c.along)}")
        tx, ty = unit(self._travel_bearing(c.along))
        before = [p for p in close if (target[0] - self._xy(p)[0]) * tx + (target[1] - self._xy(p)[1]) * ty >= 3.0]
        return min(before or close, key=lambda p: math.dist(self._xy(p), target))

    def _opening(self) -> list[Photo]:
        """Two wide sweeps taken for the explorer: ahead-right from before the start and behind-right from after it,
        each from the farthest of OPENING_OFFSETS_M with a panorama and no corner between it and the start."""
        start = self.world.starts[0].along
        lo, hi = self.world.limits
        chosen: list[tuple[Panorama, float, str, str]] = []
        for sign, facing, toward in ((-1, "ahead", "opening_before"), (1, "behind", "opening_after")):
            for offset in OPENING_OFFSETS_M:
                wanted = start + sign * offset
                if not lo <= wanted <= hi:
                    continue
                point = self.world.path.point(wanted)
                options = [q for q in self.world.panoramas if math.dist(self._xy(q), point) <= OPENING_PANO_M
                           and all(q.pano_id != c[0].pano_id for c in chosen)]
                if not options:
                    continue
                pano = min(options, key=lambda q: math.dist(self._xy(q), point))
                along = self.world.path.along_near(self._xy(pano), wanted, 20.0)
                clear_of_corners = self._bend_between(along, start) is None and all(
                    abs(b - along) > BEARING_SPAN_M for b, _ in self.bends)  # the facing follows the road
                if clear_of_corners and sign * (along - start) > 3.0:
                    chosen.append((pano, along, facing, toward))
                    break
        if not chosen:  # a short or broken scan: the panorama nearest the start, looking ahead
            near = [q for q in self.world.panoramas if math.dist(self._xy(q), self.world.path.point(start)) <= 40.0]
            if not near:
                raise ToolError("no panorama near the start")
            q = min(near, key=lambda q: math.dist(self._xy(q), self.world.path.point(start)))
            chosen.append((q, self.world.path.along_near(self._xy(q), start, 60.0), "ahead", "opening_before"))
        photos = []
        for pano, along, facing, toward in chosen:
            self._spend()
            heading = (self._travel_bearing(along) + SWEEP_TURNS[facing]) % 360
            photo = self._shoot(pano, heading, SWEEP_FOV, 0.0, toward, along=along)
            self._mark_seen_close(photo)
            photos.append(photo)
        return photos

    def _opening_caption(self, p: Photo) -> str:
        where = ("AHEAD-RIGHT, from BEFORE the start" if p.toward == "opening_before" else
                 "BEHIND-RIGHT, from AFTER the start")
        return (f"PHOTO {p.index}: opening sweep {where}, from the panorama at {_m(p.along)}, scan {p.date}. "
                f"In view: {self._coverage(p)}.")

    def _shoot(self, pano: Panorama, heading: float, fov: float, pitch: float, toward: str, along: float,
               shot: int = 0, parent: int | None = None, source: str = "static", tiles: int = 0) -> Photo:
        width, height = ZOOM_SIZE if source == "tiles" else IMAGE_SIZE
        key = (f"{'t_' if source == 'tiles' else ''}{pano.pano_id}_{heading:.1f}_{fov:.1f}_{pitch:.1f}_"
               f"{width}x{height}.jpg")
        cached = self.image_cache / key
        billed = tiles > 0 if source == "tiles" else not cached.is_file()
        if not cached.is_file():
            self.image_cache.mkdir(parents=True, exist_ok=True)
            if source == "tiles":
                cached.write_bytes(self.tile_source.render(pano.pano_id, heading, pitch, fov, width, height))
            else:
                cached.write_bytes(self.fetch_image(pano.pano_id, heading, fov, pitch, width, height))
        index = len(self.photos) + 1
        file = f"photos/{index:02d}_{key}"
        (self.run_dir / file).write_bytes(cached.read_bytes())
        _, offset = self._offset_at(self._xy(pano), along)
        photo = Photo(index, pano.pano_id, pano.date, along, offset, heading % 360, fov, pitch, toward, file,
                      pano.lat, pano.lon, width, height, shot, parent, billed, source, tiles)
        self.photos.append(photo)
        return photo

    def _photograph_stop(self, c: Candidate) -> list[Photo]:
        """The found stop and its surroundings, for the next stage: a wider view from the panorama that confirmed it,
        and one from a panorama about STOP_PHOTO_BACK_M before it (as a passenger arrives), aimed at its position."""
        photos: list[Photo] = []
        source = self._photo(c.confirm_photo or c.views[-1][0])
        bearing = next((b for i, b, _ in c.views if i == source.index), source.heading)
        photos.append(self._shoot(self._pano(source.pano_id), bearing, STOP_CONTEXT_FOV[0], 0.0, "stop_photo",
                                  along=source.along))
        target = self.world.frame.to_xy(c.lat, c.lon)
        wanted = self.world.path.point(c.along - STOP_PHOTO_BACK_M)
        others = [p for p in self.world.panoramas if p.pano_id != source.pano_id and p.date == source.date
                  and math.dist(self._xy(p), target) >= 6.0 and math.dist(self._xy(p), wanted) <= 25.0]
        if others:
            pano = min(others, key=lambda p: math.dist(self._xy(p), wanted))
            heading = compass(target[0] - self._xy(pano)[0], target[1] - self._xy(pano)[1])
            along = self.world.path.along_near(self._xy(pano), c.along, 40.0)
            photos.append(self._shoot(pano, heading, STOP_CONTEXT_FOV[1], 0.0, "stop_photo", along=along))
        return photos

    def _find_bends(self) -> list[tuple[float, float]]:
        """(along, signed turn in degrees, + right) of every corner of the path within the limits."""
        lo, hi = self.world.limits
        path = self.world.path
        turns = []
        for a in _frange(lo, hi, 2.0):
            before = path.point(a - BEND_SPAN_M), path.point(a)
            after = path.point(a), path.point(a + BEND_SPAN_M)
            if math.dist(*before) < 1 or math.dist(*after) < 1:
                continue
            d = angle_diff(compass(after[1][0] - after[0][0], after[1][1] - after[0][1]),
                           compass(before[1][0] - before[0][0], before[1][1] - before[0][1]))
            turns.append((a, d))
        bends, run = [], []
        for a, d in [*turns, (math.inf, 0.0)]:
            if abs(d) >= BEND_DEG and (not run or (a - run[-1][0] <= 2.5 and (d > 0) == (run[-1][1] > 0))):
                run.append((a, d))
                continue
            if run:
                bends.append(max(run, key=lambda t: abs(t[1])))
            run = [(a, d)] if abs(d) >= BEND_DEG else []
        return bends

    def _bend_between(self, a: float, b: float, margin: float = 3.0) -> float | None:
        """The corner nearest `a` strictly between a and b (no view from a sees round it), or None."""
        lo, hi = sorted((a, b))
        inside = [x for x, _ in self.bends if lo + margin < x < hi - margin]
        return min(inside, key=lambda x: abs(x - a)) if inside else None

    def _unexamined_corners(self) -> list[tuple[float, float, float]]:
        """(along, turn, share of the remaining likelihood within CORNER_M) of corners not yet seen close, most
        likely first."""
        lik = self._likelihood()
        total = sum(lik) or 1.0
        out = []
        for x, d in self.bends:
            if x in self.corners_done:
                continue
            near = [i for i, a in enumerate(self.cells) if abs(a - x) <= CORNER_M and self.state[i] != "unscanned"]
            if not near:
                continue
            done = sum(1 for i in near if self.state[i] in ("seen_close", "surveyed_clear")) / len(near)
            if done < 0.7:
                out.append((x, d, sum(lik[i] for i in near) / total))
        return sorted(out, key=lambda t: -t[2])

    def _mark_seen_close(self, photo: Photo) -> None:
        """Sidewalk where a stop sign would be at least READABLE_PX wide in this photo is seen close; at least
        SPOT_PX wide, glimpsed (the explorer still has to notice it and zoom)."""
        for i, state in self._seen_by(self._camera(photo), photo.along).items():
            self.state[i] = state

    def _seen_by(self, camera: Camera, along: float) -> dict[int, str]:
        """The cells a photo from `along` would improve, and the state each would get. Nothing round a corner: the
        sidewalk past a bend is hidden by what stands on the corner."""
        out = {}
        for i, p in enumerate(self._sidewalk):
            now = self.state[i]
            if now in ("unscanned", "hidden", "seen_close") or camera.column_of(p) is None:
                continue
            bend = self._bend_between(along, self.cells[i])
            if bend is not None and abs(self.cells[i] - bend) > 4.0:
                continue
            px = camera.pixels_across(SIGN_M, math.dist(p, camera.position))
            if px >= READABLE_PX:
                out[i] = "seen_close"
            elif px >= SPOT_PX and now == "not_looked":
                out[i] = "glimpsed"
        return out

    def _prior(self) -> list[float]:
        """Where the stop probably is: the measured spread around the start (the most accurate source), plus
        bumps at the OSM hints."""
        weights = [0.0] * len(self.cells)
        start = self.world.starts[0]
        spread = SPREAD["osm" if start.kind.startswith("osm") else start.kind if start.kind in SPREAD else "gtfs"]
        origin = self.world.frame.to_xy(start.lat, start.lon)
        for i, a in enumerate(self.cells):  # by distance on the ground: a later pass can be close to the start
            d, lo = math.dist(self.world.path.sidewalk(a), origin), 0
            for hi, share in spread:
                if d < hi:  # the ring's share, spread over the ring's length of sidewalk on both sides
                    weights[i] += share / (2 * (hi - lo)) * CELL_M
                    break
                lo = hi
        for h in self.world.hints:
            if h.offset < -3:
                continue
            w = HINT_WEIGHT.get(h.kind, 0.1)
            for i, a in enumerate(self.cells):
                weights[i] += w * math.exp(-0.5 * ((a - h.along) / HINT_SIGMA_M) ** 2) * CELL_M / (
                    HINT_SIGMA_M * math.sqrt(2 * math.pi))
        total = sum(weights) or 1.0
        return [w / total for w in weights]

    def _likelihood(self) -> list[float]:
        return [w * SEEN_FACTOR.get(s, 1.0) for w, s in zip(self.prior, self.state, strict=True)]

    # ------------------------------------------------------------- geometry

    def _xy(self, pano) -> tuple[float, float]:
        return self.world.frame.to_xy(pano.lat, pano.lon)

    def _camera(self, photo: Photo) -> Camera:
        return Camera(self.world.frame.to_xy(photo.lat, photo.lon), photo.heading, photo.fov, photo.pitch,
                      photo.width, photo.height)

    def _offset_at(self, p, along: float) -> tuple[float, float]:
        q = self.world.path.point(along)
        rx, ry = self.world.path.right(along)
        return along, (p[0] - q[0]) * rx + (p[1] - q[1]) * ry

    def _pano(self, pano_id: str) -> Panorama:
        return next(p for p in self.world.panoramas if p.pano_id == pano_id)

    def _usable_panoramas(self, scan: str | None) -> list[Panorama]:
        panos = [p for p in self.world.panoramas if scan is None or p.date == scan]
        if not panos:
            raise ToolError(f"no panorama from scan {scan}" if scan else "no panorama at all")
        return panos

    def _nearest_pano(self, along: float, scan: str | None) -> Panorama:
        lo, hi = self.world.limits
        if not lo - 20 <= along <= hi + 20:
            raise ToolError(f"{_m(along)} is outside the search limits ({_m(lo)} to {_m(hi)})")
        panos = self._usable_panoramas(scan)
        target = self.world.path.point(along)
        best = min(panos, key=lambda p: (math.dist(self._xy(p), target), p.date and -int(p.date[:4])))
        if math.dist(self._xy(best), target) > 25:
            raise ToolError(f"no panorama within 25 m of {_m(along)}; that stretch may be unscanned")
        return best

    def _pixel(self, photo: Photo, x: float, y: float) -> tuple[float, float]:
        """The pixel of a point given on the 0-1000 grid of a photo."""
        if not (0 <= x <= GRID and 0 <= y <= GRID):
            raise ToolError(f"x and y are on a 0-{GRID} grid over the photo (0,0 top left, {GRID},{GRID} bottom right)")
        return min(x, GRID - 0.5) * photo.width / GRID, min(y, GRID - 0.5) * photo.height / GRID

    def _check_pixel(self, photo: Photo, x: float, y: float) -> None:
        if not (0 <= x < photo.width and 0 <= y < photo.height):
            raise ValueError(f"pixel ({x}, {y}) outside photo {photo.index} ({photo.width}x{photo.height})")

    def _point(self, photo: Photo, x: float, y: float):
        """(bearing, point) of a pixel on the right-hand sidewalk: where its sight line reaches the sidewalk, else
        where the pointed spot meets the ground (near the horizon a row says almost nothing about distance, and on
        slopes the ground range was 5-70 m off)."""
        self._check_pixel(photo, x, y)
        camera = self._camera(photo)
        bearing = camera.bearing_of(x)
        on_sidewalk = ray_to_sidewalk(self.world.path, camera.position, bearing)
        if on_sidewalk is not None:
            return bearing, on_sidewalk
        distance = camera.ground_range(y)
        return bearing, ray_point(camera.position, bearing, distance if distance is not None else 15.0)

    def _candidate_point(self, photo: Photo, x: float, y: float):
        """(bearing, point, basis) of a candidate seen once. The bearing is precise; the distance is not: from the
        ground under the object it was 5-70 m off in the dry runs (slopes, small pitch errors). So, in order: the point
        of the sight line nearest an OSM start it passes close to (about 5 m off), where the sight line meets the
        right-hand sidewalk (about 10 m), the ground distance."""
        self._check_pixel(photo, x, y)
        camera = self._camera(photo)
        bearing = camera.bearing_of(x)
        start = self.world.starts[0]
        if start.kind.startswith("osm"):
            q = self.world.frame.to_xy(start.lat, start.lon)
            ux, uy = unit(bearing)
            k = (q[0] - camera.position[0]) * ux + (q[1] - camera.position[1]) * uy
            nearest = ray_point(camera.position, bearing, k)
            if k > 0 and math.dist(nearest, q) <= OSM_SNAP_M:
                return bearing, nearest, "ray_near_osm"
        on_sidewalk = ray_to_sidewalk(self.world.path, camera.position, bearing)
        if on_sidewalk is not None:
            return bearing, on_sidewalk, "single_ray_sidewalk"
        _, point = self._point(photo, x, y)
        return bearing, point, "ground_range"

    def _place_candidate(self, c: Candidate) -> None:
        rays = [(self._camera(self._photo(i)).position, b) for i, b, _ in c.views]
        panos = {self._photo(i).pano_id for i, _, _ in c.views}
        dates = {self._photo(i).date for i, _, _ in c.views}
        crossing = triangulate(rays) if len(panos) >= 2 and len(dates) == 1 else None
        if crossing and crossing[1] < 3.0:
            point, c.basis = crossing[0], "triangulated"
            c.along, c.offset, _ = self.world.path.locate(point)
            c.lat, c.lon = self.world.latlon(point)

    def _briefing(self) -> str:
        w = self.world
        lo, hi = w.limits
        lines = [f"STOP {w.stop.stop_id}: {w.stop.name}",
                 f"Positions are metres along the bus's path from the start (0 m), + ahead in the direction of "
                 f"travel, - behind. 'right'/'left' are relative to the direction of travel. The stop is on the "
                 f"RIGHT-hand sidewalk of travel. Search limits: {_m(lo)} to {_m(hi)}."]
        if w.previous:
            lines.append(f"Previous stop of this route: {w.previous.label} at {_m(w.previous.along)}.")
        if w.next:
            lines.append(f"Next stop of this route: {w.next.label} at {_m(w.next.along)}.")
        lines.append("The path: " + self._path_text())
        lines.extend(self._shared_text())
        trust = {"osm_ref": "OpenStreetMap object tagged with this stop's id: usually within 10 m of the stop",
                 "osm_nearest": "OpenStreetMap stop-like object nearest this stop: usually within 10-25 m",
                 "places": "Google Places: often 10-50 m off",
                 "gtfs": "the timetable's position: often 25-100 m off, sometimes on the wrong side of the road"}
        first = w.starts[0]
        lines.append(f"THE START (0 m) is the most accurate position we have: {first.label} ({trust[first.kind]}). "
                     f"Look there first.")
        if len(w.starts) > 1:
            lines.append("Other, less accurate positions: " + "; ".join(
                f"{s.label} at {_m(s.along)}, {abs(s.offset):.0f} m {_side(s.offset)} of the path centre line"
                for s in w.starts[1:]) + ".")
        lines.append("OpenStreetMap hints (stop-like objects mapped by volunteers; not proof): " + ("; ".join(
            f"{h.label}{' ref ' + h.ref if h.ref else ''} at {_m(h.along)}, {abs(h.offset):.0f} m {_side(h.offset)}"
            for h in w.hints) or "none") + ".")
        lines.append("Other stops nearby (NOT this stop; don't submit a sign of theirs): " + ("; ".join(
            f"{o.label} at {_m(o.along)}, {_side(o.offset)}" for o in w.others) or "none") + ".")
        lines.append("Panoramas: " + self._panorama_text())
        lines.append(f"Budget: {EXPLORE_IMAGES} wide images (the opening one included; 1 per sweep) for looking broadly, "
                     f"{MAX_TILES} tiles for close views (a zoom or look_from costs about 2-4 tiles), {MAX_CONFIRMS} "
                     f"confirmations (free).")
        lines.append("Below: the two opening sweeps, taken for you: AHEAD-RIGHT from before the start and "
                     "BEHIND-RIGHT from after it, so the sidewalk around the start is in front of both cameras. Signs "
                     "face the arriving buses: the first sees their faces, the second their backs.")
        return "\n".join(lines)

    def _path_text(self) -> str:
        lo, hi = self.world.limits
        turns, last = [], self.world.path.bearing(lo)
        a = lo
        while a <= hi:
            b = self.world.path.bearing(a)
            d = angle_diff(b, last)
            if abs(d) >= 30:
                turns.append(f"at {_m(a)} it turns {'right' if d > 0 else 'left'} ({abs(d):.0f}°)")
                last = b
            a += 5
        start = self.world.path.bearing(0)
        return f"at the start it heads {_compass_name(start)} ({start:.0f}°); " + (", ".join(turns) or "no sharp turns")

    def _shared_text(self) -> list[str]:
        out = []
        for s in self.shared:
            if s.opposite:
                out.append(f"SAME ROAD TWICE (out and back): from {_m(s.a_from)} to {_m(s.a_to)} the bus drives a road "
                           f"it drives again later in the OPPOSITE direction, from {_m(s.b_to)} to {_m(s.b_from)}: "
                           f"{_m(s.a_from)} is the same place as {_m(s.b_from)}, {_m(s.a_to)} the same place as "
                           f"{_m(s.b_to)}. Each pass has its own right-hand sidewalk, on OPPOSITE sides of the road, "
                           f"and either can hold the stop. A sweep shows the right-hand side of the pass you ask for: "
                           f"to see the other side of the same place, sweep from the matching position on the other "
                           f"pass.")
            else:
                out.append(f"SAME ROAD TWICE (loop): from {_m(s.a_from)} to {_m(s.a_to)} and again from {_m(s.b_from)} "
                           f"to {_m(s.b_to)} the bus drives the same road in the same direction: the same right-hand "
                           f"sidewalk.")
        return out

    def _panorama_text(self) -> str:
        by_date: dict[str, list[Panorama]] = {}
        for p in self.world.panoramas:
            by_date.setdefault(p.date, []).append(p)
        parts = []
        for date, panos in sorted(by_date.items(), reverse=True):
            alongs = sorted(p.along for p in panos)
            gaps = [b - a for a, b in zip(alongs, alongs[1:])]
            spacing = f", spacing about {sorted(gaps)[len(gaps) // 2]:.0f} m" if gaps else ""
            parts.append(f"scan {date}: {len(panos)} from {_m(alongs[0])} to {_m(alongs[-1])}{spacing}")
        unscanned = self._ranges("unscanned")
        return "; ".join(parts) + (". Unscanned (no Street View, can't be searched): " + ", ".join(unscanned)
                                   if unscanned else ". No unscanned stretch.")

    def _coverage(self, p: Photo) -> str:
        """Which stretch of the right-hand sidewalk a wide photo shows, and how big a sign would look along it. No
        points on the photo: given ready-made points, the explorer zoomed on them instead of looking (16 of 16 zooms
        on caption points, f4156, 0.13.0: cars, motorcycles and faces, while the sign stood in plain view)."""
        camera = self._camera(p)
        lo, hi = self.world.limits
        seen = []  # (along, size) of the sidewalk in view, nearest first
        for a in _frange(math.ceil(lo), hi, 2.0):
            s = self.world.path.sidewalk(a)
            d = math.dist(s, camera.position)
            # only the pass near this photo: a far-away pass of the same road would be described twice
            if camera.column_of(s) is not None and d <= 80 and abs(a - p.along) <= 120 \
                    and 0 <= camera.row_of(s, SIGN_HEIGHT_M) < p.height:
                seen.append((d, a, _sign_size(camera.pixels_across(SIGN_M, d))))
        if not seen:
            return "no right-hand sidewalk within 80 m"
        seen.sort()
        near, far = seen[0][1], seen[-1][1]
        text = f"right-hand sidewalk from {_m(near)} ({seen[0][0]:.0f} m away) to {_m(far)} ({seen[-1][0]:.0f} m away)"
        parts = []
        for size in ("clear", "small", "a speck"):
            stretch = [a for _, a, z in seen if z == size]
            if stretch:
                parts.append(f"{size} from {_m(stretch[0])} to {_m(stretch[-1])}")
        return text + "; a sign there would look " + ", ".join(parts)

    def _sweep_caption(self, p: Photo) -> str:
        where = "AHEAD-RIGHT" if p.toward == "sweep_ahead" else "BEHIND-RIGHT"
        return (f"PHOTO {p.index}: sweep {p.shot} {where} from the panorama at {_m(p.along)} ({abs(p.offset):.0f} m "
                f"{_side(p.offset)} of the centre line), scan {p.date}. In view: {self._coverage(p)}.")

    def _state(self) -> str:
        lik = self._likelihood()
        total = sum(lik)
        lines = [f"STATE: {EXPLORE_IMAGES - self.explore_used}/{EXPLORE_IMAGES} images, "
                 f"{MAX_TILES - len(self.tiles_paid)}/{MAX_TILES} tiles, {MAX_CONFIRMS - self.confirms}/{MAX_CONFIRMS} "
                 f"confirmations left."]
        for state in ("seen_close", "surveyed_clear", "glimpsed", "hidden", "not_looked", "unscanned"):
            ranges = self._ranges(state)
            if ranges:
                lines.append(f"- {state.replace('_', ' ')}: {', '.join(ranges)}")
        corners = self._unexamined_corners()
        if corners and self.outcome is None:
            lines.append("- CORNERS NOT YET EXAMINED: " + "; ".join(
                             f"{_m(x)} ({'right' if d > 0 else 'left'} turn {abs(d):.0f}°, {share:.0%})"
                             for x, d, share in corners[:4]) + (f"; {len(corners) - 4} more" if len(corners) > 4 else ""))
        if self.candidates:
            lines.append("- candidates: " + "; ".join(
                f"{c.index} {c.kind} at {_m(c.along)} {_side(c.offset)} [{c.status}]" for c in self.candidates))
        if self.explore_used >= EXPLORE_IMAGES and self.outcome is None:
            lines.append("- NO IMAGES LEFT: zoom, look_from, mark and confirm on the photos you have; the search ends "
                         "by itself when nothing is left.")
        if self.outcome:
            lines.append(f"- SEARCH OVER: {self.outcome['status']}")
        return "\n".join(lines)

    def _ranges(self, state: str) -> list[str]:
        out, start = [], None
        for i, s in enumerate([*self.state, None]):
            if s == state and start is None:
                start = i
            elif s != state and start is not None:
                a, b = self.cells[start] - CELL_M / 2, self.cells[i - 1] + CELL_M / 2
                out.append(f"{_m(a)} to {_m(b)}")
                start = None
        return out

    def _describe(self, c: Candidate) -> str:
        return (f"at {_m(c.along)}, {abs(c.offset):.0f} m {_side(c.offset)} of the path centre line "
                f"({c.basis.replace('_', ' ')}, {len(c.views)} view{'s' if len(c.views) > 1 else ''}).")

    # ---------------------------------------------------------------- record

    def _photo(self, index: int) -> Photo:
        if not 1 <= index <= len(self.photos):
            raise ToolError(f"no photo {index}")
        return self.photos[index - 1]

    def _candidate(self, index: int) -> Candidate:
        if not 1 <= index <= len(self.candidates):
            raise ToolError(f"no candidate {index}")
        return self.candidates[index - 1]

    def _file(self, photo: Photo) -> Path:
        return self.run_dir / photo.file

    def _log(self, tool: str, args: dict, result: ToolResult) -> ToolResult:
        self.events.append({"seq": len(self.events) + 1, "at": utc_now(), "tool": tool, "args": args,
                            "result": result.text, "photos": [str(p.relative_to(self.run_dir)) for p in result.images],
                            "photos_used": len(self.photos), "budget_used": self.explore_used, "error": None})
        self.save()
        return result

    def log_error(self, tool: str, args: dict, message: str) -> None:
        self.events.append({"seq": len(self.events) + 1, "at": utc_now(), "tool": tool, "args": args,
                            "result": None, "photos": [], "photos_used": len(self.photos),
                            "budget_used": self.explore_used, "error": message})
        self.save()

    def record(self) -> dict:
        w = self.world
        return {
            "layout": "agent-explorer/1",
            "harness": self.harness,
            "billed_requests": self.billed_requests(),
            "stop": {"stop_id": w.stop.stop_id, "name": w.stop.name, "lat": w.stop.lat, "lon": w.stop.lon},
            "started_at": self.started_at, "saved_at": utc_now(),
            "limits": list(w.limits), "max_photos": MAX_IMAGES,
            "budget": {"unit": "images", "images": EXPLORE_IMAGES, "stop_photos": STOP_PHOTOS, "tiles": MAX_TILES,
                       "confirms": MAX_CONFIRMS,
                       "used": {"images": self.explore_used, "sweeps": self.sweeps,
                                "zooms": sum(1 for p in self.photos if p.toward == "zoom"),
                                "look_froms": sum(1 for p in self.photos if p.toward == "look_from"),
                                "tiles": len(self.tiles_paid),
                                "stop_photos": sum(1 for p in self.photos if p.toward == "stop_photo"),
                                "confirms": self.confirms, "billed": self.billed}},
            "path": [list(w.latlon(p)) for p in w.path.points], "start_s": w.path.start_s,
            "starts": [asdict(s) for s in w.starts], "hints": [asdict(h) for h in w.hints],
            "others": [asdict(o) for o in w.others],
            "previous": asdict(w.previous) if w.previous else None, "next": asdict(w.next) if w.next else None,
            "shared": [asdict(s) for s in self.shared],
            "panoramas": [asdict(p) for p in w.panoramas],
            "cells": [{"along": a, "state": s} for a, s in zip(self.cells, self.state, strict=True)],
            "photos": [asdict(p) for p in self.photos], "candidates": [asdict(c) for c in self.candidates],
            "events": self.events, "outcome": self.outcome,
        }

    def billed_requests(self) -> dict[str, int]:
        """Requests actually sent to the billed APIs: Static images not in the cache, tiles fetched from Google."""
        return {"static": sum(1 for p in self.photos if p.source == "static" and p.billed),
                "tiles": int(getattr(self.tile_source, "fetched", 0))}

    def save(self) -> None:
        (self.run_dir / "record.json").write_text(json.dumps(self.record(), indent=1, ensure_ascii=False))


def _frange(lo: float, hi: float, step: float):
    v = lo
    while v <= hi + 1e-9:
        yield v
        v += step


# What a zoom may be aimed at: something that could be a stop. 0.15.0 NVFP4 zoomed on a grid of guessed points (tree
# tops, sky, hedges: 26 zooms on f306) while the sign's pole stood in one of its photos.
STOP_LIKE_WORDS = ("sign", "panel", "pole", "post", "plate", "shelter", "canopy", "bench", "marking", "bus", "stop",
                   "fermata", "waiting", "timetable", "board", "lay-by", "layby", "zig")


def names_a_stop_like_thing(what: str) -> bool:
    words = re.findall(r"[a-z-]+", what.lower())
    return len(words) >= 2 and any(w.startswith(k) and not w.startswith("bush") for w in words for k in STOP_LIKE_WORDS)


def plate_matches(plate_text: str, stop_id: str) -> bool:
    """Whether a plate as read ("N.f 2164", "f.2164", "F 2164") carries this stop's id ("f2164"): its number, as a
    whole number on the plate. A plain substring test refused f2164 28 times over a dot and a space (0.14.0)."""
    number = re.sub(r"\D", "", stop_id).lstrip("0")
    return bool(number) and number in (n.lstrip("0") for n in re.findall(r"\d+", plate_text))


def _m(v: float) -> str:
    return f"{v:+.0f} m"


def _sign_size(px: float) -> str:
    """How a 0.6 m sign looks at that distance in a sweep: readable, noticeable, or a speck you can't rely on."""
    return "clear" if px >= READABLE_PX else "small" if px >= SPOT_PX else "a speck"


def _side(offset: float) -> str:
    return "right" if offset >= 0 else "left"


def _compass_name(bearing: float) -> str:
    return ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")[
        int(((bearing + 22.5) % 360) // 45)]
