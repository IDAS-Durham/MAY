#!/usr/bin/env python3
"""Generate synthetic bus pseudo-routes for the commute RouteDistributor (D8).

Rationale
---------
Bus is the most-used commute mode after car_solo, but the rail/tube data layer
does not include real bus topology. Modelling real GB bus routes (BODS GTFS
feeds, ~thousands of operators) is hyper-messy and we don't need it for
epidemic FOI — the only thing the simulator needs is a *bounded shared-air
contact pool* for bus riders. So we synthesise the minimum structure:

  • **Within-LGU**: one `transport_line` venue per origin MGU. line_id =
    ``bus_pool_<MGU>``. Every rider boarding in that MGU joins the same pool
    regardless of where they alight — matches how real-world bus contacts
    actually concentrate (people boarding at the same stop ride together).
  • **Cross-LGU**: one `transport_line` venue per ordered (origin_LGU,
    dest_LGU) pair. line_id = ``bus_pool_lgu_<origin>__<dest>``. Every rider
    making that LGU-to-LGU journey joins the same pool, regardless of their
    specific MGU endpoints — captures inter-borough/inter-district commute
    corridors (Durham→Darlington, etc.). Only LGU pairs whose centroids are
    within ``--cross-lgu-radius-km`` (default 50 km) are enumerated; further-
    apart pairs would never be a realistic daily bus commute and would only
    bloat the routing table.
  • Travel time = Euclid(origin centroid, dest centroid) / avg-speed, clamped
    to [min, max] minutes. Centroids are British National Grid (EPSG:27700)
    in metres, so a plain Euclidean distance is correct.

The bus RouteDistributor (`configs/2021/distributors/route_commute_bus.yaml`)
then needs zero code change to consume these rows — the format is identical
to the rail/tube rows already in `routes.csv` / `route_legs.csv`.

This script is idempotent: any pre-existing ``mode_class == "bus"`` rows in
the target CSVs are stripped before the new rows are appended, so re-running
the script always yields the same final state.

Inputs
------
  data/geography/hierarchy.csv
  june2/data/domain_decomposition/2021/mgu_centroids.csv   (BNG)

Outputs (appended)
------------------
  data/transport/routes.csv          (+ N bus rows; one per MGU-MGU pair)
  data/transport/route_legs.csv      (+ N bus rows; one per MGU-MGU pair)
  data/transport/lines.csv           (+ M bus_pool_* rows; per-origin-MGU
                                       pools for within-LGU + per-LGU-pair
                                       pools for cross-LGU)
"""

from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

# Defaults: 30 km/h ~ urban-bus average. 5-min floor catches same-MGU trips;
# 60-min ceiling keeps the largest LGUs (e.g. County Durham, geographically
# huge) from generating implausibly long synthetic rides.
DEFAULT_AVG_SPEED_KMH = 30.0
DEFAULT_MIN_MIN = 5
DEFAULT_MAX_MIN = 60
# Cross-LGU LGU-centroid distance threshold. Cuts off implausibly long bus
# commutes (Durham→London) which only bloat the routing table.
DEFAULT_CROSS_LGU_RADIUS_KM = 50.0


def _sanitize_lgu(name: str) -> str:
    """LGU names contain spaces, commas, and punctuation ('Bristol, City of').
    Squash to lowercase alnum+underscore so the line_id is filesystem- and
    log-friendly."""
    s = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()
    return s or "lgu"


def load_mgu_to_lgu(hierarchy_csv: Path) -> dict[str, str]:
    """Return {mgu_name: lgu_name}. Drops duplicates (one MGU lives in one LGU)."""
    df = pd.read_csv(hierarchy_csv, usecols=["MGU", "LGU"])
    return dict(df.drop_duplicates("MGU").itertuples(index=False, name=None))


def load_centroids(centroids_csv: Path) -> dict[str, tuple[float, float]]:
    """Return {mgu_name: (X, Y)} in BNG metres."""
    df = pd.read_csv(centroids_csv)
    return {row.geo_unit: (row.X, row.Y) for row in df.itertuples(index=False)}


def time_min(d_meters: float, speed_kmh: float, lo: int, hi: int) -> int:
    """Distance → minutes, clamped to [lo, hi]. Same-MGU trips → lo."""
    minutes = d_meters / 1000.0 / speed_kmh * 60.0
    return max(lo, min(hi, int(math.ceil(minutes))))


def build_bus_rows(
    mgu_to_lgu: dict[str, str],
    centroids: dict[str, tuple[float, float]],
    avg_speed_kmh: float,
    min_min: int,
    max_min: int,
    cross_lgu_radius_km: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Generate (routes_rows, legs_rows, lines_rows).

    Two passes:
      1. **Within-LGU**: every ordered (origin_mgu, dest_mgu) pair inside the
         same LGU → line_id ``bus_pool_<origin_mgu>`` (per-origin-MGU pool).
      2. **Cross-LGU**: every ordered (origin_mgu, dest_mgu) pair across two
         different LGUs whose *LGU centroids* lie within
         ``cross_lgu_radius_km`` → line_id
         ``bus_pool_lgu_<origin_lgu>__<dest_lgu>`` (per-LGU-pair pool).
    """
    # Group MGUs by their LGU, dropping any that lack a centroid (otherwise we
    # can't compute travel time). We log the orphans rather than failing.
    lgu_to_mgus: dict[str, list[str]] = defaultdict(list)
    orphans = []
    for mgu, lgu in mgu_to_lgu.items():
        if mgu in centroids:
            lgu_to_mgus[lgu].append(mgu)
        else:
            orphans.append(mgu)
    if orphans:
        print(f"  warning: {len(orphans):,} MGUs have no centroid and were skipped "
              f"(first 3: {orphans[:3]})")

    # LGU centroid = mean of constituent MGU centroids. Used only to gate
    # which cross-LGU pairs we enumerate; t_alight for each emitted row is
    # still computed from the MGU-pair distance.
    lgu_centroids: dict[str, tuple[float, float]] = {}
    for lgu, mgus in lgu_to_mgus.items():
        xs = [centroids[m][0] for m in mgus]
        ys = [centroids[m][1] for m in mgus]
        lgu_centroids[lgu] = (sum(xs) / len(xs), sum(ys) / len(ys))

    routes_rows, legs_rows = [], []
    seen_pool_lines: set[str] = set()
    lines_rows: list[dict] = []

    def add_line(line_id: str) -> None:
        if line_id in seen_pool_lines:
            return
        seen_pool_lines.add(line_id)
        lines_rows.append({
            "line_id": line_id,
            "source": "synthetic_bus_pool",
            "mode": "bus",
            "carriages": 1,
            "capacity_per_carriage": 50,
            "frequency_peak": 0,   # pool, not a timetabled line
            "n_stops": 1,
        })

    # Sort once for deterministic output.
    sorted_lgus = sorted(lgu_to_mgus)
    sorted_mgus_by_lgu = {lgu: sorted(lgu_to_mgus[lgu]) for lgu in sorted_lgus}

    # -------- Pass 1: within-LGU (per-origin-MGU pools) ---------------------
    for lgu in sorted_lgus:
        mgus = sorted_mgus_by_lgu[lgu]
        for o in mgus:
            line_id = f"bus_pool_{o}"
            add_line(line_id)
            ox, oy = centroids[o]
            for d in mgus:
                dx, dy = centroids[d]
                t = time_min(math.hypot(dx - ox, dy - oy),
                             avg_speed_kmh, min_min, max_min)
                routes_rows.append({
                    "origin_mgu": o, "dest_mgu": d, "mode_class": "bus",
                    "n_legs": 1, "total_time_min": float(t),
                })
                legs_rows.append({
                    "origin_mgu": o, "dest_mgu": d, "mode_class": "bus",
                    "leg_idx": 0, "line_id": line_id,
                    "board_mgu": o, "alight_mgu": d,
                    "t_board_min": 0, "t_alight_min": t,
                })

    # -------- Pass 2: cross-LGU (per-LGU-pair pools) ------------------------
    radius_m = cross_lgu_radius_km * 1000.0
    n_within = len(routes_rows)
    cross_lgu_pairs_emitted = 0
    for o_lgu in sorted_lgus:
        oc = lgu_centroids[o_lgu]
        for d_lgu in sorted_lgus:
            if d_lgu == o_lgu:
                continue
            dc = lgu_centroids[d_lgu]
            if math.hypot(dc[0] - oc[0], dc[1] - oc[1]) > radius_m:
                continue
            cross_lgu_pairs_emitted += 1
            line_id = f"bus_pool_lgu_{_sanitize_lgu(o_lgu)}__{_sanitize_lgu(d_lgu)}"
            add_line(line_id)
            o_mgus = sorted_mgus_by_lgu[o_lgu]
            d_mgus = sorted_mgus_by_lgu[d_lgu]
            for o in o_mgus:
                ox, oy = centroids[o]
                for d in d_mgus:
                    dx, dy = centroids[d]
                    t = time_min(math.hypot(dx - ox, dy - oy),
                                 avg_speed_kmh, min_min, max_min)
                    routes_rows.append({
                        "origin_mgu": o, "dest_mgu": d, "mode_class": "bus",
                        "n_legs": 1, "total_time_min": float(t),
                    })
                    legs_rows.append({
                        "origin_mgu": o, "dest_mgu": d, "mode_class": "bus",
                        "leg_idx": 0, "line_id": line_id,
                        "board_mgu": o, "alight_mgu": d,
                        "t_board_min": 0, "t_alight_min": t,
                    })
    print(f"  within-LGU rows : {n_within:,}")
    print(f"  cross-LGU pairs : {cross_lgu_pairs_emitted:,} "
          f"(LGU centroids within {cross_lgu_radius_km:g} km)")
    print(f"  cross-LGU rows  : {len(routes_rows) - n_within:,}")
    return routes_rows, legs_rows, lines_rows


def merge_strip_existing_bus(target_csv: Path, new_rows: list[dict]) -> int:
    """Read target_csv, drop mode-class=bus (or mode=bus for lines.csv) rows,
    append new_rows, write back. Returns the row count written."""
    existing = pd.read_csv(target_csv)
    # Strip rows that match a previous bus generation, so the script is
    # idempotent. lines.csv has `mode` instead of `mode_class`.
    if "mode_class" in existing.columns:
        existing = existing[existing["mode_class"] != "bus"]
    elif "mode" in existing.columns:
        existing = existing[existing["mode"] != "bus"]
    combined = pd.concat([existing, pd.DataFrame(new_rows, columns=existing.columns)],
                         ignore_index=True)
    combined.to_csv(target_csv, index=False)
    return len(combined)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hierarchy", default="data/geography/hierarchy.csv")
    ap.add_argument("--centroids",
                    default="/Users/marthacorrea/june2/data/domain_decomposition/2021/mgu_centroids.csv")
    ap.add_argument("--routes", default="data/transport/routes.csv")
    ap.add_argument("--legs",   default="data/transport/route_legs.csv")
    ap.add_argument("--lines",  default="data/transport/lines.csv")
    ap.add_argument("--avg-speed-kmh", type=float, default=DEFAULT_AVG_SPEED_KMH)
    ap.add_argument("--min-min", type=int, default=DEFAULT_MIN_MIN)
    ap.add_argument("--max-min", type=int, default=DEFAULT_MAX_MIN)
    ap.add_argument("--cross-lgu-radius-km", type=float,
                    default=DEFAULT_CROSS_LGU_RADIUS_KM,
                    help="LGU-centroid distance threshold for emitting "
                         "cross-LGU MGU-pair rows. Set to 0 to disable "
                         "cross-LGU pools entirely.")
    args = ap.parse_args()

    hierarchy = Path(args.hierarchy)
    centroids = Path(args.centroids)
    routes = Path(args.routes)
    legs = Path(args.legs)
    lines = Path(args.lines)

    print(f"Loading hierarchy : {hierarchy}")
    mgu_to_lgu = load_mgu_to_lgu(hierarchy)
    print(f"  {len(mgu_to_lgu):,} MGUs across {len(set(mgu_to_lgu.values())):,} LGUs")
    print(f"Loading centroids : {centroids}")
    coords = load_centroids(centroids)
    print(f"  {len(coords):,} MGU centroids (BNG)")

    print(f"Building synthetic bus pseudo-routes "
          f"(avg {args.avg_speed_kmh} km/h, clamp [{args.min_min}, {args.max_min}] min)...")
    routes_rows, legs_rows, lines_rows = build_bus_rows(
        mgu_to_lgu, coords, args.avg_speed_kmh, args.min_min, args.max_min,
        args.cross_lgu_radius_km,
    )
    print(f"  {len(routes_rows):,} bus routes  ({len(lines_rows):,} bus_pool venues)")
    print(f"  {len(legs_rows):,} bus legs    (one per route — all 1-leg)")

    print(f"Appending to {routes}, {legs}, {lines} ...")
    rn = merge_strip_existing_bus(routes, routes_rows)
    ln = merge_strip_existing_bus(legs, legs_rows)
    sn = merge_strip_existing_bus(lines, lines_rows)
    print(f"  routes.csv     : {rn:,} rows total")
    print(f"  route_legs.csv : {ln:,} rows total")
    print(f"  lines.csv      : {sn:,} rows total")


if __name__ == "__main__":
    main()
