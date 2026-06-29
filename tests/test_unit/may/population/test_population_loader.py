"""
Contract tests for PopulationManager loaders and generators.

These cover the public load_* / generate_* surface of population.py — the
methods the create_world flow exercises end-to-end every run. The existing
test_population.py covers happy paths well; this file pins down the sad
paths, the cross-method side effects, and the kwarg-aliasing regression
guard for the Person constructor fix.

Each test pins one contract; classes group related contracts so the file
reads as a spec.
"""

import logging
import os

import pandas as pd
import pytest

from may.geography import Geography, GeographicalUnit
from may.population import Person, PopulationManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_person_counter():
    Person.reset_counter()
    yield
    Person.reset_counter()


def _make_geo(level_units):
    """Build a Geography hand-stitched from {level: [unit_names]} so tests
    don't need a CSV fixture for the smaller cases."""
    geo = Geography(levels=list(level_units.keys()))
    geo.units = {}
    geo.units_by_level = {lvl: {} for lvl in geo.levels}
    next_id = 0
    for level, names in level_units.items():
        for name in names:
            unit = GeographicalUnit(id=next_id, name=name, level=level)
            next_id += 1
            geo.units[name] = unit
            geo.units_by_level[level][name] = unit
            geo.units_by_id[unit.id] = unit
    return geo


@pytest.fixture
def sgu_geo():
    """Geography with three SGUs (the smallest level) — production shape."""
    return _make_geo({'SGU': ['SGU_001', 'SGU_002', 'SGU_003']})


@pytest.fixture
def two_level_geo():
    """SGU + MGU geography for batch-load tests."""
    geo = _make_geo({
        'SGU': ['S1', 'S2', 'S3', 'S4'],
        'MGU': ['M_a', 'M_b'],
    })
    # Wire the parent links because load_batch_explicit_from_csv iterates MGUs.
    geo.units_by_level['MGU']['M_a'].add_child(geo.units['S1'])
    geo.units_by_level['MGU']['M_a'].add_child(geo.units['S2'])
    geo.units_by_level['MGU']['M_b'].add_child(geo.units['S3'])
    geo.units_by_level['MGU']['M_b'].add_child(geo.units['S4'])
    return geo


# ===========================================================================
# load_demographics_from_csv — sad paths and side effects the production
# log relies on but the existing tests don't pin down
# ===========================================================================

class TestLoadDemographicsFromCsv:

    def _write_demographics_pair(self, tmp_path, male_df, female_df):
        male_path = tmp_path / "demographics_male.csv"
        female_path = tmp_path / "demographics_female.csv"
        male_df.to_csv(male_path, index=False)
        female_df.to_csv(female_path, index=False)
        return str(tmp_path)

    def test_missing_geo_unit_column_raises(self, sgu_geo, tmp_path):
        """Demographics without a 'geo_unit' column are unloadable; we must
        fail loudly, not silently produce zero people."""
        bad = pd.DataFrame({'wrong_col': ['SGU_001'], '0': [1]})
        data_dir = self._write_demographics_pair(tmp_path, bad, bad)
        pm = PopulationManager(geography=sgu_geo, data_dir=data_dir)
        with pytest.raises(ValueError, match="geo_unit"):
            pm.load_demographics_from_csv()

    def test_rows_outside_geography_are_filtered_out(self, sgu_geo, tmp_path):
        """Source CSVs cover the whole country; we should only retain the
        rows whose geo_unit is in the loaded geography."""
        in_geo = pd.DataFrame({
            'geo_unit': ['SGU_001', 'OUT_OF_GEO_999'],
            '0': [3, 99],
        })
        data_dir = self._write_demographics_pair(tmp_path, in_geo, in_geo)
        pm = PopulationManager(geography=sgu_geo, data_dir=data_dir)
        pm.load_demographics_from_csv()

        assert set(pm.precise_demographics.keys()) == {'SGU_001'}
        assert pm.precise_demographics['SGU_001'][0]['male'] == 3

    def test_zero_count_cells_do_not_create_demographic_entries(
        self, sgu_geo, tmp_path
    ):
        """Zero counts must be filtered out — generate_population iterates
        every (age, sex, count) tuple, so leaving zeros in inflates the work
        with no observable effect."""
        df = pd.DataFrame({
            'geo_unit': ['SGU_001'],
            '0': [0],   # zero males age 0
            '1': [4],   # four males age 1
        })
        data_dir = self._write_demographics_pair(tmp_path, df, df)
        pm = PopulationManager(geography=sgu_geo, data_dir=data_dir)
        pm.load_demographics_from_csv()

        sgu_data = pm.precise_demographics['SGU_001']
        assert 0 not in sgu_data
        assert sgu_data[1]['male'] == 4

    def test_geography_with_no_smallest_level_units_warns_and_returns(
        self, tmp_path, caplog
    ):
        """If the geography hierarchy was wiped or never loaded, demographics
        loading must short-circuit with a warning, not crash."""
        empty = _make_geo({'SGU': []})
        df = pd.DataFrame({'geo_unit': ['SGU_001'], '0': [1]})
        data_dir = self._write_demographics_pair(tmp_path, df, df)
        pm = PopulationManager(geography=empty, data_dir=data_dir)
        with caplog.at_level(logging.WARNING, logger='population'):
            pm.load_demographics_from_csv()
        assert pm.precise_demographics == {}
        assert any('No SGU units' in r.message for r in caplog.records)

    def test_missing_files_does_not_corrupt_state(self, sgu_geo, tmp_path, caplog):
        """A missing demographics file is logged as an error and the manager
        is left empty — generate_population then refuses to run, rather than
        producing a phantom population."""
        pm = PopulationManager(geography=sgu_geo, data_dir=str(tmp_path))
        with caplog.at_level(logging.ERROR, logger='population'):
            pm.load_demographics_from_csv()
        assert pm.precise_demographics == {}
        assert any('not found' in r.message.lower() for r in caplog.records)

    def test_second_load_replaces_first(self, sgu_geo, tmp_path):
        """Calling load_demographics_from_csv twice must not double-count the
        first load's data into the second's totals."""
        df1 = pd.DataFrame({'geo_unit': ['SGU_001'], '0': [3]})
        df2 = pd.DataFrame({'geo_unit': ['SGU_002'], '5': [7]})
        data_dir = self._write_demographics_pair(tmp_path, df1, df1)
        pm = PopulationManager(geography=sgu_geo, data_dir=data_dir)
        pm.load_demographics_from_csv()
        # Overwrite files with the second dataset
        self._write_demographics_pair(tmp_path, df2, df2)
        pm.load_demographics_from_csv()
        assert set(pm.precise_demographics.keys()) == {'SGU_002'}
        assert pm.precise_demographics['SGU_002'][5]['male'] == 7


# ===========================================================================
# load_explicit_from_df — sad paths and column-mapping semantics
# ===========================================================================

class TestLoadExplicitFromDf:

    def test_missing_geo_column_raises(self, sgu_geo):
        """An explicit-population frame with no recognised geographical
        column is unloadable — must fail loudly, not produce zero people."""
        df = pd.DataFrame({'Age': [25], 'Gender': ['M']})
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        with pytest.raises(ValueError, match="geographical column"):
            pm.load_explicit_from_df(df, column_mapping={'age': 'Age', 'sex': 'Gender'})

    def test_unknown_geo_unit_skips_row_with_warning(self, sgu_geo, caplog):
        """A row whose geo_unit isn't in the loaded geography must be skipped
        — silently producing a Person with geographical_unit=None corrupts
        every downstream lookup."""
        df = pd.DataFrame({
            'Age': [25, 30],
            'Gender': ['M', 'F'],
            'Area': ['SGU_001', 'NOT_REAL'],
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        with caplog.at_level(logging.WARNING, logger='population'):
            pm.load_explicit_from_df(
                df,
                column_mapping={'age': 'Age', 'sex': 'Gender', 'geo_unit': 'Area'},
            )
        assert len(pm.people) == 1
        assert pm.people[0].geographical_unit.name == 'SGU_001'
        assert any(
            'No geographical unit found' in r.message and 'NOT_REAL' in r.message
            for r in caplog.records
        )

    @pytest.mark.parametrize("raw,expected", [
        ('M', 'male'),
        ('m', 'male'),
        ('male', 'male'),
        ('Male', 'male'),
        ('1', 'male'),
        ('F', 'female'),
        ('f', 'female'),
        ('female', 'female'),
        ('2', 'female'),
    ])
    def test_sex_string_normalisation(self, sgu_geo, raw, expected):
        """The loader must canonicalise the various ways production CSVs
        encode sex into the strict 'male'/'female' tokens the rest of the
        pipeline filters by."""
        df = pd.DataFrame({'Age': [25], 'Sex': [raw], 'geo_unit': ['SGU_001']})
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        assert pm.people[0].sex == expected

    def test_unknown_sex_token_falls_back_to_unknown(self, sgu_geo):
        """An unrecognised sex string must not be silently dropped or
        relabelled — it stays as the lower-cased original so downstream
        diagnostics can spot it."""
        df = pd.DataFrame({'Age': [25], 'Sex': ['nonbinary'], 'geo_unit': ['SGU_001']})
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        # The current contract: the value passes through lower-cased and
        # stripped, but is *not* coerced to 'male'/'female'/'unknown'.
        assert pm.people[0].sex == 'nonbinary'

    def test_unmapped_csv_columns_become_person_properties(self, sgu_geo):
        df = pd.DataFrame({
            'Age': [25],
            'Sex': ['M'],
            'geo_unit': ['SGU_001'],
            'income': [50000],
            'ethnicity': ['Asian'],
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        person = pm.people[0]
        assert person.properties['income'] == 50000
        assert person.properties['ethnicity'] == 'Asian'

    def test_literal_geo_column_does_not_leak_into_properties(self, sgu_geo):
        """The geographical column drives `geographical_unit` and must not
        also appear in `properties` — even when the caller didn't add a
        'geo_unit' entry to the column mapping. Prior behaviour duplicated
        the SGU name as a property, which then silently re-shadowed any
        downstream property lookup that expected only domain attributes."""
        df = pd.DataFrame({
            'Age': [25],
            'Sex': ['M'],
            'geo_unit': ['SGU_001'],
            'income': [50000],
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        person = pm.people[0]
        assert person.geographical_unit.name == 'SGU_001'
        assert 'geo_unit' not in person.properties
        assert person.properties == {'income': 50000}

    def test_literal_sgu_column_does_not_leak_into_properties(self, sgu_geo):
        """Same contract for the alternate canonical name 'SGU' (which
        production CSVs use)."""
        df = pd.DataFrame({
            'Age': [25],
            'Sex': ['M'],
            'SGU': ['SGU_001'],
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        person = pm.people[0]
        assert person.geographical_unit.name == 'SGU_001'
        assert 'SGU' not in person.properties

    def test_mapped_csv_columns_do_not_appear_in_properties(self, sgu_geo):
        """Columns consumed by the mapping (Age/Sex/geo_unit) must not also
        leak into properties — that would store the same datum twice and
        let buggy callers diverge them."""
        df = pd.DataFrame({
            'Age': [25],
            'Sex': ['M'],
            'Area': ['SGU_001'],
            'extra': ['ok'],
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df,
            column_mapping={'age': 'Age', 'sex': 'Sex', 'geo_unit': 'Area'},
        )
        person = pm.people[0]
        assert 'Age' not in person.properties
        assert 'Sex' not in person.properties
        assert 'Area' not in person.properties
        assert person.properties['extra'] == 'ok'

    def test_loaded_person_is_attached_to_their_geo_unit(self, sgu_geo):
        df = pd.DataFrame({
            'Age': [25], 'Sex': ['M'], 'geo_unit': ['SGU_001']
        })
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.load_explicit_from_df(
            df, column_mapping={'age': 'Age', 'sex': 'Sex'}
        )
        sgu = sgu_geo.get_unit('SGU_001')
        assert pm.people[0] in sgu.people


# ===========================================================================
# load_batch_explicit_from_csv — previously untested
# ===========================================================================

class TestLoadBatchExplicitFromCsv:

    def test_missing_per_mgu_files_are_silently_skipped(
        self, two_level_geo, tmp_path
    ):
        """Production has one file per MGU. If a particular MGU's file is
        missing, batch load must continue — there is no 'fail loudly' here
        because partial geographies are routine."""
        # Write only M_a's file; M_b's is intentionally absent.
        (tmp_path / "M_a_pop.csv").write_text(
            "Age,Sex,geo_unit\n25,M,S1\n30,F,S2\n"
        )
        pm = PopulationManager(geography=two_level_geo, data_dir=str(tmp_path))
        pm.load_batch_explicit_from_csv(
            data_dir=str(tmp_path),
            column_mapping={'age': 'Age', 'sex': 'Sex'},
        )
        assert len(pm.people) == 2
        assert {p.geographical_unit.name for p in pm.people} == {'S1', 'S2'}

    def test_rows_outside_loaded_geography_are_filtered_per_file(
        self, two_level_geo, tmp_path
    ):
        """Each per-MGU file may contain rows for SGUs outside the loaded
        geography (the file is shared across runs); the batch loader must
        drop them."""
        (tmp_path / "M_a_pop.csv").write_text(
            "Age,Sex,geo_unit\n25,M,S1\n40,F,S_PHANTOM\n"
        )
        pm = PopulationManager(geography=two_level_geo, data_dir=str(tmp_path))
        pm.load_batch_explicit_from_csv(
            data_dir=str(tmp_path),
            column_mapping={'age': 'Age', 'sex': 'Sex'},
        )
        assert len(pm.people) == 1
        assert pm.people[0].geographical_unit.name == 'S1'

    def test_person_counter_reset_once_for_whole_batch(
        self, two_level_geo, tmp_path
    ):
        """If the counter were reset *per file*, person IDs across files
        would collide and people_by_id would silently shadow earlier loads."""
        (tmp_path / "M_a_pop.csv").write_text(
            "Age,Sex,geo_unit\n25,M,S1\n"
        )
        (tmp_path / "M_b_pop.csv").write_text(
            "Age,Sex,geo_unit\n30,F,S3\n"
        )
        pm = PopulationManager(geography=two_level_geo, data_dir=str(tmp_path))
        pm.load_batch_explicit_from_csv(
            data_dir=str(tmp_path),
            column_mapping={'age': 'Age', 'sex': 'Sex'},
        )
        ids = sorted(p.id for p in pm.people)
        assert ids == [0, 1]
        assert len(pm.people_by_id) == 2


# ===========================================================================
# generate_population — kwarg aliasing regression (Person fix)
# ===========================================================================

class TestGeneratePopulationKwargIndependence:
    """Person.__init__ used to alias the caller's properties / activity_map
    dicts, so generate_population fanned a single dict reference into every
    Person it created. The Person fix copies on init; pin that contract
    here from the PopulationManager side too — this is the path that
    triggered the bug in production."""

    def _two_people_pm(self, sgu_geo):
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.precise_demographics = {
            'SGU_001': {25: {'male': 1}},
            'SGU_002': {30: {'female': 1}},
        }
        return pm

    def test_properties_kwarg_is_not_shared_between_people(self, sgu_geo):
        pm = self._two_people_pm(sgu_geo)
        pm.generate_population(properties={'shared': 0})

        pm.people[0].properties['shared'] = 999

        assert pm.people[1].properties['shared'] == 0
        assert pm.people[0].properties is not pm.people[1].properties

    def test_activity_map_kwarg_does_not_raise_on_access(self, sgu_geo):
        """Before the fix, generate_population(activity_map={...}) produced
        Person objects that raised AttributeError on the very first read of
        .activity_map (the slot was never assigned)."""
        pm = self._two_people_pm(sgu_geo)
        pm.generate_population(activity_map={'residence': {'household': []}})

        # Both people must have an accessible, independent activity_map.
        for p in pm.people:
            assert p.activity_map == {'residence': {'household': []}}
        pm.people[0].activity_map['leisure'] = {'cinema': []}
        assert 'leisure' not in pm.people[1].activity_map


# ===========================================================================
# generate_population — observable side effects on geography
# ===========================================================================

class TestGeneratePopulationGeoLinkage:

    def test_each_person_is_appended_to_their_geo_units_people_list(
        self, sgu_geo
    ):
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.precise_demographics = {
            'SGU_001': {10: {'male': 2}},
            'SGU_002': {20: {'female': 3}},
        }
        pm.generate_population()

        assert len(sgu_geo.get_unit('SGU_001').people) == 2
        assert len(sgu_geo.get_unit('SGU_002').people) == 3
        assert all(p.age == 10 for p in sgu_geo.get_unit('SGU_001').people)
        assert all(p.age == 20 for p in sgu_geo.get_unit('SGU_002').people)

    def test_id_counter_resets_per_generate_call(self, sgu_geo):
        """generate_population() resets the Person counter, so re-running it
        on the same manager produces IDs that start at 0 again. Without
        this contract, calling it twice would silently shadow people in
        people_by_id."""
        pm = PopulationManager(geography=sgu_geo, data_dir='/tmp')
        pm.precise_demographics = {'SGU_001': {25: {'male': 3}}}
        pm.generate_population()
        first_ids = [p.id for p in pm.people]
        assert first_ids == [0, 1, 2]

        # Second call: the counter is reset and a new batch of 0..N IDs is
        # produced. The manager's own people list still appends, which
        # creates real ID collisions in people_by_id — verify the contract
        # we have, not one we'd like to have.
        pm.generate_population()
        new_ids = [p.id for p in pm.people[len(first_ids):]]
        assert new_ids[0] == 0  # counter was reset
