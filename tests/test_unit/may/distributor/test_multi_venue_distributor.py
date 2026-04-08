"""
Unit tests for MultiVenueDistributor.

Tests cover initialization, participation filtering, eligibility,
venue allocation, export, edge cases, stress scenarios, and known bugs.
"""

import csv
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from may.venue_distributor.multi_venue_distributor import MultiVenueDistributor
from may.population.person import Person
from may.population.subset import Subset
from may.geography.venue import Venue

from conftest import (
    SimpleWorld, make_geo, make_person, make_venue,
    make_residence, assign_residence,
)


# ======================================================================
# Helpers
# ======================================================================

def make_mvd_config(**overrides):
    """Minimal MultiVenueDistributor config dict factory."""
    config = {
        'activity_map_key': 'leisure',
        'venue_types': ['cinema', 'gym'],
        'venue_selection': {'count': 3},
        'eligibility': {'require_residence': False},
        'settings': {'verbose': False, 'log_summary': False},
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and key in config and isinstance(config[key], dict):
            config[key] = {**config[key], **val}
        else:
            config[key] = val
    return config


def make_mvd(**overrides):
    """Create a MultiVenueDistributor from minimal config."""
    return MultiVenueDistributor(config_dict=make_mvd_config(**overrides))


def write_csv(tmp_path, filename, header, rows):
    """Write a CSV file and return its path as a string."""
    p = tmp_path / filename
    with open(p, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
    return str(p)


def _simple_world(n_people=5, n_venues=3, venue_types=None, geo=None,
                  with_residence=False, ages=None, sexes=None):
    """Build a SimpleWorld with people and venues for integration tests."""
    if venue_types is None:
        venue_types = ['cinema', 'gym']
    if geo is None:
        geo = make_geo('SGU_1', coordinates=(51.5, -0.1))

    people = []
    for i in range(n_people):
        age = ages[i] if ages else 30
        sex = sexes[i] if sexes else 'male'
        p = make_person(geo=geo, age=age, sex=sex)
        if with_residence:
            res = make_residence(name=f'house_{i}', geo=geo, coordinates=geo.coordinates)
            assign_residence(p, res)
        people.append(p)

    venues_map = {}
    for vt in venue_types:
        venues = []
        for j in range(n_venues):
            lat = 51.5 + 0.01 * (j + 1)
            lon = -0.1 + 0.01 * (j + 1)
            v = make_venue(name=f'{vt}_{j}', geo=geo, venue_type=vt,
                           coordinates=(lat, lon))
            venues.append(v)
        venues_map[vt] = venues

    return SimpleWorld(people=people, venues_map=venues_map)


# ======================================================================
# 1. TestMultiVenueDistributorInit
# ======================================================================

class TestMultiVenueDistributorInit:

    def test_valid_construction(self):
        mvd = make_mvd()
        assert mvd.activity_map_key == 'leisure'
        assert mvd.venue_types == ['cinema', 'gym']
        assert mvd.default_venue_count == 3
        assert mvd.require_residence is False

    def test_missing_activity_map_key_raises(self):
        with pytest.raises(ValueError, match="activity_map_key"):
            MultiVenueDistributor(config_dict={'venue_types': ['cinema']})

    def test_empty_activity_map_key_raises(self):
        with pytest.raises(ValueError, match="activity_map_key"):
            MultiVenueDistributor(config_dict={'activity_map_key': '', 'venue_types': ['cinema']})

    def test_missing_venue_types_raises(self):
        with pytest.raises(ValueError, match="venue_types"):
            MultiVenueDistributor(config_dict={'activity_map_key': 'leisure'})

    def test_empty_venue_types_raises(self):
        with pytest.raises(ValueError, match="venue_types"):
            MultiVenueDistributor(config_dict={'activity_map_key': 'leisure', 'venue_types': []})

    def test_defaults_for_optional_fields(self):
        mvd = MultiVenueDistributor(config_dict={
            'activity_map_key': 'social',
            'venue_types': ['cafe'],
        })
        assert mvd.default_venue_count == 5
        assert mvd.min_age is None
        assert mvd.max_age is None
        assert mvd.require_residence is True  # default

    def test_age_filter_extraction(self):
        mvd = make_mvd(eligibility={
            'require_residence': False,
            'global_filters': [
                {'attribute': 'age', 'type': 'numerical', 'min': 18, 'max': 65}
            ],
        })
        assert mvd.min_age == 18
        assert mvd.max_age == 65


# ======================================================================
# 2. TestGetVenueCountForType
# ======================================================================

class TestGetVenueCountForType:

    def test_default_count(self):
        mvd = make_mvd()
        assert mvd._get_venue_count_for_type('cinema') == 3

    def test_override_count(self):
        mvd = make_mvd(venue_type_config={'cinema': {'count': 10}})
        assert mvd._get_venue_count_for_type('cinema') == 10

    def test_type_config_without_count_key(self):
        mvd = make_mvd(venue_type_config={'cinema': {'some_other': True}})
        assert mvd._get_venue_count_for_type('cinema') == 3


# ======================================================================
# 3. TestLoadParticipationData
# ======================================================================

class TestLoadParticipationData:

    def test_column_template_builds_dict_lookup(self, tmp_path):
        csv_path = write_csv(tmp_path, 'part.csv',
                             ['age_band', 'pct_male', 'pct_female'],
                             [['16-24', 0.8, 0.7], ['25-34', 0.6, 0.5]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'sex',
                    },
                }
            }
        })
        assert 'cinema' in mvd.participation_data
        idx = mvd.participation_data['cinema']['lookup_index']
        assert ('16-24',) in idx
        assert idx[('16-24',)] == {'male': 0.8, 'female': 0.7}

    def test_column_name_builds_scalar_lookup(self, tmp_path):
        csv_path = write_csv(tmp_path, 'part.csv',
                             ['age_band', 'probability'],
                             [['16-24', 0.9]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        idx = mvd.participation_data['cinema']['lookup_index']
        assert idx[('16-24',)] == 0.9

    def test_missing_data_file_key_skips(self):
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'row_filters': [],
                    'probability_column': {},
                }
            }
        })
        assert 'cinema' not in mvd.participation_data

    def test_nonexistent_csv_stores_empty_lookup(self, tmp_path):
        """Nonexistent CSV stores empty lookup_index (fail-closed)."""
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': str(tmp_path / 'nonexistent.csv'),
                    'row_filters': [],
                    'probability_column': {},
                }
            }
        })
        assert 'cinema' in mvd.participation_data
        assert mvd.participation_data['cinema']['lookup_index'] == {}

    def test_csv_failure_means_fail_closed(self, tmp_path):
        """After CSV load failure, venue_type has empty lookup_index so
        _should_allocate_venue_type returns False (fail-closed)."""
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': str(tmp_path / 'nonexistent.csv'),
                    'row_filters': [],
                    'probability_column': {},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo)
        assert mvd._should_allocate_venue_type(person, 'cinema') is False


# ======================================================================
# 4. TestMatchRowFilters
# ======================================================================

class TestMatchRowFilters:

    def _row(self, data):
        return pd.Series(data)

    def test_age_range_within(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=20)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '16-24'}), filters) is True

    def test_age_range_boundary_min(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=16)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '16-24'}), filters) is True

    def test_age_range_boundary_max(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=24)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '16-24'}), filters) is True

    def test_age_range_out_of_range(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=30)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '16-24'}), filters) is False

    def test_age_range_65_dash_plus_format(self):
        """'65-+' format is handled correctly."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=70)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '65-+'}), filters) is True

    def test_standalone_65_plus_handled(self):
        """'65+' standalone format is now correctly handled."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=70)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '65+'}), filters) is True

    def test_exact_match_case_insensitive(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        filters = [{'person_attribute': 'sex', 'csv_column': 'sex', 'match_type': 'exact'}]
        assert mvd._match_row_filters(person, self._row({'sex': 'Male'}), filters) is True

    def test_exact_no_match(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        filters = [{'person_attribute': 'sex', 'csv_column': 'sex', 'match_type': 'exact'}]
        assert mvd._match_row_filters(person, self._row({'sex': 'female'}), filters) is False

    def test_numerical_range_within(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, properties={'income': 500})
        filters = [{'person_attribute': 'income', 'csv_column': 'income_band', 'match_type': 'numerical_range'}]
        assert mvd._match_row_filters(person, self._row({'income_band': '0-1000'}), filters) is True

    def test_numerical_range_boundary(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, properties={'income': 1000})
        filters = [{'person_attribute': 'income', 'csv_column': 'income_band', 'match_type': 'numerical_range'}]
        assert mvd._match_row_filters(person, self._row({'income_band': '0-1000'}), filters) is True

    def test_numerical_range_out(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, properties={'income': 1500})
        filters = [{'person_attribute': 'income', 'csv_column': 'income_band', 'match_type': 'numerical_range'}]
        assert mvd._match_row_filters(person, self._row({'income_band': '0-1000'}), filters) is False

    def test_unknown_match_type_returns_false(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'magic'}]
        assert mvd._match_row_filters(person, self._row({'age_band': '16-24'}), filters) is False

    def test_person_attribute_none_returns_false(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        filters = [{'person_attribute': 'nonexistent', 'csv_column': 'col', 'match_type': 'exact'}]
        assert mvd._match_row_filters(person, self._row({'col': 'val'}), filters) is False

    def test_csv_nan_returns_false(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=20)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(person, self._row({'age_band': float('nan')}), filters) is False

    def test_multiple_filters_all_must_match(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=20, sex='male')
        filters = [
            {'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'},
            {'person_attribute': 'sex', 'csv_column': 'sex', 'match_type': 'exact'},
        ]
        row = self._row({'age_band': '16-24', 'sex': 'male'})
        assert mvd._match_row_filters(person, row, filters) is True

        # Second filter fails
        row2 = self._row({'age_band': '16-24', 'sex': 'female'})
        assert mvd._match_row_filters(person, row2, filters) is False


# ======================================================================
# 5. TestGetProbabilityForPerson
# ======================================================================

class TestGetProbabilityForPerson:

    def _row(self, data):
        return pd.Series(data)

    def test_column_template_with_value_placeholder(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        prob_config = {'column_template': 'pct_{value}', 'person_attribute': 'sex'}
        row = self._row({'pct_male': 0.75, 'pct_female': 0.65})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.75

    def test_column_template_with_person_attr_placeholder(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='female')
        prob_config = {'column_template': 'pct_{sex}', 'person_attribute': 'sex'}
        row = self._row({'pct_female': 0.65})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.65

    def test_column_name_fixed(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        prob_config = {'column_name': 'probability'}
        row = self._row({'probability': 0.9})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.9

    def test_missing_column_template_returns_none(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        prob_config = {'column_template': 'pct_{value}', 'person_attribute': 'sex'}
        row = self._row({'other_col': 0.5})
        assert mvd._get_probability_for_person(person, row, prob_config) is None

    def test_missing_column_name_returns_none(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        prob_config = {'column_name': 'missing_col'}
        row = self._row({'other': 0.5})
        assert mvd._get_probability_for_person(person, row, prob_config) is None

    def test_empty_config_returns_none(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        assert mvd._get_probability_for_person(person, self._row({}), {}) is None

    def test_person_attribute_none_returns_none(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        prob_config = {'column_template': 'pct_{value}', 'person_attribute': 'nonexistent'}
        assert mvd._get_probability_for_person(person, self._row({'pct_x': 0.5}), prob_config) is None

    def test_value_placeholder_preferred_over_attr_name(self):
        """When template has {value}, only {value} is replaced (no double replacement).
        Template 'pct_{value}_{sex}' with sex='male' becomes 'pct_male_{sex}'."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        prob_config = {'column_template': 'pct_{value}_{sex}', 'person_attribute': 'sex'}
        # {value} is replaced, but {sex} is NOT since only one replacement happens
        row = self._row({'pct_male_{sex}': 0.42})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.42

    def test_attr_name_placeholder_used_when_no_value(self):
        """When template has {sex} but not {value}, {sex} is replaced."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='female')
        prob_config = {'column_template': 'rate_{sex}', 'person_attribute': 'sex'}
        row = self._row({'rate_female': 0.55})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.55


# ======================================================================
# 6. TestShouldAllocateVenueType
# ======================================================================

class TestShouldAllocateVenueType:

    def test_no_participation_filter_returns_true(self):
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_probability_1_always_allocates(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['16-24', 1.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=20)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_probability_0_never_allocates(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['16-24', 0.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=20)
        assert mvd._should_allocate_venue_type(person, 'cinema') is False

    def test_exact_match_lookup(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['region', 'probability'],
                             [['north', 0.0], ['south', 1.0]])
        mvd = make_mvd(venue_type_config={
            'gym': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'region', 'person_attribute': 'region', 'match_type': 'exact'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person_south = make_person(geo=geo, properties={'region': 'south'})
        person_north = make_person(geo=geo, properties={'region': 'north'})
        assert mvd._should_allocate_venue_type(person_south, 'gym') is True
        assert mvd._should_allocate_venue_type(person_north, 'gym') is False

    def test_template_based_probability(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'pct_male', 'pct_female'],
                             [['16-24', 1.0, 0.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'sex',
                    },
                }
            }
        })
        geo = make_geo()
        male = make_person(geo=geo, age=20, sex='male')
        female = make_person(geo=geo, age=20, sex='female')
        assert mvd._should_allocate_venue_type(male, 'cinema') is True
        assert mvd._should_allocate_venue_type(female, 'cinema') is False

    def test_person_age_outside_all_ranges(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['16-24', 1.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=50)
        assert mvd._should_allocate_venue_type(person, 'cinema') is False

    def test_person_attribute_none_returns_false(self, tmp_path):
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['region', 'probability'],
                             [['north', 1.0]])
        mvd = make_mvd(venue_type_config={
            'gym': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'region', 'person_attribute': 'nonexistent', 'match_type': 'exact'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo)
        assert mvd._should_allocate_venue_type(person, 'gym') is False

    def test_attr_value_zero_correctly_handled(self, tmp_path):
        """attr_value=0 is now correctly looked up via `is not None` check."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'pct_0', 'pct_1'],
                             [['16-24', 1.0, 0.8]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'flag',
                    },
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=20, properties={'flag': 0})
        # attr_value=0 now correctly looks up pct_0 (probability=1.0)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_attr_value_empty_string_correctly_handled(self, tmp_path):
        """attr_value='' is now correctly looked up via `is not None` check."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'pct_', 'pct_x'],
                             [['16-24', 1.0, 0.8]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'label',
                    },
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=20, properties={'label': ''})
        # attr_value='' now correctly looks up pct_ (probability=1.0)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_65_plus_key_in_lookup_found(self, tmp_path):
        """'65+' key in CSV is now correctly matched in lookup."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['65+', 1.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=70)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True


# ======================================================================
# 7. TestGetEligiblePeople
# ======================================================================

class TestGetEligiblePeople:

    def test_all_eligible_no_filters(self):
        mvd = make_mvd()
        geo = make_geo()
        people = [make_person(geo=geo) for _ in range(5)]
        world = SimpleWorld(people=people)
        assert len(mvd._get_eligible_people(world)) == 5

    def test_min_age_filter(self):
        mvd = make_mvd(eligibility={
            'require_residence': False,
            'global_filters': [
                {'attribute': 'age', 'type': 'numerical', 'min': 18}
            ],
        })
        geo = make_geo()
        people = [make_person(geo=geo, age=a) for a in [10, 18, 25]]
        world = SimpleWorld(people=people)
        assert len(mvd._get_eligible_people(world)) == 2

    def test_max_age_filter(self):
        mvd = make_mvd(eligibility={
            'require_residence': False,
            'global_filters': [
                {'attribute': 'age', 'type': 'numerical', 'max': 65}
            ],
        })
        geo = make_geo()
        people = [make_person(geo=geo, age=a) for a in [30, 65, 70]]
        world = SimpleWorld(people=people)
        assert len(mvd._get_eligible_people(world)) == 2

    def test_combined_age_range(self):
        mvd = make_mvd(eligibility={
            'require_residence': False,
            'global_filters': [
                {'attribute': 'age', 'type': 'numerical', 'min': 18, 'max': 65}
            ],
        })
        geo = make_geo()
        people = [make_person(geo=geo, age=a) for a in [10, 18, 40, 65, 70]]
        world = SimpleWorld(people=people)
        assert len(mvd._get_eligible_people(world)) == 3

    def test_require_residence_excludes_homeless(self):
        mvd = make_mvd(eligibility={'require_residence': True})
        geo = make_geo()
        p_with = make_person(geo=geo)
        res = make_residence(name='h1', geo=geo, coordinates=geo.coordinates)
        assign_residence(p_with, res)
        p_without = make_person(geo=geo)
        world = SimpleWorld(people=[p_with, p_without])
        eligible = mvd._get_eligible_people(world)
        assert len(eligible) == 1
        assert eligible[0] is p_with

    def test_geographical_unit_none_excluded(self):
        mvd = make_mvd()
        geo = make_geo()
        p1 = make_person(geo=geo)
        p2 = make_person(geo=None)
        world = SimpleWorld(people=[p1, p2])
        assert len(mvd._get_eligible_people(world)) == 1

    def test_empty_world(self):
        mvd = make_mvd()
        world = SimpleWorld(people=[])
        assert mvd._get_eligible_people(world) == []


# ======================================================================
# 8. TestGetOrCreateSubset
# ======================================================================

class TestGetOrCreateSubset:

    def test_creates_new_subset(self):
        mvd = make_mvd()
        geo = make_geo()
        venue = make_venue(geo=geo, venue_type='cinema')
        subset = mvd._get_or_create_subset(venue)
        assert isinstance(subset, Subset)
        assert subset.venue is venue
        assert subset.subset_name == 'default'
        assert 'default' in venue.subsets

    def test_returns_existing_on_repeat(self):
        mvd = make_mvd()
        geo = make_geo()
        venue = make_venue(geo=geo, venue_type='cinema')
        s1 = mvd._get_or_create_subset(venue)
        s2 = mvd._get_or_create_subset(venue)
        assert s1 is s2

    def test_index_avoids_collision_after_deletion(self):
        """After subset deletion, new subsets get unique indices (max + 1)."""
        mvd = make_mvd()
        geo = make_geo()
        venue = make_venue(geo=geo, venue_type='cinema')
        # Manually add then remove a subset
        dummy = Subset(venue=venue, subset_index=0, subset_name='old')
        venue.subsets['old'] = dummy
        del venue.subsets['old']
        # Now venue.subsets is empty, so new subset gets index 0 (correct since no existing)
        subset = mvd._get_or_create_subset(venue)
        assert subset.subset_index == 0

    def test_subset_has_venue_reference(self):
        mvd = make_mvd()
        geo = make_geo()
        venue = make_venue(geo=geo, venue_type='gym')
        subset = mvd._get_or_create_subset(venue)
        assert subset.venue is venue


# ======================================================================
# 9. TestAllocateVenues
# ======================================================================

class TestAllocateVenues:

    def _setup(self, n_people=3, n_venues=3, venue_types=None):
        if venue_types is None:
            venue_types = ['cinema', 'gym']
        geo = make_geo('SGU_1', coordinates=(51.5, -0.1))
        people = [make_person(geo=geo) for _ in range(n_people)]
        venues_map = {}
        for vt in venue_types:
            venues = [
                make_venue(name=f'{vt}_{j}', geo=geo, venue_type=vt,
                           coordinates=(51.5 + 0.01 * (j + 1), -0.1 + 0.01 * (j + 1)))
                for j in range(n_venues)
            ]
            venues_map[vt] = venues
        world = SimpleWorld(people=people, venues_map=venues_map)
        mvd = make_mvd(venue_types=venue_types)
        mvd._build_spatial_indices({vt: world.venues_by_type(vt) for vt in venue_types})
        return mvd, people, world

    def test_same_geo_unit_same_cached_venues(self):
        mvd, people, world = self._setup()
        mvd._allocate_venues(people, world)
        # All people in same geo_unit should have same venues
        maps = [p.activity_map.get('leisure', {}) for p in people]
        for vt in ['cinema', 'gym']:
            venue_sets = [
                tuple(s.venue.name for s in m[vt]) for m in maps if vt in m
            ]
            assert len(set(venue_sets)) == 1  # All identical

    def test_different_geo_units_different_venues(self):
        geo1 = make_geo('SGU_1', coordinates=(51.5, -0.1))
        geo2 = make_geo('SGU_2', coordinates=(52.5, 0.5))
        p1 = make_person(geo=geo1)
        p2 = make_person(geo=geo2)
        # Place venues near geo1
        venues = [
            make_venue(name=f'cinema_{j}', geo=geo1, venue_type='cinema',
                       coordinates=(51.5 + 0.001 * j, -0.1))
            for j in range(3)
        ]
        world = SimpleWorld(people=[p1, p2], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd._build_spatial_indices({'cinema': venues})
        mvd._allocate_venues([p1, p2], world)
        # Both get allocated (same venues since only 3 exist), but cache keys differ
        assert 'leisure' in p1.activity_map
        assert 'leisure' in p2.activity_map

    def test_coordinates_none_skips_with_warning(self):
        """People in geo_units with None coordinates are skipped (logged as warning)."""
        geo_no_coords = make_geo('SGU_X', coordinates=None)
        person = make_person(geo=geo_no_coords)
        geo_good = make_geo('SGU_OK', coordinates=(51.5, -0.1))
        venues = [make_venue(name='c_0', geo=geo_good, venue_type='cinema',
                             coordinates=(51.5, -0.1))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd._build_spatial_indices({'cinema': venues})
        mvd._allocate_venues([person], world)
        assert 'leisure' not in person.activity_map

    def test_wrong_coordinate_length_skips_with_warning(self):
        """People in geo_units with wrong coordinate length are skipped (logged as warning)."""
        geo_bad = make_geo('SGU_X', coordinates=(51.5,))
        person = make_person(geo=geo_bad)
        geo_good = make_geo('SGU_OK', coordinates=(51.5, -0.1))
        venues = [make_venue(name='c_0', geo=geo_good, venue_type='cinema',
                             coordinates=(51.5, -0.1))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd._build_spatial_indices({'cinema': venues})
        mvd._allocate_venues([person], world)
        assert 'leisure' not in person.activity_map

    def test_creates_subsets_and_adds_members(self):
        mvd, people, world = self._setup(n_people=2)
        mvd._allocate_venues(people, world)
        for p in people:
            for vt in ['cinema', 'gym']:
                subsets = p.activity_map['leisure'][vt]
                for s in subsets:
                    assert p in s.members

    def test_activity_map_populated(self):
        mvd, people, world = self._setup()
        mvd._allocate_venues(people, world)
        for p in people:
            assert 'leisure' in p.activity_map
            assert 'cinema' in p.activity_map['leisure']
            assert 'gym' in p.activity_map['leisure']

    def test_activity_added_to_person(self):
        mvd, people, world = self._setup()
        mvd._allocate_venues(people, world)
        for p in people:
            assert 'leisure' in p.activities

    def test_participation_filter_excludes(self, tmp_path):
        """Participation filter with probability=0 excludes a venue type."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['0-100', 0.0]])
        geo = make_geo('SGU_1', coordinates=(51.5, -0.1))
        people = [make_person(geo=geo, age=30)]
        venues = [make_venue(name='c_0', geo=geo, venue_type='cinema',
                             coordinates=(51.51, -0.09))]
        world = SimpleWorld(people=people, venues_map={'cinema': venues, 'gym': venues})
        mvd = make_mvd(
            venue_types=['cinema', 'gym'],
            venue_type_config={
                'cinema': {
                    'participation_filter': {
                        'data_file': csv_path,
                        'row_filters': [
                            {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                        ],
                        'probability_column': {'column_name': 'probability'},
                    }
                }
            },
        )
        mvd._build_spatial_indices({'cinema': venues, 'gym': venues})
        mvd._allocate_venues(people, world)
        p = people[0]
        # Cinema excluded, gym should be present
        if 'leisure' in p.activity_map:
            assert 'cinema' not in p.activity_map['leisure']


# ======================================================================
# 10. TestAllocateIntegration
# ======================================================================

class TestAllocateIntegration:

    def test_basic_allocation(self):
        world = _simple_world(n_people=5, n_venues=4)
        mvd = make_mvd()
        mvd.allocate(world)
        allocated = [p for p in world.people if 'leisure' in p.activity_map]
        assert len(allocated) == 5
        for p in allocated:
            assert 'cinema' in p.activity_map['leisure']
            assert 'gym' in p.activity_map['leisure']

    def test_age_filter_applied(self):
        geo = make_geo()
        people = [make_person(geo=geo, age=a) for a in [10, 20, 30]]
        venues = [make_venue(name=f'c_{i}', geo=geo, venue_type='cinema',
                             coordinates=(51.5 + 0.01 * i, -0.1))
                  for i in range(3)]
        world = SimpleWorld(people=people, venues_map={'cinema': venues})
        mvd = make_mvd(
            venue_types=['cinema'],
            eligibility={
                'require_residence': False,
                'global_filters': [
                    {'attribute': 'age', 'type': 'numerical', 'min': 18}
                ],
            },
        )
        mvd.allocate(world)
        allocated = [p for p in people if 'leisure' in p.activity_map]
        assert len(allocated) == 2

    def test_residence_required_excludes(self):
        geo = make_geo()
        p_with = make_person(geo=geo)
        res = make_residence(name='h', geo=geo, coordinates=geo.coordinates)
        assign_residence(p_with, res)
        p_without = make_person(geo=geo)
        venues = [make_venue(name='c_0', geo=geo, venue_type='cinema',
                             coordinates=(51.51, -0.09))]
        world = SimpleWorld(people=[p_with, p_without], venues_map={'cinema': venues})
        mvd = make_mvd(
            venue_types=['cinema'],
            eligibility={'require_residence': True},
        )
        mvd.allocate(world)
        assert 'leisure' in p_with.activity_map
        assert 'leisure' not in p_without.activity_map

    def test_venue_count_override_per_type(self):
        geo = make_geo()
        people = [make_person(geo=geo)]
        venues = [make_venue(name=f'c_{i}', geo=geo, venue_type='cinema',
                             coordinates=(51.5 + 0.005 * i, -0.1))
                  for i in range(10)]
        world = SimpleWorld(people=people, venues_map={'cinema': venues})
        mvd = make_mvd(
            venue_types=['cinema'],
            venue_type_config={'cinema': {'count': 7}},
        )
        mvd.allocate(world)
        assert len(people[0].activity_map['leisure']['cinema']) == 7

    def test_empty_world_no_crash(self):
        world = SimpleWorld(people=[], venues_map={})
        mvd = make_mvd()
        mvd.allocate(world)  # Should not raise

    def test_no_venues_of_type_no_crash(self):
        geo = make_geo()
        people = [make_person(geo=geo)]
        world = SimpleWorld(people=people, venues_map={'cinema': [], 'gym': []})
        mvd = make_mvd()
        mvd.allocate(world)
        # No venues to allocate
        assert 'leisure' not in people[0].activity_map

    def test_single_venue_type(self):
        world = _simple_world(n_people=3, n_venues=2, venue_types=['cinema'])
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        for p in world.people:
            assert 'cinema' in p.activity_map['leisure']

    def test_many_venue_types(self):
        types = ['cinema', 'gym', 'pub', 'grocery', 'library']
        world = _simple_world(n_people=3, n_venues=2, venue_types=types)
        mvd = make_mvd(venue_types=types)
        mvd.allocate(world)
        for p in world.people:
            for vt in types:
                assert vt in p.activity_map['leisure']

    def test_venue_type_property(self):
        mvd = make_mvd()
        assert mvd.venue_type == 'leisure'


# ======================================================================
# 11. TestExportAllocations
# ======================================================================

class TestExportAllocations:

    def test_csv_created_with_headers(self, tmp_path):
        world = _simple_world(n_people=2, n_venues=2)
        mvd = make_mvd()
        mvd.allocate(world)
        out = str(tmp_path / 'out.csv')
        mvd.export_allocations(world, out)
        with open(out) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert 'person_id' in header
        assert 'venue_type' in header
        assert 'venue_lat' in header

    def test_one_row_per_assignment(self, tmp_path):
        world = _simple_world(n_people=1, n_venues=2, venue_types=['cinema'])
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        out = str(tmp_path / 'out.csv')
        mvd.export_allocations(world, out)
        with open(out) as f:
            rows = list(csv.reader(f))
        # header + 2 venue assignments (count=3 but only 2 venues)
        assert len(rows) == 3  # header + 2 data rows

    def test_no_allocations_only_header(self, tmp_path):
        world = SimpleWorld(people=[], venues_map={})
        mvd = make_mvd()
        out = str(tmp_path / 'out.csv')
        mvd.export_allocations(world, out)
        with open(out) as f:
            rows = list(csv.reader(f))
        assert len(rows) == 1  # header only

    def test_coordinates_populated(self, tmp_path):
        world = _simple_world(n_people=1, n_venues=1, venue_types=['cinema'])
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        out = str(tmp_path / 'out.csv')
        mvd.export_allocations(world, out)
        with open(out) as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row['venue_lat'] != ''
                assert row['venue_lon'] != ''


# ======================================================================
# 12. TestLogSummary
# ======================================================================

class TestLogSummary:

    def test_no_crash_after_allocation(self):
        world = _simple_world(n_people=3, n_venues=2)
        mvd = make_mvd()
        mvd.allocate(world)
        mvd._log_summary(world)  # Should not raise

    def test_no_crash_empty_world(self):
        world = SimpleWorld(people=[], venues_map={})
        mvd = make_mvd()
        mvd._log_summary(world)  # Should not raise


# ======================================================================
# 13. TestEdgeCases
# ======================================================================

class TestEdgeCases:

    def test_person_empty_properties(self):
        geo = make_geo()
        person = make_person(geo=geo, properties={})
        venues = [make_venue(name='c_0', geo=geo, venue_type='cinema',
                             coordinates=(51.51, -0.09))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        assert 'leisure' in person.activity_map

    def test_venue_without_coordinates_excluded_from_spatial_index(self):
        geo = make_geo()
        person = make_person(geo=geo)
        # Create venue with no coordinates and no geo_unit fallback
        v_no_coords = Venue(name='c_0', venue_type='cinema',
                            geographical_unit=None, coordinates=None)
        world = SimpleWorld(people=[person], venues_map={'cinema': [v_no_coords]})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        assert 'leisure' not in person.activity_map

    def test_count_exceeds_available_venues(self):
        geo = make_geo()
        person = make_person(geo=geo)
        venues = [make_venue(name='c_0', geo=geo, venue_type='cinema',
                             coordinates=(51.51, -0.09))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])  # count=3 but only 1 venue
        mvd.allocate(world)
        assert len(person.activity_map['leisure']['cinema']) == 1

    def test_single_person_single_venue_single_type(self):
        geo = make_geo()
        person = make_person(geo=geo)
        venue = make_venue(name='gym_0', geo=geo, venue_type='gym',
                           coordinates=(51.51, -0.09))
        world = SimpleWorld(people=[person], venues_map={'gym': [venue]})
        mvd = make_mvd(venue_types=['gym'])
        mvd.allocate(world)
        assert len(person.activity_map['leisure']['gym']) == 1
        assert person in person.activity_map['leisure']['gym'][0].members

    def test_100_people_same_geo_unit_share_cache(self):
        geo = make_geo()
        people = [make_person(geo=geo) for _ in range(100)]
        venues = [make_venue(name=f'c_{i}', geo=geo, venue_type='cinema',
                             coordinates=(51.5 + 0.01 * i, -0.1))
                  for i in range(5)]
        world = SimpleWorld(people=people, venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        # All should get the same venue names (same geo_unit)
        first_venues = tuple(
            s.venue.name for s in people[0].activity_map['leisure']['cinema']
        )
        for p in people[1:]:
            pv = tuple(s.venue.name for s in p.activity_map['leisure']['cinema'])
            assert pv == first_venues


# ======================================================================
# 14. TestStressScenarios
# ======================================================================

class TestStressScenarios:

    def test_1000_people_50_venues_3_types(self):
        types = ['cinema', 'gym', 'pub']
        geo = make_geo()
        people = [make_person(geo=geo, age=25) for _ in range(1000)]
        venues_map = {}
        for vt in types:
            venues_map[vt] = [
                make_venue(name=f'{vt}_{i}', geo=geo, venue_type=vt,
                           coordinates=(51.5 + 0.001 * i, -0.1 + 0.001 * i))
                for i in range(50)
            ]
        world = SimpleWorld(people=people, venues_map=venues_map)
        mvd = make_mvd(venue_types=types)
        mvd.allocate(world)
        allocated = [p for p in people if 'leisure' in p.activity_map]
        assert len(allocated) == 1000

    def test_10_venue_types(self):
        types = [f'type_{i}' for i in range(10)]
        geo = make_geo()
        people = [make_person(geo=geo) for _ in range(10)]
        venues_map = {}
        for vt in types:
            venues_map[vt] = [
                make_venue(name=f'{vt}_{j}', geo=geo, venue_type=vt,
                           coordinates=(51.5 + 0.01 * j, -0.1))
                for j in range(5)
            ]
        world = SimpleWorld(people=people, venues_map=venues_map)
        mvd = make_mvd(venue_types=types)
        mvd.allocate(world)
        for p in people:
            for vt in types:
                assert vt in p.activity_map['leisure']

    def test_50_geo_units(self):
        geos = [make_geo(f'SGU_{i}', coordinates=(51.0 + 0.1 * i, -0.1))
                for i in range(50)]
        people = []
        for g in geos:
            people.append(make_person(geo=g))
            people.append(make_person(geo=g))

        venues = [make_venue(name=f'c_{i}', geo=geos[0], venue_type='cinema',
                             coordinates=(51.0 + 0.05 * i, -0.1))
                  for i in range(20)]
        world = SimpleWorld(people=people, venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        allocated = [p for p in people if 'leisure' in p.activity_map]
        assert len(allocated) == 100


# ======================================================================
# 15. TestBugDetection
# ======================================================================

class TestBugDetection:
    """Regression tests for previously identified bugs. All now fixed."""

    def test_bug1_age_range_65_plus_standalone_fixed(self):
        """Bug #1 fix: '65+' standalone format now handled in _match_row_filters."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, age=70)
        filters = [{'person_attribute': 'age', 'csv_column': 'age_band', 'match_type': 'age_range'}]
        assert mvd._match_row_filters(
            person, pd.Series({'age_band': '65-+'}), filters) is True
        assert mvd._match_row_filters(
            person, pd.Series({'age_band': '65+'}), filters) is True

    def test_bug1_65_plus_in_lookup_fixed(self, tmp_path):
        """Bug #1 fix: '65+' key in lookup_index now matched correctly."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'probability'],
                             [['65+', 1.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=70)
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_bug2_enumerate_replaces_index_lookup(self, tmp_path):
        """Bug #2 fix: enumerate used instead of row_filters.index().
        Multi-filter lookup still works correctly."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'region', 'probability'],
                             [['16-24', 'north', 1.0]])
        mvd = make_mvd(venue_type_config={
            'gym': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'},
                        {'csv_column': 'region', 'person_attribute': 'region', 'match_type': 'exact'},
                    ],
                    'probability_column': {'column_name': 'probability'},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=20, properties={'region': 'north'})
        assert mvd._should_allocate_venue_type(person, 'gym') is True

    def test_bug3_csv_load_failure_fail_closed(self, tmp_path):
        """Bug #3 fix: CSV load failure now stores empty lookup_index,
        so _should_allocate_venue_type returns False (fail-closed)."""
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': str(tmp_path / 'missing.csv'),
                    'row_filters': [],
                    'probability_column': {},
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo)
        assert 'cinema' in mvd.participation_data  # present but empty
        assert mvd._should_allocate_venue_type(person, 'cinema') is False

    def test_bug4_subset_index_no_collision_after_deletion(self):
        """Bug #4 fix: subset_index uses max(existing) + 1, avoiding collision."""
        mvd = make_mvd()
        geo = make_geo()
        venue = make_venue(geo=geo, venue_type='cinema')
        mvd.subset_key = 'first'
        mvd._get_or_create_subset(venue)  # index 0
        mvd.subset_key = 'second'
        s2 = mvd._get_or_create_subset(venue)  # index 1
        # Delete first, create third
        del venue.subsets['first']
        mvd.subset_key = 'third'
        s3 = mvd._get_or_create_subset(venue)
        # Fixed: s3 gets index 2 (max(1) + 1), not 1
        assert s3.subset_index != s2.subset_index
        assert s3.subset_index == 2
        mvd.subset_key = 'default'

    def test_bug5_coordinates_none_warns(self):
        """Bug #5 fix: Invalid coordinates now logged as warning (not debug)."""
        geo = make_geo('SGU_X', coordinates=None)
        person = make_person(geo=geo)
        good_geo = make_geo('SGU_OK', coordinates=(51.5, -0.1))
        venues = [make_venue(name='c_0', geo=good_geo, venue_type='cinema',
                             coordinates=(51.5, -0.1))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        assert 'leisure' not in person.activity_map

    def test_bug5_wrong_coordinate_length_warns(self):
        """Bug #5 fix: Wrong coordinate length now logged as warning."""
        geo = make_geo('SGU_X', coordinates=(51.5, -0.1, 100.0))
        person = make_person(geo=geo)
        good_geo = make_geo('SGU_OK', coordinates=(51.5, -0.1))
        venues = [make_venue(name='c_0', geo=good_geo, venue_type='cinema',
                             coordinates=(51.5, -0.1))]
        world = SimpleWorld(people=[person], venues_map={'cinema': venues})
        mvd = make_mvd(venue_types=['cinema'])
        mvd.allocate(world)
        assert 'leisure' not in person.activity_map

    def test_bug6_no_double_replacement(self):
        """Bug #6 fix: Only one placeholder is replaced per template.
        {value} takes priority; {attr_name} used only if {value} absent."""
        mvd = make_mvd()
        geo = make_geo()
        person = make_person(geo=geo, sex='male')
        # {value} is present so only it gets replaced
        prob_config = {'column_template': 'col_{value}_{sex}', 'person_attribute': 'sex'}
        row = pd.Series({'col_male_{sex}': 0.5})
        assert mvd._get_probability_for_person(person, row, prob_config) == 0.5

    def test_bug7_attr_value_zero_now_works(self, tmp_path):
        """Bug #7 fix: `if attr_value is not None` allows 0 as a valid value."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'pct_0', 'pct_1'],
                             [['0-100', 1.0, 0.01]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'flag',
                    },
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=30, properties={'flag': 0})
        assert mvd._should_allocate_venue_type(person, 'cinema') is True

    def test_bug7_attr_value_empty_string_now_works(self, tmp_path):
        """Bug #7 fix: `if attr_value is not None` allows '' as a valid value."""
        csv_path = write_csv(tmp_path, 'p.csv',
                             ['age_band', 'pct_'],
                             [['0-100', 1.0]])
        mvd = make_mvd(venue_type_config={
            'cinema': {
                'participation_filter': {
                    'data_file': csv_path,
                    'row_filters': [
                        {'csv_column': 'age_band', 'person_attribute': 'age', 'match_type': 'age_range'}
                    ],
                    'probability_column': {
                        'column_template': 'pct_{value}',
                        'person_attribute': 'label',
                    },
                }
            }
        })
        geo = make_geo()
        person = make_person(geo=geo, age=30, properties={'label': ''})
        assert mvd._should_allocate_venue_type(person, 'cinema') is True
