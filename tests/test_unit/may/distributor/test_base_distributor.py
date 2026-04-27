"""
Unit tests for BaseDistributor utility methods.

Covers: _normalize_value, _get_venue_capacity, _haversine_distance,
_get_person_attribute, _get_nested_value_with_dict_support.
"""

import pytest
import numpy as np

from may.venue_distributor.base_distributor import BaseDistributor

from conftest import make_geo, make_person, make_venue, make_residence, assign_residence


def _make_base(**config_overrides):
    config = {
        'settings': {'verbose': False},
        'venue_selection': {'venue_geo_level': 'SGU'},
        'allocation': {},
    }
    config.update(config_overrides)
    return BaseDistributor(config_dict=config)


# ==============================================================================
# TestNormalizeValue
# ==============================================================================

class TestNormalizeValue:
    def setup_method(self):
        self.bd = _make_base()

    def test_none_returns_empty(self):
        assert self.bd._normalize_value(None) == ""

    def test_empty_string_returns_empty(self):
        assert self.bd._normalize_value('') == ""

    def test_float_integer_returns_int_string(self):
        assert self.bd._normalize_value(787.0) == "787"

    def test_float_decimal_preserved(self):
        assert self.bd._normalize_value(3.14) == "3.14"

    def test_string_dot_zero_trimmed(self):
        assert self.bd._normalize_value("787.0") == "787"

    def test_whitespace_stripped(self):
        assert self.bd._normalize_value("  hello  ") == "hello"

    def test_numpy_float_integer(self):
        assert self.bd._normalize_value(np.float64(42.0)) == "42"


# ==============================================================================
# TestGetVenueCapacity
# ==============================================================================

class TestGetVenueCapacity:
    def test_fixed_capacity_overrides_all(self):
        bd = _make_base(allocation={'fixed_capacity': 50})
        venue = make_venue('v', make_geo())
        assert bd._get_venue_capacity(venue) == 50

    def test_capacity_column_from_properties(self):
        bd = _make_base(allocation={'capacity_column': 'max_cap'})
        venue = make_venue('v', make_geo(), properties={'max_cap': 25})
        assert bd._get_venue_capacity(venue) == 25

    def test_no_hardcoded_heuristic_fallthrough(self):
        """No capacity_column or fixed_capacity -> falls through to capacity_handling,
        never guesses from venue properties."""
        bd = _make_base(allocation={})
        venue = make_venue('v', make_geo(), properties={'Noofroomscode': 100, 'SchoolCapacity': 50})
        # Without explicit config, capacity is treated as missing (default: ignore -> 1M)
        assert bd._get_venue_capacity(venue) == 1_000_000

    def test_capacity_column_reads_any_property(self):
        """Any venue property can be used as capacity via capacity_column in YAML."""
        bd = _make_base(allocation={'capacity_column': 'Noofroomscode'})
        venue = make_venue('v', make_geo(), properties={'Noofroomscode': 100})
        assert bd._get_venue_capacity(venue) == 100

    def test_if_missing_ignore_returns_million(self):
        bd = _make_base(allocation={'capacity_handling': {'if_missing': 'ignore'}})
        venue = make_venue('v', make_geo())
        assert bd._get_venue_capacity(venue) == 1_000_000

    def test_if_missing_default_returns_configured(self):
        bd = _make_base(allocation={
            'capacity_handling': {'if_missing': 'default', 'default_capacity': 42}
        })
        venue = make_venue('v', make_geo())
        assert bd._get_venue_capacity(venue) == 42

    def test_if_zero_skip_returns_zero(self):
        bd = _make_base(allocation={'capacity_column': 'cap'})
        venue = make_venue('v', make_geo(), properties={'cap': 0})
        assert bd._get_venue_capacity(venue) == 0

    def test_if_zero_ignore_returns_million(self):
        bd = _make_base(allocation={
            'capacity_column': 'cap',
            'capacity_handling': {'if_zero': 'ignore'}
        })
        venue = make_venue('v', make_geo(), properties={'cap': 0})
        assert bd._get_venue_capacity(venue) == 1_000_000


# ==============================================================================
# TestHaversineDistance
# ==============================================================================

class TestHaversineDistance:
    def setup_method(self):
        self.bd = _make_base()

    def test_same_point_is_zero(self):
        assert self.bd._haversine_distance((51.5, -0.1), (51.5, -0.1)) == 0.0

    def test_london_to_paris(self):
        dist = self.bd._haversine_distance((51.5074, -0.1278), (48.8566, 2.3522))
        assert 340 < dist < 350, f"Expected ~343 km, got {dist:.1f}"

    def test_vectorized_matches_scalar(self):
        loc1 = (51.5074, -0.1278)
        locs = [(48.8566, 2.3522), (52.52, 13.405)]
        scalar_dists = [self.bd._haversine_distance(loc1, l) for l in locs]
        vec_dists = self.bd._haversine_distance_vectorized(loc1, np.array(locs))
        np.testing.assert_allclose(vec_dists, scalar_dists, rtol=1e-6)


# ==============================================================================
# TestGetPersonAttribute
# ==============================================================================

class TestGetPersonAttribute:
    def setup_method(self):
        self.bd = _make_base()

    def test_residence_path(self):
        geo = make_geo()
        person = make_person(geo)
        residence = make_residence('Home1', geo)
        assign_residence(person, residence)
        assert self.bd._get_person_attribute('residence.name', person) == 'Home1'

    def test_properties_path(self):
        person = make_person(properties={'Occode': 42})
        assert self.bd._get_person_attribute('Occode', person) == 42

    def test_direct_attribute(self):
        person = make_person(age=25)
        assert self.bd._get_person_attribute('age', person) == 25

    def test_missing_returns_none(self):
        person = make_person()
        assert self.bd._get_person_attribute('nonexistent', person) is None

    def test_residence_none(self):
        person = make_person()
        assert self.bd._get_person_attribute('residence.name', person) is None

    def test_nested_path(self):
        geo = make_geo('SGU_1')
        person = make_person(geo)
        assert self.bd._get_person_attribute('geographical_unit.name', person) == 'SGU_1'
