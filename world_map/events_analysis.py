"""Load and enrich simulation events from HDF5 into analysis-ready pandas DataFrames.

This module reads infection, death, and symptom-change events from a
``simulation_events.h5`` file produced by the MAY framework, then joins each
event row with full person metadata, venue metadata, and (optionally) geographic
coordinates sourced from a ``world_state.h5`` file.

The main entry point is ``load_events_dataframe``, which returns a dict of
DataFrames keyed by event type plus an ``'all'`` key containing a concatenated
view across all types.

Example:
    Basic usage — load all event types with geo enrichment:

    >>> from events_analysis import load_events_dataframe
    >>> dfs = load_events_dataframe(
    ...     "data/simulation_events_5_mar_whole_world.h5",
    ...     world_state_path="data/world_state_medieval_updated.h5",
    ... )
    >>> print(dfs.keys())           # dict_keys(['infections', 'deaths', 'symptom_changes', 'all'])
    >>> print(dfs["all"].shape)
    >>> print(dfs["all"]["event_type"].value_counts())

    Load only infections, without per-person properties (faster):

    >>> dfs = load_events_dataframe(
    ...     "data/simulation_events_5_mar_whole_world.h5",
    ...     world_state_path="data/world_state_medieval_updated.h5",
    ...     event_types=["infections"],
    ...     include_person_properties=False,
    ... )
    >>> inf = dfs["infections"]
    >>> print(inf.columns.tolist())
    >>> # Infections by encounter type
    >>> print(inf["encounter_type"].value_counts())
    >>> # Average infector age per venue type
    >>> print(inf.groupby("venue_type")["infector_age"].mean().sort_values())

    Load without geo enrichment (no world_state.h5 required):

    >>> dfs = load_events_dataframe("data/simulation_events_5_mar_whole_world.h5")
    >>> print(dfs["deaths"][["person_id", "time", "person_age", "person_sex"]].head())
"""

from __future__ import annotations

from typing import Optional

import h5py
import numpy as np
import pandas as pd

from geo_units_dataframe import load_geo_units_dataframe

# Canonical order used when iterating over event types.
ALL_EVENT_TYPES = ["infections", "deaths", "symptom_changes"]


def _decode_bytes(series: pd.Series) -> pd.Series:
    """Decode a Series of byte strings to Python str.

    HDF5 fixed-length string datasets are read as ``bytes`` by h5py. This
    helper converts them to ``str`` while leaving non-bytes values untouched.

    Args:
        series: A pandas Series that may contain ``bytes`` objects.

    Returns:
        The same Series with all ``bytes`` values decoded to ``str`` via UTF-8.
    """
    if series.dtype == object or series.dtype.kind == "S":
        return series.apply(lambda v: v.decode() if isinstance(v, bytes) else v)
    return series


def _load_person_lookup(
    f: h5py.File,
    geo_df: Optional[pd.DataFrame],
    include_properties: bool,
) -> pd.DataFrame:
    """Build a person lookup DataFrame from the HDF5 people table.

    Reads ``lookups/people``, decodes byte strings, optionally appends dynamic
    per-person properties from ``lookups/people_properties/*``, and optionally
    joins geographic metadata from ``geo_df``.

    All columns except ``person_id`` are prefixed with ``person_`` so that
    merged event DataFrames have unambiguous column names. Dynamic property
    columns are prefixed with ``person_prop_`` instead.

    Args:
        f: An open h5py File handle for the simulation_events.h5.
        geo_df: Optional geo-unit DataFrame from
            ``load_geo_units_dataframe``; if provided, attaches
            ``person_geo_unit_name``, ``person_geo_lat``, ``person_geo_lon``,
            ``person_geo_population``, and ``person_geo_unit_level`` columns.
        include_properties: If ``True``, reads every dataset under
            ``lookups/people_properties/`` and attaches it as a
            ``person_prop_{key}`` column.

    Returns:
        A DataFrame indexed implicitly by row, with ``person_id`` as a plain
        column, ready to be merged on ``person_id``.
    """
    raw = f["lookups/people"][:]
    df = pd.DataFrame(raw)

    # Decode any byte-string columns (e.g. sex, schedule_type).
    for col in df.columns:
        if df[col].dtype.kind == "S" or df[col].dtype == object:
            df[col] = _decode_bytes(df[col])

    if include_properties and "lookups/people_properties" in f:
        for key in f["lookups/people_properties"].keys():
            df[f"person_prop_{key}"] = f[f"lookups/people_properties/{key}"][:]

    if geo_df is not None:
        # Pull only the columns we want and rename them before merging so that
        # the final column names already carry the person_ prefix.
        geo_cols = {
            "geo_unit_id": "geo_unit_id",
            "geo_unit_name": "person_geo_unit_name",
            "lat": "person_geo_lat",
            "lon": "person_geo_lon",
            "population": "person_geo_population",
            "geo_unit_level": "person_geo_unit_level",
        }
        geo_sub = geo_df[list(geo_cols.keys())].rename(columns=geo_cols)
        df = df.merge(
            geo_sub,
            left_on="geo_unit_id",
            right_on="geo_unit_id",
            how="left",
        )

    # Add person_ prefix to all plain columns that don't already have it.
    rename = {}
    for col in df.columns:
        if col == "person_id":
            continue
        if col.startswith("person_prop_"):
            continue
        if not col.startswith("person_"):
            rename[col] = f"person_{col}"
    df.rename(columns=rename, inplace=True)

    return df


def _load_venue_lookup(
    f: h5py.File,
    geo_df: Optional[pd.DataFrame],
) -> pd.DataFrame:
    """Build a venue lookup DataFrame from the HDF5 venues table.

    Reads ``lookups/venues``, decodes byte strings for ``name`` and ``type``,
    and optionally joins geographic coordinates from ``geo_df``.

    All columns except ``venue_id`` are prefixed with ``venue_``.

    Note:
        ``venue_id = -999`` is the infection seed sentinel value. Because the
        merge is a left join, seed-infection rows will have ``NaN`` for all
        ``venue_*`` columns, which is the intended behaviour.

    Args:
        f: An open h5py File handle for the simulation_events.h5.
        geo_df: Optional geo-unit DataFrame; if provided, attaches
            ``venue_geo_unit_name``, ``venue_geo_lat``, and ``venue_geo_lon``.

    Returns:
        A DataFrame with ``venue_id`` and prefixed venue metadata columns.
    """
    raw = f["lookups/venues"][:]
    df = pd.DataFrame(raw)

    for col in ("name", "type"):
        if col in df.columns:
            df[col] = _decode_bytes(df[col])

    if geo_df is not None:
        geo_cols = {
            "geo_unit_id": "geo_unit_id",
            "geo_unit_name": "venue_geo_unit_name",
            "lat": "venue_geo_lat",
            "lon": "venue_geo_lon",
        }
        geo_sub = geo_df[list(geo_cols.keys())].rename(columns=geo_cols)
        df = df.merge(
            geo_sub,
            left_on="geo_unit_id",
            right_on="geo_unit_id",
            how="left",
        )

    rename = {}
    for col in df.columns:
        if col == "venue_id":
            continue
        if not col.startswith("venue_"):
            rename[col] = f"venue_{col}"
    df.rename(columns=rename, inplace=True)

    return df


def _decode_encounter_type(
    encounter_type_ids: np.ndarray, registry: list[str]
) -> pd.Series:
    """Decode integer encounter type IDs to human-readable strings.

    The sentinel value ``255`` represents an unknown or unset encounter type
    and is decoded to the string ``'unknown'``. All other values are used as
    indices into the ``registry`` list read from
    ``metadata/registries/encounter_types``.

    Args:
        encounter_type_ids: 1-D integer array of raw encounter type IDs.
        registry: Ordered list of encounter type name strings, e.g.
            ``['romantic_encounter', 'social']``.

    Returns:
        A string Series of the same length as ``encounter_type_ids``.
    """
    def decode(v):
        if v == 255:
            return "unknown"
        try:
            return registry[v]
        except IndexError:
            return "unknown"

    return pd.Series([decode(v) for v in encounter_type_ids], dtype="object")


def _build_infections_df(
    f: h5py.File,
    person_df: pd.DataFrame,
    venue_df: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble the enriched infections DataFrame.

    Reads ``events/infections``, decodes the encounter type, then performs
    three merges:

    1. ``person_id`` → full ``person_*`` columns for the infected person.
    2. ``infector_id`` → a subset of person columns re-prefixed as
       ``infector_age``, ``infector_sex``, ``infector_geo_unit_id``,
       ``infector_schedule_type``.
    3. ``venue_id`` → full ``venue_*`` columns.

    Args:
        f: An open h5py File handle for the simulation_events.h5.
        person_df: Pre-built person lookup DataFrame.
        venue_df: Pre-built venue lookup DataFrame.

    Returns:
        One row per infection event with all enriched columns and
        ``event_type = 'infections'``.
    """
    raw = f["events/infections"][:]
    df = pd.DataFrame(raw)

    registry = [
        s.decode() if isinstance(s, bytes) else s
        for s in f["metadata/registries/encounter_types"][:]
    ]
    df["encounter_type"] = _decode_encounter_type(
        df["encounter_type_id"].values, registry
    )
    df.drop(columns=["encounter_type_id"], inplace=True)

    df = df.merge(person_df, on="person_id", how="left")

    # Build a slim infector lookup using only the most useful person columns.
    infector_cols = [
        "person_id",
        "person_age",
        "person_sex",
        "person_geo_unit_id",
        "person_schedule_type",
    ]
    available_infector_cols = [c for c in infector_cols if c in person_df.columns]
    infector_sub = person_df[available_infector_cols].copy()
    infector_rename = {"person_id": "infector_id"}
    for col in available_infector_cols:
        if col != "person_id":
            infector_rename[col] = col.replace("person_", "infector_", 1)
    infector_sub.rename(columns=infector_rename, inplace=True)

    df = df.merge(infector_sub, on="infector_id", how="left")
    df = df.merge(venue_df, on="venue_id", how="left")
    df["event_type"] = "infections"
    return df


def _build_deaths_df(
    f: h5py.File,
    person_df: pd.DataFrame,
    venue_df: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble the enriched deaths DataFrame.

    Reads ``events/deaths`` and merges person and venue metadata.

    Args:
        f: An open h5py File handle for the simulation_events.h5.
        person_df: Pre-built person lookup DataFrame.
        venue_df: Pre-built venue lookup DataFrame.

    Returns:
        One row per death event with all enriched columns and
        ``event_type = 'deaths'``.
    """
    raw = f["events/deaths"][:]
    df = pd.DataFrame(raw)
    df = df.merge(person_df, on="person_id", how="left")
    df = df.merge(venue_df, on="venue_id", how="left")
    df["event_type"] = "deaths"
    return df


def _build_symptom_changes_df(
    f: h5py.File,
    person_df: pd.DataFrame,
    venue_df: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble the enriched symptom changes DataFrame.

    Reads ``events/symptom_changes``, decodes ``old_symptom`` and
    ``new_symptom`` byte strings, then merges person and venue metadata.

    Args:
        f: An open h5py File handle for the simulation_events.h5.
        person_df: Pre-built person lookup DataFrame.
        venue_df: Pre-built venue lookup DataFrame.

    Returns:
        One row per symptom-change event with all enriched columns and
        ``event_type = 'symptom_changes'``.
    """
    raw = f["events/symptom_changes"][:]
    df = pd.DataFrame(raw)

    for col in ("old_symptom", "new_symptom"):
        if col in df.columns:
            df[col] = _decode_bytes(df[col])

    df = df.merge(person_df, on="person_id", how="left")
    df = df.merge(venue_df, on="venue_id", how="left")
    df["event_type"] = "symptom_changes"
    return df


def load_events_dataframe(
    events_path: str,
    world_state_path: Optional[str] = None,
    event_types: Optional[list[str]] = None,
    include_person_properties: bool = True,
) -> dict[str, pd.DataFrame]:
    """Load simulation events from HDF5 and enrich them with person/venue metadata.

    Opens ``simulation_events.h5``, builds person and venue lookup tables, then
    assembles one enriched DataFrame per requested event type. An ``'all'`` key
    is always added containing a concatenation of all loaded event DataFrames;
    columns absent for a given event type (e.g. ``encounter_type`` in deaths)
    will be ``NaN``.

    Geo enrichment (coordinates, population, level names) requires a
    ``world_state.h5`` path. Without it, person and venue columns are still
    fully populated — only the ``*_geo_lat`` / ``*_geo_lon`` / etc. columns
    will be absent.

    Args:
        events_path: Path to the ``simulation_events.h5`` file.
        world_state_path: Optional path to ``world_state.h5``. When provided,
            adds geographic columns to both person and venue data.
        event_types: Subset of event types to load. Must be a list containing
            any combination of ``'infections'``, ``'deaths'``,
            ``'symptom_changes'``. Defaults to all three.
        include_person_properties: If ``True`` (default), reads all datasets
            under ``lookups/people_properties/`` and attaches them as
            ``person_prop_{key}`` columns. Set to ``False`` for faster loads
            when property columns are not needed.

    Returns:
        A dict with one key per requested event type plus an ``'all'`` key:

        - ``'infections'``: DataFrame with infection events and enriched columns.
        - ``'deaths'``: DataFrame with death events and enriched columns.
        - ``'symptom_changes'``: DataFrame with symptom-change events.
        - ``'all'``: ``pd.concat`` of all loaded event DataFrames.

    Example:
        >>> dfs = load_events_dataframe(
        ...     "data/simulation_events_5_mar_whole_world.h5",
        ...     world_state_path="data/world_state_medieval_updated.h5",
        ... )
        >>> inf = dfs["infections"]
        >>> # Infections by venue type
        >>> inf.groupby("venue_type").size().sort_values(ascending=False)
        >>> # Age distribution of people who died
        >>> dfs["deaths"]["person_age"].hist(bins=20)
        >>> # Symptom progression counts
        >>> sc = dfs["symptom_changes"]
        >>> sc.groupby(["old_symptom", "new_symptom"]).size()
        >>> # Events spread over simulation time
        >>> dfs["all"].groupby("event_type")["time"].describe()
    """
    requested = set(event_types) if event_types is not None else set(ALL_EVENT_TYPES)

    geo_df = None
    if world_state_path is not None:
        geo_df = load_geo_units_dataframe(world_state_path)

    with h5py.File(events_path, "r") as f:
        person_df = _load_person_lookup(f, geo_df, include_person_properties)
        venue_df = _load_venue_lookup(f, geo_df)

        builders = {
            "infections": _build_infections_df,
            "deaths": _build_deaths_df,
            "symptom_changes": _build_symptom_changes_df,
        }

        result = {}
        for name in ALL_EVENT_TYPES:
            if name in requested:
                result[name] = builders[name](f, person_df, venue_df)

    result["all"] = pd.concat(list(result.values()), ignore_index=True)
    return result
