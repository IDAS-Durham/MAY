"""
Unit tests for VenueDistributor orchestration logic.

Covers: _get_unassigned_people, _handle_priority_allocation, _enforce_no_empty_venues.
"""

import pytest
import numpy as np

from conftest import (
    make_geo, make_person, make_venue, make_vd, build_world, SimpleWorld,
)


# ==============================================================================
# TestGetUnassignedPeople
# ==============================================================================

class TestGetUnassignedPeople:
    def test_require_unassigned_true_skips_assigned(self):
        vd = make_vd()
        geo = make_geo()
        p1 = make_person(geo, age=10)
        p2 = make_person(geo, age=12)
        p1.activity_map['primary_activity'] = {'education': []}

        world = SimpleWorld(people=[p1, p2])
        result = vd._get_unassigned_people(world)
        assert len(result) == 1
        assert result[0].id == p2.id

    def test_require_unassigned_false_includes_all(self):
        vd = make_vd(eligibility={
            'require_unassigned': False,
            'global_filters': [], 'attributes': [], 'exclude': {},
        })
        geo = make_geo()
        p1 = make_person(geo, age=10)
        p1.activity_map['primary_activity'] = {'education': []}
        p2 = make_person(geo, age=12)

        world = SimpleWorld(people=[p1, p2])
        assert len(vd._get_unassigned_people(world)) == 2

    def test_required_attributes_filtering(self):
        vd = make_vd(validation={'required_person_attributes': ['age']})
        geo = make_geo()
        p = make_person(geo, age=10)
        assert len(vd._get_unassigned_people(SimpleWorld(people=[p]))) == 1


# ==============================================================================
# TestHandlePriorityAllocation
# ==============================================================================

class TestHandlePriorityAllocation:
    def _priority_vd(self, groups, **kw):
        return make_vd(
            eligibility={
                'global_filters': [], 'attributes': [], 'exclude': {},
                'priority_allocation': {'enabled': True, 'groups': groups},
            },
            **kw,
        )

    def test_groups_sorted_by_priority(self):
        """Higher priority (lower number) groups are processed first."""
        geo = make_geo('SGU', (51.5, -0.1))
        groups = [
            {'name': 'low', 'priority': 10, 'filters': [
                {'attribute': 'age', 'type': 'numerical', 'min': 60}
            ]},
            {'name': 'high', 'priority': 1, 'filters': [
                {'attribute': 'age', 'type': 'numerical', 'min': 18, 'max': 30}
            ]},
        ]
        vd = self._priority_vd(groups)
        venues = [make_venue(f'v{i}', geo, coordinates=(51.5 + 0.01*(i+1), -0.1)) for i in range(3)]
        build_world(vd, [], venues)

        people = [make_person(geo, age=a) for a in [25, 65, 10]]
        remaining, unalloc = vd._handle_priority_allocation(people, venues)
        # Age 10 doesn't match either group -> stays in remaining
        assert any(p.age == 10 for p in remaining)
        # Age 25 and 65 were matched to groups
        assert not any(p.age == 25 for p in remaining)
        assert not any(p.age == 65 for p in remaining)

    def test_overflow_config_restored_after_allocation(self):
        """Bug #7: when allow_overflow=True, config['allocation']['when_full'] is
        temporarily mutated to 'overflow'. Must be restored afterwards."""
        geo = make_geo('SGU', (51.5, -0.1))
        groups = [{
            'name': 'overflow_group', 'priority': 1, 'allow_overflow': True,
            'filters': [{'attribute': 'age', 'type': 'numerical', 'min': 0}],
        }]
        vd = self._priority_vd(groups, allocation={
            'when_full': 'exclude', 'fixed_capacity': 100, 'strategy': 'closest',
        })
        venues = [make_venue('v', geo, coordinates=(51.501, -0.1))]
        build_world(vd, [], venues)

        people = [make_person(geo, age=25)]
        vd._handle_priority_allocation(people, venues)
        assert vd.config['allocation']['when_full'] == 'exclude'

    def test_overflow_actually_allows_over_capacity(self):
        """With allow_overflow, people can be placed even when venue is full."""
        geo = make_geo('SGU', (51.5, -0.1))
        groups = [{
            'name': 'must_place', 'priority': 1, 'allow_overflow': True,
            'filters': [{'attribute': 'age', 'type': 'numerical', 'min': 0}],
        }]
        vd = self._priority_vd(groups, allocation={
            'when_full': 'exclude', 'fixed_capacity': 1, 'strategy': 'closest',
        })
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])
        vd._increment_venue_count(venue)  # fill to capacity

        people = [make_person(geo, age=25)]
        vd._handle_priority_allocation(people, [venue])
        # Person should be allocated despite venue being "full"
        assert vd.allocated_this_run > 0

    def test_probability_filter_zero_skips_allocation(self):
        geo = make_geo('SGU', (51.5, -0.1))
        groups = [{
            'name': 'prob_group', 'priority': 1,
            'probability_config': 0.001,  # nearly zero
            'filters': [{'attribute': 'age', 'type': 'numerical', 'min': 0}],
        }]
        np.random.seed(0)
        vd = self._priority_vd(groups)
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        people = [make_person(geo, age=25) for _ in range(5)]
        remaining, unalloc = vd._handle_priority_allocation(people, [venue])
        # With prob near 0, most people should not be selected for priority allocation
        # They're removed from remaining regardless (matched to group), but not allocated
        assert vd.allocated_this_run <= 1

    def test_disabled_returns_all(self):
        """When priority_allocation is disabled, all people pass through."""
        vd = make_vd(eligibility={
            'global_filters': [], 'attributes': [], 'exclude': {},
            'priority_allocation': {'enabled': False},
        })
        geo = make_geo()
        people = [make_person(geo, age=a) for a in [10, 20, 30]]
        remaining, unalloc = vd._handle_priority_allocation(people, [])
        assert len(remaining) == 3
        assert unalloc == []


# ==============================================================================
# TestEnforceNoEmptyVenues
# ==============================================================================

class TestEnforceNoEmptyVenues:
    def _setup_vd(self):
        return make_vd(allocation={
            'enforce_no_empty_venues': True,
            'fixed_capacity': 100, 'strategy': 'closest',
        })

    def test_no_empty_does_nothing(self):
        vd = self._setup_vd()
        geo = make_geo('SGU', (51.5, -0.1))
        venues = [make_venue(f'v{i}', geo, coordinates=(51.5 + 0.001*i, -0.1)) for i in range(3)]
        build_world(vd, [], venues)

        for v in venues:
            p = make_person(geo)
            v.add_to_subset(p, subset_key='student',
                            activity_name='primary_activity', activity_type='education')
            vd._increment_venue_count(v)

        vd._enforce_no_empty_venues(venues)
        for v in venues:
            assert vd.venue_capacity_tracker[id(v)] >= 1

    def test_steals_from_most_populated(self):
        vd = self._setup_vd()
        geo = make_geo('SGU', (51.5, -0.1))
        v_full = make_venue('full', geo, coordinates=(51.5, -0.1))
        v_empty = make_venue('empty', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [v_full, v_empty])

        for _ in range(5):
            p = make_person(geo)
            v_full.add_to_subset(p, subset_key='student',
                                 activity_name='primary_activity', activity_type='education')
            vd._increment_venue_count(v_full)

        vd._enforce_no_empty_venues([v_full, v_empty])
        assert vd.venue_capacity_tracker.get(id(v_empty), 0) == 1
        assert vd.venue_capacity_tracker[id(v_full)] == 4

    def test_insufficient_donors_cannot_fill(self):
        """When all populated venues have exactly 1 person, can't steal."""
        vd = self._setup_vd()
        geo = make_geo('SGU', (51.5, -0.1))
        v1 = make_venue('v1', geo, coordinates=(51.5, -0.1))
        v_empty = make_venue('empty', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [v1, v_empty])

        p = make_person(geo)
        v1.add_to_subset(p, subset_key='student',
                         activity_name='primary_activity', activity_type='education')
        vd._increment_venue_count(v1)

        vd._enforce_no_empty_venues([v1, v_empty])
        assert vd.venue_capacity_tracker.get(id(v_empty), 0) == 0
        assert vd.venue_capacity_tracker[id(v1)] == 1

    def test_single_person_venues_protected(self):
        """Venues with exactly 1 person should never be stolen from."""
        vd = self._setup_vd()
        geo = make_geo('SGU', (51.5, -0.1))
        v1 = make_venue('v1', geo, coordinates=(51.5, -0.1))
        v2 = make_venue('v2', geo, coordinates=(51.501, -0.1))
        v_empty = make_venue('empty', geo, coordinates=(51.502, -0.1))
        build_world(vd, [], [v1, v2, v_empty])

        p1 = make_person(geo)
        v1.add_to_subset(p1, subset_key='student',
                         activity_name='primary_activity', activity_type='education')
        vd._increment_venue_count(v1)

        for _ in range(3):
            p = make_person(geo)
            v2.add_to_subset(p, subset_key='student',
                             activity_name='primary_activity', activity_type='education')
            vd._increment_venue_count(v2)

        vd._enforce_no_empty_venues([v1, v2, v_empty])
        assert vd.venue_capacity_tracker[id(v1)] == 1  # protected
        assert vd.venue_capacity_tracker[id(v2)] == 2  # stolen from
        assert vd.venue_capacity_tracker.get(id(v_empty), 0) == 1

    def test_multiple_empty_venues(self):
        """Multiple empty venues get filled by stealing from overfull venues."""
        vd = self._setup_vd()
        geo = make_geo('SGU', (51.5, -0.1))
        v_big = make_venue('big', geo, coordinates=(51.5, -0.1))
        empty1 = make_venue('empty1', geo, coordinates=(51.501, -0.1))
        empty2 = make_venue('empty2', geo, coordinates=(51.502, -0.1))
        build_world(vd, [], [v_big, empty1, empty2])

        for _ in range(10):
            p = make_person(geo)
            v_big.add_to_subset(p, subset_key='student',
                                activity_name='primary_activity', activity_type='education')
            vd._increment_venue_count(v_big)

        vd._enforce_no_empty_venues([v_big, empty1, empty2])
        assert vd.venue_capacity_tracker.get(id(empty1), 0) == 1
        assert vd.venue_capacity_tracker.get(id(empty2), 0) == 1
        assert vd.venue_capacity_tracker[id(v_big)] == 8
