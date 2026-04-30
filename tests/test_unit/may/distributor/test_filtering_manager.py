"""
Unit tests for FilteringManager.

Covers: _check_condition, person_excluded, apply_global_filters,
apply_probability_filter, person_matches_filters.
"""

import pytest
import numpy as np

from conftest import (
    make_geo, make_person, make_venue, make_residence, assign_residence, make_vd,
)


# ==============================================================================
# TestCheckCondition
# ==============================================================================

class TestCheckCondition:
    def setup_method(self):
        self.fm = make_vd().filtering

    def test_numerical_within_range(self):
        assert self.fm._check_condition(30, {'type': 'numerical', 'min': 5, 'max': 65}) is True

    def test_numerical_below_min(self):
        assert self.fm._check_condition(10, {'type': 'numerical', 'min': 18}) is False

    def test_numerical_above_max(self):
        assert self.fm._check_condition(70, {'type': 'numerical', 'max': 65}) is False

    def test_numerical_no_constraints(self):
        assert self.fm._check_condition(999, {'type': 'numerical'}) is True

    def test_categorical_value_match(self):
        assert self.fm._check_condition('male', {'type': 'categorical', 'value': 'male'}) is True

    def test_categorical_value_mismatch(self):
        assert self.fm._check_condition('male', {'type': 'categorical', 'value': 'female'}) is False

    def test_categorical_values_match(self):
        assert self.fm._check_condition('male', {'type': 'categorical', 'values': ['male', 'female']}) is True

    def test_categorical_values_mismatch(self):
        assert self.fm._check_condition('male', {'type': 'categorical', 'values': ['female']}) is False

    def test_default_type_is_numerical(self):
        assert self.fm._check_condition(15, {'min': 10, 'max': 20}) is True
        assert self.fm._check_condition(5, {'min': 10, 'max': 20}) is False


# ==============================================================================
# TestPersonExcluded
# ==============================================================================

class TestPersonExcluded:
    def setup_method(self):
        self.fm = make_vd().filtering

    def test_household_property_match_excluded(self):
        geo = make_geo()
        person = make_person(geo)
        hh = make_residence('hh', geo, properties={'tenure': 'social'})
        assign_residence(person, hh)
        assert self.fm.person_excluded(person, {'households': {'tenure': 'social'}}) is True

    def test_household_property_no_match(self):
        geo = make_geo()
        person = make_person(geo)
        hh = make_residence('hh', geo, properties={'tenure': 'owned'})
        assign_residence(person, hh)
        assert self.fm.person_excluded(person, {'households': {'tenure': 'social'}}) is False

    def test_no_residence_not_excluded(self):
        person = make_person()
        assert self.fm.person_excluded(person, {'households': {'tenure': 'social'}}) is False

    def test_non_household_always_returns_false(self):
        """Bug #6: person_excluded returns False immediately for non-household residents.
        A person in a 'farm' with matching property is NOT excluded because the check
        only applies to residence.type == 'household'."""
        geo = make_geo()
        person = make_person(geo)
        farm = make_residence('farm_1', geo, residence_type='farm', properties={'tenure': 'social'})
        assign_residence(person, farm)
        assert self.fm.person_excluded(person, {'households': {'tenure': 'social'}}) is False

    def test_empty_config_not_excluded(self):
        geo = make_geo()
        person = make_person(geo)
        hh = make_residence('hh', geo)
        assign_residence(person, hh)
        assert self.fm.person_excluded(person, {}) is False


# ==============================================================================
# TestApplyGlobalFilters (scalar path — list < 1000)
# ==============================================================================

class TestApplyGlobalFilters:
    def test_age_filter(self):
        vd = make_vd(eligibility={
            'global_filters': [{'attribute': 'age', 'type': 'numerical', 'min': 5, 'max': 18}],
            'attributes': [], 'exclude': {},
        })
        geo = make_geo()
        people = [make_person(geo, age=a) for a in [3, 10, 15, 20, 65]]
        eligible = vd.filtering.apply_global_filters(people)
        ages = sorted(p.age for p in eligible)
        assert ages == [10, 15]

    def test_sex_filter(self):
        vd = make_vd(eligibility={
            'global_filters': [{'attribute': 'sex', 'type': 'categorical', 'value': 'female'}],
            'attributes': [], 'exclude': {},
        })
        geo = make_geo()
        people = [make_person(geo, sex='male'), make_person(geo, sex='female'), make_person(geo, sex='female')]
        eligible = vd.filtering.apply_global_filters(people)
        assert len(eligible) == 2
        assert all(p.sex == 'female' for p in eligible)

    def test_combined_filters_and_exclusion(self):
        vd = make_vd(eligibility={
            'global_filters': [{'attribute': 'age', 'type': 'numerical', 'min': 5, 'max': 18}],
            'attributes': [],
            'exclude': {'households': {'tenure': 'social'}},
        })
        geo = make_geo()
        p1 = make_person(geo, age=10)
        hh = make_residence('hh', geo, properties={'tenure': 'social'})
        assign_residence(p1, hh)
        p2 = make_person(geo, age=12)
        p3 = make_person(geo, age=3)

        eligible = vd.filtering.apply_global_filters([p1, p2, p3])
        assert len(eligible) == 1
        assert eligible[0].id == p2.id

    def test_all_filtered_returns_empty(self):
        vd = make_vd(eligibility={
            'global_filters': [{'attribute': 'age', 'type': 'numerical', 'min': 100}],
            'attributes': [], 'exclude': {},
        })
        people = [make_person(age=a) for a in [10, 20, 30]]
        assert vd.filtering.apply_global_filters(people) == []

    def test_empty_filters_returns_all(self):
        vd = make_vd()
        people = [make_person(age=a) for a in [10, 20, 30]]
        assert len(vd.filtering.apply_global_filters(people)) == 3


# ==============================================================================
# TestApplyProbabilityFilter
# ==============================================================================

class TestApplyProbabilityFilter:
    def setup_method(self):
        self.fm = make_vd().filtering

    def test_none_config_returns_all(self):
        people = [make_person() for _ in range(5)]
        assert self.fm.apply_probability_filter(people, None, 'g') == people

    def test_probability_zero_is_falsy_returns_all(self):
        """0.0 is falsy in Python so `if not prob_config` catches it — all people returned."""
        people = [make_person() for _ in range(5)]
        result = self.fm.apply_probability_filter(people, 0.0, 'g')
        assert len(result) == 5

    def test_probability_near_zero_filters_most(self):
        np.random.seed(42)
        people = [make_person() for _ in range(1000)]
        result = self.fm.apply_probability_filter(people, 0.001, 'g')
        assert len(result) < 20

    def test_probability_one_returns_all(self):
        people = [make_person() for _ in range(50)]
        assert len(self.fm.apply_probability_filter(people, 1.0, 'g')) == 50

    def test_probability_half_roughly_half(self):
        np.random.seed(42)
        people = [make_person() for _ in range(1000)]
        result = self.fm.apply_probability_filter(people, 0.5, 'g')
        assert 400 < len(result) < 600

    def test_missing_cache_uses_default(self):
        people = [make_person() for _ in range(100)]
        prob_config = {
            'type': 'file', 'file_path': 'missing.csv',
            'probability_column': 'prob', 'default': 0.0,
        }
        assert self.fm.apply_probability_filter(people, prob_config, 'g') == []


# ==============================================================================
# TestPersonMatchesFilters
# ==============================================================================

class TestPersonMatchesFilters:
    def setup_method(self):
        self.vd = make_vd()
        self.fm = self.vd.filtering

    def test_empty_filters_always_matches(self):
        assert self.fm.person_matches_filters(make_person(), []) is True

    def test_pre_processed_path(self):
        filters = self.vd._pre_process_filters([
            {'attribute': 'age', 'type': 'numerical', 'min': 18, 'max': 65}
        ])
        assert self.fm.person_matches_filters(make_person(age=30), filters) is True
        assert self.fm.person_matches_filters(make_person(age=10), filters) is False

    def test_raw_fallback(self):
        raw = [{'attribute': 'age', 'type': 'numerical', 'min': 18}]
        assert self.fm.person_matches_filters(make_person(age=25), raw) is True
        assert self.fm.person_matches_filters(make_person(age=10), raw) is False

    def test_none_value_returns_false(self):
        filters = self.vd._pre_process_filters([
            {'attribute': 'nonexistent', 'type': 'numerical', 'min': 0}
        ])
        assert self.fm.person_matches_filters(make_person(), filters) is False
