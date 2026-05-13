"""
Contract tests for HouseholdDistributor.load_household_data — the loader
exercised by these production log lines:

    Loading household data from data/households/households.csv
    Filtering household data to N SGUs in loaded geography
    Filtered to N geo_units with M household types
    Loaded household data for N geographical units

Existing residence tests focus on allocation/backtracking. This file pins
the contract of the loader itself: filtering, zero-count exclusion, sad
paths (missing file, empty geography), and the re-load reset contract.
"""

import logging
import os

import pytest

from may.geography import Geography, GeographicalUnit
from may.geography.venue_manager import VenueManager
from may.population.population import PopulationManager
from may.residence.household_distributor import HouseholdDistributor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_geo(sgus):
    """Make a single-level geography with the given SGU names."""
    geo = Geography()
    geo.levels = ['SGU']
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


# ===========================================================================
# Happy path: filtering, zero-count exclusion, count of geo_units logged
# ===========================================================================

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


# ===========================================================================
# Sad paths
# ===========================================================================

class TestLoadHouseholdDataSadPaths:

    def test_missing_file_warns_and_leaves_state_empty(self, tmp_path, caplog):
        """A missing households CSV must log a warning and leave the
        distributor with empty counts — parallel to load_demographics_from_csv
        and load_venue_type_from_csv. Crashing here would diverge from the
        rest of the loader contract and abort world creation."""
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        with caplog.at_level(logging.WARNING, logger='household'):
            hd.load_household_data("does_not_exist.csv")
        assert hd.household_counts_by_geo_unit == {}
        assert any('not found' in r.message for r in caplog.records)

    def test_empty_geography_warns_and_returns(self, tmp_path, caplog):
        """If the geography hierarchy has no smallest-level units, loading
        must short-circuit with a warning rather than process the file."""
        geo = _make_geo([])  # No SGUs at all
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "households.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],
        )
        with caplog.at_level(logging.WARNING, logger='household'):
            hd.load_household_data("households.csv")
        assert hd.household_counts_by_geo_unit == {}
        assert any('No SGU units' in r.message for r in caplog.records)


# ===========================================================================
# Re-load contract: a second call replaces, never accumulates
# ===========================================================================

class TestLoadHouseholdDataReload:

    def test_second_load_replaces_first(self, tmp_path):
        """Calling load_household_data twice must produce the same state
        as calling it once with the second file — not a union of the two.
        Otherwise stale entries from a prior load silently shadow the
        intended state, and downstream allocators see geo_units that the
        current run shouldn't include."""
        geo = _make_geo(['SGU_001', 'SGU_002'])
        hd = _make_distributor(geo, str(tmp_path))
        # First file: covers SGU_001
        _write_households_csv(
            tmp_path / "first.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],
        )
        hd.load_household_data("first.csv")
        assert 'SGU_001' in hd.household_counts_by_geo_unit

        # Second file: covers ONLY SGU_002. SGU_001's stale entry must be
        # gone after the re-load.
        _write_households_csv(
            tmp_path / "second.csv",
            ['1 0 0 0'],
            [('SGU_002', [5])],
        )
        hd.load_household_data("second.csv")
        assert set(hd.household_counts_by_geo_unit.keys()) == {'SGU_002'}
        assert hd.household_counts_by_geo_unit['SGU_002'] == {'1 0 0 0': 5}

    def test_reload_after_missing_file_does_not_keep_stale_state(self, tmp_path):
        """If a re-load points at a missing file, prior state must be
        cleared rather than silently re-served. The world otherwise looks
        loaded when in fact the new run has no household data."""
        geo = _make_geo(['SGU_001'])
        hd = _make_distributor(geo, str(tmp_path))
        _write_households_csv(
            tmp_path / "first.csv",
            ['1 0 0 0'],
            [('SGU_001', [3])],
        )
        hd.load_household_data("first.csv")
        assert hd.household_counts_by_geo_unit  # populated

        hd.load_household_data("vanished.csv")
        assert hd.household_counts_by_geo_unit == {}
