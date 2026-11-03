"""On-disk image store, which doubles as the download cache.

Layout: <root>/<stop_id>/<view.key>.jpg, with a <view.key>.json sidecar
recording the panorama, distance and heading the image was taken from, and a
<root>/<stop_id>/stop.json manifest summarising the stop's images and their date.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .fileutils import write_atomic, write_json_atomic
from .models import Shot, Stop, View
from .provenance import utc_now

logger = logging.getLogger(__name__)

MANIFEST_NAME = "stop.json"


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

    def manifest_path(self, stop_id: str) -> Path:
        return self.root / stop_id / MANIFEST_NAME

    def read_manifest(self, stop_id: str) -> dict | None:
        path = self.manifest_path(stop_id)
        return json.loads(path.read_text()) if path.is_file() else None

    def write_manifest(self, stop: Stop, views: Sequence[View]) -> Path | None:
        """Summarise a stop's downloaded images, in shot plan order, from their sidecars.

        `imagery_date` is the oldest panorama date among the images, so filtering
        stops by it never keeps a stop with any image older than the cutoff.
        """
        images = []
        for view in views:
            path = self.image_path(stop.stop_id, view)
            if path.is_file():
                sidecar = json.loads(path.with_suffix(".json").read_text())
                images.append({"view": view.name, "file": path.name, "shot": sidecar["shot"]})
        if not images:
            # A manifest listing images that are gone would mislead every later reader.
            self.manifest_path(stop.stop_id).unlink(missing_ok=True)
            return None
        dates = [i["shot"]["pano"]["date"] for i in images if i["shot"]["pano"]["date"]]
        manifest = {
            "stop": asdict(stop),
            "imagery_date": min(dates) if dates else None,
            "images": images,
        }
        path = self.manifest_path(stop.stop_id)
        write_json_atomic(path, manifest)
        return path

