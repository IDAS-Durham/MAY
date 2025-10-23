"""
Unit tests for SubsetDistributor class (distributor_venue_to_subsets.py)

Tests the logic for distributing people into subsets within venues.
"""

import pytest
from unittest.mock import Mock, patch
import random

from may.distributor import SubsetDistributor
from may.population import Person, Subset
from may.geography import GeographicalUnit, Venue


@pytest.fixture
def mock_geo_unit():
    """Create a mock geographical unit."""
    return GeographicalUnit(id=0, name='TestSGU', level='SGU')


@pytest.fixture
def mock_venue(mock_geo_unit):
    """Create a mock venue."""
    venue = Venue(
        name='Test Venue',
        venue_type='test_type',
        geographical_unit=mock_geo_unit,
        properties={}
    )
    return venue


class TestSubsetDistributorInitialization:
    """Test SubsetDistributor initialization."""

    def test_init_basic(self):
        """Test basic initialization with default parameters."""
        distributor = SubsetDistributor('test_venue')

        assert distributor.venue_type == 'test_venue'
        assert distributor.subset_names == ['everyone']
        assert distributor.properties == {}
        assert distributor.n_subsets == 1

    def test_init_with_custom_subsets(self):
        """Test initialization with custom subset names."""
        subset_names = ['kids', 'adults', 'elderly']
        distributor = SubsetDistributor('school', subset_names=subset_names)

        assert distributor.venue_type == 'school'
        assert distributor.subset_names == subset_names
        assert distributor.n_subsets == 3

    def test_init_with_properties(self):
        """Test initialization with custom properties."""
        properties = {'max_capacity': 100, 'location': 'downtown'}
        distributor = SubsetDistributor('workplace', properties=properties)

        assert distributor.properties == properties

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        subset_names = ['group_a', 'group_b', 'group_c']
        properties = {'test': 'value'}

        distributor = SubsetDistributor(
            'custom_venue',
            subset_names=subset_names,
            properties=properties
        )

        assert distributor.venue_type == 'custom_venue'
        assert distributor.subset_names == subset_names
        assert distributor.properties == properties
        assert distributor.n_subsets == 3

    def test_init_n_subsets_calculated_correctly(self):
        """Test that n_subsets is calculated from subset_names length."""
        for n in [1, 2, 5, 10]:
            subset_names = [f'subset_{i}' for i in range(n)]
            distributor = SubsetDistributor('test', subset_names=subset_names)
            assert distributor.n_subsets == n

    def test_init_with_none_subset_names_uses_default(self):
        """Test that None subset_names uses default value."""
        distributor = SubsetDistributor('test', subset_names=None)
        assert distributor.subset_names == ['everyone']

    def test_init_with_none_properties_uses_default(self):
        """Test that None properties uses default value."""
        distributor = SubsetDistributor('test', properties=None)
        assert distributor.properties == {}


class TestGenerateEmptySubsets:
    """Test generating empty subsets for venues."""

    def test_generate_empty_subsets_creates_subsets(self, mock_venue):
        """Test that subsets are created for a venue."""
        distributor = SubsetDistributor('test', subset_names=['kids', 'adults'])
        distributor.generate_empty_subsets(mock_venue)

        assert mock_venue.subsets is not None
        assert len(mock_venue.subsets) == 2
        assert 'kids' in mock_venue.subsets
        assert 'adults' in mock_venue.subsets

    def test_generate_empty_subsets_creates_subset_objects(self, mock_venue):
        """Test that created subsets are Subset objects."""
        distributor = SubsetDistributor('test', subset_names=['group_a', 'group_b'])
        distributor.generate_empty_subsets(mock_venue)

        for subset_name, subset in mock_venue.subsets.items():
            assert isinstance(subset, Subset)
            assert subset.venue == mock_venue
            assert subset.subset_name == subset_name

    def test_generate_empty_subsets_assigns_correct_indices(self, mock_venue):
        """Test that subsets get correct indices."""
        subset_names = ['first', 'second', 'third']
        distributor = SubsetDistributor('test', subset_names=subset_names)
        distributor.generate_empty_subsets(mock_venue)

        for i, subset_name in enumerate(subset_names):
            assert mock_venue.subsets[subset_name].subset_index == i

    def test_generate_empty_subsets_overwrites_existing(self, mock_venue):
        """Test that existing subsets dict is overwritten."""
        # Pre-populate with old subsets
        mock_venue.subsets = {'old': Mock()}

        distributor = SubsetDistributor('test', subset_names=['new'])
        distributor.generate_empty_subsets(mock_venue)

        assert 'old' not in mock_venue.subsets
        assert 'new' in mock_venue.subsets

    def test_generate_empty_subsets_with_single_subset(self, mock_venue):
        """Test generating single subset (default case)."""
        distributor = SubsetDistributor('test')  # Default: ['everyone']
        distributor.generate_empty_subsets(mock_venue)

        assert len(mock_venue.subsets) == 1
        assert 'everyone' in mock_venue.subsets
        assert mock_venue.subsets['everyone'].subset_index == 0

    def test_generate_empty_subsets_with_many_subsets(self, mock_venue):
        """Test generating many subsets."""
        subset_names = [f'subset_{i}' for i in range(20)]
        distributor = SubsetDistributor('test', subset_names=subset_names)
        distributor.generate_empty_subsets(mock_venue)

        assert len(mock_venue.subsets) == 20
        for i, name in enumerate(subset_names):
            assert name in mock_venue.subsets
            assert mock_venue.subsets[name].subset_index == i


class TestFindSubsetForPerson:
    """Test finding appropriate subset for a person."""

    def test_find_subset_for_person_returns_valid_index(self, mock_geo_unit):
        """Test that a valid subset index is returned."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b', 'c'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True]

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        assert 0 <= subset_index < 3
        assert subset_name in ['a', 'b', 'c']

    def test_find_subset_for_person_returns_tuple(self, mock_geo_unit):
        """Test that return value is a tuple of (int, str)."""
        distributor = SubsetDistributor('test', subset_names=['x', 'y'])
        person = Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True]

        result = distributor.find_subset_for_person(venue_has_capacity, person)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], int)
        assert isinstance(result[1], str)

    def test_find_subset_for_person_respects_capacity_all_true(self, mock_geo_unit):
        """Test that capacity is respected when all subsets have capacity."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True]

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        # Should return a valid subset
        assert subset_index in [0, 1]
        assert subset_name in ['a', 'b']

    def test_find_subset_for_person_no_capacity_available(self, mock_geo_unit):
        """Test behavior when no capacity is available."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [False, False]

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        # Should return "No subset available"
        assert subset_index == -1
        assert subset_name == 'No subset available'

    def test_find_subset_for_person_partial_capacity(self, mock_geo_unit):
        """Test when only some subsets have capacity."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b', 'c'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        # Try many times to check randomization respects capacity
        results = []
        for _ in range(50):
            venue_has_capacity = [True, False, True]
            subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)
            if subset_name != 'No subset available':
                results.append((subset_index, subset_name))

        # All results should be from available subsets (0 or 2, not 1)
        for subset_index, subset_name in results:
            assert subset_index in [0, 2]
            assert subset_name in ['a', 'c']

    def test_find_subset_for_person_single_subset_with_capacity(self, mock_geo_unit):
        """Test with single subset having capacity."""
        distributor = SubsetDistributor('test', subset_names=['only_one'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True]

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        assert subset_index == 0
        assert subset_name == 'only_one'

    def test_find_subset_for_person_single_subset_no_capacity(self, mock_geo_unit):
        """Test with single subset having no capacity."""
        distributor = SubsetDistributor('test', subset_names=['only_one'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [False]

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        assert subset_index == -1
        assert subset_name == 'No subset available'

    @pytest.mark.parametrize("n_subsets", [2, 3, 5, 10])
    def test_find_subset_for_person_various_subset_counts(self, mock_geo_unit, n_subsets):
        """Test with various numbers of subsets."""
        subset_names = [f'subset_{i}' for i in range(n_subsets)]
        distributor = SubsetDistributor('test', subset_names=subset_names)
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True] * n_subsets

        subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)

        assert 0 <= subset_index < n_subsets
        assert subset_name == subset_names[subset_index]


class TestSubsetDistributorEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_subset_names(self):
        """Test initialization with empty subset names list."""
        distributor = SubsetDistributor('test', subset_names=[])

        assert distributor.n_subsets == 0
        assert distributor.subset_names == []

    def test_empty_capacity_list(self, mock_geo_unit):
        """Test find_subset with empty capacity list."""
        distributor = SubsetDistributor('test', subset_names=[])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = []

        # Should handle gracefully (may raise error or return 'No subset available')
        with pytest.raises(ValueError):
            # random.randint(0, -1) should raise ValueError
            distributor.find_subset_for_person(venue_has_capacity, person)

    def test_subset_names_with_duplicates(self, mock_venue):
        """Test that duplicate subset names create separate subsets."""
        distributor = SubsetDistributor('test', subset_names=['a', 'a', 'b'])
        distributor.generate_empty_subsets(mock_venue)

        # Dict will overwrite duplicates, so only 2 keys
        assert len(mock_venue.subsets) == 2
        assert 'a' in mock_venue.subsets
        assert 'b' in mock_venue.subsets

    def test_subset_names_with_special_characters(self, mock_venue):
        """Test subset names with special characters."""
        special_names = ['subset-1', 'subset_2', 'subset.3', 'subset 4']
        distributor = SubsetDistributor('test', subset_names=special_names)
        distributor.generate_empty_subsets(mock_venue)

        for name in special_names:
            assert name in mock_venue.subsets

    def test_very_long_subset_names(self, mock_venue):
        """Test with very long subset names."""
        long_name = 'a' * 1000
        distributor = SubsetDistributor('test', subset_names=[long_name])
        distributor.generate_empty_subsets(mock_venue)

        assert long_name in mock_venue.subsets


class TestSubsetDistributorRandomization:
    """Test randomization behavior."""

    def test_find_subset_uses_randomization(self, mock_geo_unit):
        """Test that subset selection is randomized."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b', 'c'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True]

        # Run many times and collect results
        results = set()
        for _ in range(100):
            subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)
            results.add(subset_name)

        # Should have hit multiple different subsets (with high probability)
        assert len(results) >= 2  # At least 2 different subsets in 100 tries

    def test_find_subset_randomization_respects_seed(self, mock_geo_unit):
        """Test that random seed affects subset selection."""
        distributor = SubsetDistributor('test', subset_names=['a', 'b', 'c'])
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True]

        # Set seed and get results
        random.seed(42)
        results1 = [
            distributor.find_subset_for_person(venue_has_capacity, person)
            for _ in range(10)
        ]

        # Reset seed and get results again
        random.seed(42)
        results2 = [
            distributor.find_subset_for_person(venue_has_capacity, person)
            for _ in range(10)
        ]

        # Should be identical
        assert results1 == results2


class TestSubsetDistributorIntegration:
    """Integration tests combining multiple features."""

    def test_full_workflow_generate_and_assign(self, mock_venue, mock_geo_unit):
        """Test complete workflow of generating subsets and assigning people."""
        # Create distributor
        subset_names = ['kids', 'adults', 'elderly']
        distributor = SubsetDistributor('household', subset_names=subset_names)

        # Generate subsets
        distributor.generate_empty_subsets(mock_venue)

        # Assign people
        people = [
            Person(age=10, sex='male', geographical_unit=mock_geo_unit),
            Person(age=30, sex='female', geographical_unit=mock_geo_unit),
            Person(age=70, sex='male', geographical_unit=mock_geo_unit),
        ]

        venue_has_capacity = [True, True, True]

        for person in people:
            subset_index, subset_name = distributor.find_subset_for_person(venue_has_capacity, person)
            if subset_name != 'No subset available':
                subset = mock_venue.subsets[subset_name]
                subset.add_member(person)

        # Verify assignments
        total_members = sum(s.num_members for s in mock_venue.subsets.values())
        assert total_members == len(people)

    def test_capacity_exhaustion_workflow(self, mock_venue, mock_geo_unit):
        """Test workflow where capacity gets exhausted."""
        distributor = SubsetDistributor('test', subset_names=['only'])
        distributor.generate_empty_subsets(mock_venue)

        # Start with capacity
        venue_has_capacity = [True]

        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        subset_index1, subset_name1 = distributor.find_subset_for_person(venue_has_capacity, person1)

        assert subset_index1 == 0
        assert subset_name1 == 'only'

        # Exhaust capacity
        venue_has_capacity = [False]

        person2 = Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        subset_index2, subset_name2 = distributor.find_subset_for_person(venue_has_capacity, person2)

        assert subset_index2 == -1
        assert subset_name2 == 'No subset available'
