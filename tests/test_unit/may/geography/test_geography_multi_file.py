"""
Multi-file geography: several hierarchy/coordinate files stack into one world.
Covers the cross-file consistency rules (disjoint leaves, unique parentage,
disjoint coordinate names) and that a stacked load equals the single-file one.
"""

import pytest

from may.geography import Geography

LEVELS = ["SGU", "MGU", "LGU"]


def _write_csv(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(",".join(str(c) for c in row) + "\n")


@pytest.fixture
def two_nation_dir(tmp_path):
    """Two disjoint 'nations', each with its own hierarchy and SGU coords."""
    _write_csv(
        tmp_path / "hierarchy_A.csv",
        [LEVELS, ["A1", "AM1", "AL1"], ["A2", "AM1", "AL1"], ["A3", "AM2", "AL1"]],
    )
    _write_csv(
        tmp_path / "hierarchy_B.csv",
        [LEVELS, ["B1", "BM1", "BL1"], ["B2", "BM2", "BL1"]],
    )
    _write_csv(
        tmp_path / "coord_A.csv",
        [["SGU", "latitude", "longitude"], ["A1", 1.0, 1.0], ["A2", 2.0, 2.0], ["A3", 3.0, 3.0]],
    )
    _write_csv(
        tmp_path / "coord_B.csv",
        [["SGU", "latitude", "longitude"], ["B1", 4.0, 4.0], ["B2", 5.0, 5.0]],
    )
    return tmp_path


def test_stacked_nations_form_one_world(two_nation_dir):
    geo = Geography(
        data_dir=str(two_nation_dir),
        levels=LEVELS,
        hierarchy_file=["hierarchy_A.csv", "hierarchy_B.csv"],
        coord_files={"SGU": ["coord_A.csv", "coord_B.csv"]},
    )
    geo.load_from_csv()

    assert len(geo.get_units_by_level("SGU")) == 5
    assert len(geo.get_units_by_level("MGU")) == 4
    assert len(geo.get_units_by_level("LGU")) == 2
    assert geo.get_unit("A1").get_ancestor_by_level("LGU").name == "AL1"
    assert geo.get_unit("B2").get_ancestor_by_level("LGU").name == "BL1"
    assert geo.get_unit("A1").coordinates == (1.0, 1.0)
    assert geo.get_unit("B2").coordinates == (5.0, 5.0)


def test_filter_spans_files(two_nation_dir):
    """One filter can select units contributed by different files."""
    geo = Geography(
        data_dir=str(two_nation_dir),
        levels=LEVELS,
        hierarchy_file=["hierarchy_A.csv", "hierarchy_B.csv"],
        coord_files={},
        filters={"level": "MGU", "codes": ["AM1", "BM2"]},
    )
    geo.load_from_csv()

    assert set(geo.get_units_by_level("SGU")) == {"A1", "A2", "B2"}


def test_leaf_defined_in_two_files_raises(tmp_path):
    _write_csv(tmp_path / "h1.csv", [LEVELS, ["X1", "M1", "L1"]])
    _write_csv(tmp_path / "h2.csv", [LEVELS, ["X1", "M2", "L2"]])

    geo = Geography(
        data_dir=str(tmp_path),
        levels=LEVELS,
        hierarchy_file=["h1.csv", "h2.csv"],
    )
    with pytest.raises(Exception, match="X1"):
        geo.load_from_csv()


def test_shared_parent_across_files_is_allowed(tmp_path):
    """One nation split across two files: shared MGU/LGU names must work."""
    _write_csv(tmp_path / "h1.csv", [LEVELS, ["X1", "M1", "L1"]])
    _write_csv(tmp_path / "h2.csv", [LEVELS, ["X2", "M1", "L1"], ["X3", "M2", "L1"]])

    geo = Geography(
        data_dir=str(tmp_path),
        levels=LEVELS,
        hierarchy_file=["h1.csv", "h2.csv"],
    )
    geo.load_from_csv()

    assert len(geo.get_units_by_level("SGU")) == 3
    assert len(geo.get_units_by_level("MGU")) == 2
    assert len(geo.get_units_by_level("LGU")) == 1
    assert {c.name for c in geo.get_unit("M1").children} == {"X1", "X2"}


def test_conflicting_parent_across_files_raises(tmp_path):
    """The same MGU under two different LGUs in different files must fail."""
    _write_csv(tmp_path / "h1.csv", [LEVELS, ["X1", "M1", "L1"]])
    _write_csv(tmp_path / "h2.csv", [LEVELS, ["X2", "M1", "L2"]])

    geo = Geography(
        data_dir=str(tmp_path),
        levels=LEVELS,
        hierarchy_file=["h1.csv", "h2.csv"],
    )
    with pytest.raises(ValueError, match="more than one LGU parent"):
        geo.load_from_csv()


def test_hierarchy_files_with_different_columns_raise(tmp_path):
    _write_csv(tmp_path / "h1.csv", [LEVELS, ["X1", "M1", "L1"]])
    _write_csv(tmp_path / "h2.csv", [["SGU", "MGU"], ["X2", "M2"]])

    geo = Geography(
        data_dir=str(tmp_path),
        levels=LEVELS,
        hierarchy_file=["h1.csv", "h2.csv"],
    )
    with pytest.raises(Exception, match="column"):
        geo.load_from_csv()


def test_coord_unit_in_two_files_raises(two_nation_dir):
    _write_csv(
        two_nation_dir / "coord_dup.csv",
        [["SGU", "latitude", "longitude"], ["A1", 9.0, 9.0]],
    )
    geo = Geography(
        data_dir=str(two_nation_dir),
        levels=LEVELS,
        hierarchy_file=["hierarchy_A.csv", "hierarchy_B.csv"],
        coord_files={"SGU": ["coord_A.csv", "coord_dup.csv"]},
    )
    with pytest.raises(ValueError, match="A1"):
        geo.load_from_csv()


def test_stacked_load_matches_single_file_load(tmp_path, two_nation_dir):
    """Stacking two files gives the same units and tree as one merged file."""
    merged = [LEVELS,
              ["A1", "AM1", "AL1"], ["A2", "AM1", "AL1"], ["A3", "AM2", "AL1"],
              ["B1", "BM1", "BL1"], ["B2", "BM2", "BL1"]]
    _write_csv(tmp_path / "merged.csv", merged)

    stacked = Geography(
        data_dir=str(two_nation_dir),
        levels=LEVELS,
        hierarchy_file=["hierarchy_A.csv", "hierarchy_B.csv"],
    )
    stacked.load_from_csv()
    single = Geography(
        data_dir=str(tmp_path),
        levels=LEVELS,
        hierarchy_file="merged.csv",
    )
    single.load_from_csv()

    assert set(stacked.units) == set(single.units)
    for name, unit in stacked.units.items():
        other = single.get_unit(name)
        assert unit.level == other.level
        parent_a = unit.parent.name if unit.parent else None
        parent_b = other.parent.name if other.parent else None
        assert parent_a == parent_b
