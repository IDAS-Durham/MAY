"""Load geographical unit metadata from a world_state.h5 file into a pandas DataFrame.

This module is a standalone helper with no Flask dependency. It reads geography
hierarchies, coordinates, level names, and population counts from a MAY framework
world_state HDF5 file and returns a single flat DataFrame suitable for merging with
event data or for standalone geographic analysis.

Example:
    >>> from geo_units_dataframe import load_geo_units_dataframe
    >>> geo_df = load_geo_units_dataframe("data/world_state_medieval_updated.h5")
    >>> print(geo_df.head())
    >>> print(f"Geo units: {len(geo_df)}, total pop: {geo_df['population'].sum()}")
    >>> # Filter to a specific level
    >>> mgus = geo_df[geo_df["geo_unit_level"] == "MGU"]
    >>> # Find the parent of a given unit
    >>> unit = geo_df[geo_df["geo_unit_name"] == "TEMP000123"].iloc[0]
    >>> parent = geo_df[geo_df["geo_unit_id"] == unit["parent_id"]]
"""

import h5py
import numpy as np
import pandas as pd


def load_geo_units_dataframe(world_state_path: str) -> pd.DataFrame:
    """Load all geographical units from a world_state HDF5 file.

    Reads geography IDs, coordinates, level names, parent relationships, and
    population counts into a single flat DataFrame. Population per unit is
    computed by counting occurrences of each geo_unit_id in
    ``population/geo_unit_ids`` using ``np.bincount``.

    Args:
        world_state_path: Absolute or relative path to the world_state.h5 file
            produced by the MAY framework.

    Returns:
        A DataFrame with one row per geographical unit and the following columns:

        - ``geo_unit_id`` (int): Integer ID used throughout the simulation.
        - ``geo_unit_name`` (str): Human-readable name (e.g. ``"TEMP000123"``).
        - ``geo_unit_level`` (str): Decoded level label (e.g. ``"SGU"``, ``"MGU"``).
        - ``lat`` (float): Latitude in decimal degrees.
        - ``lon`` (float): Longitude in decimal degrees.
        - ``population`` (int): Number of people whose home geo_unit_id matches
          this unit.
        - ``parent_id`` (int): ID of the parent unit; ``-1`` for root units.

    Example:
        >>> geo_df = load_geo_units_dataframe("data/world_state_medieval_updated.h5")
        >>> geo_df.dtypes
        geo_unit_id        int64
        geo_unit_name     object
        geo_unit_level    object
        lat              float64
        lon              float64
        population         int64
        parent_id          int64
        >>> geo_df[geo_df["population"] > 500].sort_values("population", ascending=False)
    """
    with h5py.File(world_state_path, "r") as f:
        ids = f["geography/ids"][:]
        lats = f["geography/latitudes"][:]
        lons = f["geography/longitudes"][:]
        levels = f["geography/levels"][:]
        parent_ids = f["geography/parent_ids"][:]

        # Decode the integer level codes to human-readable level names.
        level_registry = [
            s.decode() if isinstance(s, bytes) else s
            for s in f["metadata/registries/geo_levels"][:]
        ]

        names = [
            s.decode() if isinstance(s, bytes) else s
            for s in f["metadata/names/geography"][:]
        ]

        # One entry per person — counting gives population per unit.
        pop_geo_unit_ids = f["population/geo_unit_ids"][:]

    level_names = [level_registry[lv] for lv in levels]

    max_id = int(ids.max()) + 1
    pop_counts = np.bincount(pop_geo_unit_ids, minlength=max_id)
    population = [int(pop_counts[gid]) if gid < len(pop_counts) else 0 for gid in ids]

    return pd.DataFrame(
        {
            "geo_unit_id": ids.astype(int),
            "geo_unit_name": names,
            "geo_unit_level": level_names,
            "lat": lats.astype(float),
            "lon": lons.astype(float),
            "population": population,
            "parent_id": parent_ids.astype(int),
        }
    )
