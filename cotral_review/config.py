"""Settings of the review server: which run to show, where its own data lives, where to listen."""

import os
from dataclasses import dataclass, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(path: Path | str) -> Path:
    """A relative path is relative to the repository root, not to where the server was started."""
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    run: Path | None = None  # runs/<RUN>; required to serve
    database: Path = Path("data/review.sqlite3")
    truth_csv: Path = Path("data/ground_truth_manual.csv")
    osm_store: Path = Path("data/osm/osm.sqlite3")
    shape_check_json: Path = Path("data/shape_check/stops.json")
    shape_verdicts_db: Path = Path("data/shape_verdicts.sqlite3")
    frontend_dist: Path = Path("review-ui/dist")
    host: str = "127.0.0.1"
    port: int = 8765
    seed: int | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        """Defaults, overridden by COTRAL_REVIEW_* environment variables."""
        base = cls()
        env = os.environ.get
        run = env("COTRAL_REVIEW_RUN")
        return replace(
            base,
            run=Path(run) if run else None,
            database=Path(env("COTRAL_REVIEW_DB", base.database)),
            truth_csv=Path(env("COTRAL_REVIEW_TRUTH_CSV", base.truth_csv)),
            osm_store=Path(env("COTRAL_REVIEW_OSM_STORE", base.osm_store)),
            shape_check_json=Path(env("COTRAL_REVIEW_SHAPE_CHECK", base.shape_check_json)),
            shape_verdicts_db=Path(env("COTRAL_REVIEW_SHAPE_DB", base.shape_verdicts_db)),
            frontend_dist=Path(env("COTRAL_REVIEW_DIST", base.frontend_dist)),
            host=env("COTRAL_REVIEW_HOST", base.host),
            port=int(env("COTRAL_REVIEW_PORT", base.port)),
        )
