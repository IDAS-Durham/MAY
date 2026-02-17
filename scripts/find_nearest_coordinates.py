"""
Find nearest geographic coordinates using the Haversine formula.

Usage:
    python scripts/find_nearest_coordinates.py --lat 51.5 --lon -0.1 --n 5
    python scripts/find_nearest_coordinates.py --lat 51.5 --lon -0.1  # returns closest
"""

import numpy as np
import pandas as pd
from typing import Tuple
import argparse


def haversine_distances(
    target_lat: float,
    target_lon: float,
    lats: np.ndarray,
    lons: np.ndarray,
    radius_km: float = 6371.0
) -> np.ndarray:
    """
    Compute Haversine distances from a target point to an array of coordinates.

    Args:
        target_lat: Target latitude in degrees
        target_lon: Target longitude in degrees
        lats: Array of latitudes in degrees
        lons: Array of longitudes in degrees
        radius_km: Earth's radius in km (default 6371)

    Returns:
        Array of distances in km
    """
    # Convert to radians
    lat1 = np.radians(target_lat)
    lon1 = np.radians(target_lon)
    lat2 = np.radians(lats)
    lon2 = np.radians(lons)

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))

    return radius_km * c


def find_nearest_indices(
    target_lat: float,
    target_lon: float,
    lats: np.ndarray,
    lons: np.ndarray,
    n: int = 1
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Find the indices of the N closest coordinates to a target location.

    Args:
        target_lat: Target latitude in degrees
        target_lon: Target longitude in degrees
        lats: Array of latitudes in degrees
        lons: Array of longitudes in degrees
        n: Number of nearest points to return

    Returns:
        Tuple of (indices, distances) sorted by distance ascending
    """
    distances = haversine_distances(target_lat, target_lon, lats, lons)

    # Use argpartition for selection of k smallest, then sort those k
    n = min(n, len(distances))
    if n == len(distances):
        indices = np.argsort(distances)
    else:
        # then we only sort the k smallest
        partition_indices = np.argpartition(distances, n)[:n]
        sorted_order = np.argsort(distances[partition_indices])
        indices = partition_indices[sorted_order]

    return indices, distances[indices]


def main():
    parser = argparse.ArgumentParser(description="Find nearest coordinates in CSV file")
    parser.add_argument("--lat", type=float, required=True, help="Target latitude")
    parser.add_argument("--lon", type=float, required=True, help="Target longitude")
    parser.add_argument("--n", type=int, default=1, help="Number of nearest points to return")
    parser.add_argument(
        "--csv",
        type=str,
        default="world_specific_code/MedievalYaml/data/geography/coord_mbd_temp_id.csv",
        help="Path to CSV file with latitude, longitude columns"
    )
    parser.add_argument("--lat-col", type=str, default="latitude", help="Latitude column name")
    parser.add_argument("--lon-col", type=str, default="longitude", help="Longitude column name")

    args = parser.parse_args()

    # Load data
    df = pd.read_csv(args.csv)
    lats = df[args.lat_col].values
    lons = df[args.lon_col].values

    # Find nearest
    indices, distances = find_nearest_indices(args.lat, args.lon, lats, lons, args.n)

    # Display results
    print(f"Target: ({args.lat}, {args.lon})")
    print(f"\n{args.n} nearest location(s):\n")

    for rank, (idx, dist) in enumerate(zip(indices, distances), 1):
        row = df.iloc[idx]
        print(f"{rank}. Index {idx}: {row.to_dict()} — {dist:.2f} km")


if __name__ == "__main__":
    main()
