"""HDF5 loading and pre-aggregation for epidemic animation.

Reads simulation events and geo-unit metadata from HDF5 files produced by the
MAY framework, then builds dense (geo_units × days) count matrices used by the
animation's per-frame update function.

The world_map directory is added to sys.path so that
``geo_units_dataframe.load_geo_units_dataframe`` can be imported without any
modifications to those files.  Events are read directly from the HDF5 structure
to avoid the full person/venue merge overhead of ``events_analysis``, which is
designed for analysis rather than animation pre-aggregation.
"""

from __future__ import annotations

import os
import sys

import h5py
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORLD_MAP_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "world_map"))

if _WORLD_MAP_DIR not in sys.path:
    sys.path.insert(0, _WORLD_MAP_DIR)

from geo_units_dataframe import load_geo_units_dataframe  # noqa: E402


def _load_raw_events(events_path: str, event_types: list[str]) -> dict:
    """Read time and person geo_unit_id for each event type from HDF5.

    Builds a person_id → geo_unit_id lookup array from ``lookups/people``,
    then vectorises the mapping over each event table.  This avoids the full
    person/venue merge done by ``events_analysis.load_events_dataframe``.

    Args:
        events_path: Path to simulation_events.h5.
        event_types: List of event type names to load (e.g. ['infections', 'deaths']).

    Returns:
        Dict mapping event_type → {'time': float array, 'geo_unit_id': int array}.
    """
    with h5py.File(events_path, "r") as f:
        # Build person_id → geo_unit_id vectorised lookup.
        people = f["lookups/people"][:]
        person_ids_all = people["person_id"].astype(np.int64)
        geo_unit_ids_all = people["geo_unit_id"].astype(np.int64)

        max_pid = int(person_ids_all.max()) + 1
        pid_to_gid = np.full(max_pid, -1, dtype=np.int64)
        pid_to_gid[person_ids_all] = geo_unit_ids_all

        result = {}
        for et in event_types:
            key = f"events/{et}"
            if key not in f:
                print(f"  Warning: '{key}' not found in {events_path}, skipping.")
                continue
            raw = f[key][:]
            person_ids = raw["person_id"].astype(np.int64)
            times = raw["time"].astype(np.float64)

            # Vectorised map: person_id → geo_unit_id
            clipped = np.clip(person_ids, 0, max_pid - 1)
            geo_ids = pid_to_gid[clipped]
            # Mask out any unmapped persons (shouldn't happen in valid data)
            valid = geo_ids >= 0
            result[et] = {
                "time":        times[valid],
                "geo_unit_id": geo_ids[valid],
            }
            print(f"  Loaded {valid.sum():,} {et} events")

    return result


def load_simulation_events(cfg: dict) -> dict:
    """Load and pre-aggregate simulation events into geo_unit × day count matrices.

    Steps:
    1. Load geo-unit metadata via ``load_geo_units_dataframe``, filtered to
       ``cfg['geo_unit_level']``.
    2. Read raw event times and person geo_unit_ids from HDF5.
    3. Bin each event to integer day; accumulate into a preallocated
       ``(U, D)`` int32 matrix using vectorised np.add.at.
    4. Compute daily global totals and cumulatives.

    Args:
        cfg: The CONFIG dict from ``animate_epidemic.py``.  Required keys:
            ``events_file``, ``world_state_file``, ``event_types``,
            ``geo_unit_level``, ``time_range``.

    Returns:
        Dict with keys:

        - ``geo_units``    list[dict]  — [{id, name, lat, lon, pop}, ...]
        - ``unit_index``   dict        — geo_unit_id → row index
        - ``counts``       dict        — event_type → ndarray (U, D) int32
        - ``daily_global`` dict        — event_type → ndarray (D,) int32
        - ``cumulative``   dict        — event_type → ndarray (D,) int32
        - ``n_days``       int
        - ``day_offset``   int         — matrix column 0 = simulation day day_offset
        - ``time_range``   (float, float) — actual start/end t used
    """
    events_file     = cfg["events_file"]
    world_state_file = cfg["world_state_file"]
    event_types     = cfg.get("event_types", ["infections", "deaths"])
    level           = cfg.get("geo_unit_level", "SGU")

    # --- Geo units ---
    print(f"  Loading geo units (level={level})...")
    geo_df = load_geo_units_dataframe(world_state_file)
    geo_df_filtered = geo_df[geo_df["geo_unit_level"] == level].reset_index(drop=True)
    if geo_df_filtered.empty:
        raise ValueError(
            f"No geo units found for level '{level}'. "
            f"Available levels: {geo_df['geo_unit_level'].unique().tolist()}"
        )
    print(f"  {len(geo_df_filtered)} geo units at level {level}")

    geo_units = geo_df_filtered.rename(columns={
        "geo_unit_id":   "id",
        "geo_unit_name": "name",
        "population":    "pop",
    })[["id", "name", "lat", "lon", "pop"]].to_dict("records")

    unit_index = {int(u["id"]): i for i, u in enumerate(geo_units)}
    U = len(geo_units)

    # --- Raw events ---
    print(f"  Loading events from {events_file}...")
    raw = _load_raw_events(events_file, event_types)

    if not raw:
        raise ValueError("No events loaded — check event_types and events_file.")

    # --- Determine time range ---
    all_times = np.concatenate([raw[et]["time"] for et in raw])
    t_global_min = float(all_times.min())
    t_global_max = float(all_times.max())

    time_range_cfg = cfg.get("time_range")
    if time_range_cfg is not None:
        t_min = max(t_global_min, float(time_range_cfg[0]))
        t_max = min(t_global_max, float(time_range_cfg[1]))
    else:
        t_min, t_max = t_global_min, t_global_max

    day_offset = int(np.floor(t_min))
    n_days     = int(np.ceil(t_max)) - day_offset + 1
    print(f"  Time range: day {day_offset} → {day_offset + n_days - 1}  ({n_days} days)")

    # --- Build count matrices ---
    # Vectorised lookup: geo_unit_id → row index (for units not at this level → -1)
    all_gids = np.array(sorted(unit_index.keys()), dtype=np.int64)
    max_gid  = int(all_gids.max()) + 1
    gid_to_row = np.full(max_gid, -1, dtype=np.int32)
    for gid, row in unit_index.items():
        gid_to_row[gid] = row

    counts       = {}
    daily_global = {}
    cumulative   = {}

    for et in event_types:
        if et not in raw:
            continue

        times    = raw[et]["time"]
        geo_ids  = raw[et]["geo_unit_id"].astype(np.int64)

        # Filter to time range
        mask = (times >= t_min) & (times <= t_max)
        times   = times[mask]
        geo_ids = geo_ids[mask]

        # Day index within the matrix
        day_idx = (times - day_offset).astype(np.int32)

        # Map geo_unit_id → row index
        clipped = np.clip(geo_ids, 0, max_gid - 1)
        row_idx = gid_to_row[clipped]

        # Keep only valid (unit at correct level, day in range)
        valid = (row_idx >= 0) & (day_idx >= 0) & (day_idx < n_days)
        row_idx = row_idx[valid]
        day_idx = day_idx[valid]

        mat = np.zeros((U, n_days), dtype=np.int32)
        np.add.at(mat, (row_idx, day_idx), 1)

        counts[et]       = mat
        daily_global[et] = mat.sum(axis=0).astype(np.int32)
        cumulative[et]   = np.cumsum(daily_global[et]).astype(np.int32)
        print(f"  {et}: {valid.sum():,} events binned into ({U}, {n_days}) matrix")

    return {
        "geo_units":    geo_units,
        "unit_index":   unit_index,
        "counts":       counts,
        "daily_global": daily_global,
        "cumulative":   cumulative,
        "n_days":       n_days,
        "day_offset":   day_offset,
        "time_range":   (t_min, t_max),
    }
