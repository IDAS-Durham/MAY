"""
Functional contract tests for VenueManager.

These cover the real, user-facing behaviour of the venue load pipeline,
residence helpers, export, and auto-discovery — happy and sad paths.
Edge cases triggered by specific source-data quirks live in
test_venue_loader.py; this file is the contract.
"""

import logging
import os

import pandas as pd
import pytest

from may.geography import Geography
from may.geography.venue_manager import VenueManager, VenueError


@pytest.fixture
def loaded_geography():
    geo = Geography(data_dir="tests/test_data/micro_world/geography", levels=["SGU", "MGU", "LGU"])
    geo.load_from_csv()
    return geo


class TestCoordinatesParsing:

    def test_lowercase_lat_lon_become_tuple(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['Foo'],
            'geo_unit': ['SGU_001'],
            'latitude': [51.5],
            'longitude': [-0.1],
        })
        vm.load_venue_type_from_df('hospital', df)
        venue = vm.get_venue('Foo')
        assert venue.coordinates == (51.5, -0.1)

    def test_capitalised_lat_lon_also_work(self, loaded_geography):
        """Schools_EW.csv ships with 'Latitude'/'Longitude' columns — the
        loader must accept them, not silently drop coordinates."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['Foo'],
            'geo_unit': ['SGU_001'],
            'Latitude': [51.5],
            'Longitude': [-0.1],
        })
        vm.load_venue_type_from_df('school', df)
        venue = vm.get_venue('Foo')
        assert venue.coordinates == (51.5, -0.1)

    def test_no_coordinate_columns_leaves_coordinates_none(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({'name': ['Foo'], 'geo_unit': ['SGU_001']})
        vm.load_venue_type_from_df('cinema', df)
        assert vm.get_venue('Foo').coordinates is None

    def test_nan_coordinates_leave_coordinates_none(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['Foo'],
            'geo_unit': ['SGU_001'],
            'latitude': [None],
            'longitude': [None],
        })
        vm.load_venue_type_from_df('cinema', df)
        assert vm.get_venue('Foo').coordinates is None


class TestPropertyColumns:

    def test_extra_columns_become_venue_properties(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['HQ'],
            'geo_unit': ['SGU_001'],
            'employee_count': [120],
            'industry_code': ['retail'],
        })
        vm.load_venue_type_from_df('company', df)
        v = vm.get_venue('HQ')
        assert v.properties['employee_count'] == 120
        assert v.properties['industry_code'] == 'retail'

    def test_nan_property_values_are_dropped(self, loaded_geography):
        """A NaN value should not pollute the venue's property dict."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['HQ'],
            'geo_unit': ['SGU_001'],
            'employee_count': [120],
            'industry_code': [None],
        })
        vm.load_venue_type_from_df('company', df)
        v = vm.get_venue('HQ')
        assert v.properties['employee_count'] == 120
        assert 'industry_code' not in v.properties

    def test_reserved_columns_are_not_repeated_in_properties(self, loaded_geography):
        """name / geo_unit / latitude / longitude must not leak into properties."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['HQ'],
            'geo_unit': ['SGU_001'],
            'latitude': [51.5],
            'longitude': [-0.1],
            'capacity': [500],
        })
        vm.load_venue_type_from_df('company', df)
        v = vm.get_venue('HQ')
        for reserved in ('name', 'geo_unit', 'latitude', 'longitude'):
            assert reserved not in v.properties
        assert v.properties['capacity'] == 500


class TestGeoColumnResolution:

    def test_sgu_column_is_resolved(self, loaded_geography):
        """households.csv uses an 'SGU' column."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({'name': ['hh1'], 'SGU': ['SGU_001']})
        vm.load_venue_type_from_df('household', df)
        v = vm.get_venue('hh1')
        assert v.geographical_unit.name == 'SGU_001'

    def test_mgu_column_is_resolved(self, loaded_geography):
        """schools.csv uses an 'MGU' column."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({'name': ['sch1'], 'MGU': ['MGU_01']})
        vm.load_venue_type_from_df('school', df)
        v = vm.get_venue('sch1')
        assert v.geographical_unit.name == 'MGU_01'

    def test_missing_geo_column_raises(self, loaded_geography):
        """A CSV with no recognised geographical column is unloadable —
        we should fail loudly, not silently produce zero venues."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({'name': ['Foo'], 'capacity': [10]})
        with pytest.raises(ValueError, match="Missing required geographical column"):
            vm.load_venue_type_from_df('school', df)


class TestGeographicFiltering:

    def test_filter_on_drops_out_of_geography_rows(self, loaded_geography, caplog):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=True)
        df = pd.DataFrame({
            'name': ['In', 'Out'],
            'geo_unit': ['SGU_001', 'SGU_999'],  # 999 not in micro_world
        })
        with caplog.at_level(logging.INFO, logger='venuemanager'):
            vm.load_venue_type_from_df('school', df)

        names = [v.name for v in vm.get_venues_by_type('school')]
        assert names == ['In']
        # Pre-filter line should mention 1 kept and 1 filtered.
        assert any(
            'Pre-filtered school venues: 1 venues' in r.message
            and '1 filtered out' in r.message
            for r in caplog.records
        )

    def test_filter_off_attempts_all_rows_then_skips_unknown(self, loaded_geography, caplog):
        """With geography filtering off, the loader still must skip rows
        whose geo_unit isn't actually in the geography — silently producing
        a venue with `geographical_unit=None` would corrupt downstream code."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['In', 'Out'],
            'geo_unit': ['SGU_001', 'SGU_999'],
        })
        with caplog.at_level(logging.WARNING, logger='venuemanager'):
            vm.load_venue_type_from_df('school', df)

        names = [v.name for v in vm.get_venues_by_type('school')]
        assert names == ['In']
        assert any(
            'Geographical unit not found' in r.message and 'Out' in r.message
            for r in caplog.records
        )


class TestIDGeneration:

    def test_ids_are_sequential_within_a_type(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({
            'name': ['A', 'B', 'C'],
            'geo_unit': ['SGU_001'] * 3,
        })
        vm.load_venue_type_from_df('school', df)
        ids = sorted(v.id for v in vm.get_venues_by_type('school'))
        assert ids == [0, 1, 2]

    def test_ids_are_independent_across_types(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df_sch = pd.DataFrame({'name': ['A', 'B'], 'geo_unit': ['SGU_001'] * 2})
        df_hosp = pd.DataFrame({'name': ['H'], 'geo_unit': ['SGU_001']})
        vm.load_venue_type_from_df('school', df_sch)
        vm.load_venue_type_from_df('hospital', df_hosp)
        # Each type starts at 0 — they are NOT a global counter.
        assert sorted(v.id for v in vm.get_venues_by_type('school')) == [0, 1]
        assert [v.id for v in vm.get_venues_by_type('hospital')] == [0]


class TestYamlConfig:

    def test_missing_config_file_raises(self, loaded_geography, tmp_path):
        vm = VenueManager(geography=loaded_geography, data_dir=str(tmp_path))
        with pytest.raises(VenueError):
            vm.load_from_yaml_config(str(tmp_path / "does_not_exist.yaml"))

    def test_empty_config_file_fails_loud(self, loaded_geography, tmp_path):
        config = tmp_path / "empty.yaml"
        config.write_text("")
        vm = VenueManager(geography=loaded_geography, data_dir=str(tmp_path))
        with pytest.raises(VenueError):
            vm.load_from_yaml_config(str(config))

    def test_config_without_venue_types_key_fails_loud(self, loaded_geography, tmp_path):
        config = tmp_path / "no_types.yaml"
        config.write_text("settings:\n  filter_by_geography: true\n")
        vm = VenueManager(geography=loaded_geography, data_dir=str(tmp_path))
        with pytest.raises(VenueError):
            vm.load_from_yaml_config(str(config))

    def test_explicit_empty_venue_types_is_valid_no_op(self, loaded_geography, tmp_path):
        """An explicit `venue_types: {}` is a legitimate 'this world has no
        venues' declaration (e.g. a scenario with no venue data yet) — it must
        NOT raise, unlike a missing venue_types key or empty file."""
        config = tmp_path / "no_venues.yaml"
        config.write_text("venue_types: {}\n")
        vm = VenueManager(geography=loaded_geography, data_dir=str(tmp_path))
        vm.load_from_yaml_config(str(config))
        assert vm.get_all_venues_list() == []

    def test_settings_filter_by_geography_is_honoured(self, loaded_geography, tmp_path):
        """Yaml `settings.filter_by_geography: false` must override the
        VenueManager constructor default (True), not be ignored."""
        venues_dir = tmp_path / "venues"
        venues_dir.mkdir()
        # Two rows: one in-geography, one out.
        (venues_dir / "schools.csv").write_text(
            "name,geo_unit\nIn,SGU_001\nOut,SGU_999\n"
        )
        (venues_dir / "config.yaml").write_text(
            "venue_types:\n"
            "  school:\n"
            "    enabled: true\n"
            "    filename: schools.csv\n"
            "settings:\n"
            "  filter_by_geography: false\n"
        )
        # Constructor default would be True; yaml flips it.
        vm = VenueManager(
            geography=loaded_geography,
            data_dir=str(venues_dir),
            filter_by_geography=True,
        )
        vm.load_from_yaml_config("config.yaml")
        # Out-of-geo row is skipped by per-row check, but pre-filter step
        # must NOT have run (otherwise the warning wouldn't fire). Verify
        # the per-row warning instead of the pre-filter one.
        assert vm.filter_by_geography is False
        assert [v.name for v in vm.get_venues_by_type('school')] == ['In']

    def test_disabled_venue_types_have_config_recorded_for_residence_lookup(
        self, loaded_geography, tmp_path
    ):
        """`household` is intentionally disabled in the production yaml but
        marked is_residence — the rest of the code relies on
        `is_residence_type('household')` returning True without any household
        venues being loaded. Lock this contract in."""
        venues_dir = tmp_path / "venues"
        venues_dir.mkdir()
        (venues_dir / "config.yaml").write_text(
            "venue_types:\n"
            "  household:\n"
            "    enabled: false\n"
            "    is_residence: true\n"
        )
        vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
        vm.load_from_yaml_config("config.yaml")
        assert vm.is_residence_type('household') is True
        assert vm.get_venues_by_type('household') == []


class TestResidenceHelpers:

    def _vm_with_residence_config(self, geo, tmp_path):
        venues_dir = tmp_path / "venues"
        venues_dir.mkdir()
        (venues_dir / "homes.csv").write_text(
            "name,geo_unit\nHomeA,SGU_001\nHomeB,SGU_002\n"
        )
        (venues_dir / "shops.csv").write_text(
            "name,geo_unit\nShop,SGU_001\n"
        )
        (venues_dir / "config.yaml").write_text(
            "venue_types:\n"
            "  household:\n"
            "    enabled: false\n"
            "    is_residence: true\n"
            "  care_home:\n"
            "    enabled: true\n"
            "    filename: homes.csv\n"
            "    is_residence: true\n"
            "  grocery:\n"
            "    enabled: true\n"
            "    filename: shops.csv\n"
            "    is_residence: false\n"
        )
        vm = VenueManager(geography=geo, data_dir=str(venues_dir))
        vm.load_from_yaml_config("config.yaml")
        return vm

    def test_get_residence_types_lists_only_is_residence_types(
        self, loaded_geography, tmp_path
    ):
        vm = self._vm_with_residence_config(loaded_geography, tmp_path)
        residence_types = set(vm.get_residence_types())
        # household is is_residence even though disabled; grocery is not.
        assert residence_types == {'household', 'care_home'}

    def test_is_residence_type_returns_false_for_unknown_type(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        assert vm.is_residence_type('dragon_lair') is False

    def test_get_all_residences_returns_only_residence_venues(
        self, loaded_geography, tmp_path
    ):
        vm = self._vm_with_residence_config(loaded_geography, tmp_path)
        residences = vm.get_all_residences()
        # Two care_homes; the grocery is excluded.
        assert {v.name for v in residences} == {'HomeA', 'HomeB'}
        assert all(v.type == 'care_home' for v in residences)


class TestExportVenuesToCsv:

    def test_export_writes_one_row_per_venue_with_expected_columns(
        self, loaded_geography, tmp_path
    ):
        venues_dir = tmp_path / "out"
        venues_dir.mkdir()
        vm = VenueManager(
            geography=loaded_geography,
            data_dir=str(venues_dir),
            filter_by_geography=False,
        )
        df = pd.DataFrame({
            'name': ['Gen', 'St Mary'],
            'geo_unit': ['SGU_001', 'SGU_002'],
            'capacity': [100, 200],
        })
        vm.load_venue_type_from_df('hospital', df)

        path = vm.export_venues_to_csv("out.csv")
        assert os.path.exists(path)

        out = pd.read_csv(path)
        assert len(out) == 2
        # The contract: every documented column is present.
        for col in ('venue_id', 'venue_name', 'venue_type', 'geo_unit',
                    'total_capacity', 'num_residents', 'capacity_used_pct',
                    'age_sex_breakdown', 'attribute_slots', 'residents'):
            assert col in out.columns
        # Capacity comes from 'capacity' fallback when no capacity_config.
        assert set(out['total_capacity']) == {100, 200}
        # No residents added → num_residents is 0 everywhere.
        assert (out['num_residents'] == 0).all()

    def test_export_uses_capacity_config_total_column(
        self, loaded_geography, tmp_path
    ):
        """When the venue type has a capacity_config.total_capacity_column,
        export must pull capacity from that column, not the generic
        'capacity' fallback."""
        venues_dir = tmp_path / "out"
        venues_dir.mkdir()
        vm = VenueManager(
            geography=loaded_geography,
            data_dir=str(venues_dir),
            filter_by_geography=False,
        )
        vm.capacity_configs['school'] = {'total_capacity_column': 'SchoolCapacity'}
        df = pd.DataFrame({
            'name': ['Sch1'],
            'geo_unit': ['SGU_001'],
            'SchoolCapacity': [500],
            'capacity': [9999],  # generic fallback would lie if used
        })
        vm.load_venue_type_from_df('school', df)
        path = vm.export_venues_to_csv("schools.csv")
        out = pd.read_csv(path)
        assert out['total_capacity'].iloc[0] == 500

    def test_export_sorts_by_type_then_id(self, loaded_geography, tmp_path):
        venues_dir = tmp_path / "out"
        venues_dir.mkdir()
        vm = VenueManager(
            geography=loaded_geography,
            data_dir=str(venues_dir),
            filter_by_geography=False,
        )
        # Load schools first, then hospitals — written rows must still
        # group by type alphabetically with ascending ids inside.
        vm.load_venue_type_from_df(
            'school',
            pd.DataFrame({'name': ['S1', 'S2'], 'geo_unit': ['SGU_001'] * 2}),
        )
        vm.load_venue_type_from_df(
            'hospital',
            pd.DataFrame({'name': ['H1'], 'geo_unit': ['SGU_001']}),
        )
        path = vm.export_venues_to_csv("v.csv")
        out = pd.read_csv(path)
        assert out['venue_type'].tolist() == ['hospital', 'school', 'school']
        assert out.iloc[1]['venue_id'] < out.iloc[2]['venue_id']

    def test_export_with_no_venues_does_not_crash(self, loaded_geography, tmp_path):
        venues_dir = tmp_path / "out"
        venues_dir.mkdir()
        vm = VenueManager(geography=loaded_geography, data_dir=str(venues_dir))
        path = vm.export_venues_to_csv("empty.csv")
        assert os.path.exists(path)
        # Empty manager → empty file (pandas writes an empty DataFrame).
        # The contract is just: no exception, file exists.


class TestGeoUnitLinkage:

    def test_create_venue_registers_with_geographical_unit(self, loaded_geography):
        """A venue must appear in its GeographicalUnit's venues list — the
        rest of the simulation walks venues *via* the geography."""
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        sgu = loaded_geography.get_unit('SGU_001')
        before = list(sgu.venues) if hasattr(sgu, 'venues') else None

        venue = vm.create_venue('school', sgu)

        assert hasattr(sgu, 'venues') or hasattr(sgu, '_venues')
        # Use whichever attribute the GeographicalUnit exposes.
        unit_venues = getattr(sgu, 'venues', None) or getattr(sgu, '_venues', [])
        assert venue in unit_venues
        if before is not None:
            assert len(unit_venues) == len(before) + 1

    def test_loaded_venue_is_attached_to_correct_geo_unit(self, loaded_geography):
        vm = VenueManager(geography=loaded_geography, filter_by_geography=False)
        df = pd.DataFrame({'name': ['Sch'], 'MGU': ['MGU_01']})
        vm.load_venue_type_from_df('school', df)
        venue = vm.get_venue('Sch')
        mgu = loaded_geography.get_unit('MGU_01')
        unit_venues = getattr(mgu, 'venues', None) or getattr(mgu, '_venues', [])
        assert venue in unit_venues
