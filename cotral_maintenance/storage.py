"""On-disk image store, which doubles as the download cache.

Layout: <root>/<stop_id>/<view.key>.jpg, with a <view.key>.json sidecar
recording the panorama, distance and heading the image was taken from.
"""

import logging
from dataclasses import asdict
from pathlib import Path

from .fileutils import write_atomic, write_json_atomic
from .models import Shot, Stop, View
from .provenance import utc_now

logger = logging.getLogger(__name__)


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def image_path(self, stop_id: str, view: View) -> Path:
        return self.root / stop_id / f"{view.key}.jpg"

    def has(self, stop_id: str, view: View) -> bool:
        return self.image_path(stop_id, view).is_file()

    def save(self, stop: Stop, view: View, image: bytes, shot: Shot) -> Path:
        path = self.image_path(stop.stop_id, view)
        sidecar = {
            "stop": asdict(stop),
            "view": asdict(view),
            "shot": asdict(shot),
            "downloaded_at": utc_now(),
        }
        write_json_atomic(path.with_suffix(".json"), sidecar)
        # Image written last: its presence marks the cache entry as complete.
        write_atomic(path, image)
        logger.debug("Saved %s (%d bytes)", path, len(image))
        return path

