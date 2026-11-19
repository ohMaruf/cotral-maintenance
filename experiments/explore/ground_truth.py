"""Convert the manually verified stops spreadsheet into a ground-truth CSV for the explorer (agent_dry_run.py).

Input: inputs/GROUND_TRUTH/bus_stops_new_coordinates.xlsx, one row per GTFS stop. A verifier
checked a row when `Verified` is TRUE; `Latitude/Longitude_with_corrections` is then
where they found the stop in Street View, unless `Not found?` is TRUE.

Output: data/ground_truth_manual.csv with stop_id, lat, lon (the corrected position)
and, for analysis, has_sign, comments and offset_m: how far the correction moved the
stop from its position in our GTFS (GTFS_COTRAL/stops.txt, which the explorer
starts from; the sheet's own GTFS_original_* columns are empty for some rows).

Kept: verified, found, numeric corrected coordinates, stop id in our GTFS.

openpyxl is only needed here, once, so it is not a project dependency:
    uv run --with openpyxl python experiments/explore/ground_truth.py
"""

import csv
import sys
from collections import Counter
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cotral_maintenance.geo import distance_m  # noqa: E402
from cotral_maintenance.stops import load_stops  # noqa: E402

SHEET = Path("inputs/GROUND_TRUTH/bus_stops_new_coordinates.xlsx")
STOPS = Path("GTFS_COTRAL/stops.txt")
OUT = Path("data/ground_truth_manual.csv")
COLUMNS = ("stop_id", "lat", "lon", "has_sign", "comments", "offset_m")


def number(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    gtfs = {stop.stop_id: stop for stop in load_stops(STOPS)}
    rows = openpyxl.load_workbook(SHEET, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True)
    header = next(rows)
    kept, skipped = [], Counter()
    for values in rows:
        row = dict(zip(header, values))
        if row["Verified"] is not True:
            continue
        stop_id = str(row["stop_id"]).strip()
        lat, lon = number(row["Latitude_with_corrections"]), number(row["Longitude_with_corrections"])
        if row["Not found?"] is True:
            skipped["not found by the verifier"] += 1
        elif lat is None or lon is None:
            skipped["no corrected coordinates"] += 1
        elif stop_id not in gtfs:
            skipped["stop id not in our GTFS"] += 1
        else:
            stop = gtfs[stop_id]
            kept.append({
                "stop_id": stop_id, "lat": lat, "lon": lon,
                "has_sign": row["Has_Sign"] or "", "comments": row["COMMENTS"] or "",
                "offset_m": round(distance_m(stop.lat, stop.lon, lat, lon), 1),
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(kept, key=lambda r: r["stop_id"]))
    print(f"Wrote {len(kept)} stops to {OUT}; skipped {dict(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
