"""MCP server exposing the explorer's tools (cotral_maintenance/explorer) for one stop.

Started by the agent runner (agent_dry_run.py) as the ONLY tool source of a sandboxed
Claude Code session. The run directory comes from EXPLORER_RUN_DIR; its config.json
names the stop. Everything the explorer does is recorded in <run dir>/record.json.

Run it from the repository root (the runner does): .venv/bin/python experiments/explore/agent_server.py
"""

import io
import json
import logging
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.explorer.drawing import draw_map
from cotral_maintenance.explorer.session import Session, ToolError
from confirmer import ClaudeCodeConfirmer  # experiments/explore/confirmer.py, next to this script
from setup import LOOKALIKES, REFERENCE, build_session  # experiments/explore/setup.py

MAX_REFERENCE_PX = 800

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
RUN_DIR = Path(os.environ["EXPLORER_RUN_DIR"])
CONFIG = json.loads((RUN_DIR / "config.json").read_text())
mcp = MCPServer("explorer")
_session: Session | None = None


def session() -> Session:
    if _session is None:
        raise ValueError("call begin() first")
    return _session


def _build() -> Session:
    def confirmer(log_dir: Path) -> ClaudeCodeConfirmer:
        return ClaudeCodeConfirmer(CONFIG.get("confirmer_model") or CONFIG.get("model", "haiku"), REFERENCE,
                                   sorted(LOOKALIKES.glob("*.png")), Path.cwd(), log_dir)

    return build_session(RUN_DIR, CONFIG, confirmer)


def _jpeg(path: Path, max_px: int | None = None) -> Image:
    img = PILImage.open(path).convert("RGB")
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return Image(data=buffer.getvalue(), format="jpeg")


def _call(tool: str, args: dict, fn):
    try:
        result = fn()
    except ToolError as error:
        session().log_error(tool, args, str(error))
        raise ValueError(str(error)) from error
    return [result.text, *(_jpeg(p) for p in result.images)]


@mcp.tool()
def begin() -> list:
    """Start the search. Returns the reference Cotral sign, the look-alike signs that are NOT bus stops, the map of
    the bus's path with everything placed on it, the opening sweep at the start and the state. Call it once, first."""
    global _session
    if _session is None:
        _session = _build()
    refs = ["REFERENCE: the Cotral bus stop sign (navy panel, 'FERMATA', white Cotral logo, plate with the stop id).",
            _jpeg(REFERENCE, MAX_REFERENCE_PX),
            "LOOK-ALIKES: blue road signs that are NOT bus stops (pedestrian crossing, lanes, bus-lane signs with a"
            " bus pictogram, parking, directions). Never confirm these."]
    refs += [_jpeg(p, MAX_REFERENCE_PX) for p in sorted(LOOKALIKES.glob("*.png"))]
    return refs + _call("begin", {}, session().begin)


@mcp.tool()
def sweep(from_m: float, facing: str = "ahead", scan: str | None = None) -> list:
    """Costs 1 image. One wide photo (fov 110) from the panorama nearest `from_m` metres along the path.
    facing 'ahead' (default): from straight ahead along the road round to just behind straight right: the
    right-hand sidewalk ahead, far along it, and beside the camera. facing 'behind': from just ahead of straight
    right round to straight back: the right-hand sidewalk beside and behind the camera. scan 'YYYY-MM' to use
    another scan's panorama."""
    args = {"from_m": from_m, "facing": facing, "scan": scan}
    return _call("sweep", args, lambda: session().sweep(from_m, facing, scan))


@mcp.tool()
def zoom(photo: int, x: float, y: float, fov: float = 10.0) -> list:
    """A narrow, sharp, full-resolution view centred on point (x, y) of a photo (0-1000 grid), from the same panorama. Costs about
    2-4 tiles (or 1 image when the tiles run out). Use it on anything small or far that might be a stop sign,
    shelter or marking. fov 5-20 degrees (10 is a good start; 6 for something tiny and far). Only a candidate
    marked on a close view (zoom or look_from) can be confirmed."""
    args = {"photo": photo, "x": x, "y": y, "fov": fov}
    return _call("zoom", args, lambda: session().zoom(photo, x, y, fov))


@mcp.tool()
def look_from(candidate: int, from_m: float | None = None, fov: float = 10.0) -> list:
    """A new viewpoint: a narrow, sharp view of a candidate from ANOTHER panorama, aimed at its estimated position.
    Costs about 2-4 tiles. Use it when a candidate can't be seen clearly (edge on, from behind, hidden, too far or
    blurry). By default the harness picks the closest other panorama before it in the direction of travel (stop
    signs face the arriving buses); from_m picks the panorama nearest that position instead."""
    args = {"candidate": candidate, "from_m": from_m, "fov": fov}
    return _call("look_from", args, lambda: session().look_from(candidate, from_m, fov))


@mcp.tool()
def mark_candidate(photo: int, x: float, y: float, kind: str, same_as: int | None = None) -> list:
    """Free. Mark something that may be the stop at point (x, y) of a photo (0-1000 grid; mark it on a ZOOM to be able to confirm
    it). Point where the object meets the GROUND (the foot of the sign's pole, the base of the shelter): that gives
    its distance. If the foot is hidden, point at the object itself. kind: sign, shelter, pole_with_panel, bench,
    road_marking, people_waiting. same_as: an existing candidate number, when this is a view of it from ANOTHER
    panorama (two views from different panoramas give a triangulated position)."""
    args = {"photo": photo, "x": x, "y": y, "kind": kind, "same_as": same_as}
    return _call("mark_candidate", args, lambda: session().mark_candidate(photo, x, y, kind, same_as))


@mcp.tool()
def confirm(candidate: int) -> list:
    """No image (capped). An independent confirmer judges the close view (zoom or look_from) the candidate was last
    marked on, answering a
    checklist (stop text, Cotral logo, shelter... and look-alike features); the harness decides confirmed or
    rejected."""
    return _call("confirm", {"candidate": candidate}, lambda: session().confirm(candidate))


@mcp.tool()
def find_other_scans(at_m: float) -> list:
    """Free. Look for panoramas of other drives (other dates, the other carriageway) around `at_m`."""
    return _call("find_other_scans", {"at_m": at_m}, lambda: session().find_other_scans(at_m))


@mcp.tool()
def show_map() -> list:
    """Free. A drawn map of the search so far (path, sidewalk coverage, photos, hints, candidates) and the state."""
    return _call("show_map", {}, lambda: session().show_map(draw_map))


@mcp.tool()
def note(text: str) -> list:
    """Free. Write down your plan or your reasoning; it is kept in the record."""
    return _call("note", {"text": text}, lambda: session().note(text))


@mcp.tool()
def submit_found(candidate: int) -> list:
    """End the search: the stop is this CONFIRMED candidate. Refused unless the checklist confirmed it. The harness
    then photographs the stop and its surroundings (from images kept back for it)."""
    return _call("submit_found", {"candidate": candidate}, lambda: session().submit_found(candidate))


if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        if _session is not None:
            _session.finish("the explorer stopped without submitting")
