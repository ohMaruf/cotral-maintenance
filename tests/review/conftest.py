import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cotral_review.api import create_app
from cotral_review.config import Settings

from .explore_fixtures import IDS, JPEG, build_run  # noqa: F401  (re-exported for the tests)


@pytest.fixture(scope="session")
def template_run(tmp_path_factory) -> Path:
    return build_run(tmp_path_factory.mktemp("template") / "r1")


@pytest.fixture
def run_dir(tmp_path: Path, template_run: Path) -> Path:
    """A private copy of the run: tests may write to it."""
    return Path(shutil.copytree(template_run, tmp_path / "runs" / "r1"))


@pytest.fixture
def settings(tmp_path: Path, run_dir: Path) -> Settings:
    return Settings(
        run=run_dir, database=tmp_path / "review.sqlite3", truth_csv=tmp_path / "truth.csv",
        osm_store=tmp_path / "osm.sqlite3", shape_check_json=tmp_path / "shape_check" / "stops.json",
        shape_verdicts_db=tmp_path / "verdicts.sqlite3", frontend_dist=tmp_path / "dist", seed=1,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
