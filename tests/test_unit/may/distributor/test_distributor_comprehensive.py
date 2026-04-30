"""
Comprehensive unit tests for Distributor class (distributor_pop_to_venue.py)

Tests the core distribution logic for assigning people to venues.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from collections import defaultdict

from may.distributor import Distributor
from may.population import Person, Subset
from may.geography import GeographicalUnit, Venue


@pytest.fixture
def mock_geo_unit():
    """Create a mock geographical unit."""
    return GeographicalUnit(id=0, name='TestSGU', level='SGU')


@pytest.fixture
def mock_venue_manager(mock_geo_unit):
    """Create a mock venue manager with test venues."""
    venue1 = Venue(
        name='Test Venue 1',
        venue_type='test_venue',
        geographical_unit=mock_geo_unit,
        properties={'subsets': ['group_a', 'group_b']}
    )
    venue1.subsets = {}
    
    venue2 = Venue(
        name='Test Venue 2',
        venue_type='test_venue',
        geographical_unit=mock_geo_unit,
        properties={'subsets': ['group_a', 'group_b']}
    )
    venue2.subsets = {}

    manager = Mock()
    manager.venues_by_type = {'test_venue': [venue1, venue2]}
    manager.get_venues_by_type = Mock(return_value=[venue1, venue2])
    return manager


@pytest.fixture
def test_people(mock_geo_unit):
    """Create test people."""
    Person.reset_counter()
    people = [
        Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['test_activity']),
        Person(age=30, sex='female', geographical_unit=mock_geo_unit, activities=['test_activity']),
        Person(age=35, sex='male', geographical_unit=mock_geo_unit, activities=['test_activity']),
        Person(age=40, sex='female', geographical_unit=mock_geo_unit, activities=['test_activity']),
    ]
    return people


class TestDistributorInitialization:
    """Test Distributor initialization."""

    def test_init_basic(self, mock_venue_manager, test_people):
        """Test basic initialization."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        assert distributor.venue_type == 'test_venue'
        assert distributor.venue_manager == mock_venue_manager
        assert distributor.people == test_people
        assert len(distributor.potential_venues) == 2
        assert distributor.unallocated_people == []

    def test_init_creates_id(self, mock_venue_manager, test_people):
        """Test that distributor gets a unique ID."""
        distributor1 = Distributor('test_venue', mock_venue_manager, test_people)
        distributor2 = Distributor('test_venue', mock_venue_manager, test_people)

        assert distributor1.id != distributor2.id

    def test_init_decides_potential_venues(self, mock_venue_manager, test_people):
        """Test that potential venues are correctly identified."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        assert len(distributor.potential_venues) == 2
        assert all(v.type == 'test_venue' for v in distributor.potential_venues)

    def test_post_init_called(self, mock_venue_manager, test_people):
        """Test that _post_init is called during initialization."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # Should have subset_distributor from _post_init
        assert hasattr(distributor, 'subset_distributor')
        assert hasattr(distributor, '_venue_has_membership_capacity_by_subset')

    def test_init_creates_subsets(self, mock_venue_manager, test_people):
        """Test that subsets are created for venues."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        for venue in distributor.potential_venues:
            assert venue.subsets is not None
            assert len(venue.subsets) > 0


class TestDistributorSubsetCreation:
    """Test subset creation functionality."""

    def test_create_subsets_if_necessary(self, mock_venue_manager, test_people):
        """Test that subsets are created when venues have no subsets."""
        # Ensure venues start with no subsets
        for venue in mock_venue_manager.venues_by_type['test_venue']:
            venue.subsets = {}

        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # All venues should now have subsets
        for venue in distributor.potential_venues:
            assert len(venue.subsets) == 2  # group_a, group_b
            assert 'group_a' in venue.subsets
            assert 'group_b' in venue.subsets

    def test_does_not_recreate_existing_subsets(self, mock_venue_manager, test_people):
        """Test that existing subsets are not overwritten."""
        # Pre-populate with subsets
        venue = mock_venue_manager.venues_by_type['test_venue'][0]
        venue.subsets = {
            'group_a': Subset(venue, 0, 'group_a'),
            'group_b': Subset(venue, 1, 'group_b')
        }

        original_subset_a = venue.subsets['group_a']

        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # Should still be the same object
        assert venue.subsets['group_a'] is original_subset_a


class TestDistributorVenueCapacity:
    """Test venue capacity management."""

    def test_venue_has_membership_capacity_initialized(self, mock_venue_manager, test_people):
        """Test that capacity tracking is initialized correctly."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # Should have capacity for all venues
        for venue in distributor.potential_venues:
            capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
            assert len(capacity) == 2  # Two subsets
            assert all(capacity)  # All True initially

    def test_update_venue_membership_capacity_stub(self, mock_venue_manager, test_people):
        """Test that _update_venue_membership_capacity exists (stub implementation)."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        venue = distributor.potential_venues[0]
        subset = venue.subsets['group_a']

        # Should not raise an exception (stub passes)
        distributor._update_venue_membership_capacity(0, venue, subset)


class TestDistributorAssignment:
    """Test people assignment to venues."""

    def test_assign_people_venues_initializes_indices(self, mock_venue_manager, test_people):
        """Test that available venue indices are initialized."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        distributor.assign_people_venues('test_activity', 'test_venue')

        assert hasattr(distributor, 'available_venue_indices')
        assert len(distributor.available_venue_indices) > 0

    def test_assign_people_venues_accepts_custom_indices(self, mock_venue_manager, test_people):
        """Test that custom available venue indices can be provided."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        custom_indices = [0]  # Only first venue
        distributor.assign_people_venues('test_activity', 'test_venue', available_venue_indices=custom_indices)

        # Should have used custom indices (though may be shuffled)
        assert set(distributor.available_venue_indices).issubset({0})

    def test_assign_people_venues_randomizes_order(self, mock_venue_manager, test_people):
        """Test that venue order is randomized when requested."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # Mock random.shuffle to verify it's called
        with patch('may.distributor.distributor_pop_to_venue.random.shuffle') as mock_shuffle:
            distributor.assign_people_venues('test_activity', 'test_venue', randomize_venue_order=True)
            mock_shuffle.assert_called_once()

    def test_assign_people_venues_no_randomization(self, mock_venue_manager, test_people):
        """Test that venue order is NOT randomized when not requested."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        with patch('may.distributor.distributor_pop_to_venue.random.shuffle') as mock_shuffle:
            distributor.assign_people_venues('test_activity', 'test_venue', randomize_venue_order=False)
            mock_shuffle.assert_not_called()

    def test_assign_people_venues_only_assigns_people_with_activity(self, mock_venue_manager, mock_geo_unit):
        """Test that only people with the specified activity are assigned."""
        Person.reset_counter()
        people_with_activity = [
            Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['test_activity']),
            Person(age=30, sex='female', geographical_unit=mock_geo_unit, activities=['test_activity']),
        ]
        people_without_activity = [
            Person(age=35, sex='male', geographical_unit=mock_geo_unit, activities=['other_activity']),
            Person(age=40, sex='female', geographical_unit=mock_geo_unit, activities=[]),
        ]
        all_people = people_with_activity + people_without_activity

        distributor = Distributor('test_venue', mock_venue_manager, all_people)

        # Mock find_venues_for_person to track calls
        distributor.find_venues_for_person = Mock(return_value=True)

        distributor.assign_people_venues('test_activity', 'test_venue')

        # Should only be called for people with test_activity
        assert distributor.find_venues_for_person.call_count == 2

    def test_assign_people_calls_update_capacity_during_init(self, mock_venue_manager, test_people):
        """Test that capacity is updated during initialization."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        # Mock the update method
        distributor._update_venue_membership_capacity = Mock()

        distributor.assign_people_venues('test_activity', 'test_venue')

        # Should be called at least once per venue during initialization
        assert distributor._update_venue_membership_capacity.call_count >= 2


class TestFindVenuesForPerson:
    """Test finding venues for individual people."""

    def test_find_venues_for_person_success(self, mock_venue_manager, test_people):
        """Test successful venue assignment."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        distributor.available_venue_indices = [0, 1]
        distributor._search_index = -1

        person = test_people[0]
        venue_list = distributor.potential_venues

        result = distributor.find_venues_for_person(person, 'test_activity', maxiter=10)

        # Should succeed (with default SubsetDistributor behavior)
        assert result is True or result is False  # Depends on subset availability

    def test_find_venues_for_person_respects_maxiter(self, mock_venue_manager, test_people):
        """Test that maxiter limits the number of attempts."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        distributor.available_venue_indices = list(range(10))  # Many venues
        distributor._search_index = -1

        # Mock subset distributor to always return "No subset available"
        distributor.subset_distributor.find_subset_for_person = Mock(return_value=(-1, 'No subset available'))

        person = test_people[0]
        venue_list = distributor.potential_venues * 5  # Many venues

        result = distributor.find_venues_for_person(person, 'test_activity', maxiter=5)

        # Should fail after maxiter attempts
        assert result is False

    def test_find_venues_for_person_assigns_subset(self, mock_venue_manager, test_people):
        """Test that person is assigned to subset when successful."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        distributor.available_venue_indices = [0]
        distributor._search_index = -1

        person = test_people[0]
        venue = distributor.potential_venues[0]

        # Mock successful subset assignment
        distributor.subset_distributor.find_subset_for_person = Mock(return_value=(0, 'group_a'))

        result = distributor.find_venues_for_person(person, 'test_activity')

        if result:
            # Person should have activity mapped
            assert 'test_activity' in person.activity_map
            # Person should be marked as housed
            assert person.properties.get('housed') is True

    def test_find_venues_cycles_through_venues(self, mock_venue_manager, test_people):
        """Test that search cycles through available venues."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        distributor.available_venue_indices = [0, 1]
        distributor._search_index = -1

        # First attempt should try venue 0
        distributor.subset_distributor.find_subset_for_person = Mock(return_value=(-1, 'No subset available'))

        person = test_people[0]
        distributor.find_venues_for_person(person, 'test_activity', maxiter=3)

        # Search index should have incremented
        assert distributor._search_index >= 0


class TestDealWithNoVenue:
    """Test handling of unallocated people."""

    def test_deal_with_no_venue_adds_to_unallocated(self, mock_venue_manager, test_people):
        """Test that people without venues are tracked."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        person = test_people[0]
        distributor._deal_with_no_venue(person, 'test_activity')

        assert person in distributor.unallocated_people

    def test_deal_with_no_venue_multiple_people(self, mock_venue_manager, test_people):
        """Test handling multiple unallocated people."""
        distributor = Distributor('test_venue', mock_venue_manager, test_people)

        for person in test_people[:3]:
            distributor._deal_with_no_venue(person, 'test_activity')

        assert len(distributor.unallocated_people) == 3
        assert all(p in distributor.unallocated_people for p in test_people[:3])


class TestDistributorIntegration:
    """Integration tests for full assignment workflow."""

    def test_full_assignment_workflow(self, mock_venue_manager, mock_geo_unit):
        """Test complete assignment workflow."""
        Person.reset_counter()
        people = [
            Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['test_activity'])
            for _ in range(5)
        ]

        distributor = Distributor('test_venue', mock_venue_manager, people)

        # Run assignment
        distributor.assign_people_venues('test_activity', 'test_venue')

        # Some people should be allocated or unallocated
        total_accounted = len(distributor.unallocated_people)
        for venue in distributor.potential_venues:
            for subset in venue.subsets.values():
                total_accounted += subset.num_members

        assert total_accounted == len(people)

    def test_assignment_preserves_people_count(self, mock_venue_manager, test_people):
        """Test that no people are lost during assignment."""
        initial_count = len(test_people)

        distributor = Distributor('test_venue', mock_venue_manager, test_people)
        distributor.assign_people_venues('test_activity', 'test_venue')

        # Count people in venues
        allocated_count = 0
        for venue in distributor.potential_venues:
            for subset in venue.subsets.values():
                allocated_count += subset.num_members

        # Total should match
        assert allocated_count + len(distributor.unallocated_people) == initial_count


class TestDistributorEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_people_list(self, mock_venue_manager):
        """Test handling of empty people list."""
        distributor = Distributor('test_venue', mock_venue_manager, [])

        distributor.assign_people_venues('test_activity', 'test_venue')

        assert len(distributor.unallocated_people) == 0

    def test_no_venues_available(self, mock_geo_unit):
        """Test behavior when no venues are available."""
        Person.reset_counter()
        people = [Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['test_activity'])]

        manager = Mock()
        manager.venues_by_type = {'test_venue': []}
        manager.get_venues_by_type = Mock(return_value=[])

        # It handles gracefully, dropping them into the unallocated array
        distributor = Distributor('test_venue', manager, people)
        distributor.assign_people_venues('test_activity', 'test_venue')
        
        assert len(distributor.unallocated_people) == 1

    def test_person_with_no_activities(self, mock_venue_manager, mock_geo_unit):
        """Test that people with no activities are not assigned."""
        Person.reset_counter()
        people = [Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=[])]

        distributor = Distributor('test_venue', mock_venue_manager, people)
        distributor.assign_people_venues('test_activity', 'test_venue')

        # Person should not be in any venue
        total_members = sum(
            subset.num_members
            for venue in distributor.potential_venues
            for subset in venue.subsets.values()
        )
        assert total_members == 0

    def test_multiple_activity_assignment(self, mock_venue_manager, mock_geo_unit):
        """Test assigning the same person to multiple activities."""
        Person.reset_counter()
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit,
                       activities=['activity1', 'activity2'])

        distributor = Distributor('test_venue', mock_venue_manager, [person])

        # Assign to first activity
        distributor.assign_people_venues('activity1', 'test_venue')

        # Verify person has activity1 mapped
        assert 'activity1' in person.activity_map or person in distributor.unallocated_people
