import csv
import io
import json
import os
import threading
from collections.abc import Iterator, Sequence
from dataclasses import asdict, fields
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json_atomic(path: Path, obj: object) -> None:
    write_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"))


def write_dataset(rows: Sequence, row_type: type, path: Path) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[f.name for f in fields(row_type)])
    writer.writeheader()
    writer.writerows(asdict(row) for row in rows)
    write_atomic(path, buffer.getvalue().encode("utf-8"))


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, stop_id: str) -> Path:
        return self.root / f"{stop_id}.json"

    def has(self, stop_id: str) -> bool:
        return self.path(stop_id).is_file()

    def save(self, stop_id: str, record: dict) -> None:
        write_json_atomic(self.path(stop_id), record)

    def records(self) -> Iterator[dict]:
        for path in sorted(self.root.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))
