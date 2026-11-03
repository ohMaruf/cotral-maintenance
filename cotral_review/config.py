"""Settings of the review server: where data lives and where to listen."""

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_SCORES = {
    "clef": Path("data/stop_scores.csv"),
    "gemma": Path("experiments/gemma/stop_scores.csv"),
}


@dataclass(frozen=True)
class Settings:
    images_dir: Path = Path("images")
    # model key -> scores CSV (the phase 3 layout); missing files are skipped
    score_sources: dict[str, Path] = field(default_factory=lambda: dict(DEFAULT_SCORES))
    gemma_raw_dir: Path = Path("experiments/gemma/scores_raw")
    database: Path = Path("data/review.sqlite3")
    frontend_dist: Path = Path("review-ui/dist")
    host: str = "127.0.0.1"
    port: int = 8765
    seed: int | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        """Defaults, overridden by COTRAL_REVIEW_* environment variables."""
        base = cls()
        env = os.environ.get
        return replace(
            base,
            images_dir=Path(env("COTRAL_REVIEW_IMAGES", base.images_dir)),
            gemma_raw_dir=Path(env("COTRAL_REVIEW_GEMMA_RAW", base.gemma_raw_dir)),
            database=Path(env("COTRAL_REVIEW_DB", base.database)),
            frontend_dist=Path(env("COTRAL_REVIEW_DIST", base.frontend_dist)),
            host=env("COTRAL_REVIEW_HOST", base.host),
            port=int(env("COTRAL_REVIEW_PORT", base.port)),
        )
