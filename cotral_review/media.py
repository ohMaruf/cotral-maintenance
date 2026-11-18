"""Photos of a run: media files named by their sha256, served only when they belong to the stop asked for."""

import re
from pathlib import Path

from cotral_maintenance.runstore import RunStore

PHOTO_FILE = re.compile(r"([0-9a-f]{64})\.jpg")
COPYRIGHT = "© Google"  # every photo of a run is Street View


def photo_file(run: RunStore, allowed: set[str], file: str) -> Path | None:
    """The media file for `<sha256>.jpg`, or None unless the sha is in `allowed` and the file exists.

    The name is a hex digest checked against the stop's own photos, so it cannot name another path.
    """
    match = PHOTO_FILE.fullmatch(file)
    if match is None or match[1] not in allowed:
        return None
    path = run.media(match[1])
    return path if path.is_file() else None
