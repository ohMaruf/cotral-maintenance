"""Runtime settings, loaded from the environment / .env file."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

API_KEY_VAR = "MAPS_API_KEY"
REFERRER_VAR = "MAPS_API_REFERRER"


@dataclass(frozen=True)
class Settings:
    api_key: str
    referrer: str | None = None
    stops_file: Path = Path("GTFS_COTRAL/stops.txt")
    images_dir: Path = Path("images")
    tiles_dir: Path = Path("data/tiles")
    places_raw_dir: Path = Path("data/places_raw")
    corrected_stops_file: Path = Path("data/stops_corrected.csv")
    scores_raw_dir: Path = Path("data/scores_raw")
    stop_scores_file: Path = Path("data/stop_scores.csv")
    runs_log: Path = Path("data/runs.jsonl")
    log_file: Path = Path("logs/pipeline.log")
    request_timeout_s: float = 20.0

    @classmethod
    def from_env(cls, env_file: Path = Path(".env")) -> "Settings":
        load_dotenv(env_file)
        api_key = os.getenv(API_KEY_VAR)
        if not api_key:
            raise ConfigError(f"{API_KEY_VAR} is not set (expected in {env_file})")
        return cls(api_key=api_key, referrer=os.getenv(REFERRER_VAR) or None)
