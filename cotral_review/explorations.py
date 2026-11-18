"""Explorations of the run: one per stop, read from the run store on every request (never cached)."""

import json
import logging
from pathlib import Path
from typing import Any

from cotral_maintenance.geo import distance_m
from cotral_maintenance.runstore import RunStore

from .explore_schemas import (
    AlongLimits, Exploration, ExplorationCandidate, ExplorationEvent, ExplorationPhoto, ExplorationSummary,
    Harness, HarnessVersion, Position, PositionKind, RawExchange, UNVERSIONED,
)
from .media import COPYRIGHT, photo_file
from .osm_lookup import OsmLookup
from .positions import Coords, PositionIndex

logger = logging.getLogger(__name__)

Record = dict[str, Any]
LABELS: dict[PositionKind, str] = {
    "gtfs": "GTFS", "places": "Places", "verified": "Verified", "estimate": "Submitted position",
}

# One parse of the (large) record per stop: its budget, photo cap and first start, and the tool calls it holds.
SUMMARY_SQL = """
    SELECT e.stop_id, s.name, s.gtfs_lat, s.gtfs_lon, e.status, e.reason, e.lat, e.lon, e.scan_date, e.explorer,
           e.harness, e.billed_static, e.billed_tiles, e.turns, e.seconds, e.started_at, e.finished_at,
           json_extract(e.record, '$.budget', '$.max_photos', '$.starts[0].kind') AS extras,
           COALESCE(json_array_length(e.record, '$.events'), 0) AS events,
           (SELECT COUNT(*) FROM photos p WHERE p.stop_id = e.stop_id) AS photos, st.source AS start_source
    FROM explorations e JOIN stops s USING (stop_id) LEFT JOIN starts st USING (stop_id)
    {where} ORDER BY s.position"""


class UnknownRun(Exception):
    """No exploration for the stop id."""


class UnknownLayout(Exception):
    """The exploration's record does not match its layout."""


def version_order(version: str) -> tuple[int, tuple[int, ...], str]:
    """Sort key, ascending = oldest first: numeric by dotted part, "unversioned" and unparseable lowest."""
    try:
        return 1, tuple(int(part) for part in version.split(".")), version
    except ValueError:
        return 0, (), version


def photo_url(stop_id: str, file: str) -> str:
    return f"/api/explorations/{stop_id}/photos/{file}"


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _harness(harness: Record, explorer: Record) -> Harness:
    git = harness.get("git") or {}
    confirmer = explorer.get("confirmer")
    return Harness(
        version=harness.get("version") or UNVERSIONED, git_commit=git.get("commit"), git_dirty=git.get("dirty"),
        prompt_sha256=harness.get("prompt_sha256"), explorer_model=explorer.get("model"),
        confirmer_model=confirmer if isinstance(confirmer, str) else None)


def _positions(gtfs: Coords, places: Coords | None, verified: Coords | None, found: Coords | None) -> list[Position]:
    wanted: list[tuple[PositionKind, Coords | None]] = [
        ("gtfs", gtfs), ("places", places), ("verified", verified), ("estimate", found)]
    return [
        Position(kind=kind, lat=c[0], lon=c[1], label=LABELS[kind],
                 error_m=None if verified is None or kind == "verified" else distance_m(*c, *verified))
        for kind, c in wanted if c is not None
    ]


def _photo(stop_id: str, p: Record, opening: list[str]) -> ExplorationPhoto:
    return ExplorationPhoto(
        index=p["index"], url=photo_url(stop_id, f"{p['file']}.jpg"), pano_id=p["pano_id"],
        lat=p["lat"], lon=p["lon"], date=p.get("date"), heading=p["heading"], fov=p["fov"], pitch=p["pitch"],
        along_m=p["along"], right_m=p["offset"], toward=p["toward"], opening=p["file"] in opening,
        copyright=COPYRIGHT, billed=p.get("billed"), width=p.get("width"), height=p.get("height"),
        shot=p.get("shot") or 0, parent=p.get("parent"), source=p.get("source") or "static",
        tiles=p.get("tiles") or 0,
    )


def _candidate(c: Record) -> ExplorationCandidate:
    return ExplorationCandidate(
        index=c["index"], kind=c["kind"], lat=c["lat"], lon=c["lon"], along_m=c["along"], right_m=c["offset"],
        status=c["status"], evidence=c.get("evidence") or None, basis=c.get("basis", ""),
        checklist=dict(c.get("checklist") or {}), confirmer_note=c.get("confirmer_note") or "",
        confirm_photo=c.get("confirm_photo"),
    )


def _events(recorded: list[Record], lines: list[Record], by_file: dict[str, int]) -> list[ExplorationEvent]:
    """The record's tool calls in order, each model turn's reasoning and text placed before its calls."""
    events: list[ExplorationEvent] = []
    used = budget_used = 0

    def add(kind: str, summary: str, error: str | None, files: list[str], photos_used: int | None,
            request: Any, response: Any, spent: int | None = None) -> None:
        nonlocal used, budget_used
        used = max(used, photos_used or 0)
        budget_used = max(budget_used, spent or 0)
        events.append(ExplorationEvent(
            seq=len(events) + 1, kind=kind, summary=summary, error=error,
            photos=[by_file[f] for f in files if f in by_file], photos_used=used, budget_used=budget_used,
            raw=RawExchange(request=request, response=response)))

    def add_recorded(e: Record) -> None:
        error, result = e.get("error"), e.get("result")
        add(e["tool"], f"ERROR: {error}" if error else first_line(result or ""), error, e.get("photos") or [],
            e.get("photos_used"), e.get("args"), error if error else result, e.get("budget_used"))

    pending = iter(recorded)
    upcoming = next(pending, None)
    for line in lines:
        if "tool" in line:
            if upcoming is not None and upcoming["tool"] == line["tool"]:
                add_recorded(upcoming)
                upcoming = next(pending, None)
            continue
        for key in ("reasoning", "content"):
            text = line.get(key)
            if isinstance(text, str) and text.strip():
                add("thought", text.strip(), None, [], None, None, text.strip())
    while upcoming is not None:  # not matched to a transcript line (or no transcript)
        add_recorded(upcoming)
        upcoming = next(pending, None)
    return events


def _transcript(text: str | None) -> list[Record]:
    lines = []
    for raw in (text or "").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines


def _report(lines: list[Record]) -> str | None:
    """The text of the last model turn, when it made no tool call: the explorer's closing words."""
    turns = [line for line in lines if "tool" not in line and "turn" in line and "finish" in line]
    last = turns[-1] if turns else {}
    content = last.get("content")
    return content.strip() if isinstance(content, str) and content.strip() and not last.get("tool_calls") else None


class ExplorationRepository:
    def __init__(self, run: RunStore, positions: PositionIndex, osm: OsmLookup) -> None:
        self.run = run
        self.positions = positions
        self.osm = osm

    def list(self, harness: str | None = None) -> list[ExplorationSummary]:
        """Summaries in the run's stop order (only those of the harness version, if given)."""
        summaries = [self._summary(r) for r in self.run.query(SUMMARY_SQL.format(where=""))]
        return [s for s in summaries if harness is None or s.harness.version == harness]

    def harness_versions(self) -> list[HarnessVersion]:
        """The harness versions present with their counts, newest first, "unversioned" last."""
        counts: dict[str, int] = {}
        for summary in self.list():
            counts[summary.harness.version] = counts.get(summary.harness.version, 0) + 1
        return [HarnessVersion(version=v, runs=counts[v]) for v in sorted(counts, key=version_order, reverse=True)]

    def get(self, stop_id: str) -> Exploration:
        """Raises UnknownRun, or UnknownLayout when the record does not match its layout."""
        rows = self.run.query(SUMMARY_SQL.format(where="WHERE e.stop_id = ?"), (stop_id,))
        row = self.run.exploration(stop_id)
        if not rows or row is None:
            raise UnknownRun(stop_id)
        try:
            return self._detail(self._summary(rows[0]), row)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise UnknownLayout(f"the record of {stop_id} does not match its layout: {error!r}") from error

    def photo_path(self, stop_id: str, file: str) -> Path | None:
        """The media file of a photo of that stop, or None unless the stop has the photo and the file exists."""
        row = self.run.exploration(stop_id)
        if row is None:
            raise UnknownRun(stop_id)
        taken = {r["media"] for r in self.run.query("SELECT media FROM photos WHERE stop_id = ?", (stop_id,))}
        return photo_file(self.run, taken | set(row["stop_photos"]), file)

    def _summary(self, r) -> ExplorationSummary:
        budget, max_photos, start_kind = json.loads(r["extras"])
        budget = budget if isinstance(budget, dict) else {}
        used = budget.get("used") or {}
        billed = used.get("billed")
        gtfs: Coords = (r["gtfs_lat"], r["gtfs_lon"])
        found: Coords | None = (r["lat"], r["lon"]) if r["lat"] is not None else None
        verified = self.positions.verified.get(r["stop_id"])
        return ExplorationSummary(
            run_id=r["stop_id"], stop_id=r["stop_id"], name=r["name"], outcome=r["status"], outcome_reason=r["reason"],
            model=json.loads(r["explorer"]).get("model"), turns=r["turns"], seconds=r["seconds"],
            scan_date=r["scan_date"], photos=r["photos"], max_photos=max_photos or 0, budget_unit="images",
            budget_used=used.get("images", 0), budget_max=budget.get("images", 0), zooms_used=used.get("zooms", 0),
            confirms_used=used.get("confirms", 0), billed_used=billed if isinstance(billed, int) else None,
            stop_photos_used=used.get("stop_photos", 0),
            harness=_harness(json.loads(r["harness"]), json.loads(r["explorer"])),
            billed_static=r["billed_static"], billed_tiles=r["billed_tiles"],
            tiles_used=used.get("tiles") if "tiles" in budget else None, tiles_max=budget.get("tiles"),
            start_kind=start_kind or r["start_source"], events=r["events"],
            err_gtfs_m=distance_m(*gtfs, *verified) if verified else None,
            err_found_m=distance_m(*found, *verified) if verified and found else None,
            started_at=r["started_at"], finished_at=r["finished_at"])

    def _detail(self, summary: ExplorationSummary, row: Record) -> Exploration:
        stop_id, record = summary.stop_id, row["record"]
        outcome = record.get("outcome") or {}
        stop = self.run.stop(stop_id)
        gtfs: Coords = (stop["gtfs_lat"], stop["gtfs_lon"])
        start = self.run.start(stop_id) or {}
        places = (start["lat"], start["lon"]) if start.get("source") == "places" else None
        found = (row["lat"], row["lon"]) if row["lat"] is not None else None
        photo_records = record.get("photos") or []
        opening = next((e.get("photos") or [] for e in record.get("events") or [] if e.get("tool") == "begin"), [])
        by_file = {p["file"]: p["index"] for p in photo_records}
        lines = _transcript(next(iter(self.run.query(
            "SELECT lines FROM transcripts WHERE stop_id = ?", (stop_id,))), {"lines": None})["lines"])
        events = _events(record.get("events") or [], lines, by_file)
        limits = record.get("limits") or [0.0, 0.0]
        return Exploration(
            **summary.model_dump(),
            positions=_positions(gtfs, places, self.positions.verified.get(stop_id), found),
            osm_features=self.osm.near(*gtfs), limits=AlongLimits(along_from=limits[0], along_to=limits[1]),
            path=[(lat, lon) for lat, lon in record.get("path") or []],
            candidates=[_candidate(c) for c in record.get("candidates") or []], report=_report(lines),
            photo_list=[_photo(stop_id, p, opening) for p in photo_records], event_list=events, transcript=lines,
            stop_photos=[by_file[f] for f in outcome.get("stop_photos") or [] if f in by_file],
            close_up=by_file.get(outcome.get("close_up")),
        )
