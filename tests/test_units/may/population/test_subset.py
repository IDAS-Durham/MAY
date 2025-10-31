"""
Unit tests for Subset class (subset.py)

Tests the Subset class that represents groups of people within venues.
"""

import pytest
from unittest.mock import Mock

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


@pytest.fixture(autouse=True)
def reset_person_counter():
    """Reset Person ID counter before each test."""
    Person.reset_counter()
    yield
    Person.reset_counter()


class TestSubsetInitialization:
    """Test Subset initialization."""

    def test_init_basic(self, mock_venue):
        """Test basic initialization with required parameters."""
        subset = Subset(venue=mock_venue, subset_index=0)

        assert subset.venue == mock_venue
        assert subset.subset_index == 0
        assert subset.people_present == []
        assert subset.members == set()

    def test_init_with_subset_name(self, mock_venue):
        """Test initialization with subset name."""
        subset = Subset(venue=mock_venue, subset_index=0, subset_name='kids')

        assert subset.subset_name == 'kids'

    def test_init_without_subset_name_uses_index(self, mock_venue):
        """Test that subset_name defaults to string of index."""
        subset = Subset(venue=mock_venue, subset_index=5)

        assert subset.subset_name == '5'

    def test_init_with_people_present(self, mock_venue, mock_geo_unit):
        """Test initialization with initial people_present."""
        people = [
            Person(age=25, sex='male', geographical_unit=mock_geo_unit),
            Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        ]

        subset = Subset(venue=mock_venue, subset_index=0, people_present=people)

        assert len(subset.people_present) == 2
        assert subset.people_present == people

    def test_init_with_members(self, mock_venue, mock_geo_unit):
        """Test initialization with initial members set."""
        people = {
            Person(age=25, sex='male', geographical_unit=mock_geo_unit),
            Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        }

        subset = Subset(venue=mock_venue, subset_index=0, members=people)

        assert len(subset.members) == 2
        assert subset.members == people

    def test_init_with_all_parameters(self, mock_venue, mock_geo_unit):
        """Test initialization with all parameters."""
        people_present = [Person(age=25, sex='male', geographical_unit=mock_geo_unit)]
        members = {Person(age=30, sex='female', geographical_unit=mock_geo_unit)}

        subset = Subset(
            venue=mock_venue,
            subset_index=2,
            subset_name='adults',
            people_present=people_present,
            members=members
        )

        assert subset.venue == mock_venue
        assert subset.subset_index == 2
        assert subset.subset_name == 'adults'
        assert subset.people_present == people_present
        assert subset.members == members

    def test_init_with_none_people_present(self, mock_venue):
        """Test that None people_present becomes empty list."""
        subset = Subset(venue=mock_venue, subset_index=0, people_present=None)

        assert subset.people_present == []

    def test_init_with_none_members(self, mock_venue):
        """Test that None members becomes empty set."""
        subset = Subset(venue=mock_venue, subset_index=0, members=None)

        assert subset.members == set()


class TestSubsetMemberManagement:
    """Test member management methods."""

    def test_add_member(self, mock_venue, mock_geo_unit):
        """Test adding a member to the subset."""
        subset = Subset(venue=mock_venue, subset_index=0)
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        subset.add_member(person)

        assert person in subset.members
        assert len(subset.members) == 1

    def test_add_multiple_members(self, mock_venue, mock_geo_unit):
        """Test adding multiple members."""
        subset = Subset(venue=mock_venue, subset_index=0)
        people = [
            Person(age=25, sex='male', geographical_unit=mock_geo_unit),
            Person(age=30, sex='female', geographical_unit=mock_geo_unit),
            Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        ]

        for person in people:
            subset.add_member(person)

        assert len(subset.members) == 3
        assert all(p in subset.members for p in people)

    def test_add_member_duplicate(self, mock_venue, mock_geo_unit):
        """Test that adding same member twice doesn't create duplicates."""
        subset = Subset(venue=mock_venue, subset_index=0)
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        subset.add_member(person)
        subset.add_member(person)

        assert len(subset.members) == 1

    def test_remove_member(self, mock_venue, mock_geo_unit):
        """Test removing a member from the subset."""
        subset = Subset(venue=mock_venue, subset_index=0)
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        subset.add_member(person)
        subset.remove_member(person)

        assert person not in subset.members
        assert len(subset.members) == 0

    def test_remove_member_not_present(self, mock_venue, mock_geo_unit):
        """Test removing a member that's not in the set."""
        subset = Subset(venue=mock_venue, subset_index=0)
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        with pytest.raises(KeyError):
            subset.remove_member(person)

    def test_num_members_property(self, mock_venue, mock_geo_unit):
        """Test num_members property."""
        subset = Subset(venue=mock_venue, subset_index=0)

        assert subset.num_members == 0

        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        subset.add_member(person)

        assert subset.num_members == 1

