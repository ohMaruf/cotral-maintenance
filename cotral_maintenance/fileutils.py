"""Crash-safe file writes: an interrupted run never leaves a partial file behind."""

import json
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file + rename; the rename is atomic on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json_atomic(path: Path, obj: object) -> None:
    write_atomic(path, json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"))
