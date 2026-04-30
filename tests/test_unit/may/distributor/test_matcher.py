"""
Unit tests for VenueMatcher.

Covers: build_attribute_index, venue_accepts_person, select_venue,
filter_venues_with_expansion.
"""

import pytest
import numpy as np

from conftest import make_geo, make_person, make_venue, make_vd, build_world


def _school_venues(geo, n=5):
    """Create N school venues spread ~1 km apart."""
    venues = []
    for i in range(n):
        coords = (geo.coordinates[0] + 0.01 * (i + 1), geo.coordinates[1])
        venues.append(make_venue(f'school_{i}', geo, coordinates=coords))
    return venues


# ==============================================================================
# TestBuildAttributeIndex
# ==============================================================================

class TestBuildAttributeIndex:
    def test_empty_attributes(self):
        vd = make_vd()
        geo = make_geo()
        venues = _school_venues(geo, 3)
        vd.matcher.build_attribute_index(venues)
        assert vd.matcher.attribute_index_built is True
        assert vd.matcher.num_constraints == {}

    def test_numerical_constraints_populated(self):
        vd = make_vd(eligibility={
            'global_filters': [], 'exclude': {},
            'attributes': [{
                'name': 'age', 'type': 'numerical',
                'venue_constraints': {'min_column': 'min_age', 'max_column': 'max_age'},
            }],
        })
        geo = make_geo()
        v1 = make_venue('s1', geo, properties={'min_age': 5, 'max_age': 11})
        v2 = make_venue('s2', geo, properties={'min_age': 11, 'max_age': 16})
        vd.matcher.build_attribute_index([v1, v2])
        np.testing.assert_array_equal(vd.matcher.num_constraints['age']['min'], [5, 11])
        np.testing.assert_array_equal(vd.matcher.num_constraints['age']['max'], [11, 16])

    def test_categorical_index_built(self):
        vd = make_vd(eligibility={
            'global_filters': [], 'exclude': {},
            'attributes': [{
                'name': 'sex', 'type': 'categorical', 'venue_column': 'gender_type',
                'case_sensitive': False,
                'matching_rules': {'boys': ['male'], 'girls': ['female'], 'mixed': ['male', 'female']},
            }],
        })
        geo = make_geo()
        v1 = make_venue('boys_school', geo, properties={'gender_type': 'Boys'})
        v2 = make_venue('mixed_school', geo, properties={'gender_type': 'Mixed'})
        vd.matcher.build_attribute_index([v1, v2])
        male_ids = vd.matcher.categorical_index[('sex', 'male')]
        assert id(v1) in male_ids
        assert id(v2) in male_ids

    def test_assume_if_missing(self):
        vd = make_vd(eligibility={
            'global_filters': [], 'exclude': {},
            'attributes': [{
                'name': 'sex', 'type': 'categorical', 'venue_column': 'gender_type',
                'assume_if_missing': 'Mixed', 'case_sensitive': False,
                'matching_rules': {'mixed': ['male', 'female']},
            }],
        })
        geo = make_geo()
        v = make_venue('no_type', geo, properties={})
        vd.matcher.build_attribute_index([v])
        assert id(v) in vd.matcher.categorical_index.get(('sex', 'male'), set())


# ==============================================================================
# TestVenueAcceptsPerson
# ==============================================================================

class TestVenueAcceptsPerson:
    def _age_vd(self, venues):
        vd = make_vd(eligibility={
            'global_filters': [], 'exclude': {},
            'attributes': [{
                'name': 'age', 'type': 'numerical',
                'venue_constraints': {'min_column': 'min_age', 'max_column': 'max_age'},
            }],
        })
        vd.matcher.build_attribute_index(venues)
        return vd

    def test_within_range_accepted(self):
        geo = make_geo()
        v = make_venue('s', geo, properties={'min_age': 5, 'max_age': 11})
        vd = self._age_vd([v])
        assert vd.matcher.venue_accepts_person(make_person(geo, age=8), v, vd.matcher.numerical_match_rules) is True

    def test_below_min_rejected(self):
        geo = make_geo()
        v = make_venue('s', geo, properties={'min_age': 5, 'max_age': 11})
        vd = self._age_vd([v])
        assert vd.matcher.venue_accepts_person(make_person(geo, age=3), v, vd.matcher.numerical_match_rules) is False

    def test_above_max_rejected(self):
        geo = make_geo()
        v = make_venue('s', geo, properties={'min_age': 5, 'max_age': 11})
        vd = self._age_vd([v])
        assert vd.matcher.venue_accepts_person(make_person(geo, age=15), v, vd.matcher.numerical_match_rules) is False

    def test_sentinel_uses_int32_extremes(self):
        """Bug #8 fix: sentinels use int32 min/max instead of -1000/1000,
        so real constraints near those values are not silently ignored."""
        geo = make_geo()
        v = make_venue('s', geo, properties={})  # no min_age/max_age -> defaults to int32 min/max
        vd = self._age_vd([v])
        assert vd.matcher.num_constraints['age']['min'][0] == np.iinfo(np.int32).min
        assert vd.matcher.num_constraints['age']['max'][0] == np.iinfo(np.int32).max
        # Any realistic age passes because sentinel is at int32 extremes
        assert vd.matcher.venue_accepts_person(make_person(geo, age=-5000), v, vd.matcher.numerical_match_rules) is True

    def test_none_attribute_returns_false(self):
        geo = make_geo()
        v = make_venue('s', geo, properties={'min_age': 5, 'max_age': 11})
        vd = make_vd(eligibility={
            'global_filters': [], 'exclude': {},
            'attributes': [{
                'name': 'nonexistent_attr', 'type': 'numerical',
                'venue_constraints': {'min_column': 'min_age', 'max_column': 'max_age'},
            }],
        })
        vd.matcher.build_attribute_index([v])
        assert vd.matcher.venue_accepts_person(make_person(geo), v, vd.matcher.numerical_match_rules) is False


# ==============================================================================
# TestSelectVenue
# ==============================================================================

class TestSelectVenue:
    def test_closest_selects_nearest(self):
        vd = make_vd(allocation={'strategy': 'closest', 'fixed_capacity': 100})
        geo = make_geo()
        venues = _school_venues(geo, 5)
        vd.matcher.build_attribute_index(venues)
        assert vd.matcher.select_venue(None, venues, geo.coordinates) == venues[0]

    def test_random_returns_a_venue(self):
        vd = make_vd(allocation={'strategy': 'random', 'fixed_capacity': 100})
        geo = make_geo()
        venues = _school_venues(geo, 5)
        np.random.seed(42)
        assert vd.matcher.select_venue(None, venues, geo.coordinates) in venues

    def test_proportional_returns_a_venue(self):
        vd = make_vd(allocation={'strategy': 'proportional', 'fixed_capacity': 100})
        geo = make_geo()
        venues = _school_venues(geo, 5)
        np.random.seed(42)
        assert vd.matcher.select_venue(None, venues, geo.coordinates) in venues

    def test_closest_balanced_all_full_falls_back_to_closest(self):
        vd = make_vd(allocation={'strategy': 'closest_balanced', 'fixed_capacity': 1})
        geo = make_geo()
        venues = _school_venues(geo, 3)
        vd.matcher.build_attribute_index(venues)
        for v in venues:
            vd._increment_venue_count(v)
        selected = vd.matcher.select_venue(None, venues, geo.coordinates)
        assert selected == venues[0]

    def test_largest_capacity(self):
        vd = make_vd(allocation={'strategy': 'largest_capacity', 'fixed_capacity': 100})
        geo = make_geo()
        venues = _school_venues(geo, 3)
        assert vd.matcher.select_venue(None, venues, geo.coordinates) in venues

    def test_unknown_strategy_returns_first(self):
        vd = make_vd(allocation={'strategy': 'nonexistent', 'fixed_capacity': 100})
        geo = make_geo()
        venues = _school_venues(geo, 3)
        assert vd.matcher.select_venue(None, venues, geo.coordinates) == venues[0]

    def test_empty_list_returns_none(self):
        vd = make_vd()
        assert vd.matcher.select_venue(None, [], (51.5, -0.1)) is None


# ==============================================================================
# TestFilterVenuesWithExpansion
# ==============================================================================

class TestFilterVenuesWithExpansion:
    def test_initial_pool_match_no_expansion(self):
        vd = make_vd()
        geo = make_geo()
        venues = _school_venues(geo, 3)
        vd.matcher.build_attribute_index(venues)
        person = make_person(geo, age=10)
        result = vd.matcher.filter_venues_with_expansion(
            person, venues, venues, geo.coordinates, [5]
        )
        assert len(result) == 3

    def test_empty_pool_single_limit_returns_empty(self):
        vd = make_vd(venue_selection={'consider_by': 'count', 'count': 5})
        geo = make_geo()
        venues = _school_venues(geo, 3)
        vd.matcher.build_attribute_index(venues)
        result = vd.matcher.filter_venues_with_expansion(
            make_person(geo), venues, [], geo.coordinates, [5]
        )
        assert result == []
