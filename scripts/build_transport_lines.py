#!/usr/bin/env python3
"""Build transport-line definitions from the acquired data (commute plan task 6).

Consumes the raw transport data + the station→LGU snap, and emits the line
definitions the venue child creator will read. These are bulk DATA (thousands of
lines), not engine/module config, so they are normalised CSVs under data/transport/
(consistent with every other data artifact here), NOT YAML:

  data/transport/lines.csv       one row per line:
      line_id, source(rail|tube), mode(train|tube), carriages,
      capacity_per_carriage, frequency_peak (rail only), n_stops
  data/transport/line_stops.csv  one row per stop (join on line_id):
      line_id, position, node_mgu, node_lgu, name, t_offset_min

Every stop carries both node_mgu and node_lgu (MGU⊂LGU), so the routing table can
match riders on either level.

Design (see COMMUTE_PLAN.md):
  RAIL (D4: stations are sparse → keep station granularity, tag each with its geo)
    * Group GTFS trips by ordered stop_id pattern (310k trips → 14k patterns).
    * Keep patterns with ≥1 run departing in the AM peak window — the commute
      model only fires peak slots, so off-peak-only patterns are irrelevant.
    * t_offset_min per stop = median over that pattern's peak runs of
      (departure − first departure), from real GTFS times.
    * frequency_peak = number of peak runs (lets the distributor/JUNE sample runs).

  TUBE/METRO (collapse to MGU-level nodes — user decision, finer than the plan's
  LGU so compact single-LGU systems like the Glasgow Subway are still resolved)
    * One line per (line/route, direction/branch) ordered station sequence.
    * Collapse consecutive same-MGU stations into a single node; node offset =
      estimated time at the first station entering that MGU run.
    * No timetable from TfL/OSM, so t_offset is ESTIMATED from a per-submode
      inter-station time (documented below) — calibrate later.
    * Mode mapping: tube/dlr/tram/subway/light_rail → `tube` (dense carriages);
      overground/elizabeth-line → `train` (heavy-rail-like, per census TS061).

Usage:  python3 scripts/build_transport_lines.py
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSPORT = REPO_ROOT / "data" / "transport"
OUT_DIR = TRANSPORT

# --- tunables --------------------------------------------------------------
PEAK_START_MIN = 6 * 60      # 06:00 inclusive
PEAK_END_MIN = 10 * 60       # 10:00 exclusive
# Default vehicle sizing per mode (carriages × capacity). Calibrate later.
VEHICLE = {
    "train": {"carriages": 8, "capacity_per_carriage": 70},
    "tube":  {"carriages": 8, "capacity_per_carriage": 150},
}
# Estimated inter-station travel time (minutes) by source submode, used only when
# no timetable is available (tube/metro). Rough peak-service values.
SUBMODE_HOP_MIN = {
    "tube": 2.0, "dlr": 2.0, "tram": 2.0,
    "subway": 1.5,          # Glasgow Subway (very short hops)
    "light_rail": 2.5,      # Tyne & Wear Metro
    "overground": 3.0, "elizabeth-line": 2.5,
}
# Which epidemic mode each source submode maps to.
SUBMODE_TO_MODE = {
    "tube": "tube", "dlr": "tube", "tram": "tube",
    "subway": "tube", "light_rail": "tube",
    "overground": "train", "elizabeth-line": "train",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def load_lgu_lookup() -> dict[tuple[str, str], tuple[str, str, str]]:
    """(source, station_id) -> (mgu, lgu, name)."""
    df = pd.read_csv(TRANSPORT / "stations_to_lgu.csv",
                     dtype={"station_id": str})
    return {(r.source, r.station_id): (r.mgu, r.lgu, r.name)
            for r in df.itertuples(index=False)}


def gtfs_minutes(t: str) -> int | None:
    """'HH:MM:SS' -> minutes since midnight (GTFS may exceed 24h)."""
    try:
        h, m, _ = t.split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return None


# --- rail ------------------------------------------------------------------
def build_rail(lgu: dict) -> list[dict]:
    print("Reading GTFS stop_times (206MB)...")
    st = pd.read_csv(TRANSPORT / "rail_gtfs" / "stop_times.txt",
                     usecols=["trip_id", "departure_time", "stop_id", "stop_sequence"],
                     dtype={"trip_id": str, "stop_id": str})
    st = st.sort_values(["trip_id", "stop_sequence"])
    st["dep"] = st["departure_time"].map(gtfs_minutes)

    print("Grouping trips into patterns...")
    # Per trip: ordered stop list, ordered dep list, first departure.
    trips = st.groupby("trip_id", sort=False).agg(
        stops=("stop_id", lambda s: tuple(s)),
        deps=("dep", lambda s: tuple(s)),
    )
    trips["first_dep"] = trips["deps"].map(lambda d: d[0] if d and d[0] is not None else None)
    trips = trips.dropna(subset=["first_dep"])
    trips["peak"] = trips["first_dep"].between(PEAK_START_MIN, PEAK_END_MIN - 1)

    # Aggregate per stop-pattern over its PEAK runs only.
    pat_offsets: dict[tuple, list] = {}     # pattern -> list of per-stop offset lists
    pat_freq: dict[tuple, int] = defaultdict(int)
    pat_first: dict[tuple, list] = defaultdict(list)
    for row in trips.itertuples(index=False):
        if not row.peak:
            continue
        pat = row.stops
        offs = [None if d is None else d - row.first_dep for d in row.deps]
        pat_offsets.setdefault(pat, []).append(offs)
        pat_freq[pat] += 1
        pat_first[pat].append(row.first_dep)

    print(f"  peak patterns: {len(pat_freq)}")
    lines, skipped = [], 0
    for pat, runs in pat_offsets.items():
        # Median offset per stop position across this pattern's peak runs.
        med = []
        for i in range(len(pat)):
            vals = [r[i] for r in runs if r[i] is not None]
            med.append(int(round(pd.Series(vals).median())) if vals else 0)
        stops = []
        for sid, off in zip(pat, med):
            info = lgu.get(("rail", sid))
            if info is None:
                stops.append(None)
                continue
            mgu, l, name = info
            stops.append({"node_mgu": mgu, "node_lgu": l,
                          "name": name.title(), "t_offset_min": off})
        if any(s is None for s in stops) or len(stops) < 2:
            skipped += 1
            continue
        rep = int(round(pd.Series(pat_first[pat]).median()))
        hhmm = f"{rep // 60:02d}{rep % 60:02d}"
        lid = f"{slug(stops[0]['name'])}_{slug(stops[-1]['name'])}_{hhmm}"
        lines.append({
            "id": lid, "mode": "train",
            **VEHICLE["train"],
            "frequency_peak": pat_freq[pat],
            "stops": stops,
        })
    # Disambiguate duplicate ids (same endpoints + rep time, different calling pts).
    _dedupe_ids(lines)
    print(f"  rail lines: {len(lines)} (skipped {skipped} with unmappable stops)")
    return lines


# --- tube / metro ----------------------------------------------------------
def _collapse_to_mgu_nodes(seq: list[tuple[str, str, str]], hop_min: float) -> list[dict]:
    """seq = ordered [(mgu, lgu, name)]; collapse consecutive same-MGU stations into
    one node (user decision: MGU-level nodes for tube/metro, finer than LGU so that
    compact single-LGU systems like the Glasgow Subway are still resolved). Each node
    keeps node_lgu too (MGU⊂LGU) so routing can match on either level.
    t_offset_min = estimated time at the first station entering that MGU run."""
    nodes = []
    for i, (mgu, l, name) in enumerate(seq):
        if nodes and nodes[-1]["node_mgu"] == mgu:
            continue  # same MGU as previous station -> already covered by the node
        nodes.append({"node_mgu": mgu, "node_lgu": l,
                      "name": name,  # TfL/OSM names are already proper-case
                      "t_offset_min": int(round(i * hop_min))})
    return nodes


def build_tube(lgu: dict) -> list[dict]:
    lines = []

    # --- TfL ---
    tfl = pd.read_csv(TRANSPORT / "tfl" / "sequences.csv", dtype={"station_id": str})
    tfl["branch_id"] = tfl["branch_id"].fillna(0).astype(int)
    for (line, mode, direction, branch), grp in tfl.groupby(
            ["line", "mode", "direction", "branch_id"], sort=False):
        grp = grp.sort_values("position")
        seq = []
        for sid in grp["station_id"]:
            info = lgu.get(("tfl", sid))
            if info:
                seq.append(info)
        if len(seq) < 2:
            continue
        nodes = _collapse_to_mgu_nodes(seq, SUBMODE_HOP_MIN.get(mode, 2.0))
        if len(nodes) < 2:
            continue
        lines.append({
            "id": f"{slug(line)}_{slug(direction)}_b{branch}",
            "mode": SUBMODE_TO_MODE.get(mode, "tube"),
            **VEHICLE[SUBMODE_TO_MODE.get(mode, "tube")],
            "stops": nodes,
        })

    # --- other metros (Glasgow / Tyne&Wear / Manchester) ---
    met = pd.read_csv(TRANSPORT / "metros" / "sequences.csv", dtype={"station_id": str})
    NET_SUBMODE = {"Glasgow Subway": "subway",
                   "Tyne and Wear Metro": "light_rail",
                   "Manchester Metrolink": "tram"}
    for (net, rid, ref), grp in met.groupby(["network", "route_id", "route_ref"], sort=False):
        grp = grp.sort_values("position")
        seq = []
        for sid in grp["station_id"]:
            info = lgu.get(("metro", sid))
            if info:
                seq.append(info)
        if len(seq) < 2:
            continue
        sub = NET_SUBMODE.get(net, "light_rail")
        nodes = _collapse_to_mgu_nodes(seq, SUBMODE_HOP_MIN.get(sub, 2.0))
        if len(nodes) < 2:
            continue
        lines.append({
            "id": f"{slug(net)}_{slug(ref)}_{rid}",
            "mode": SUBMODE_TO_MODE.get(sub, "tube"),
            **VEHICLE[SUBMODE_TO_MODE.get(sub, "tube")],
            "stops": nodes,
        })

    _dedupe_ids(lines)
    print(f"  tube/metro lines: {len(lines)}")
    return lines


def _dedupe_ids(lines: list[dict]) -> None:
    seen = defaultdict(int)
    for ln in lines:
        base = ln["id"]
        if seen[base]:
            ln["id"] = f"{base}_{seen[base]}"
        seen[base] += 1


# --- csv output ------------------------------------------------------------
# Line definitions are bulk DATA (thousands of lines), not engine config, so they
# live under data/transport/ as normalised CSVs (joinable on line_id), consistent
# with every other data artifact in the repo:
#   lines.csv       one row per line   (line-level attributes)
#   line_stops.csv  one row per stop   (ordered stops, joined via line_id)
def _write_csv(rail: list[dict], tube: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    line_rows, stop_rows = [], []
    for source, lines in (("rail", rail), ("tube", tube)):
        for ln in lines:
            line_rows.append({
                "line_id": ln["id"],
                "source": source,
                "mode": ln["mode"],
                "carriages": ln["carriages"],
                "capacity_per_carriage": ln["capacity_per_carriage"],
                "frequency_peak": ln.get("frequency_peak", ""),  # rail only
                "n_stops": len(ln["stops"]),
            })
            for pos, s in enumerate(ln["stops"]):
                stop_rows.append({
                    "line_id": ln["id"],
                    "position": pos,
                    "node_mgu": s["node_mgu"],
                    "node_lgu": s["node_lgu"],
                    "name": s["name"],
                    "t_offset_min": s["t_offset_min"],
                })
    pd.DataFrame(line_rows).to_csv(OUT_DIR / "lines.csv", index=False)
    pd.DataFrame(stop_rows).to_csv(OUT_DIR / "line_stops.csv", index=False)


def main() -> int:
    print("Loading station→LGU lookup...")
    lgu = load_lgu_lookup()

    rail = build_rail(lgu)
    tube = build_tube(lgu)
    _write_csv(rail, tube)

    n_stops = sum(len(l["stops"]) for l in rail) + sum(len(l["stops"]) for l in tube)
    print(f"\nDone. {len(rail) + len(tube)} lines, {n_stops} stops.")
    print(f"  -> {OUT_DIR/'lines.csv'}       ({len(rail)} rail + {len(tube)} tube/metro lines)")
    print(f"  -> {OUT_DIR/'line_stops.csv'}  ({n_stops} stop rows)")
    if not rail or not tube:
        print("WARN: a line set is empty.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
