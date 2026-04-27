"""
Unit tests for SpecialCaseManager.

Covers: matches_special_case, allocate_special_case, handle_special_cases.
"""

import pytest
import numpy as np

from conftest import (
    make_geo, make_person, make_venue, make_residence, assign_residence,
    make_vd, build_world, SimpleWorld,
)


# ==============================================================================
# TestMatchesSpecialCase
# ==============================================================================

class TestMatchesSpecialCase:
    def setup_method(self):
        self.vd = make_vd()
        self.sc = self.vd.special_cases

    def test_residence_type_match(self):
        geo = make_geo()
        person = make_person(geo, age=14)
        boarding = make_residence('boarding_1', geo, residence_type='boarding_school')
        assign_residence(person, boarding)
        assert self.sc.matches_special_case(
            person, {'condition': {'person_residence_type': 'boarding_school'}}
        ) is True

    def test_residence_type_mismatch(self):
        geo = make_geo()
        person = make_person(geo)
        hh = make_residence('hh', geo, residence_type='household')
        assign_residence(person, hh)
        assert self.sc.matches_special_case(
            person, {'condition': {'person_residence_type': 'boarding_school'}}
        ) is False

    def test_no_residence_fails(self):
        person = make_person(age=14)
        assert self.sc.matches_special_case(
            person, {'condition': {'person_residence_type': 'boarding_school'}}
        ) is False

    def test_with_filters(self):
        geo = make_geo()
        teen = make_person(geo, age=14)
        adult = make_person(geo, age=50)
        case = {'condition': {
            'filters': [{'attribute': 'age', 'type': 'numerical', 'min': 11, 'max': 18}]
        }}
        assert self.sc.matches_special_case(teen, case) is True
        assert self.sc.matches_special_case(adult, case) is False

    def test_empty_condition_matches_all(self):
        assert self.sc.matches_special_case(make_person(), {'condition': {}}) is True


# ==============================================================================
# TestAllocateSpecialCase
# ==============================================================================

class TestAllocateSpecialCase:
    def _setup(self):
        vd = make_vd()
        return vd

    def test_closest_strategy_picks_nearest(self):
        """Bug #3: closest strategy does O(n) linear scan. Correct result but slow."""
        vd = self._setup()
        geo = make_geo('SGU', (51.5, -0.1))
        person = make_person(geo, age=14)
        v_near = make_venue('near', geo, coordinates=(51.501, -0.1))
        v_far = make_venue('far', geo, coordinates=(51.6, -0.1))

        result = vd.special_cases.allocate_special_case(
            person, {'allocation_rule': {'strategy': 'closest'}},
            [v_far, v_near], {}
        )
        assert result is True
        # Nearest venue was selected despite being second in list
        assert person.activity_map['primary_activity']['education'][0].venue.id == v_near.id

    def test_random_strategy(self):
        vd = self._setup()
        geo = make_geo('SGU', (51.5, -0.1))
        person = make_person(geo)
        venues = [make_venue(f'v{i}', geo) for i in range(5)]
        np.random.seed(42)
        result = vd.special_cases.allocate_special_case(
            person, {'allocation_rule': {'strategy': 'random'}}, venues, {}
        )
        assert result is True

    def test_match_by_with_venue_index(self):
        vd = self._setup()
        geo = make_geo('SGU', (51.5, -0.1))
        person = make_person(geo)
        boarding = make_residence('Eton', geo, residence_type='boarding_school')
        assign_residence(person, boarding)

        target = make_venue('Eton_School', geo)
        venue_index = {('Eton', 'SGU'): target}

        case = {'allocation_rule': {'match_by': [
            {'source': 'person.residence.name', 'target': 'venue.name'},
            {'source': 'person.residence.geographical_unit.name', 'target': 'venue.geographical_unit.name'},
        ]}}
        assert vd.special_cases.allocate_special_case(person, case, [target], venue_index) is True

    def test_fallback_search_linear(self):
        vd = self._setup()
        geo = make_geo('SGU', (51.5, -0.1))
        person = make_person(geo)
        boarding = make_residence('BoardingX', geo, residence_type='boarding_school')
        assign_residence(person, boarding)

        target = make_venue('BoardingX', geo)
        case = {'allocation_rule': {'match_by': [
            {'source': 'person.residence.name', 'target': 'venue.name', 'match_type': 'exact'}
        ]}}
        assert vd.special_cases.allocate_special_case(person, case, [target], {}) is True

    def test_if_no_match_error(self):
        vd = self._setup()
        person = make_person(make_geo())
        case = {'allocation_rule': {'match_by': [
            {'source': 'person.residence.name', 'target': 'venue.name'}
        ], 'if_no_match': 'error'}}
        with pytest.raises(ValueError, match="Special case allocation failed"):
            vd.special_cases.allocate_special_case(person, case, [], {})

    def test_if_no_match_warn_returns_false(self):
        vd = self._setup()
        person = make_person(make_geo())
        case = {'allocation_rule': {'match_by': [
            {'source': 'person.residence.name', 'target': 'venue.name'}
        ], 'if_no_match': 'warn'}}
        assert vd.special_cases.allocate_special_case(person, case, [], {}) is False

    def test_if_no_match_skip_returns_false(self):
        vd = self._setup()
        person = make_person()
        case = {'allocation_rule': {'match_by': [
            {'source': 'person.residence.name', 'target': 'venue.name'}
        ], 'if_no_match': 'skip'}}
        assert vd.special_cases.allocate_special_case(person, case, [], {}) is False

    def test_add_to_subset_called(self):
        """Verify allocation actually puts the person in the venue's subset."""
        vd = self._setup()
        geo = make_geo('SGU', (51.5, -0.1))
        person = make_person(geo)
        venue = make_venue('target', geo, coordinates=(51.501, -0.1))
        vd.special_cases.allocate_special_case(
            person, {'allocation_rule': {'strategy': 'closest'}}, [venue], {}
        )
        members = venue.get_all_members()
        assert person in members


# ==============================================================================
# TestHandleSpecialCases
# ==============================================================================

class TestHandleSpecialCases:
    def test_no_config_returns_all(self):
        vd = make_vd()
        people = [make_person(age=a) for a in [10, 20, 30]]
        remaining, unallocated = vd.special_cases.handle_special_cases(people, [], SimpleWorld())
        assert len(remaining) == 3
        assert unallocated == []

    def test_matched_separated_from_remaining(self):
        vd = make_vd(special_cases=[{
            'condition': {'person_residence_type': 'boarding_school'},
            'allocation_rule': {'strategy': 'closest', 'if_no_match': 'skip'},
        }])
        geo = make_geo('SGU', (51.5, -0.1))
        p1 = make_person(geo, age=10)
        p2 = make_person(geo, age=12)
        p3 = make_person(geo, age=14)
        boarding = make_residence('b', geo, residence_type='boarding_school')
        assign_residence(p3, boarding)

        venue = make_venue('target', geo, coordinates=(51.501, -0.1))
        remaining, unallocated = vd.special_cases.handle_special_cases(
            [p1, p2, p3], [venue], SimpleWorld()
        )
        assert len(remaining) == 2
        assert vd.allocated_this_run == 1

    def test_unallocated_tracked(self):
        vd = make_vd(special_cases=[{
            'condition': {'person_residence_type': 'boarding_school'},
            'allocation_rule': {'match_by': [
                {'source': 'person.residence.name', 'target': 'venue.name'}
            ], 'if_no_match': 'skip'},
        }])
        geo = make_geo()
        person = make_person(geo)
        boarding = make_residence('NoMatch', geo, residence_type='boarding_school')
        assign_residence(person, boarding)

        remaining, unallocated = vd.special_cases.handle_special_cases(
            [person], [], SimpleWorld()
        )
        assert len(remaining) == 0
        assert len(unallocated) == 1
