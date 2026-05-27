#!/usr/bin/env python3
"""Snap transport stations to their MGU and LGU (commute-line build, plan task 5).

Takes every station from the acquired transport sources and assigns each one a
geographical unit, so the line builder can express line stops as LGU nodes
(plan D4) and the routing graph can connect lines that share an LGU.

Method (no boundary shapefiles needed):
  1. Read stations (lat/lon, WGS84) from the three acquired sources.
  2. Reproject to British National Grid (EPSG:27700) so nearest-neighbour
     distances are true metres.
  3. Snap each station to the nearest MGU (MSOA) centroid. Centroids come from
     JUNE's domain-decomposition geometry, keeping MAY lines consistent with the
     MGU partition JUNE simulates on.
  4. Map MGU -> LGU (and XLGU) via MAY's geography hierarchy. NOTE: in MAY's
     schema LGU is a *name* (e.g. "Newcastle upon Tyne"), not an ONS code.

Stations that snap farther than FAR_THRESHOLD_M are flagged (`far` column) —
typically non-GB rail stops (e.g. Paris Gare du Nord) that the GTFS includes.

Inputs:
  data/transport/{rail_gtfs/stops.txt, tfl/stations.csv, metros/stations.csv}
  <JUNE>/data/domain_decomposition/2021/mgu_centroids.csv   (BNG centroids)
  data/geography/hierarchy.csv                              (SGU,MGU,LGU,XLGU)

Output:
  data/transport/stations_to_lgu.csv
    source, station_id, name, lat, lon, mgu, lgu, xlgu, snap_dist_m, far

Usage:  python3 scripts/snap_stations_to_lgu.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSPORT = REPO_ROOT / "data" / "transport"
HIERARCHY = REPO_ROOT / "data" / "geography" / "hierarchy.csv"
CENTROIDS = Path("/Users/marthacorrea/june2/data/domain_decomposition/2021/mgu_centroids.csv")
OUT = TRANSPORT / "stations_to_lgu.csv"

FAR_THRESHOLD_M = 20_000  # snaps beyond this are flagged (likely non-GB / data gap)

# (source label, file, column map). Each source is normalised to id/name/lat/lon.
SOURCES = [
    ("rail",  TRANSPORT / "rail_gtfs" / "stops.txt",
     {"id": "stop_id", "name": "stop_name", "lat": "stop_lat", "lon": "stop_lon"}),
    ("tfl",   TRANSPORT / "tfl" / "stations.csv",
     {"id": "station_id", "name": "name", "lat": "lat", "lon": "lon"}),
    ("metro", TRANSPORT / "metros" / "stations.csv",
     {"id": "station_id", "name": "name", "lat": "lat", "lon": "lon"}),
]


def load_stations() -> pd.DataFrame:
    frames = []
    for label, path, cols in SOURCES:
        if not path.exists():
            print(f"WARN: source missing, skipping: {path}", file=sys.stderr)
            continue
        df = pd.read_csv(path, dtype={cols["id"]: str})
        df = df.rename(columns={cols["id"]: "station_id", cols["name"]: "name",
                                cols["lat"]: "lat", cols["lon"]: "lon"})
        df = df[["station_id", "name", "lat", "lon"]].copy()
        df["source"] = label
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        n0 = len(df)
        df = df.dropna(subset=["lat", "lon"])
        if len(df) < n0:
            print(f"  {label}: dropped {n0 - len(df)} rows with missing coords")
        frames.append(df)
        print(f"  {label}: {len(df)} stations")
    if not frames:
        sys.exit("ERROR: no station sources found.")
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    print("Loading stations...")
    stations = load_stations()

    print("Loading MGU centroids + hierarchy...")
    cent = pd.read_csv(CENTROIDS).rename(columns={"geo_unit": "mgu"})
    cent = cent.dropna(subset=["X", "Y"])
    hier = pd.read_csv(HIERARCHY)
    mgu2lgu = (hier[["MGU", "LGU", "XLGU"]]
               .dropna(subset=["MGU"])
               .drop_duplicates(subset=["MGU"])
               .set_index("MGU"))
    # Coverage sanity: centroids vs hierarchy MGUs
    missing = set(cent["mgu"]) - set(mgu2lgu.index)
    if missing:
        print(f"  note: {len(missing)} centroid MGUs not in hierarchy "
              f"(will yield blank LGU if snapped to)")

    # Reproject stations WGS84 -> BNG to match the centroid CRS.
    print("Reprojecting + snapping...")
    tf = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    sx, sy = tf.transform(stations["lon"].to_numpy(), stations["lat"].to_numpy())

    tree = cKDTree(cent[["X", "Y"]].to_numpy())
    dist, idx = tree.query(np.column_stack([sx, sy]), k=1)

    stations["mgu"] = cent["mgu"].to_numpy()[idx]
    stations["snap_dist_m"] = np.round(dist).astype(int)
    stations["lgu"] = stations["mgu"].map(mgu2lgu["LGU"])
    stations["xlgu"] = stations["mgu"].map(mgu2lgu["XLGU"])
    stations["far"] = stations["snap_dist_m"] > FAR_THRESHOLD_M

    cols = ["source", "station_id", "name", "lat", "lon",
            "mgu", "lgu", "xlgu", "snap_dist_m", "far"]
    stations[cols].to_csv(OUT, index=False)

    # Diagnostics
    d = stations["snap_dist_m"]
    print(f"\nDone. {len(stations)} stations -> {OUT}")
    print(f"  snap distance (m): median {int(d.median())}, "
          f"p90 {int(d.quantile(0.9))}, p99 {int(d.quantile(0.99))}, max {int(d.max())}")
    print(f"  unique LGUs touched: {stations['lgu'].nunique()}")
    print(f"  stations with blank LGU: {int(stations['lgu'].isna().sum())}")
    n_far = int(stations["far"].sum())
    print(f"  flagged far (> {FAR_THRESHOLD_M//1000} km): {n_far}")
    if n_far:
        sample = stations[stations["far"]].nlargest(5, "snap_dist_m")
        for _, r in sample.iterrows():
            print(f"      {r['source']:5s} {r['name'][:40]:40s} "
                  f"{r['snap_dist_m']/1000:.0f} km -> {r['lgu']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
