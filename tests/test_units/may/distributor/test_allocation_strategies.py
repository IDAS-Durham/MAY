"""
Tests for venue allocation strategies: random, closest, closest_balanced, proportional.

Tests use lightweight mocks to verify that:
1. All strategies allocate people to venues correctly
2. closest_balanced distributes across multiple venues (vs closest filling one at a time)
3. Capacity is respected
4. Edge cases (single venue, no capacity, no coordinates) are handled
"""

import pytest
import numpy as np
from unittest.mock import MagicMock, PropertyMock
from collections import defaultdict

from may.venue_distributor.allocation_engine import AllocationEngine
from may.venue_distributor.matcher import VenueMatcher


# ==============================================================================
# Test Fixtures
# ==============================================================================

class MockGeoUnit:
    """Lightweight mock for GeographicalUnit."""
    def __init__(self, name, coordinates, level='SGU'):
        self.name = name
        self.coordinates = coordinates
        self.level = level
    
    def get_ancestor_by_level(self, level):
        return self if self.level == level else None

    def __hash__(self):
        return hash(self.name)
    
    def __eq__(self, other):
        return isinstance(other, MockGeoUnit) and self.name == other.name


class MockSubset:
    """Lightweight mock for Subset."""
    def __init__(self, venue):
        self.venue = venue
        self.members = []
    
    def add_member(self, person):
        self.members.append(person)


class MockPerson:
    """Lightweight mock for Person."""
    _next_id = 0
    
    def __init__(self, geo_unit, age=10, sex='male', properties=None):
        self.id = MockPerson._next_id
        MockPerson._next_id += 1
        self.age = age
        self.sex = sex
        self.geographical_unit = geo_unit
        self.properties = properties or {}
        self.activities = set()
        self.activity_map = {}
    
    def add_activity(self, name):
        self.activities.add(name)


class MockVenue:
    """Lightweight mock for Venue with subset support."""
    _next_id = 0
    
    def __init__(self, name, geo_unit, coordinates=None):
        self.id = MockVenue._next_id
        MockVenue._next_id += 1
        self.name = name
        self.type = 'school'
        self.geographical_unit = geo_unit
        self.coordinates = coordinates or (geo_unit.coordinates if geo_unit else None)
        self.properties = {}
        self.subsets = {}
    
    def add_to_subset(self, person, subset_key=None, activity_name=None, activity_type=None):
        if subset_key not in self.subsets:
            self.subsets[subset_key] = MockSubset(self)
        self.subsets[subset_key].add_member(person)
        
        if activity_name not in person.activities:
            person.add_activity(activity_name)
        
        if activity_name not in person.activity_map:
            person.activity_map[activity_name] = {}
        
        at = activity_type or self.type
        if at not in person.activity_map[activity_name]:
            person.activity_map[activity_name][at] = []
        person.activity_map[activity_name][at].append(self.subsets[subset_key])


def make_distributor(strategy='closest', capacity=100, venue_type='school'):
    """Create a mock distributor with the given strategy and capacity."""
    config = {
        'venue_type': venue_type,
        'activity_map_key': 'primary_activity',
        'subset_key': 'student',
        'activity_type': 'education',
        'settings': {'verbose': True, 'use_spatial_index': True},
        'venue_selection': {
            'venue_geo_level': 'SGU',
            'batch_geo_level': 'SGU',
            'consider_by': 'geo_unit',
            'count': 50,
            'respect_capacity': True,
        },
        'allocation': {
            'track_capacity': True,
            'when_full': 'exclude',
            'fixed_capacity': capacity,
            'strategy': strategy,
        },
        'eligibility': {'attributes': []},
    }
    
    distributor = MagicMock()
    distributor.config = config
    distributor.venue_type = venue_type
    distributor.activity_map_key = 'primary_activity'
    distributor.subset_key = 'student'
    distributor.activity_type = 'education'
    distributor.verbose = True
    distributor.batch_geo_level = 'SGU'
    distributor.venue_geo_level = 'SGU'
    distributor.venue_capacity_tracker = {}
    distributor.allocated_this_run = 0
    distributor.population_arrays = {}
    distributor.person_id_to_index = {}
    
    # Real haversine distance
    import math
    def haversine(loc1, loc2):
        lat1, lon1 = loc1
        lat2, lon2 = loc2
        r_lat1 = math.radians(lat1)
        r_lon1 = math.radians(lon1)
        r_lat2 = math.radians(lat2)
        r_lon2 = math.radians(lon2)
        dlat = r_lat2 - r_lat1
        dlon = r_lon2 - r_lon1
        a = math.sin(dlat/2)**2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return c * 6371
    
    distributor._haversine_distance = haversine
    
    def get_venue_location(v):
        return v.coordinates
    distributor._get_venue_location = get_venue_location
    
    def get_venue_capacity(v):
        return config['allocation']['fixed_capacity']
    distributor._get_venue_capacity = get_venue_capacity
    
    def increment_venue_count(v):
        v_id = id(v)
        distributor.venue_capacity_tracker[v_id] = distributor.venue_capacity_tracker.get(v_id, 0) + 1
    distributor._increment_venue_count = increment_venue_count
    
    def get_remaining_capacity(v):
        v_id = id(v)
        current = distributor.venue_capacity_tracker.get(v_id, 0)
        return max(0, config['allocation']['fixed_capacity'] - current)
    distributor._get_remaining_capacity = get_remaining_capacity
    
    def filter_venues_by_capacity(venues):
        return [v for v in venues if get_remaining_capacity(v) > 0]
    distributor._filter_venues_by_capacity = filter_venues_by_capacity

    def get_geo_unit_at_level(person, world, target_level=None):
        return person.geographical_unit
    distributor._get_geo_unit_at_level = get_geo_unit_at_level

    def get_person_attribute(attr, person):
        if hasattr(person, attr):
            return getattr(person, attr)
        return person.properties.get(attr)
    distributor._get_person_attribute = get_person_attribute

    # Pre-processed match attributes (empty = no attribute matching required)
    distributor._pre_processed_match_attrs = []
    
    # Set up matcher with real VenueMatcher
    matcher = VenueMatcher(distributor)
    distributor.matcher = matcher
    
    return distributor


@pytest.fixture(autouse=True)
def reset_mock_ids():
    """Reset auto-incrementing IDs between tests."""
    MockPerson._next_id = 0
    MockVenue._next_id = 0
    yield


# ==============================================================================
# Tests for allocate_by_geo_unit
# ==============================================================================

class TestAllocateByGeoUnit:
    """Test the allocate_by_geo_unit method with different strategies."""

    def _make_scenario(self, strategy='closest', capacity=100, n_people=50, n_venues=5):
        """
        Create a standard test scenario:
        - One SGU at coordinates (54.9, -1.5)
        - N venues at slightly different distances
        - N people all in the same SGU
        """
        geo = MockGeoUnit('TEST_SGU', (54.9, -1.5))
        
        # Spread venues at different distances (0.01 degree ~ 1km apart)
        venues = []
        for i in range(n_venues):
            v_coords = (54.9 + 0.01 * (i + 1), -1.5)  # Each 1km further
            v = MockVenue(f'school_{i}', geo, coordinates=v_coords)
            venues.append(v)
        
        people = [MockPerson(geo, age=10) for _ in range(n_people)]
        
        distributor = make_distributor(strategy=strategy, capacity=capacity)
        engine = AllocationEngine(distributor)
        
        # Initialize venue attribute index (required by matcher)
        distributor.matcher.build_attribute_index(venues)
        
        return engine, people, venues, distributor

    def test_closest_fills_sequentially(self):
        """'closest' strategy should fill the nearest venue first, then the next."""
        engine, people, venues, dist = self._make_scenario(
            strategy='closest', capacity=20, n_people=50, n_venues=5
        )
        
        unallocated = engine.allocate_by_geo_unit(people, venues)
        
        # With 50 people and capacity 20, the 2 closest venues should be full,
        # the 3rd should have 10 people
        counts = [dist.venue_capacity_tracker.get(id(v), 0) for v in venues]
        assert counts[0] == 20, f"Closest venue should be full, got {counts[0]}"
        assert counts[1] == 20, f"Second closest should be full, got {counts[1]}"
        assert counts[2] == 10, f"Third closest should have remainder, got {counts[2]}"
        assert counts[3] == 0, "Fourth venue should be empty"
        assert counts[4] == 0, "Fifth venue should be empty"
        assert len(unallocated) == 0

    def test_closest_balanced_spreads_across_venues(self):
        """'closest_balanced' should distribute students across multiple venues."""
        engine, people, venues, dist = self._make_scenario(
            strategy='closest_balanced', capacity=50, n_people=100, n_venues=5
        )
        
        # Fix seed for reproducibility
        np.random.seed(42)
        unallocated = engine.allocate_by_geo_unit(people, venues)
        
        counts = [dist.venue_capacity_tracker.get(id(v), 0) for v in venues]
        
        # All 100 people should be allocated (total capacity = 5*50 = 250)
        assert len(unallocated) == 0, f"Expected 0 unallocated, got {len(unallocated)}"
        assert sum(counts) == 100, f"Expected 100 total allocated, got {sum(counts)}"
        
        # Key assertion: ALL venues should have students (balanced distribution)
        venues_with_students = sum(1 for c in counts if c > 0)
        assert venues_with_students == 5, (
            f"Expected all 5 venues to have students, but only {venues_with_students} do: {counts}"
        )
        
        # No single venue should be at capacity while others are underused
        # The std dev should be much lower than with 'closest'
        assert max(counts) < 50, (
            f"No venue should be at capacity with balanced distribution: {counts}"
        )

    def test_closest_balanced_respects_capacity(self):
        """'closest_balanced' should not exceed venue capacity."""
        engine, people, venues, dist = self._make_scenario(
            strategy='closest_balanced', capacity=10, n_people=60, n_venues=5
        )
        
        np.random.seed(42)
        unallocated = engine.allocate_by_geo_unit(people, venues)
        
        counts = [dist.venue_capacity_tracker.get(id(v), 0) for v in venues]
        
        # Total capacity = 5 * 10 = 50, so 10 people should be unallocated
        assert sum(counts) == 50, f"Expected 50 allocated, got {sum(counts)}"
        assert len(unallocated) == 10, f"Expected 10 unallocated, got {len(unallocated)}"
        
        # No venue should exceed capacity
        for i, c in enumerate(counts):
            assert c <= 10, f"Venue {i} exceeds capacity: {c}"

    def test_random_strategy_allocates_all(self):
        """'random' strategy should allocate all people when capacity allows."""
        engine, people, venues, dist = self._make_scenario(
            strategy='random', capacity=100, n_people=50, n_venues=5
        )
        
        np.random.seed(42)
        unallocated = engine.allocate_by_geo_unit(people, venues)
        
        counts = [dist.venue_capacity_tracker.get(id(v), 0) for v in venues]
        assert sum(counts) == 50
        assert len(unallocated) == 0

    def test_no_venues_gives_unallocated(self):
        """When no venues available, all people should be unallocated."""
        geo = MockGeoUnit('EMPTY', (54.9, -1.5))
        people = [MockPerson(geo) for _ in range(10)]
        
        distributor = make_distributor(strategy='closest_balanced', capacity=100)
        engine = AllocationEngine(distributor)
        
        unallocated = engine.allocate_by_geo_unit(people, [])
        assert len(unallocated) == 10

    def test_single_venue(self):
        """All strategies should work correctly with a single venue."""
        for strategy in ['closest', 'closest_balanced', 'random']:
            MockPerson._next_id = 0
            MockVenue._next_id = 0
            
            geo = MockGeoUnit('SINGLE', (54.9, -1.5))
            venue = MockVenue('only_school', geo, coordinates=(54.91, -1.5))
            people = [MockPerson(geo) for _ in range(5)]
            
            distributor = make_distributor(strategy=strategy, capacity=100)
            engine = AllocationEngine(distributor)
            distributor.matcher.build_attribute_index([venue])
            
            np.random.seed(42)
            unallocated = engine.allocate_by_geo_unit(people, [venue])
            count = distributor.venue_capacity_tracker.get(id(venue), 0)
            
            assert count == 5, f"Strategy '{strategy}': expected 5 in venue, got {count}"
            assert len(unallocated) == 0, f"Strategy '{strategy}': expected 0 unallocated"


# ==============================================================================
# Tests for select_venue (used by allocate_group)
# ==============================================================================

class TestSelectVenue:
    """Test the matcher's select_venue with different strategies."""

    def _make_venues(self, n=5):
        geo = MockGeoUnit('GEO', (54.9, -1.5))
        venues = []
        for i in range(n):
            v_coords = (54.9 + 0.01 * (i + 1), -1.5)
            v = MockVenue(f'venue_{i}', geo, coordinates=v_coords)
            venues.append(v)
        return venues, geo

    def test_closest_selects_nearest(self):
        venues, geo = self._make_venues(5)
        dist = make_distributor(strategy='closest')
        matcher = VenueMatcher(dist)
        
        location = (54.9, -1.5)
        selected = matcher.select_venue(None, venues, location)
        
        # Should pick the closest venue (smallest coordinate offset)
        assert selected == venues[0], "Should select the closest venue"

    def test_closest_balanced_selects_with_capacity(self):
        venues, geo = self._make_venues(3)
        dist = make_distributor(strategy='closest_balanced', capacity=10)
        matcher = VenueMatcher(dist)
        
        # Fill the closest venue completely
        for _ in range(10):
            dist._increment_venue_count(venues[0])
        
        np.random.seed(42)
        location = (54.9, -1.5)
        
        # Run multiple selections — the full venue should never be picked
        selections = set()
        for _ in range(20):
            v = matcher.select_venue(None, venues, location)
            selections.add(v.name)
        
        assert 'venue_0' not in selections, (
            "Full venue should not be selected by closest_balanced"
        )
        assert len(selections) > 0, "Should select some venues"

    def test_closest_balanced_falls_back_when_all_full(self):
        venues, geo = self._make_venues(3)
        dist = make_distributor(strategy='closest_balanced', capacity=10)
        matcher = VenueMatcher(dist)
        
        # Fill all venues
        for v in venues:
            for _ in range(10):
                dist._increment_venue_count(v)
        
        location = (54.9, -1.5)
        selected = matcher.select_venue(None, venues, location)
        
        # Should fall back to closest (not None)
        assert selected is not None, "Should fall back to closest when all full"
        assert selected == venues[0], "Fallback should pick closest"

    def test_random_returns_random(self):
        venues, geo = self._make_venues(5)
        dist = make_distributor(strategy='random')
        matcher = VenueMatcher(dist)
        
        np.random.seed(42)
        selections = set()
        for _ in range(50):
            v = matcher.select_venue(None, venues, (54.9, -1.5))
            selections.add(v.name)
        
        # Random should pick from multiple venues
        assert len(selections) > 1, "Random should pick from multiple venues"

    def test_select_venue_empty_list(self):
        dist = make_distributor()
        matcher = VenueMatcher(dist)
        
        result = matcher.select_venue(None, [], (54.9, -1.5))
        assert result is None, "Empty venue list should return None"
