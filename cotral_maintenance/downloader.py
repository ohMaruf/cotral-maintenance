"""Download orchestration: cache lookup, panorama search, image fetch, save."""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import TransportError
from .models import Stop, View
from .panoramas import plan_shots
from .storage import ImageStore
from .streetview import ImageSource

logger = logging.getLogger(__name__)


class Outcome(Enum):
    DOWNLOADED = "downloaded"
    CACHED = "cached"
    NO_IMAGERY = "no_imagery"
    FAILED = "failed"


@dataclass(frozen=True)
class DownloadResult:
    stop_id: str
    view: View
    outcome: Outcome
    path: Path | None = None


def download_stop(
    stop: Stop,
    views: Sequence[View],
    client: ImageSource,
    store: ImageStore,
    force: bool = False,
    pair: Stop | None = None,
) -> list[DownloadResult]:
    """Fetch every view of one stop, skipping views already on disk unless `force`.
    `pair` is the opposite-direction stop, if any (stops.find_pairs).

    Raises ApiError (fatal) and TransportError.
    """
    pending = [view for view in views if force or not store.has(stop.stop_id, view)]
    results = [
        DownloadResult(stop.stop_id, view, Outcome.CACHED, store.image_path(stop.stop_id, view))
        for view in views
        if view not in pending
    ]
    for result in results:
        logger.debug("Cached: stop %s view %s", stop.stop_id, result.view.key)
    if not pending:
        # Rebuilt from the sidecars, in case a run was interrupted before writing it.
        store.write_manifest(stop, views)
        return results

    plan = plan_shots(client, stop, pair)
    if not plan:
        logger.info("No imagery near stop %s (%s)", stop.stop_id, stop.name)
    for view in pending:
        shot = plan.get(view.name)
        if shot is None:
            results.append(DownloadResult(stop.stop_id, view, Outcome.NO_IMAGERY))
            continue
        image = client.get_image(shot.pano.pano_id, shot.heading, view)
        path = store.save(stop, view, image, shot)
        logger.info(
            "Downloaded stop %s (%s) %s from %.0f m, heading %.0f° -> %s",
            stop.stop_id, stop.name, view.name, shot.distance_m, shot.heading, path,
        )
        results.append(DownloadResult(stop.stop_id, view, Outcome.DOWNLOADED, path))
    if plan:
        store.write_manifest(stop, views)
    return results


def download_stops(
    stops: Iterable[Stop],
    views: Sequence[View],
    client: ImageSource,
    store: ImageStore,
    force: bool = False,
    pairs: Mapping[str, Stop] | None = None,
) -> list[DownloadResult]:
    """Process every stop in order. `pairs` maps stop ids to their opposite-direction stop.

    Network failures are logged and the stop is skipped; ApiError propagates,
    since it would affect every following request too.
    """
    results: list[DownloadResult] = []
    for stop in stops:
        try:
            stop_results = download_stop(stop, views, client, store, force, (pairs or {}).get(stop.stop_id))
        except TransportError as exc:
            logger.error("Failed stop %s (%s): %s", stop.stop_id, stop.name, exc)
            stop_results = [DownloadResult(stop.stop_id, v, Outcome.FAILED) for v in views]
        results.extend(stop_results)
    return results
