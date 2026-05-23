#!/usr/bin/env python3
"""Fetch London transit line geometry from the TfL Unified API (mode: `tube`).

Covers tube, DLR, Overground (6 named lines), Elizabeth line, and tram. The TfL
Unified API allows low-volume unauthenticated access, so no app key is required.

For each line and direction we pull the route *sequence*, which gives:
  - orderedLineRoutes[].naptanIds : the ordered station sequence (the line's path)
  - stations[]                    : station detail keyed by stationId (NaPTAN),
                                    including name, lat, lon, stopType, zone

We do NOT get inter-station travel times from this endpoint; t_offset_min for tube
lines is estimated downstream in build_transport_lines.py (plan D4 collapses tube
stations to LGU nodes anyway).

Outputs (under data/transport/tfl/, gitignored):
  raw/{line}_{direction}.json   raw API responses (full fidelity, re-runnable)
  stations.csv                  deduped station_id, name, lat, lon, stop_type, zone, modes
  sequences.csv                 line, mode, direction, route_name, position, station_id

Source: https://api.tfl.gov.uk/  (Powered by TfL Open Data; contains OS data
        (c) Crown copyright and database rights). Free reuse under TfL terms.

Usage:  python3 scripts/fetch_tfl_lines.py
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.tfl.gov.uk"
# TfL "modes" whose lines we want. All map to the epidemic model's `tube` category
# except the Elizabeth line / Overground (heavy rail-ish) — the mode mapping is
# decided later in the distributor config; here we just record the source mode.
MODES = ["tube", "dlr", "overground", "elizabeth-line", "tram"]
DIRECTIONS = ["inbound", "outbound"]

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "transport" / "tfl"
RAW_DIR = OUT_DIR / "raw"


def get_json(url: str, retries: int = 3, pause: float = 1.0):
    """GET + parse JSON, with simple retry/backoff for the public endpoint."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MAY-commute-builder"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001 - network flakiness, retry
            last_err = e
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"failed after {retries} tries: {url}\n  {last_err}")


def lines_for_mode(mode: str) -> list[dict]:
    return get_json(f"{API}/Line/Mode/{mode}")


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    stations: dict[str, dict] = {}          # station_id -> attrs (deduped across lines)
    sequence_rows: list[dict] = []          # ordered membership rows
    summary: list[tuple[str, str, int]] = []  # (line, mode, n_stations)

    for mode in MODES:
        try:
            lines = lines_for_mode(mode)
        except RuntimeError as e:
            print(f"WARN: could not list lines for mode {mode}: {e}", file=sys.stderr)
            continue

        for line in lines:
            line_id = line["id"]
            n_in_line = 0
            for direction in DIRECTIONS:
                url = f"{API}/Line/{line_id}/Route/Sequence/{direction}?serviceTypes=Regular"
                try:
                    data = get_json(url)
                except RuntimeError as e:
                    print(f"WARN: {line_id}/{direction}: {e}", file=sys.stderr)
                    continue

                (RAW_DIR / f"{line_id}_{direction}.json").write_text(
                    json.dumps(data, indent=2)
                )

                # Use stopPointSequences: ordered stops with inline id/name/lat/lon
                # per branch. This is the only field whose ids (the 940G... tube
                # naptans) join consistently — the `stations[]` array returns HUB
                # parents (stationId=None) for interchanges, and orderedLineRoutes
                # references the tube ids those HUBs don't expose. (branchId lets us
                # keep distinct branches separate.)
                for sps in data.get("stopPointSequences", []):
                    branch = sps.get("branchId")
                    for pos, sp in enumerate(sps.get("stopPoint", [])):
                        sid = sp.get("id") or sp.get("stationId")
                        if not sid:
                            continue
                        if sid not in stations:
                            stations[sid] = {
                                "station_id": sid,
                                "name": (sp.get("name") or "").strip(),
                                "lat": sp.get("lat"),
                                "lon": sp.get("lon"),
                                "stop_type": sp.get("stopType", ""),
                                "zone": sp.get("zone", ""),
                                "modes": "|".join(sp.get("modes", [])),
                            }
                        sequence_rows.append({
                            "line": line_id,
                            "mode": mode,
                            "direction": direction,
                            "branch_id": branch,
                            "position": pos,
                            "station_id": sid,
                        })
                        n_in_line += 1
                time.sleep(0.2)  # be gentle with the public endpoint
            summary.append((line_id, mode, n_in_line))
            print(f"  {mode:14s} {line_id:18s} {n_in_line:5d} ordered stops (both dirs)")

    # Write consolidated CSVs.
    with (OUT_DIR / "stations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["station_id", "name", "lat", "lon",
                                          "stop_type", "zone", "modes"])
        w.writeheader()
        for sid in sorted(stations):
            w.writerow(stations[sid])

    with (OUT_DIR / "sequences.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["line", "mode", "direction",
                                          "branch_id", "position", "station_id"])
        w.writeheader()
        w.writerows(sequence_rows)

    print(f"\nDone. {len(stations)} unique stations, "
          f"{len(sequence_rows)} ordered membership rows, "
          f"{len(summary)} lines.")
    print(f"  -> {OUT_DIR/'stations.csv'}")
    print(f"  -> {OUT_DIR/'sequences.csv'}")
    print(f"  -> {RAW_DIR}/ (raw JSON per line/direction)")
    if not stations:
        print("ERROR: no stations fetched — check network/API.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
