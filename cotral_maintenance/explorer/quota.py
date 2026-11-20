import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FREE_PER_MONTH = {"static": 1_000, "tiles": 10_000}


@dataclass(frozen=True)
class Remaining:
    month: str
    static: int
    tiles: int

    def covers(self, static: int, tiles: int) -> bool:
        return self.static >= static and self.tiles >= tiles


class MonthlyLedger:
    def __init__(self, path: Path, free: dict[str, int] | None = None, margin: float = 0.05) -> None:
        self.path = path
        self.free = free or FREE_PER_MONTH
        self.margin = margin
        self.data: dict[str, dict] = json.loads(path.read_text()) if path.is_file() else {}

    @staticmethod
    def month(now: datetime | None = None) -> str:
        return (now or datetime.now(UTC)).strftime("%Y-%m")

    def used(self, month: str | None = None) -> dict[str, int]:
        entry = self.data.get(month or self.month(), {})
        return {k: int(entry.get(k, 0)) for k in self.free}

    def remaining(self, now: datetime | None = None) -> Remaining:
        month = self.month(now)
        used = self.used(month)
        left = {k: int(v * (1 - self.margin)) - used[k] for k, v in self.free.items()}
        return Remaining(month, max(left["static"], 0), max(left["tiles"], 0))

    def add(self, run: str, static: int, tiles: int, now: datetime | None = None) -> None:
        month = self.month(now)
        entry = self.data.setdefault(month, {"static": 0, "tiles": 0, "runs": []})
        entry["static"] += static
        entry["tiles"] += tiles
        entry["runs"].append({"run": run, "static": static, "tiles": tiles})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))
