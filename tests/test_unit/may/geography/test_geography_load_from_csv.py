"""
End-to-end coverage for Geography.load_from_csv over a 4-level config
(SGU/MGU/LGU/XLGU) with an LGU filter, exercising the filter, coordinate,
and multi-level branches.

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


def _make_geo(geo_dir, levels=LEVELS_4, coord_files=None, **kwargs):
    """Geography wired to the fixture's conventional filenames."""
    if coord_files is None:
        coord_files = {"SGU": "coord_sgu.csv", "MGU": "coord_mgu.csv"}
    return Geography(
        data_dir=str(geo_dir),
        levels=levels,
        hierarchy_file="hierarchy.csv",
        coord_files=coord_files,
        **kwargs,
    )


@pytest.fixture
def four_level_geo_dir(tmp_path):
    """
    Build a 4-level fixture shaped like the production data:
      - 1 XLGU
      - 3 LGUs (so a filter is meaningful)
      - 2 MGUs per LGU
      - 2 SGUs per MGU
    Pre-filter totals: 12 SGU, 6 MGU, 3 LGU, 1 XLGU.
    Coord files exist for SGU and MGU only (LGU/XLGU intentionally absent).
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


def test_lgu_filter_reduces_hierarchy_and_per_level_counts(four_level_geo_dir):
    """LGU filter selects 2 of 3 LGUs; downstream level counts match exactly."""
    geo = _make_geo(
        four_level_geo_dir,
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
    geo = _make_geo(
        four_level_geo_dir,
        filters={"level": "LGU", "codes": ["L_keep1", "L_keep2"]},
    )
    geo.load_from_csv()

    per_level = sum(len(geo.get_units_by_level(l)) for l in LEVELS_4)
    assert len(geo.units_by_id) == per_level == 15


def test_missing_hierarchy_file_config_raises():
    """A Geography without a configured hierarchy file must fail loud on load."""
    geo = Geography(data_dir="x", levels=["SGU", "MGU"])
    with pytest.raises(ValueError, match="hierarchy_file"):
        geo.load_from_csv()


def test_filter_level_not_in_hierarchy_raises(tmp_path):
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(geo_dir / "hierarchy.csv", [["SGU", "MGU"], ["a", "b"]])

    geo = _make_geo(
        geo_dir,
        levels=["SGU", "MGU"],
        coord_files={},
        filters={"level": "LGU", "codes": ["x"]},
    )
    with pytest.raises(ValueError, match="LGU"):
        geo.load_from_csv()


def test_empty_filter_codes_loads_everything(four_level_geo_dir):
    """An explicit empty codes list must not silently drop all rows."""
    geo = _make_geo(
        four_level_geo_dir,
        filters={"level": "LGU", "codes": []},
    )
    geo.load_from_csv()
    assert len(geo.get_units_by_level("LGU")) == 3


def test_coordinates_assigned_for_levels_with_coord_files(four_level_geo_dir):
    geo = _make_geo(four_level_geo_dir)
    geo.load_from_csv()

    for unit in geo.get_units_by_level("SGU").values():
        assert unit.coordinates is not None
        assert len(unit.coordinates) == 2
    for unit in geo.get_units_by_level("MGU").values():
        assert unit.coordinates is not None


def test_level_without_coord_entry_has_no_coordinates(four_level_geo_dir, caplog):
    """A level absent from coord_files is a declaration: coords None, no warning."""
    geo = _make_geo(four_level_geo_dir)
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    for unit in geo.get_units_by_level("LGU").values():
        assert unit.coordinates is None
    for unit in geo.get_units_by_level("XLGU").values():
        assert unit.coordinates is None


def test_coord_files_with_unknown_level_raises(four_level_geo_dir):
    geo = _make_geo(
        four_level_geo_dir,
        coord_files={"BLOCK": "coord_sgu.csv"},
    )
    with pytest.raises(ValueError, match="BLOCK"):
        geo.load_from_csv()


def test_ancestor_chain_spans_all_four_levels(four_level_geo_dir):
    geo = _make_geo(
        four_level_geo_dir,
        filters={"level": "LGU", "codes": ["L_keep1"]},
    )
    geo.load_from_csv()

    sgu = next(iter(geo.get_units_by_level("SGU").values()))
    assert sgu.get_ancestor_by_level("MGU") is not None
    assert sgu.get_ancestor_by_level("LGU").name == "L_keep1"
    assert sgu.get_ancestor_by_level("XLGU").name == "Country"


def test_roots_are_top_level_units_only(four_level_geo_dir):
    geo = _make_geo(four_level_geo_dir)
    geo.load_from_csv()

    roots = geo.get_roots()
    assert len(roots) == 1
    assert roots[0].level == "XLGU"


def test_unique_sequential_ids_across_all_levels(four_level_geo_dir):
    geo = _make_geo(four_level_geo_dir)
    geo.load_from_csv()

    ids = [u.id for u in geo.units_by_id.values()]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == list(range(len(ids)))


def test_blank_or_nan_hierarchy_rows_are_dropped_with_warning(tmp_path, caplog):
    """A blank/NaN hierarchy cell is dropped with a warning, not turned into a unit named 'nan'."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["A", "M1", "L1"], ["B", "", "L1"], ["C", "M2", ""]],
    )

    geo = _make_geo(geo_dir, levels=["SGU", "MGU", "LGU"], coord_files={})
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    assert geo.get_unit("B") is None
    assert geo.get_unit("C") is None
    assert "nan" not in geo.units
    assert any(
        "Dropping" in r.message and "blank/NaN" in r.message
        for r in caplog.records
    )


def test_child_with_two_parents_raises(tmp_path):
    """The same unit under two different parents is a hard error, not first-wins."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["a", "M1", "L1"], ["b", "M1", "L2"]],
    )

    geo = _make_geo(geo_dir, levels=["SGU", "MGU", "LGU"], coord_files={})
    with pytest.raises(ValueError, match="more than one LGU parent"):
        geo.load_from_csv()


def test_cross_level_name_collision_warns(tmp_path, caplog):
    """A name appearing at two levels must warn, not silently shadow."""
    geo_dir = tmp_path / "geography"
    geo_dir.mkdir()
    _write_csv(
        geo_dir / "hierarchy.csv",
        [["SGU", "MGU", "LGU"], ["foo", "bar", "baz"], ["bar", "bar", "baz"]],
    )

    geo = _make_geo(geo_dir, levels=["SGU", "MGU", "LGU"], coord_files={})
    with caplog.at_level(logging.WARNING, logger="geography"):
        geo.load_from_csv()

    # Both 'bar' units exist; only the by-id index proves it.
    assert len(geo.units_by_id) == 4
    assert any(
        "Name collision across levels" in r.message and "'bar'" in r.message
        for r in caplog.records
    )


def test_geography_is_hashable(four_level_geo_dir):
    """Geography is hashable even though its levels attribute is a list."""
    geo = _make_geo(four_level_geo_dir)
    assert isinstance(hash(geo), int)
    assert {geo} == {geo}


def test_geography_equality_against_non_geography_is_false():
    """Geography compares unequal to non-Geography objects instead of raising."""
    geo = Geography(data_dir="x", levels=["SGU", "MGU"])
    assert (geo == None) is False  # noqa: E711
    assert (geo == "string") is False
    assert (geo == 123) is False


def test_setup_geography_passes_levels_filter_and_files_through(four_level_geo_dir):
    """setup_geography passes levels, filter, and the explicit file keys through."""
    config = {
        "geography": {
            "data_dir": four_level_geo_dir,
            "levels": LEVELS_4,
            "hierarchy_file": "hierarchy.csv",
            "coord_files": {"SGU": "coord_sgu.csv", "MGU": "coord_mgu.csv"},
            "filter": {"level": "LGU", "codes": ["L_keep1", "L_keep2"]},
        }
    }

    geo, filters = setup_geography(config=config)
    assert geo.levels == LEVELS_4
    assert filters == {"level": "LGU", "codes": ["L_keep1", "L_keep2"]}

    geo.load_from_csv()
    assert len(geo.get_units_by_level("LGU")) == 2
    assert len(geo.get_units_by_level("XLGU")) == 1
    sgu = next(iter(geo.get_units_by_level("SGU").values()))
    assert sgu.coordinates is not None


def test_coord_loading_restricted_to_post_filter_names(tmp_path, caplog):
    """
    Coord rows for filtered-out units must not be loaded. Otherwise a 2-LGU
    run reads 239k SGU coords for nothing, a real cost on the production
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

    geo = _make_geo(
        geo_dir,
        levels=["SGU", "MGU", "LGU"],
        coord_files={"SGU": "coord_sgu.csv"},
        filters={"level": "LGU", "codes": ["L_keep"]},
    )
    with caplog.at_level(logging.INFO, logger="geography"):
        geo.load_from_csv()

    # Only 'a' should have been read from the coord file
    assert any("Loaded 1 coordinates for SGU" in r.message for r in caplog.records)
    assert geo.get_unit("a").coordinates == (1.0, 2.0)


def test_coord_file_missing_required_columns_raises(tmp_path):
    """A coord header with wrong column names raises a clear ValueError."""
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

    geo = _make_geo(
        geo_dir, levels=["SGU", "MGU"], coord_files={"SGU": "coord_sgu.csv"}
    )
    with pytest.raises(ValueError, match="latitude.*longitude|longitude.*latitude"):
        geo.load_from_csv()


def test_get_geo_unit_alias_is_removed():
    """Only get_unit exists; there is no get_geo_unit alias."""
    geo = Geography(data_dir="x", levels=["SGU"])
    assert not hasattr(geo, "get_geo_unit")
