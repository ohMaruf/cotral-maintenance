"""Crash-safe file writes: an interrupted run never leaves a partial file behind."""

import csv
import io
import json
from collections.abc import Iterator, Sequence
from dataclasses import asdict, fields
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file + rename; the rename is atomic on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json_atomic(path: Path, obj: object) -> None:
    write_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"))


def write_dataset(rows: Sequence, row_type: type, path: Path) -> None:
    """Write dataclass rows as a CSV, with its fields as columns."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[f.name for f in fields(row_type)])
    writer.writeheader()
    writer.writerows(asdict(row) for row in rows)
    write_atomic(path, buffer.getvalue().encode("utf-8"))


class RawStore:
    """Raw per-stop records, one JSON file per stop: <root>/<stop_id>.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, stop_id: str) -> Path:
        return self.root / f"{stop_id}.json"

    def has(self, stop_id: str) -> bool:
        return self.path(stop_id).is_file()

    def save(self, stop_id: str, record: dict) -> None:
        write_json_atomic(self.path(stop_id), record)

    def records(self) -> Iterator[dict]:
        """All stored records, ordered by stop id."""
        for path in sorted(self.root.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))
