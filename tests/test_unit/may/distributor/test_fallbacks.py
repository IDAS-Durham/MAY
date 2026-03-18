"""
Unit tests for FallbackManager.

Covers: handle_fallbacks, _relax_distance, _relax_capacity, _assign_closest.

All tests use real VenueDistributor, real venues with spatial indices,
and real allocation runs — no mocks.
"""

import pytest
import numpy as np

from may.population.person import Person

from conftest import make_geo, make_person, make_venue, make_vd, build_world, SimpleWorld


# ==============================================================================
# TestHandleFallbacks
# ==============================================================================

class TestHandleFallbacks:
    def test_skip_returns_unchanged(self):
        vd = make_vd(fallback={'strategy': 'skip'})
        people = [make_person() for _ in range(3)]
        result = vd.fallbacks.handle_fallbacks(people, [], SimpleWorld())
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        vd = make_vd(fallback={'strategy': 'relax_distance'})
        result = vd.fallbacks.handle_fallbacks([], [], SimpleWorld())
        assert result == []

    def test_unknown_strategy_returns_unchanged(self):
        vd = make_vd(fallback={'strategy': 'magic_unicorn'})
        people = [make_person() for _ in range(3)]
        result = vd.fallbacks.handle_fallbacks(people, [], SimpleWorld())
        assert len(result) == 3

    def test_relax_distance_allocates_people(self):
        """End-to-end: relax_distance with real allocation engine."""
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={
                'strategy': 'relax_distance',
                'relax_params': {'distance_multiplier': 2.0, 'max_iterations': 2},
            },
            venue_selection={'count': 5, 'max_distance': 10},
            allocation={'fixed_capacity': 100, 'strategy': 'closest'},
        )
        venues = [make_venue(f'v{i}', geo, coordinates=(51.5 + 0.01*(i+1), -0.1)) for i in range(3)]
        build_world(vd, [], venues)
        people = [make_person(geo, age=10) for _ in range(5)]

        result = vd.fallbacks.handle_fallbacks(people, venues, vd.world)
        # With venues nearby and plenty of capacity, all should be allocated
        assert len(result) == 0

    def test_relax_capacity_allocates_over_capacity(self):
        """End-to-end: relax_capacity sets when_full=overflow and runs allocation."""
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={'strategy': 'relax_capacity'},
            allocation={'fixed_capacity': 2, 'strategy': 'closest', 'when_full': 'exclude'},
        )
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])
        # Fill the venue to capacity
        for _ in range(2):
            vd._increment_venue_count(venue)

        people = [make_person(geo) for _ in range(3)]
        result = vd.fallbacks.handle_fallbacks(people, [venue], vd.world)
        # relax_capacity sets overflow, so all 3 should be allocated
        assert len(result) == 0


# ==============================================================================
# TestRelaxDistance
# ==============================================================================

class TestRelaxDistance:
    def test_distance_scales_from_original(self):
        """Bug #1 fix: max_distance uses original * multiplier^(i+1), not compound."""
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={
                'strategy': 'relax_distance',
                'relax_params': {'distance_multiplier': 2.0, 'max_iterations': 3},
            },
            venue_selection={'max_distance': 10, 'count': 5},
            allocation={'fixed_capacity': 0, 'strategy': 'closest'},
        )
        far_venue = make_venue('far', geo, coordinates=(60.0, -0.1))
        build_world(vd, [], [far_venue])

        sel = vd.config['venue_selection']
        observed = []
        original_allocate = vd.allocation.allocate_individual

        def tracking_allocate(people, venues):
            observed.append(sel.get('max_distance'))
            return original_allocate(people, venues)

        vd.allocation.allocate_individual = tracking_allocate
        vd.fallbacks._relax_distance(
            [make_person(geo)], [far_venue], vd.config['fallback']
        )
        # Fixed: 10*2=20, 10*4=40, 10*8=80 (from original, not compounded)
        assert observed == [20, 40, 80]

    def test_original_restored_after_run(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={
                'strategy': 'relax_distance',
                'relax_params': {'distance_multiplier': 2.0, 'max_iterations': 1},
            },
            venue_selection={'max_distance': 10, 'count': 5},
        )
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        vd.fallbacks._relax_distance([make_person(geo)], [venue], vd.config['fallback'])
        assert vd.config['venue_selection']['max_distance'] == 10
        assert vd.config['venue_selection']['count'] == 5

    def test_count_also_relaxed_from_original(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={
                'strategy': 'relax_distance',
                'relax_params': {'distance_multiplier': 3.0, 'max_iterations': 2},
            },
            venue_selection={'max_distance': 10, 'count': 5},
            allocation={'fixed_capacity': 0, 'strategy': 'closest'},
        )
        far_venue = make_venue('far', geo, coordinates=(60.0, -0.1))
        build_world(vd, [], [far_venue])

        observed_counts = []
        original_allocate = vd.allocation.allocate_individual

        def tracking(people, venues):
            observed_counts.append(vd.config['venue_selection']['count'])
            return original_allocate(people, venues)

        vd.allocation.allocate_individual = tracking
        vd.fallbacks._relax_distance([make_person(geo)], [far_venue], vd.config['fallback'])
        # Fixed: 5*3=15, 5*9=45 (from original, not 5*3=15, 15*3=45)
        assert observed_counts == [15, 45]

    def test_stops_early_when_all_allocated(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(
            fallback={
                'strategy': 'relax_distance',
                'relax_params': {'distance_multiplier': 2.0, 'max_iterations': 5},
            },
            venue_selection={'max_distance': 10, 'count': 5},
            allocation={'fixed_capacity': 100, 'strategy': 'closest'},
        )
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        call_count = 0
        original_allocate = vd.allocation.allocate_individual

        def counting(people, venues):
            nonlocal call_count
            call_count += 1
            return original_allocate(people, venues)

        vd.allocation.allocate_individual = counting
        vd.fallbacks._relax_distance([make_person(geo)], [venue], vd.config['fallback'])
        assert call_count == 1


# ==============================================================================
# TestRelaxCapacity
# ==============================================================================

class TestRelaxCapacity:
    def test_when_full_set_to_overflow_during_allocation(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(allocation={'when_full': 'exclude', 'fixed_capacity': 1, 'strategy': 'closest'})
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])
        vd._increment_venue_count(venue)  # fill to capacity

        observed = []
        original_allocate = vd.allocation.allocate_individual

        def tracking(people, venues):
            observed.append(vd.config['allocation']['when_full'])
            return original_allocate(people, venues)

        vd.allocation.allocate_individual = tracking
        vd.fallbacks._relax_capacity([make_person(geo)], [venue])
        assert observed == ['overflow']

    def test_restored_after_run(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd(allocation={'when_full': 'exclude', 'fixed_capacity': 100, 'strategy': 'closest'})
        venue = make_venue('v', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        vd.fallbacks._relax_capacity([make_person(geo)], [venue])
        assert vd.config['allocation']['when_full'] == 'exclude'


# ==============================================================================
# TestAssignClosest
# ==============================================================================

class TestAssignClosest:
    def test_person_with_location_assigned(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd()
        venue = make_venue('s', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        person = make_person(geo)
        remaining = vd.fallbacks._assign_closest([person], [venue])
        assert remaining == []
        assert vd.allocated_this_run == 1
        assert 'primary_activity' in person.activity_map
        assert person in venue.get_all_members()

    def test_no_location_stays_in_remaining(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd()
        venue = make_venue('s', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        person_no_geo = Person(age=25, sex='male')  # no geographical_unit
        remaining = vd.fallbacks._assign_closest([person_no_geo], [venue])
        assert len(remaining) == 1

    def test_person_with_location_but_no_venue_returned_in_remaining(self):
        """Bug #2 fix: People with location but no venue found are now properly
        returned in remaining instead of being silently dropped."""
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd()
        vd.spatial_indices = {}
        vd.venue_lists = {}

        person = make_person(geo)  # HAS location
        remaining = vd.fallbacks._assign_closest([person], [])

        # Fixed: person is in remaining (not allocated, not dropped)
        assert len(remaining) == 1
        assert vd.allocated_this_run == 0

    def test_multiple_people_assigned_count_incremented(self):
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd()
        venue = make_venue('s', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        people = [make_person(geo) for _ in range(3)]
        vd.fallbacks._assign_closest(people, [venue])
        assert vd.allocated_this_run == 3
        assert vd.venue_capacity_tracker[id(venue)] == 3

    def test_mixed_with_and_without_location(self):
        """People with location get assigned; without location stay in remaining."""
        geo = make_geo('SGU', (51.5, -0.1))
        vd = make_vd()
        venue = make_venue('s', geo, coordinates=(51.501, -0.1))
        build_world(vd, [], [venue])

        p_with = make_person(geo)
        p_without = Person(age=25, sex='male')
        remaining = vd.fallbacks._assign_closest([p_with, p_without], [venue])
        assert len(remaining) == 1
        assert vd.allocated_this_run == 1
