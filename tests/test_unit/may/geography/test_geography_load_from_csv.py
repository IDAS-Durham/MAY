"""
End-to-end coverage for Geography.load_from_csv that mirrors the production
flow logged when running create_world.py with a 4-level config and an LGU
filter (SGU/MGU/LGU/XLGU). The existing test suite only exercised a 3-level,
unfiltered, no-coordinate path, so none of the filter/coord/multi-level
branches the real run depends on were verified.

Each test builds its own fixture so failures point at one concrete behavior.
"""

import logging
import os

import pytest

from may.config_loader import setup_geography
from may.geography import Geography


LEVELS_4 = ["SGU", "MGU", "LGU", "XLGU"]


def _write_csv(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(",".join(str(c) for c in row) + "\n")


@pytest.fixture
def four_level_geo_dir(tmp_path):
    """
    Build a 4-level fixture shaped like the production data:
      - 1 XLGU
      - 3 LGUs (so a filter is meaningful)
      - 2 MGUs per LGU
      - 2 SGUs per MGU
    Pre-filter totals: 12 SGU, 6 MGU, 3 LGU, 1 XLGU.
    Coord files exist for SGU and MGU only (LGU/XLGU intentionally missing).
    """
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()

    xlgu = "Country"
    lgus = ["L_keep1", "L_keep2", "L_drop"]
    rows = [LEVELS_4]
    sgu_idx = 0
    for lgu in lgus:
        for m in range(2):
            mgu = f"{lgu}_M{m}"
            for _ in range(2):
                sgu = f"S{sgu_idx:03d}"
                sgu_idx += 1
                rows.append([sgu, mgu, lgu, xlgu])
    _write_csv(geo_dir / "hierarchy.csv", rows)

    sgu_coords = [["SGU", "latitude", "longitude"]]
    for r in rows[1:]:
        sgu_coords.append([r[0], 50.0 + len(sgu_coords) * 0.01, -1.0])
    _write_csv(geo_dir / "coord_sgu.csv", sgu_coords)

    mgu_names = sorted({r[1] for r in rows[1:]})
    mgu_coords = [["MGU", "latitude", "longitude"]]
    for i, name in enumerate(mgu_names):
        mgu_coords.append([name, 51.0 + i * 0.1, -2.0])
    _write_csv(geo_dir / "coord_mgu.csv", mgu_coords)

    return str(geo_dir)


# ---------------------------------------------------------------------------
# Filter pipeline
# ---------------------------------------------------------------------------

def test_lgu_filter_reduces_hierarchy_and_per_level_counts(four_level_geo_dir):
    """LGU filter selects 2 of 3 LGUs; downstream level counts match exactly."""
    geo = Geography(
        data_dir=four_level_geo_dir,
        levels=LEVELS_4,
        filters={"level": "LGU", "codes": ["L_keep1", "L_keep2"]},
    )
    geo.load_from_csv()

    assert len(geo.get_units_by_level("SGU")) == 8
    assert len(geo.get_units_by_level("MGU")) == 4
    assert len(geo.get_units_by_level("LGU")) == 2
    assert len(geo.get_units_by_level("XLGU")) == 1
    # No L_drop unit, and none of its MGUs/SGUs were created
    assert geo.get_unit("L_drop") is None
    assert geo.get_unit("L_drop_M0") is None


def test_total_units_equals_sum_of_levels(four_level_geo_dir):
    """units_by_id is the source of truth for total count; equals per-level sum."""
    geo = Geography(
        data_dir=four_level_geo_dir,
        levels=LEVELS_4,
        filters={"level": "LGU", "codes": ["L_keep1", "L_keep2"]},
    )
    geo.load_from_csv()

    per_level = sum(len(geo.get_units_by_level(l)) for l in LEVELS_4)
    assert len(geo.units_by_id) == per_level == 15


def test_filter_level_not_in_hierarchy_raises(tmp_path):
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(geo_dir / "hierarchy.csv", [["SGU", "MGU"], ["a", "b"]])

    geo = Geography(
        data_dir=str(geo_dir),
        levels=["SGU", "MGU"],
        filters={"level": "LGU", "codes": ["x"]},
    )
    with pytest.raises(ValueError, match="LGU"):
        geo.load_from_csv()


def test_empty_filter_codes_loads_everything(four_level_geo_dir):
    """An explicit empty codes list must not silently drop all rows."""
    geo = Geography(
        data_dir=four_level_geo_dir,
        levels=LEVELS_4,
        filters={"level": "LGU", "codes": []},
    )
    geo.load_from_csv()
    assert len(geo.get_units_by_level("LGU")) == 3


# ---------------------------------------------------------------------------
# Coordinate loading
# ---------------------------------------------------------------------------

def test_coordinates_assigned_for_levels_with_coord_files(four_level_geo_dir):
    geo = Geography(data_dir=four_level_geo_dir, levels=LEVELS_4)
    geo.load_from_csv()

    for unit in geo.get_units_by_level("SGU").values():
        assert unit.coordinates is not None
        assert len(unit.coordinates) == 2
    for unit in geo.get_units_by_level("MGU").values():
        assert unit.coordinates is not None


def test_missing_coord_file_warns_and_leaves_coordinates_none(
    four_level_geo_dir, caplog
):
    """LGU and XLGU have no coord file → one warning each, coords stay None."""
    geo = Geography(data_dir=four_level_geo_dir, levels=LEVELS_4)
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("No coordinate file found for LGU" in m for m in warning_msgs)
    assert any("No coordinate file found for XLGU" in m for m in warning_msgs)

    for unit in geo.get_units_by_level("LGU").values():
        assert unit.coordinates is None
    for unit in geo.get_units_by_level("XLGU").values():
        assert unit.coordinates is None


# ---------------------------------------------------------------------------
# Hierarchy correctness
# ---------------------------------------------------------------------------

def test_ancestor_chain_spans_all_four_levels(four_level_geo_dir):
    geo = Geography(
        data_dir=four_level_geo_dir,
        levels=LEVELS_4,
        filters={"level": "LGU", "codes": ["L_keep1"]},
    )
    geo.load_from_csv()

    sgu = next(iter(geo.get_units_by_level("SGU").values()))
    assert sgu.get_ancestor_by_level("MGU") is not None
    assert sgu.get_ancestor_by_level("LGU").name == "L_keep1"
    assert sgu.get_ancestor_by_level("XLGU").name == "Country"


def test_roots_are_top_level_units_only(four_level_geo_dir):
    geo = Geography(data_dir=four_level_geo_dir, levels=LEVELS_4)
    geo.load_from_csv()

    roots = geo.get_roots()
    assert len(roots) == 1
    assert roots[0].level == "XLGU"


def test_unique_sequential_ids_across_all_levels(four_level_geo_dir):
    geo = Geography(data_dir=four_level_geo_dir, levels=LEVELS_4)
    geo.load_from_csv()

    ids = [u.id for u in geo.units_by_id.values()]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == list(range(len(ids)))


# ---------------------------------------------------------------------------
# Data-quality regressions (these covered real bugs surfaced by the audit)
# ---------------------------------------------------------------------------

def test_blank_or_nan_hierarchy_rows_are_dropped_with_warning(tmp_path, caplog):
    """A blank cell used to silently create a unit literally named 'nan'."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["A", "M1", "L1"], ["B", "", "L1"], ["C", "M2", ""]],
    )

    geo = Geography(data_dir=str(geo_dir), levels=["SGU", "MGU", "LGU"])
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    assert geo.get_unit("B") is None
    assert geo.get_unit("C") is None
    assert "nan" not in geo.units
    assert any(
        "Dropping" in r.message and "blank/NaN" in r.message
        for r in caplog.records
    )


def test_cross_level_name_collision_warns(tmp_path, caplog):
    """A name appearing at two levels must warn, not silently shadow."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["foo", "bar", "baz"], ["bar", "bar", "baz"]],
    )

    geo = Geography(data_dir=str(geo_dir), levels=["SGU", "MGU", "LGU"])
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    # Both 'bar' units exist; only the by-id index proves it.
    assert len(geo.units_by_id) == 4
    assert any(
        "Name collision across levels" in r.message and "'bar'" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Geography object semantics (previously broken)
# ---------------------------------------------------------------------------

def test_geography_is_hashable(four_level_geo_dir):
    """__hash__ used to raise TypeError because levels was an unhashable list."""
    geo = Geography(data_dir=four_level_geo_dir, levels=LEVELS_4)
    assert isinstance(hash(geo), int)
    assert {geo} == {geo}


def test_geography_equality_against_non_geography_is_false():
    """__eq__ used to raise AttributeError on non-Geography input."""
    geo = Geography(data_dir="x", levels=["SGU", "MGU"])
    assert (geo == None) is False  # noqa: E711
    assert (geo == "string") is False
    assert (geo == 123) is False


# ---------------------------------------------------------------------------
# setup_geography wiring
# ---------------------------------------------------------------------------

def test_setup_geography_passes_levels_and_filter_through(four_level_geo_dir):
    """The 4-level config + LGU filter path was not exercised by any test."""
    config = {
        "geography": {
            "data_dir": four_level_geo_dir,
            "levels": LEVELS_4,
            "filter": {"level": "LGU", "codes": ["L_keep1", "L_keep2"]},
        }
    }

    class _Args:
        load_all = False
        lgu = lgu_file = mgu = mgu_file = sgu = sgu_file = None

    geo, filters = setup_geography(args=_Args(), config=config)
    assert geo.levels == LEVELS_4
    assert filters == {"level": "LGU", "codes": ["L_keep1", "L_keep2"]}

    geo.load_from_csv()
    assert len(geo.get_units_by_level("LGU")) == 2
    assert len(geo.get_units_by_level("XLGU")) == 1


# ---------------------------------------------------------------------------
# Coord pre-filtering and column validation
# ---------------------------------------------------------------------------

def test_coord_loading_restricted_to_post_filter_names(tmp_path, caplog):
    """
    Coord rows for filtered-out units must not be loaded. Otherwise a 2-LGU
    run reads 239k SGU coords for nothing — a real cost on the production
    dataset.
    """
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["a", "M1", "L_keep"], ["b", "M2", "L_drop"]],
    )
    _write_csv(
        geo_dir / "coord_sgu.csv",
        [["SGU", "latitude", "longitude"], ["a", 1.0, 2.0], ["b", 3.0, 4.0]],
    )

    geo = Geography(
        data_dir=str(geo_dir),
        levels=["SGU", "MGU", "LGU"],
        filters={"level": "LGU", "codes": ["L_keep"]},
    )
    with caplog.at_level(logging.INFO, logger="geography"):
        geo.load_from_csv()

    # Only 'a' should have been read from the coord file
    assert any("Loaded 1 coordinates for SGU" in r.message for r in caplog.records)
    assert geo.get_unit("a").coordinates == (1.0, 2.0)


def test_coord_file_missing_required_columns_raises(tmp_path):
    """A typo in the coord header used to surface as a mid-load KeyError."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU"], ["a", "M1"]],
    )
    _write_csv(
        geo_dir / "coord_sgu.csv",
        [["SGU", "lat", "lon"], ["a", 1.0, 2.0]],  # wrong column names
    )

    geo = Geography(data_dir=str(geo_dir), levels=["SGU", "MGU"])
    with pytest.raises(ValueError, match="latitude.*longitude|longitude.*latitude"):
        geo.load_from_csv()


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

def test_get_geo_unit_alias_is_removed():
    """The redundant alias was deleted; only get_unit remains."""
    geo = Geography(data_dir="x", levels=["SGU"])
    assert not hasattr(geo, "get_geo_unit")
