"""Exploration runs: run directories on disk, adapters that read them, and the repository over both.

Each explorer writes its own record layout. An adapter recognises one layout
(`can_read`) and converts a run directory into the API's `Exploration` (`convert`); to
support another explorer, write an adapter and add it to `ADAPTERS`. Runs are read on
every request, never cached: they are added (and written) while the app is open.
"""

import json
import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from cotral_maintenance.geo import distance_m

from .explore_schemas import (
    AlongLimits, Exploration, Harness, HarnessVersion, ExplorationCandidate, ExplorationEvent, ExplorationPhoto, ExplorationSummary,
    Position, PositionKind, RawExchange, UNVERSIONED,
)
from .osm_lookup import OsmLookup
from .positions import Coords, PositionIndex

logger = logging.getLogger(__name__)

SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
Record = dict[str, Any]
LABELS: dict[PositionKind, str] = {
    "gtfs": "GTFS", "places": "Places", "verified": "Verified", "estimate": "Submitted position",
}
TOOL_PREFIX = "mcp__explorer__"


class UnknownRun(Exception):
    """No record for the run id."""


class UnknownLayout(Exception):
    """The record exists but no adapter reads its layout."""


def version_order(version: str) -> tuple[int, tuple[int, ...], str]:
    """Sort key, ascending = oldest first: numeric by dotted part, "unversioned" and unparseable lowest."""
    try:
        return 1, tuple(int(part) for part in version.split(".")), version
    except ValueError:
        return 0, (), version


def photo_url(run_id: str, file: str) -> str:
    return f"/api/explorations/{run_id}/photos/{file}"


class ExplorationAdapter(Protocol):
    def can_read(self, record: Record) -> bool: ...

    def convert(self, run_id: str, run_dir: Path, record: Record, positions: PositionIndex,
                osm: OsmLookup) -> Exploration: ...

    def photo_files(self, record: Record) -> set[str]:
        """Base names of the photos of the run (served from its `photos/` directory)."""
        ...


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


class Transcript:
    """The parts of a Claude Code stream-json session the explorer view needs."""

    def __init__(self, lines: list[Record]) -> None:
        self.lines = lines
        self.results: dict[str, tuple[str, bool]] = {}  # tool_use_id -> (text, is_error)
        for line in lines:
            if line.get("type") != "user":
                continue
            for block in self._blocks(line):
                if block.get("type") == "tool_result":
                    self.results[block.get("tool_use_id", "")] = (
                        self._text(block.get("content")), bool(block.get("is_error")))

    @classmethod
    def load(cls, path: Path) -> "Transcript | None":
        if not path.is_file():
            return None
        lines: list[Record] = []
        with path.open(encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    line = json.loads(raw)
                except ValueError:  # a line still being written
                    continue
                if isinstance(line, dict):
                    lines.append(line)
        return cls(lines)

    @staticmethod
    def _blocks(line: Record) -> list[Record]:
        content = (line.get("message") or {}).get("content")
        return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        return ""

    @property
    def model(self) -> str | None:
        for line in self.lines:
            if line.get("type") == "system" and line.get("subtype") == "init":
                return line.get("model")
        return None

    @property
    def report(self) -> str | None:
        for line in reversed(self.lines):
            if line.get("type") == "result":
                result = line.get("result")
                return result if isinstance(result, str) and result else None
        return None

    def steps(self) -> list[tuple[str, Any]]:
        """In order: ("thought", text) and ("tool", the tool_use block)."""
        steps: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for line in self.lines:
            if line.get("type") != "assistant":
                continue
            for block in self._blocks(line):
                kind = block.get("type")
                if kind in ("text", "thinking"):
                    text = block.get("text" if kind == "text" else "thinking")
                    if isinstance(text, str) and text.strip():
                        steps.append(("thought", text.strip()))
                elif kind == "tool_use" and block.get("id") not in seen:
                    seen.add(block.get("id"))
                    steps.append(("tool", block))
        return steps


class AgentExplorerAdapter:
    """Run directories of `cotral_maintenance/explorer/` (layout `agent-explorer/1`)."""

    def can_read(self, record: Record) -> bool:
        return record.get("layout") == "agent-explorer/1"

    def photo_files(self, record: Record) -> set[str]:
        return {PurePosixPath(p["file"]).name for p in record.get("photos", [])}

    def convert(self, run_id: str, run_dir: Path, record: Record, positions: PositionIndex,
                osm: OsmLookup) -> Exploration:
        stop, outcome = record["stop"], record.get("outcome")
        transcript = Transcript.load(run_dir / "transcript.jsonl")
        photo_list = [self._photo(run_id, record, p) for p in record["photos"]]
        by_file = {p["file"]: p["index"] for p in record["photos"]}
        budget = self._budget(record, photo_list)
        events = self._events(record.get("events") or [], transcript, by_file, budget["budget_unit"])
        gtfs: Coords = (stop["lat"], stop["lon"])
        found = (outcome["lat"], outcome["lon"]) if outcome and outcome.get("status") == "found" else None
        position_list = self._positions(stop["stop_id"], gtfs, record.get("starts") or [], positions, found)
        error = {p.kind: p.error_m for p in position_list}
        config = read_json(run_dir / "config.json")
        model = (transcript.model if transcript else None) or (config.get("model") if isinstance(config, dict) else None)
        limits = record["limits"]
        return Exploration(
            run_id=run_id, stop_id=stop["stop_id"], name=stop.get("name", ""),
            outcome=outcome["status"] if outcome else "running", outcome_reason=outcome.get("reason") if outcome else None,
            model=model, photos=len(photo_list), max_photos=record.get("max_photos", 14), **budget,
            events=len(events), harness=self._harness(record, config), **self._billing(record),
            start_kind=next((s.get("kind") for s in record.get("starts") or []), None),
            err_gtfs_m=error["gtfs"], err_found_m=error.get("estimate"), started_at=record.get("started_at"),
            finished_at=record.get("saved_at") if outcome else None,
            positions=position_list, osm_features=osm.near(*gtfs),
            limits=AlongLimits(along_from=limits[0], along_to=limits[1]),
            path=[(lat, lon) for lat, lon in record.get("path") or []],
            candidates=[self._candidate(c) for c in record.get("candidates") or []],
            report=transcript.report if transcript else None, photo_list=photo_list, event_list=events,
            stop_photos=[by_file[f] for f in (outcome or {}).get("stop_photos") or [] if f in by_file],
            close_up=by_file.get((outcome or {}).get("close_up")),
        )

    @staticmethod
    def _budget(record: Record, photo_list: list[ExplorationPhoto]) -> Record:
        """Summary fields of the budget, whichever generation: `budget.unit` (images), sweeps, or the photos taken."""
        budget = record.get("budget")
        if not isinstance(budget, dict):
            return {"budget_unit": "photos", "budget_used": len(photo_list), "budget_max": record.get("max_photos", 14),
                    "zooms_used": 0, "confirms_used": 0, "billed_used": None, "stop_photos_used": 0}
        used = budget.get("used") or {}
        unit = budget.get("unit") or "sweeps"  # the previous format has no unit and counts sweeps
        billed = used.get("billed")
        return {"budget_unit": unit, "budget_used": used[unit], "budget_max": budget[unit],
                "zooms_used": used.get("zooms", 0), "confirms_used": used.get("confirms", 0),
                "billed_used": billed if isinstance(billed, int) else None,
                "stop_photos_used": used.get("stop_photos", 0)}

    @staticmethod
    def _harness(record: Record, config: Any) -> Harness:
        """`record.harness`, else the one in config.json, else "unversioned"."""
        found = record.get("harness")
        if not isinstance(found, dict) and isinstance(config, dict):
            found = config.get("harness")
        if not isinstance(found, dict) or not found.get("version"):
            return Harness(version=UNVERSIONED)
        return Harness(**{k: found.get(k) for k in Harness.model_fields if found.get(k) is not None})

    @staticmethod
    def _billing(record: Record) -> Record:
        billed = record.get("billed_requests")
        billed = billed if isinstance(billed, dict) else {}
        budget = record.get("budget") if isinstance(record.get("budget"), dict) else {}
        return {"billed_static": billed.get("static"), "billed_tiles": billed.get("tiles"),
                "tiles_used": (budget.get("used") or {}).get("tiles") if "tiles" in budget else None,
                "tiles_max": budget.get("tiles")}

    @staticmethod
    def _positions(stop_id: str, gtfs: Coords, starts: list[Record], index: PositionIndex,
                   found: Coords | None) -> list[Position]:
        places = next(((s["lat"], s["lon"]) for s in starts if s.get("kind") == "places"), None) \
            or index.places.get(stop_id)
        verified = index.verified.get(stop_id)
        wanted: list[tuple[PositionKind, Coords | None]] = [
            ("gtfs", gtfs), ("places", places), ("verified", verified), ("estimate", found)]
        return [
            Position(kind=kind, lat=c[0], lon=c[1], label=LABELS[kind],
                     error_m=None if verified is None or kind == "verified" else distance_m(*c, *verified))
            for kind, c in wanted if c is not None
        ]

    @staticmethod
    def _photo(run_id: str, record: Record, p: Record) -> ExplorationPhoto:
        opening = next((e.get("photos") or [] for e in record.get("events") or [] if e.get("tool") == "begin"), [])
        return ExplorationPhoto(
            index=p["index"], url=photo_url(run_id, PurePosixPath(p["file"]).name), pano_id=p["pano_id"],
            lat=p["lat"], lon=p["lon"], date=p.get("date"), heading=p["heading"], fov=p["fov"], pitch=p["pitch"],
            along_m=p["along"], right_m=p["offset"], toward=p["toward"], opening=p["file"] in opening,
            copyright=p.get("copyright"), billed=p.get("billed"), width=p.get("width"), height=p.get("height"), shot=p.get("shot") or 0,
            parent=p.get("parent"), source=p.get("source") or "static", tiles=p.get("tiles") or 0,
        )

    @staticmethod
    def _candidate(c: Record) -> ExplorationCandidate:
        return ExplorationCandidate(
            index=c["index"], kind=c["kind"], lat=c["lat"], lon=c["lon"], along_m=c["along"], right_m=c["offset"],
            status=c["status"], evidence=c.get("evidence") or None, basis=c.get("basis", ""),
            checklist=dict(c.get("checklist") or {}), confirmer_note=c.get("confirmer_note") or "",
            confirm_photo=c.get("confirm_photo"),
        )

    @staticmethod
    def _spent(e: Record, unit: str) -> int | None:
        """What the event says of the budget spent: its own `budget_used`, else by the run's unit."""
        if e.get("budget_used") is not None:
            return e["budget_used"]
        return e.get("sweeps_used") if unit == "sweeps" else e.get("photos_used")

    def _events(self, recorded: list[Record], transcript: Transcript | None,
                by_file: dict[str, int], unit: str = "photos") -> list[ExplorationEvent]:
        events: list[ExplorationEvent] = []
        used = 0  # photos taken so far
        budget_used = 0  # in the run's budget unit

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
            error = e.get("error")
            result = e.get("result")
            add(e["tool"], f"ERROR: {error}" if error else first_line(result or ""), error, e.get("photos") or [],
                e.get("photos_used"), e.get("args"), error if error else result, self._spent(e, unit))

        pending = iter(recorded)
        upcoming = next(pending, None)
        for kind, item in (transcript.steps() if transcript else []):
            if kind == "thought":
                add("thought", item, None, [], None, None, item)
                continue
            name = item.get("name", "")
            tool = name.removeprefix(TOOL_PREFIX)
            text, is_error = transcript.results.get(item.get("id", ""), ("", False))
            # An erroring call that the record shows as a success was refused before it reached the explorer.
            if upcoming is not None and upcoming["tool"] == tool and not (is_error and not upcoming.get("error")):
                add_recorded(upcoming)
                upcoming = next(pending, None)
            else:
                text = text or "the call was refused"
                add("tool_error", f"ERROR: {first_line(text)}", text, [], None,
                    {"tool": name, **(item.get("input") or {})}, text)
        while upcoming is not None:  # recorded after the transcript was last written (or no transcript)
            add_recorded(upcoming)
            upcoming = next(pending, None)
        return events


ADAPTERS: tuple[ExplorationAdapter, ...] = (AgentExplorerAdapter(),)


class ExplorationRepository:
    def __init__(self, runs_dir: Path, positions: PositionIndex, osm: OsmLookup,
                 adapters: tuple[ExplorationAdapter, ...] = ADAPTERS) -> None:
        self.runs_dir = runs_dir
        self.positions = positions
        self.osm = osm
        self.adapters = adapters

    def list(self, harness: str | None = None) -> list[ExplorationSummary]:
        """Summaries of the readable runs (only those of the harness version, if given), sorted by run id;
        unreadable records are logged and skipped."""
        if not self.runs_dir.is_dir():
            return []
        summaries = []
        for path in sorted(self.runs_dir.iterdir()):
            if not (path / "record.json").is_file():
                continue
            try:
                exploration = self.get(path.name)
            except (UnknownRun, UnknownLayout) as error:
                logger.warning("skipping %s: %s", path, error)
                continue
            if harness is None or exploration.harness.version == harness:
                summaries.append(
                    ExplorationSummary(**exploration.model_dump(include=set(ExplorationSummary.model_fields))))
        return summaries

    def harness_versions(self) -> list[HarnessVersion]:
        """The harness versions present with their run counts, newest first, "unversioned" last."""
        counts: dict[str, int] = {}
        for summary in self.list():
            counts[summary.harness.version] = counts.get(summary.harness.version, 0) + 1
        return [HarnessVersion(version=v, runs=counts[v]) for v in sorted(counts, key=version_order, reverse=True)]

    def get(self, run_id: str) -> Exploration:
        """Raises UnknownRun, or UnknownLayout when no adapter reads the record."""
        run_dir, record = self._load(run_id)
        adapter = self._adapter(record, run_dir)
        try:
            return adapter.convert(run_id, run_dir, record, self.positions, self.osm)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise UnknownLayout(f"{run_id}/record.json does not match its layout: {error!r}") from error

    def photo_path(self, run_id: str, file: str) -> Path | None:
        """The image file of a photo of that run, or None unless the record lists it and it exists."""
        if not SAFE_NAME.fullmatch(file):
            return None
        run_dir, record = self._load(run_id)
        if file not in self._adapter(record, run_dir).photo_files(record):
            return None
        root = (run_dir / "photos").resolve()
        path = (root / file).resolve()
        return path if path.parent == root and path.is_file() else None

    def _adapter(self, record: Any, run_dir: Path) -> ExplorationAdapter:
        for adapter in self.adapters:
            if isinstance(record, dict) and adapter.can_read(record):
                return adapter
        raise UnknownLayout(f"{run_dir.name}/record.json has a layout no adapter reads")

    def _load(self, run_id: str) -> tuple[Path, Any]:
        root = self.runs_dir.resolve()
        run_dir = (root / run_id).resolve() if SAFE_NAME.fullmatch(run_id) else None
        if run_dir is None or run_dir.parent != root or not (run_dir / "record.json").is_file():
            raise UnknownRun(run_id)
        try:
            return run_dir, json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise UnknownLayout(f"{run_id}/record.json is not valid JSON: {error}") from error
