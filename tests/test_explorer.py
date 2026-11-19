import math
import re

import pytest

from cotral_maintenance.explorer.confirmer import FEATURES, Checklist, ConfirmerError, parse, verdict
from cotral_maintenance.explorer.geometry import Camera, PathFrame, angle_diff, compass, triangulate
from cotral_maintenance.explorer.session import (GRID, EXPLORE_IMAGES, IMAGE_SIZE, MAX_CONFIRMS, MAX_IMAGES,
                                                 MAX_TILES, STOP_PHOTOS, SWEEP_FOV, ZOOM_SIZE, Session,
                                                 ToolError)
from cotral_maintenance.explorer.world import Panorama, Placed, World, _visible_start_shift, shared_stretches
from cotral_maintenance.models import Stop
from cotral_maintenance.roadpath import LocalFrame

FRAME = LocalFrame(41.9, 12.5)
NO = dict.fromkeys(FEATURES, "no")


class FakeMetadata:
    def save(self) -> None:
        pass


class FakeConfirmer:
    """Answers every feature 'no' except the ones given; records the photos it was shown. With `then`, the answers
    for every later call."""

    def __init__(self, then=None, **answers):
        self.answers = answers
        self.then = then
        self.seen = []

    def __call__(self, photo):
        self.seen.append(photo)
        answers = self.answers if len(self.seen) == 1 or self.then is None else self.then
        return Checklist({**NO, **answers}, note="a sign")



def at(session, photo: int, x: float, y: float) -> tuple[float, float]:
    """Tools take points on the 0-1000 grid of a photo: this converts the pixel the test reasons in."""
    p = session.photos[photo - 1]
    return x * GRID / p.width, y * GRID / p.height

def straight_world(others=()) -> World:
    """A road due east from x = 0 to 600; the start at x = 300; a panorama every 10 m on the centre line."""
    path = PathFrame([(0.0, 0.0), (600.0, 0.0)], start_s=300.0)
    panos = []
    for i, x in enumerate(range(0, 601, 10)):
        lat, lon = FRAME.to_latlon(float(x), 0.0)
        panos.append(Panorama(f"p{i}", lat, lon, "2025-06", x - 300.0, 0.0, "© Google"))
    lat, lon = FRAME.to_latlon(300.0, 0.0)
    start = Placed("GTFS", "gtfs", lat, lon, 0.0, 0.0)
    return World(stop=Stop("f1", "Test stop", lat, lon), frame=FRAME, path=path, limits=(-200.0, 200.0),
                 starts=[start], hints=[], others=list(others), panoramas=panos)


def out_and_back_world() -> World:
    # Out along y = 0 (east) to x = 300, back along y = -1 (west): one row of panoramas serves both passes.
    path = PathFrame([(0.0, 0.0), (300.0, 0.0), (300.0, -1.0), (0.0, -1.0)], start_s=150.0)
    panos = [Panorama(f"p{x}", *FRAME.to_latlon(float(x), 0.0), "2025-06", x - 150.0, 0.0, "© Google")
             for x in range(0, 301, 10)]
    lat, lon = FRAME.to_latlon(150.0, 0.0)
    return World(stop=Stop("f1", "Test", lat, lon), frame=FRAME, path=path, limits=(-150.0, 440.0),
                 starts=[Placed("GTFS", "gtfs", lat, lon, 0.0, 0.0)], hints=[], others=[], panoramas=panos)


class FakeTiles:
    """Every narrow view needs 3 tiles of its own (keyed by panorama and rounded heading); one framing nudge."""

    def __init__(self):
        self.rendered = []

    def plan(self, pano_id, heading, pitch, fov, width, height, paid):
        tiles = {(pano_id, round(heading), i) for i in range(3)}
        return heading + 1.0, pitch, tiles - set(paid)

    def render(self, pano_id, heading, pitch, fov, width, height):
        self.rendered.append((pano_id, heading, pitch, fov, width, height))
        return b"tile view"


def make_session(tmp_path, world=None, confirmer=None) -> Session:
    fetched = []

    def fetch(pano_id, heading, fov, pitch, width, height):
        fetched.append((pano_id, round(heading, 1), fov, round(pitch, 1), width, height))
        return b"jpeg"

    s = Session(world or straight_world(), tmp_path / "run", tmp_path / "cache", FakeMetadata(), fetch,
                confirmer or FakeConfirmer())
    s.fetched = fetched
    return s


@pytest.fixture
def session(tmp_path):
    return make_session(tmp_path)


# ---- geometry

def test_path_frame_measures_from_the_start_and_knows_its_right():
    path = PathFrame([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], start_s=50.0)
    assert path.point(0) == pytest.approx((50.0, 0.0))
    assert path.bearing(0) == pytest.approx(90.0)  # east
    assert path.right(0) == pytest.approx((0.0, -1.0))  # right of eastbound is south
    assert path.locate((60.0, -5.0)) == pytest.approx((10.0, 5.0, 5.0))


def test_locate_prefers_the_pass_that_has_the_point_on_its_right():
    # out along y = 0 to x = 100, back along y = 1: a point at y = 8 is left of the outbound pass, right of the return
    path = PathFrame([(0.0, 0.0), (100.0, 0.0), (100.0, 1.0), (0.0, 1.0)], start_s=0.0)
    along, offset, _ = path.locate((50.0, 8.0))
    assert offset > 0 and along == pytest.approx(151.0, abs=0.5)


def test_camera_columns_and_bearings_round_trip():
    camera = Camera((0.0, 0.0), heading=90.0, fov=90.0)
    assert camera.column_of((10.0, 0.0)) == pytest.approx(320.0)
    assert camera.column_of((10.0, -10.0)) == pytest.approx(640.0)  # 45° right, at the edge
    assert camera.column_of((-10.0, 0.0)) is None  # behind
    assert camera.bearing_of(camera.column_of((10.0, -3.0))) == pytest.approx(90 + math.degrees(math.atan(0.3)))


def test_ground_range_from_a_pixel_row():
    camera = Camera((0.0, 0.0), heading=0.0, fov=90.0)
    y = 320 + 320 * 2.5 / 10.0  # 10 m away on flat ground, camera 2.5 m up
    assert camera.ground_range(y) == pytest.approx(10.0, rel=0.01)
    assert camera.ground_range(100) is None  # above the horizon


def test_camera_of_a_wide_image():
    camera = Camera((0.0, 0.0), heading=90.0, fov=90.0, width=1536, height=768)
    assert camera.column_of((10.0, 0.0)) == pytest.approx(768.0)
    assert camera.column_of((10.0, -10.0)) == pytest.approx(1536.0)
    assert camera.ground_range(384 + 768 * 2.5 / 10.0) == pytest.approx(10.0, rel=0.01)
    assert camera.elevation_of(384) == pytest.approx(0.0)
    assert camera.pixels_across(0.6, 10.0) == pytest.approx(0.6 / 10.0 * 768)


def test_triangulates_two_sight_lines():
    (x, y), rms = triangulate([((0.0, 0.0), 45.0), ((20.0, 0.0), 315.0)])
    assert (x, y) == pytest.approx((10.0, 10.0)) and rms == pytest.approx(0.0, abs=1e-6)
    assert triangulate([((0.0, 0.0), 0.0), ((5.0, 0.0), 0.0)]) is None  # parallel


def test_finds_the_same_road_driven_out_and_back():
    world = out_and_back_world()
    stretches = shared_stretches(world.path, *world.limits)
    assert len(stretches) == 1 and stretches[0].opposite
    s = stretches[0]
    # out along -150..+150 (x 0..300) comes back along +151..+451 (x 300..0): -150 is the same place as +451
    assert s.a_from == pytest.approx(-150, abs=6) and s.a_to >= 100
    # near the turnaround the match can be off by up to `near` (12 m)
    assert s.b_from == pytest.approx(301 - s.a_from, abs=12) and s.b_to == pytest.approx(301 - s.a_to, abs=12)


def test_a_straight_road_shares_nothing():
    world = straight_world()
    assert shared_stretches(world.path, *world.limits) == []


# ---- the session

def test_begin_takes_two_sweeps_with_the_start_in_front_of_both(session):
    result = session.begin()
    assert len(result.images) == 2 and len(session.photos) == 2
    before, after = session.photos
    assert (before.toward, after.toward) == ("opening_before", "opening_after")
    assert before.along == pytest.approx(-35, abs=6) and after.along == pytest.approx(35, abs=6)
    assert before.heading == pytest.approx(90 + 50) and after.heading == pytest.approx(90 + 130)  # ahead / behind-right
    # f8520, 0.12.0: photos converging on the start from 11 m missed a sign 4 m behind one camera. Now the whole
    # stretch around the start is in view of both
    for a in (-25, -15, 0, 15, 25):
        point = session.world.path.sidewalk(a)
        assert all(session._camera(p).column_of(point) is not None for p in (before, after))
    assert all(p.fov == SWEEP_FOV for p in (before, after))
    assert session.fetched[0][4:] == IMAGE_SIZE
    assert "STOP f1" in result.text and f"{EXPLORE_IMAGES - 2}/{EXPLORE_IMAGES} images" in result.text
    with pytest.raises(ToolError):
        session.begin()


def test_an_osm_start_is_looked_at_from_both_sides(tmp_path):
    world = straight_world()
    lat, lon = FRAME.to_latlon(330.0, -20.0)  # 20 m right of the road, 30 m ahead
    world.starts.insert(0, Placed("OSM shelter", "osm_nearest", lat, lon, 30.0, 20.0))
    s = make_session(tmp_path, world)
    s.begin()
    before, after = s.photos
    assert s._camera(before).position[0] < 330 < s._camera(after).position[0]
    assert all(s._camera(p).column_of((330.0, -20.0)) is not None for p in (before, after))
    assert s.explore_used == 2


def test_an_opening_never_looks_across_a_corner(tmp_path):
    s = make_session(tmp_path, corner_world())  # the corner 100 m ahead of the start: try a start 20 m before it
    s.world.starts[0] = Placed("GTFS", "gtfs", *FRAME.to_latlon(280.0, 0.0), 80.0, 0.0)
    s.begin()
    after = s.photos[1]
    assert after.along < 100 and after.along - 80 >= 3  # stepped back to this side of the corner


def test_a_candidate_seen_once_is_placed_where_its_sight_line_passes_the_osm_start(tmp_path):
    world = straight_world()
    lat, lon = FRAME.to_latlon(330.0, -8.0)
    world.starts.insert(0, Placed("OSM bus stop", "osm_ref", lat, lon, 30.0, 8.0))
    s = make_session(tmp_path, world)
    s.begin()
    camera = s._camera(s.photos[0])
    x = camera.column_of((331.0, -9.0))  # a sign 1.4 m from the OSM point; the click's row says nothing reliable
    s.mark_candidate(1, *at(s, 1, x, 600), "sign")
    c = s.candidates[0]
    assert c.basis == "ray_near_osm" and math.dist(FRAME.to_xy(c.lat, c.lon), (331.0, -9.0)) < 2.0


def test_without_osm_a_candidate_is_placed_on_the_right_hand_sidewalk(session):
    session.begin()
    camera = session._camera(session.photos[0])
    x = camera.column_of(session.world.path.sidewalk(20))
    session.mark_candidate(1, *at(session, 1, x, 630), "sign")  # a low click would put it a couple of metres away
    c = session.candidates[0]
    assert c.basis == "single_ray_sidewalk" and c.along == pytest.approx(20, abs=1.5)
    assert c.offset == pytest.approx(6, abs=0.5)


def test_the_budget_leaves_room_for_the_stop_photos():
    assert EXPLORE_IMAGES + STOP_PHOTOS == MAX_IMAGES == 22


def test_a_sweep_can_face_behind(session):
    session.begin()
    session.sweep(from_m=-100, facing="behind")
    photo = session.photos[-1]
    assert photo.toward == "sweep_behind" and photo.heading == pytest.approx(90 + 130)
    with pytest.raises(ToolError, match="facing"):
        session.sweep(from_m=-100, facing="up")


def test_a_sweep_counts_as_seen_close_only_where_a_sign_is_readable(session):
    session.begin()
    session.sweep(from_m=-100)
    states = {round(a): s for a, s in zip(session.cells, session.state, strict=True)}
    assert states[-98] == "seen_close" and states[-94] == "seen_close"  # beside and just ahead
    assert states[-70] == "not_looked"  # 30 m ahead: a sign is a few pixels
    assert states[-114] == "not_looked"  # behind: not in an ahead sweep


def test_zoom_costs_an_image_and_aims_at_the_clicked_pixel(session):
    session.begin()
    sweep = session.photos[0]
    camera = session._camera(sweep)
    result = session.zoom(sweep.index, *at(session, sweep.index, 500, 300), fov=8)
    z = session.photos[-1]
    assert z.toward == "zoom" and z.parent == sweep.index and z.pano_id == sweep.pano_id
    assert z.heading == pytest.approx(camera.bearing_of(500)) and z.pitch == pytest.approx(camera.elevation_of(300))
    assert session.explore_used == 3 and "zoom" in result.text
    with pytest.raises(ToolError, match="fov"):
        session.zoom(sweep.index, *at(session, sweep.index, 10, 10), fov=60)
    with pytest.raises(ToolError, match="0-1000 grid"):  # points are on the grid, not pixels
        session.zoom(sweep.index, 1100, 10)


def test_cached_images_are_not_billed_again(session):
    session.begin()
    session.sweep(from_m=50)
    session.sweep(from_m=50)
    assert len(session.photos) == 4 and len(session.fetched) == 3
    assert session.billed == 3 and session.explore_used == 4  # the budget counts every image, billed or not


def spot_and_confirm(session, **answers):
    """A sweep, then a zoom on something: every zoom is judged by the confirmer at once."""
    session.confirmer = FakeConfirmer(**answers)
    session.begin()
    session.sweep(from_m=40)
    return session.zoom(session.photos[-1].index, *at(session, session.photos[-1].index, 520, 330))


def test_every_zoom_is_judged_and_a_stop_becomes_a_confirmed_candidate(session):
    result = spot_and_confirm(session, fermata_or_bus_text="yes", cotral_logo="yes")
    zoom = session.photos[-1]
    c = session.candidates[0]
    assert session.confirmer.seen == [session._file(zoom)] and c.confirm_photo == zoom.index
    assert "CONFIRMED" in result.text and c.status == "confirmed" and c.evidence == "cotral_sign"
    assert session.confirms == 1 and session.explore_used == 4


def test_a_judged_look_alike_is_closed_without_a_candidate(session):
    result = spot_and_confirm(session, walking_figure="yes", plate="yes")
    assert "not a stop" in result.text and session.candidates == [] and len(session.photos) == 4


def test_something_that_could_be_a_stop_is_looked_at_from_a_second_viewpoint(session):
    session.tile_source = FakeTiles()
    result = spot_and_confirm(session, could_be_stop_from_another_angle="yes")  # a shelter from behind, say
    zoom, second = session.photos[-2:]
    assert second.toward == "look_from" and second.pano_id != zoom.pano_id and len(session.confirmer.seen) == 2
    # a second view that doesn't confirm can't reject: it may not show the object at all
    assert "stays open" in result.text and session.candidates[0].status == "spotted"


def test_a_cotral_design_beside_a_look_alike_gets_a_second_view(session):
    # f4156, 0.11.1: the real sign behind a tree, an arrow sign in the same close view
    session.tile_source = FakeTiles()
    result = spot_and_confirm(session, same_design_as_reference="yes", arrows="yes")
    assert session.photos[-1].toward == "look_from" and "stays open" in result.text


def test_the_second_view_frames_the_first_views_sight_line(session):
    """The second view covers the sight line from 0.6 to 1.6 times the estimated distance, not just the estimate."""
    session.tile_source = FakeTiles()
    spot_and_confirm(session, could_be_stop_from_another_angle="yes")
    zoom, second = session.photos[-2:]
    c = session.candidates[0]
    origin = session._camera(zoom).position
    bearing = c.views[0][1]
    target = session.world.frame.to_xy(c.lat, c.lon)
    d0 = math.dist(origin, target)
    here = session._xy(session._pano(second.pano_id))
    for k in (0.7, 1.0, 1.5):  # the sign may be anywhere along the sight line around the estimate
        q = (origin[0] + d0 * k * math.sin(math.radians(bearing)), origin[1] + d0 * k * math.cos(math.radians(bearing)))
        off = abs(angle_diff(compass(q[0] - here[0], q[1] - here[1]), second.heading - 1.0))  # FakeTiles nudges 1°
        assert off <= second.fov / 2


def test_the_second_viewpoint_can_confirm_it(session):
    session.tile_source = FakeTiles()
    session.confirmer = FakeConfirmer(could_be_stop_from_another_angle="yes", then={"shelter": "yes"})
    session.begin()
    session.sweep(from_m=40)
    result = session.zoom(session.photos[-1].index, *at(session, session.photos[-1].index, 520, 330))
    c = session.candidates[0]
    assert c.status == "confirmed" and c.evidence == "shelter_only" and c.confirm_photo == session.photos[-1].index
    assert "submit_found(1)" in result.text


def test_confirm_needs_a_zoom(session):
    session.begin()
    session.mark_candidate(1, *at(session, 1, 500, 400), "sign")
    with pytest.raises(ToolError, match="zoom on it"):
        session.confirm(1)


def test_a_manual_confirm_judges_a_close_view_not_judged_yet(session):
    answers = iter([ConfirmerError("no JSON"), Checklist({**NO, "bus_pictogram": "yes"}, note="a bus-lane sign")])

    def flaky(photo):
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    session.confirmer = flaky
    session.begin()
    assert "Not judged automatically" in session.zoom(1, *at(session, 1, 500, 400)).text
    session.mark_candidate(3, *at(session, 3, 320, 400), "sign")
    result = session.confirm(1)
    assert "REJECTED" in result.text and "bus pictogram alone" in result.text


def test_confirm_refuses_a_photo_the_confirmer_already_judged(session):
    # first20 f8520, 0.11.1: 16 rounds of mark_candidate + confirm on already judged zooms spent every confirmation
    session.begin()
    session.zoom(1, *at(session, 1, 500, 400))  # judged at once: not a stop
    session.mark_candidate(3, *at(session, 3, 320, 400), "sign")
    with pytest.raises(ToolError, match="already judged"):
        session.confirm(1)
    assert session.confirms == 1


def test_a_failed_confirmer_call_spends_nothing(session):
    def broken(photo):
        raise ConfirmerError("no JSON object in the reply")

    session.confirmer = broken
    session.begin()
    session.zoom(1, *at(session, 1, 500, 400))
    session.mark_candidate(3, *at(session, 3, 320, 400), "sign")
    result = session.confirm(1)
    assert "no usable answer" in result.text and session.candidates[0].status == "spotted" and session.confirms == 0


def test_confirmations_are_capped(session):
    session.begin()
    session.zoom(1, *at(session, 1, 500, 400))
    session.mark_candidate(3, *at(session, 3, 320, 400), "sign")
    session.confirms = MAX_CONFIRMS
    with pytest.raises(ToolError, match="confirmations are used"):
        session.confirm(1)
    assert "Not judged automatically" in session.zoom(1, *at(session, 1, 300, 400)).text


def test_a_second_view_must_come_from_another_panorama(session):
    session.begin()
    session.zoom(1, *at(session, 1, 500, 400))
    session.mark_candidate(3, *at(session, 3, 320, 400), "sign")
    with pytest.raises(ToolError, match="another panorama"):
        session.mark_candidate(1, *at(session, 1, 500, 400), "sign", same_as=1)


def test_submit_needs_a_confirmed_candidate(session):
    session.begin()
    session.mark_candidate(1, *at(session, 1, 500, 400), "sign")
    with pytest.raises(ToolError, match="not confirmed"):
        session.submit_found(1)


def test_submit_found_ends_the_search_and_photographs_the_stop(session):
    spot_and_confirm(session, fermata_or_bus_text="yes")
    result = session.submit_found(1)
    stop_photos = [p for p in session.photos if p.toward == "stop_photo"]
    assert result.done and session.outcome["status"] == "found"
    assert len(stop_photos) == STOP_PHOTOS and len({p.pano_id for p in stop_photos}) == 2
    assert session.outcome["stop_photos"] == [p.file for p in stop_photos]
    assert session.outcome["close_up"] == session.photos[3].file
    assert len(session.photos) <= MAX_IMAGES
    with pytest.raises(ToolError, match="over"):
        session.sweep(from_m=0)


def test_the_stop_photos_are_kept_back_when_the_explorer_runs_out(session):
    session.begin()
    for i in range(EXPLORE_IMAGES - 3):
        session.sweep(from_m=-150 + 22 * i)
    session.confirmer = FakeConfirmer(fermata_or_bus_text="yes")
    session.zoom(session.photos[-1].index, *at(session, session.photos[-1].index, 500, 330))
    assert session.explore_used == EXPLORE_IMAGES and "NO IMAGES LEFT" in session._state()
    with pytest.raises(ToolError, match="no tiles and no images left"):
        session.zoom(1, *at(session, 1, 300, 300))
    session.submit_found(1)
    assert len(session.photos) == MAX_IMAGES


def test_a_sign_next_to_another_stop_needs_its_plate(session):
    spot_and_confirm(session, fermata_or_bus_text="yes")
    c = session.candidates[0]
    session.world.others.append(Placed("f2 Other stop", "stop", c.lat, c.lon, c.along, c.offset, "f2"))
    with pytest.raises(ToolError, match="another stop"):
        session.submit_found(1)


def test_the_explorer_stopping_is_not_found(session):
    session.begin()
    session.finish("the explorer stopped without submitting")
    assert session.outcome["status"] == "not_found"


def test_invalid_arguments_are_explained(session):
    session.begin()
    with pytest.raises(ToolError, match="outside the search limits"):
        session.sweep(from_m=900)
    with pytest.raises(ToolError, match="no photo"):
        session.zoom(99, 10, 10)
    with pytest.raises(ToolError, match="kind"):
        session.mark_candidate(1, *at(session, 1, 10, 10), "lamp")


def test_a_sweep_from_the_return_pass_looks_at_its_own_right_hand_side(tmp_path):
    s = make_session(tmp_path, out_and_back_world())
    s.sweep(from_m=300.0)  # 300 m along = x 150 on the way back, heading west
    photo = s.photos[-1]
    assert photo.along == pytest.approx(300.0, abs=2) and photo.heading == pytest.approx(270 + 50)


def test_the_briefing_names_the_same_road_driven_twice(tmp_path):
    assert "SAME ROAD TWICE" in make_session(tmp_path, out_and_back_world()).begin().text


def test_zooms_are_paid_in_tiles_then_in_images(session):
    session.tile_source = FakeTiles()
    session.begin()
    for i in range(MAX_TILES // 3):
        session.zoom(1, *at(session, 1, 20 + 30 * i, 330))
    zooms = session.photos[2:]
    assert all(z.source == "tiles" and z.tiles == 3 and (z.width, z.height) == ZOOM_SIZE for z in zooms)
    assert zooms[0].heading == pytest.approx(session._camera(session.photos[0]).bearing_of(20) + 1.0)  # the nudge
    assert len(session.tiles_paid) == 3 * (MAX_TILES // 3) and session.explore_used == 2
    session.zoom(1, *at(session, 1, 600, 330))  # not enough tiles left: a narrow Static image instead
    assert session.photos[-1].source == "static" and session.explore_used == 3
    session.zoom(1, *at(session, 1, 20, 330))  # the same framing again: its tiles are already paid
    assert session.photos[-1].source == "tiles" and session.photos[-1].tiles == 0


def test_look_from_shows_a_candidate_from_another_panorama_before_it(session):
    session.tile_source = FakeTiles()
    session.begin()
    session.zoom(1, *at(session, 1, 500, 330))
    session.mark_candidate(3, *at(session, 3, 256, 300), "sign")
    c = session.candidates[0]
    result = session.look_from(1)
    v = session.photos[-1]
    target = FRAME.to_xy(c.lat, c.lon)
    assert v.toward == "look_from" and v.pano_id != session.photos[0].pano_id
    assert session._camera(v).position[0] < target[0] - 2  # before it in the direction of travel (east)
    assert "same_as=1" in result.text
    assert session.confirmer.seen[-1] == session._file(v)  # the new viewpoint is judged at once
    session.mark_candidate(v.index, *at(session, v.index, 256, 300), "sign", same_as=1)
    with pytest.raises(ToolError, match="already judged"):  # asking again would get the same answer
        session.confirm(1)


def test_look_from_a_position_already_used_is_refused(session):
    session.tile_source = FakeTiles()
    session.begin()
    session.zoom(1, *at(session, 1, 500, 330))
    session.mark_candidate(3, *at(session, 3, 256, 300), "sign")
    with pytest.raises(ToolError, match="already seen"):
        session.look_from(1, from_m=session.photos[0].along)


def test_a_sweep_glimpses_the_sidewalk_where_a_sign_would_be_a_few_pixels(session):
    session.begin()
    session.sweep(from_m=-100)
    states = {round(a): s for a, s in zip(session.cells, session.state, strict=True)}
    assert states[-94] == "seen_close" and states[-78] == "glimpsed" and states[-50] == "not_looked"


def test_the_state_suggests_no_sweeps(session):
    # the model chooses where to look: a ready-made list was followed blindly (NVFP4, f8520, 0.11.1: 14 sweeps
    # marked clear, no zoom, past the real sign)
    assert "BEST NEXT" not in session.begin().text and "sweep(" not in session._state()


def test_the_search_ends_when_nothing_is_left_to_look_with(session):
    session.begin()
    assert session.exhausted() is None
    session.confirms = MAX_CONFIRMS
    assert "confirmations" in session.exhausted()
    session.confirms = 0
    while session.explore_used < EXPLORE_IMAGES:
        session.sweep(from_m=-150 + 10 * session.explore_used)
    assert "no images or tiles" in session.exhausted()  # no tile source here, so no close view either


def test_a_confirmed_candidate_keeps_the_search_open(session):
    spot_and_confirm(session, cotral_logo="yes")
    session.confirms = MAX_CONFIRMS
    assert session.exhausted() is None  # it can still be submitted


def test_an_osm_start_beside_an_unscanned_access_road_moves_to_the_scanned_road(tmp_path):
    world = straight_world()
    world.panoramas = [p for p in world.panoramas if p.along >= 30]  # no Street View before +15 m
    lat, lon = FRAME.to_latlon(300.0, -12.0)
    world.starts.insert(0, Placed("OSM shelter", "osm_nearest", lat, lon, 0.0, 12.0))
    shift = _visible_start_shift(world)
    assert not world.scanned(0.0) and world.scanned(shift) and 14 <= shift <= 20  # within 25 m of the object


def test_a_scanned_start_stays(tmp_path):
    world = straight_world()
    lat, lon = FRAME.to_latlon(300.0, -8.0)
    world.starts.insert(0, Placed("OSM bus stop", "osm_ref", lat, lon, 0.0, 8.0))
    assert _visible_start_shift(world) == 0.0


def corner_world() -> World:
    """East from x = 0 to 300, then a right turn: south to y = -300. The start at x = 200, 100 m before the corner."""
    path = PathFrame([(0.0, 0.0), (300.0, 0.0), (300.0, -300.0)], start_s=200.0)
    panos = [Panorama(f"e{x}", *FRAME.to_latlon(float(x), 0.0), "2025-06", x - 200.0, 0.0, "© Google")
             for x in range(0, 301, 10)]
    panos += [Panorama(f"s{y}", *FRAME.to_latlon(300.0, -float(y)), "2025-06", 100.0 + y, 0.0, "© Google")
              for y in range(10, 301, 10)]
    lat, lon = FRAME.to_latlon(200.0, 0.0)
    return World(stop=Stop("f1", "Test", lat, lon), frame=FRAME, path=path, limits=(-150.0, 300.0),
                 starts=[Placed("GTFS", "gtfs", lat, lon, 0.0, 0.0)], hints=[], others=[], panoramas=panos)


def test_the_corners_of_the_path_are_found(tmp_path):
    s = make_session(tmp_path, corner_world())
    assert len(s.bends) == 1
    along, turn = s.bends[0]
    assert along == pytest.approx(100, abs=3) and turn == pytest.approx(90, abs=5)


def test_nothing_round_a_corner_is_seen(tmp_path):
    s = make_session(tmp_path, corner_world())
    s.begin()
    s.sweep(from_m=55)  # 45 m before the corner, looking ahead: too far for the harness to complete the corner
    states = {round(a): st for a, st in zip(s.cells, s.state, strict=True)}
    assert states[60] == "seen_close" and states[120] == "not_looked"  # round the corner: not even glimpsed


def test_a_sweep_facing_a_corner_makes_the_harness_look_round_it(tmp_path):
    s = make_session(tmp_path, corner_world())
    s.begin()
    assert "CORNERS NOT YET EXAMINED" in s._state() and "+100 m (right turn 90°" in s._state()
    result = s.sweep(from_m=80)  # 20 m before the corner, looking ahead
    after, before = s.photos[-2:]
    assert len(result.images) == 3 and "CORNER +100 m" in result.text
    assert after.toward == "sweep_behind" and after.along == pytest.approx(106, abs=6)  # past it, looking back
    assert before.toward == "sweep_ahead" and before.along == pytest.approx(94, abs=6)
    states = {round(a): st for a, st in zip(s.cells, s.state, strict=True)}
    assert states[104] in ("seen_close", "glimpsed")  # just round the corner
    assert "CORNERS NOT YET EXAMINED" not in s._state()


# ---- the confirmer's checklist

def test_verdict_needs_a_stop_feature_and_no_lookalike():
    assert verdict({**NO, "shelter": "yes"}).evidence == "shelter_only"
    assert not verdict({**NO, "shelter": "yes", "letter_p": "yes"}).confirmed
    assert not verdict({**NO, "fermata_or_bus_text": "unsure"}).confirmed


def test_a_plate_alone_is_not_a_stop():
    # NVFP4, f8520, 0.11.1: a private-road sign with a "96" house-number plate at a dirt track was confirmed
    house_number = {**NO, "plate": "yes", "fermata_or_bus_text": "unsure", "cotral_logo": "unsure"}
    assert not verdict(house_number).confirmed and "plate alone" in verdict(house_number).reason
    assert verdict({**house_number, "fermata_or_bus_text": "yes"}).evidence == "other_stop_sign"


def test_the_cotral_logo_wins_over_a_road_sign_in_the_same_view():
    # NVFP4, f4156, 0.11.1: "A Cotral bus stop sign ... next to a bench", a parking P in the frame: rejected
    seen = {**NO, "fermata_or_bus_text": "yes", "cotral_logo": "yes", "same_design_as_reference": "yes", "letter_p": "yes"}
    assert verdict(seen).confirmed and verdict(seen).evidence == "cotral_sign"
    assert not verdict({**NO, "fermata_or_bus_text": "yes", "letter_p": "yes"}).confirmed  # FERMATA alone: no


def test_prohibition_discs_private_plates_and_narrow_tracks_are_look_alikes():
    for feature in ("prohibition_disc", "private_plate", "narrow_track"):
        assert not verdict({**NO, "fermata_or_bus_text": "yes", feature: "yes"}).confirmed


def test_a_sign_too_small_to_read_is_confirmed_by_its_design():
    far = {**NO, "same_design_as_reference": "yes", "fermata_or_bus_text": "unsure", "cotral_logo": "unsure"}
    assert verdict(far).confirmed and verdict(far).evidence == "cotral_sign_by_design"
    assert not verdict({**far, "letter_p": "yes"}).confirmed  # a look-alike still wins
    readable_other = {**far, "text_readable": "yes", "fermata_or_bus_text": "no", "cotral_logo": "no"}
    assert not verdict(readable_other).confirmed  # read, and not a Cotral sign
    # f4156, 0.11.1: "too far/obscured to read", yet text and logo answered "no": unreadable, so the design decides
    assert verdict({**far, "fermata_or_bus_text": "no", "cotral_logo": "no"}).confirmed


def test_parse_reads_the_last_json_object_and_checks_every_answer():
    body = ", ".join(f'"{k}": "{v}"' for k, v in NO.items())
    good = parse('thinking... {"x": 1} then {' + body + ', "plate_text": "F7824", "note": "a stop sign"}')
    assert good.plate_text == "F7824" and good.answers["plate"] == "no"
    with pytest.raises(ConfirmerError, match="cotral_logo"):
        parse('{"fermata_or_bus_text": "yes"}')


def test_row_of_places_heights_consistently_with_the_ground_range():
    camera = Camera((0.0, 0.0), 90.0, 110.0)
    assert camera.row_of((20.0, 0.0), 2.5) == pytest.approx(camera.height / 2)  # camera height: the horizon
    y = camera.row_of((12.0, 0.0), 0.0)  # the ground 12 m away
    assert camera.ground_range(y) == pytest.approx(12.0, rel=1e-6)
    assert camera.row_of((12.0, 0.0), 2.2) < y  # a sign panel above it is higher in the image


def test_captions_say_what_stretch_is_in_view_but_give_no_points(session):
    # f4156, 0.13.0: given ready-made points, the explorer zoomed on all 16 of them (cars, motorcycles, faces) and
    # never on the sign standing in plain view
    result = session.begin()
    caption = result.text.split("PHOTO 1")[1].split("PHOTO 2")[0]
    assert not re.search(r"\(\d+, \d+\)", caption)
    near, far = (float(v) for v in re.search(r"from ([+-]\d+) m \(\d+ m away\) to ([+-]\d+) m", caption).groups())
    assert near == pytest.approx(session.photos[0].along, abs=3) and far > 30  # from beside the camera, far ahead
    assert "clear from" in caption and "small from" in caption and "a speck from" in caption
