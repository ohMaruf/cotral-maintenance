import csv

import pytest
from PIL import Image

from cotral_maintenance import cli
from cotral_maintenance.fileutils import RawStore, write_dataset
from cotral_maintenance.models import PanoMetadata, Shot, Stop, View
from cotral_maintenance.scoring import (
    QUESTIONS,
    StopScores,
    build_dataset,
    build_request,
    score_stop,
    score_stops,
)
from cotral_maintenance.storage import ImageStore

STOP = Stop(stop_id="f4156", name="FORMIA | Piazza Mattei", lat=41.25, lon=13.6)
VIEWS = [View("sweep_2"), View("sweep_4")]
SCORES = ["shelter", "seating", "signage", "lighting", "waiting_area", "accessibility", "requires_maintenance"]


class FakeScorer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[dict, list]] = []

    def score(self, request: dict, images: list) -> dict:
        self.calls.append((request, images))
        if self.error:
            raise self.error
        answers = {name: {"score": 1.23456, "probabilities": {}} for name in SCORES}
        return {"answers": {**answers, "classifiable": {"noul": 0.8}}, "usage": {"input_tokens": 3190}}


@pytest.fixture
def images(tmp_path):
    store = ImageStore(tmp_path / "images")
    add_images(store, STOP)
    return store


@pytest.fixture
def raw(tmp_path):
    return RawStore(tmp_path / "scores_raw")


def add_images(store: ImageStore, stop: Stop) -> None:
    shot = Shot(PanoMetadata("p", 41.25, 13.6, date="2025-06"), 5.0, 90.0)
    for view in VIEWS:
        store.save(stop, view, b"", shot)
        Image.new("RGB", (4, 4)).save(store.image_path(stop.stop_id, view), "JPEG")
    store.write_manifest(stop, VIEWS)


def test_all_photos_and_questions_go_in_one_call(images, raw):
    scorer = FakeScorer()

    score_stop(STOP, scorer, images, raw)

    request, photos = scorer.calls[0]
    assert len(scorer.calls) == 1
    assert len(photos) == 2
    assert request["questions"] == QUESTIONS
    assert len(request["state"]["photos"]) == 2


def test_request_describes_each_photo_by_its_view():
    state = build_request(STOP, ["sweep_2", "sweep_4"])["state"]

    assert state["stop_name"] == STOP.name
    assert "8 m before" in state["photos"][0]
    assert "24 m after" in state["photos"][1]


def test_raw_record_keeps_the_request_and_model_for_reproducibility(images, raw):
    score_stop(STOP, FakeScorer(), images, raw)

    record = next(raw.records())

    assert record["request"]["questions"] == QUESTIONS
    assert record["model"]["revision"]
    assert record["images"] == [f"{view.key}.jpg" for view in VIEWS]


def test_dataset_has_a_row_with_every_score(images, raw, tmp_path):
    score_stop(STOP, FakeScorer(), images, raw)
    out = tmp_path / "stop_scores.csv"

    write_dataset(build_dataset(raw), StopScores, out)

    with out.open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert (row["stop_id"], row["imagery_date"], row["image_count"]) == ("f4156", "2025-06", "2")
    assert {row[name] for name in SCORES} == {"1.235"}
    assert row["classifiable"] == "0.8"
    assert float(row["latency_s"]) >= 0


@pytest.mark.parametrize("error", [ValueError("context too long"), OSError("bad image")])
def test_a_stop_that_cannot_be_scored_does_not_end_the_run(images, raw, error):
    other = Stop("f4160", "FORMIA", 41.25, 13.6)
    add_images(images, other)

    class FailsOnce(FakeScorer):
        def score(self, request, photos):
            self.error = error if not self.calls else None
            return super().score(request, photos)

    assert score_stops([STOP, other], FailsOnce(), images, raw) == 1
    assert not raw.has(STOP.stop_id)
    assert raw.has(other.stop_id)


def test_force_applies_only_to_the_phase_it_names():
    args = cli.build_parser().parse_args(["--limit", "1", "--force", "3"])

    assert args.force == [3]


def test_start_phase_after_stop_phase_is_refused():
    with pytest.raises(SystemExit):
        cli.main(["--limit", "1", "--start-phase", "3", "--stop-after-phase", "2"])
