"""
Contract tests for HouseholdDistributor.load_household_data — the loader
exercised by these production log lines:

    Loading household data from data/households/households.csv
    Filtering household data to N SGUs in loaded geography
    Filtered to N geo_units with M household types
    Loaded household data for N geographical units

These pin the contract of the loader itself: filtering, zero-count
exclusion, sad paths (missing file, empty geography), and the re-load
reset contract.
"""

import logging
import os

import pytest

from may.geography import Geography, GeographicalUnit
from may.geography.venue_manager import VenueManager
from may.population.population import PopulationManager
from may.residence.household_distributor import HouseholdDistributor, HouseholdError


# Fixtures

def _make_geo(sgus):
    """Make a single-level geography with the given SGU names."""
    geo = Geography(levels=['SGU'])
    geo.units = {}
    geo.units_by_level = {'SGU': {}}
    for i, name in enumerate(sgus):
        u = GeographicalUnit(id=i, name=name, level='SGU')
        geo.units[name] = u
        geo.units_by_level['SGU'][name] = u
        geo.units_by_id[u.id] = u
    return geo


def _make_distributor(geo, data_dir):
    """Build a HouseholdDistributor pointing at a tmp data_dir, using the
    real micro_world household categories config."""
    pm = PopulationManager(geography=geo, data_dir='/tmp')
    vm = VenueManager(geo, filter_by_geography=False)
    config_src = "tests/test_data/micro_world/households/test_households_config.yaml"
    return HouseholdDistributor(
        geography=geo,
        population=pm,
        venue_manager=vm,
        data_dir=data_dir,
        config_file=config_src,
    )


def _write_households_csv(path, header_cols, rows):
    """Write a households CSV: first column is geo_unit, rest are pattern
    columns."""
    lines = ['geo_unit,' + ','.join(header_cols)]
    for geo_name, counts in rows:
        lines.append(','.join([geo_name] + [str(c) for c in counts]))
    path.write_text('\n'.join(lines) + '\n')


# Happy path: filtering, zero-count exclusion, count of geo_units logged

class TestLoadHouseholdDataHappyPath:

    def test_only_in_geography_geo_units_are_kept(self, tmp_path, caplog):
        """Source CSVs cover the whole country; load must keep only rows
        whose geo_unit is in the loaded geography."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0', '0 0 1 0'],
            [('SGU_001', [3, 1]),
             ('SGU_002', [0, 2]),
             ('SGU_999', [9, 9])],   # NOT in geography
        )
        with caplog.at_level(logging.INFO, logger='household'):
            hd.load_household_data("households.csv")

        assert set(hd.household_counts_by_geo_unit.keys()) == {'SGU_001', 'SGU_002'}
        assert hd.household_counts_by_geo_unit['SGU_001'] == {'1 0 0 0': 3, '0 0 1 0': 1}
        # 0-count entries excluded
        assert hd.household_counts_by_geo_unit['SGU_002'] == {'0 0 1 0': 2}
        # The two log lines that the production trace ends on must fire.
        assert any('Filtering household data to 2 SGUs' in r.message for r in caplog.records)
        assert any('Loaded household data for 2 geographical units' in r.message for r in caplog.records)

    def test_geo_unit_with_only_zero_counts_is_omitted_entirely(self, tmp_path):
        """A geo_unit row whose counts are all zero must produce no entry —
        not an empty dict — so downstream `if geo_unit in counts` checks
        don't accidentally process empty households."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0'],
            [('SGU_001', [2]),
             ('SGU_002', [0])],
        )
        hd.load_household_data("households.csv")
        assert 'SGU_001' in hd.household_counts_by_geo_unit
        assert 'SGU_002' not in hd.household_counts_by_geo_unit


# Sad paths

class TestLoadHouseholdDataSadPaths:

    def test_missing_file_raises(self, tmp_path):
        """A missing households CSV must fail loud (HouseholdError), like
        PopulationError/VenueError — the engine works on complete data or not
        at all. Once a residence_allocation step is in the timeline,
        missing household data is a misconfiguration, not a tolerable no-op."""
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        with pytest.raises(HouseholdError, match="not found"):
            hd.load_household_data("does_not_exist.csv")

    def test_empty_geography_raises(self, tmp_path):
        """If the geography hierarchy has no smallest-level units, loading
        must fail loud rather than silently build an empty world."""
        geo = _make_geo([])  # No SGUs at all
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],
        )
        with pytest.raises(HouseholdError, match="No SGU units"):
            hd.load_household_data("households.csv")

    def test_no_rows_match_geography_raises(self, tmp_path):
        """A present file whose rows are all outside the loaded geography
        would build zero households — fail loud instead."""
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0'],
            [('SGU_999', [3])],  # not in geography
        )
        with pytest.raises(HouseholdError, match="no household data row"):
            hd.load_household_data("households.csv")

    def test_uncovered_geo_unit_raises(self, tmp_path):
        """Every loaded geo unit needs a household row; a partial file must
        fail loud, not quietly leave people in that unit homeless."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],  # SGU_002 has no row
        )
        with pytest.raises(HouseholdError, match="SGU_002"):
            hd.load_household_data("households.csv")


# Re-load contract: a second call replaces, never accumulates

class TestLoadHouseholdDataReload:

    def test_second_load_replaces_first(self, tmp_path):
        """Calling load_household_data twice must produce the same state
        as calling it once with the second file — not a union of the two.
        Otherwise stale entries from a prior load silently shadow the
        intended state, and downstream allocators see geo_units that the
        current run shouldn't include."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        # First file: counts only in SGU_001
        _write_households_csv(
            tmp_path / "first.csv",
            ['1 0 0 0'],
            [('SGU_001', [3]), ('SGU_002', [0])],
        )
        hd.load_household_data("first.csv")
        assert 'SGU_001' in hd.household_counts_by_geo_unit

        # Second file: counts ONLY in SGU_002. SGU_001's stale entry must be
        # gone after the re-load.
        _write_households_csv(
            tmp_path / "second.csv",
            ['1 0 0 0'],
            [('SGU_001', [0]), ('SGU_002', [5])],
        )
        hd.load_household_data("second.csv")
        assert set(hd.household_counts_by_geo_unit.keys()) == {'SGU_002'}
        assert hd.household_counts_by_geo_unit['SGU_002'] == {'1 0 0 0': 5}

    def test_reload_after_missing_file_raises_and_clears_state(self, tmp_path):
        """A re-load pointing at a missing file must fail loud, and must clear
        prior state before raising — so a caught error can't leave stale counts
        that make the world look loaded."""
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "first.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],
        )
        hd.load_household_data("first.csv")
        assert hd.household_counts_by_geo_unit  # populated

        with pytest.raises(HouseholdError):
            hd.load_household_data("vanished.csv")
        assert hd.household_counts_by_geo_unit == {}  # stale state cleared, not re-served


# Multi-file stacking: shared or unioned vocabularies, disjoint geo keys

class TestLoadHouseholdDataMultiFile:

    def test_stacked_files_with_shared_vocabulary(self, tmp_path):
        """Two sources with identical pattern columns stack under strict."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "nation_a.csv", ['1 0 0 0'], [('SGU_001', [3])]
        )
        _write_households_csv(
            tmp_path / "nation_b.csv", ['1 0 0 0'], [('SGU_002', [5])]
        )
        hd.load_household_data(["nation_a.csv", "nation_b.csv"])
        assert hd.household_counts_by_geo_unit == {
            'SGU_001': {'1 0 0 0': 3},
            'SGU_002': {'1 0 0 0': 5},
        }

    def test_stacked_files_with_different_vocabularies_fail_strict(self, tmp_path):
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "nation_a.csv", ['1 0 0 0'], [('SGU_001', [3])]
        )
        _write_households_csv(
            tmp_path / "nation_b.csv", ['0 0 2 0'], [('SGU_002', [5])]
        )
        with pytest.raises(HouseholdError, match="column"):
            hd.load_household_data(["nation_a.csv", "nation_b.csv"])

    def test_union_zero_fill_combines_vocabularies(self, tmp_path, caplog):
        """Opting into union lets sources with different pattern columns
        stack; absent patterns read as zero households, with a warning."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "nation_a.csv", ['1 0 0 0'], [('SGU_001', [3])]
        )
        _write_households_csv(
            tmp_path / "nation_b.csv", ['0 0 2 0'], [('SGU_002', [5])]
        )
        with caplog.at_level(logging.WARNING, logger='stacked_input'):
            hd.load_household_data(
                ["nation_a.csv", "nation_b.csv"],
                column_policy="union_zero_fill",
            )

        # Zero-filled cells create no counts; each unit keeps its own patterns.
        assert hd.household_counts_by_geo_unit == {
            'SGU_001': {'1 0 0 0': 3},
            'SGU_002': {'0 0 2 0': 5},
        }
        # The vocabulary is the union, so strategy steps can target both.
        assert hd.household_pattern_vocabulary == {'1 0 0 0', '0 0 2 0'}
        assert any('zero-filling' in r.message for r in caplog.records)

    def test_geo_unit_in_two_files_raises(self, tmp_path):
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "nation_a.csv", ['1 0 0 0'], [('SGU_001', [3])]
        )
        _write_households_csv(
            tmp_path / "nation_b.csv", ['1 0 0 0'], [('SGU_001', [5])]
        )
        with pytest.raises(HouseholdError, match="already appear"):
            hd.load_household_data(["nation_a.csv", "nation_b.csv"])
