"""
Unit tests for Person class (person.py)

Tests the Person class that represents individual agents in the simulation.
"""

import pytest
from collections import defaultdict

from may.population import Person
from may.geography import GeographicalUnit


@pytest.fixture
def mock_geo_unit():
    """Create a mock geographical unit."""
    return GeographicalUnit(id=0, name='TestSGU', level='SGU')


@pytest.fixture(autouse=True)
def reset_person_counter():
    """Reset Person ID counter before each test."""
    Person.reset_counter()
    yield
    Person.reset_counter()


class TestPersonInitialization:
    """Test Person initialization."""

    def test_init_basic(self, mock_geo_unit):
        """Test basic initialization with required parameters."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        assert person.age == 25
        assert person.sex == 'male'
        assert person.geographical_unit == mock_geo_unit
        assert person.activities == set()
        assert person.properties == {}
        assert isinstance(person.activity_map, dict)

    def test_init_with_activities(self, mock_geo_unit):
        """Test initialization with activities list."""
        activities = ['work', 'home', 'shop']
        person = Person(age=30, sex='female', geographical_unit=mock_geo_unit, activities=activities)

        assert person.activities == set(activities)

    def test_init_with_properties(self, mock_geo_unit):
        """Test initialization with custom properties."""
        properties = {'job': 'teacher', 'income': 50000}
        person = Person(age=35, sex='male', geographical_unit=mock_geo_unit, properties=properties)

        assert person.properties == properties

    def test_init_all_parameters(self, mock_geo_unit):
        """Test initialization with all parameters."""
        activities = ['home', 'work']
        properties = {'test': 'value'}

        person = Person(
            age=40,
            sex='female',
            geographical_unit=mock_geo_unit,
            activities=activities,
            properties=properties
        )

        assert person.age == 40
        assert person.sex == 'female'
        assert person.geographical_unit == mock_geo_unit
        assert person.activities == set(activities)
        assert person.properties == properties

    def test_init_without_geo_unit(self):
        """Test initialization without geographical unit."""
        person = Person(age=25, sex='male')

        assert person.geographical_unit is None

    def test_init_with_none_activities(self, mock_geo_unit):
        """Test that None activities becomes empty list."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=None)

        assert person.activities == set()

    def test_init_with_none_properties(self, mock_geo_unit):
        """Test that None properties becomes empty dict."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, properties=None)

        assert person.properties == {}

    def test_init_fractional_age(self, mock_geo_unit):
        """Test initialization with fractional age."""
        person = Person(age=25.5, sex='male', geographical_unit=mock_geo_unit)

        assert person.age == 25.5

    def test_init_infant_age(self, mock_geo_unit):
        """Test initialization with infant age."""
        person = Person(age=0.5, sex='female', geographical_unit=mock_geo_unit)

        assert person.age == 0.5

    def test_init_elderly_age(self, mock_geo_unit):
        """Test initialization with elderly age."""
        person = Person(age=95, sex='male', geographical_unit=mock_geo_unit)

        assert person.age == 95


class TestPersonIDAssignment:
    """Test Person ID assignment and counter."""

    def test_id_assigned_on_creation(self, mock_geo_unit):
        """Test that ID is assigned when Person is created."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        assert hasattr(person, 'id')
        assert isinstance(person.id, int)

    def test_id_increments_for_each_person(self, mock_geo_unit):
        """Test that each person gets a unique, incrementing ID."""
        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        person3 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)

        assert person1.id == 0
        assert person2.id == 1
        assert person3.id == 2

    def test_id_counter_resets(self, mock_geo_unit):
        """Test that ID counter can be reset."""
        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        assert person1.id == 0

        Person.reset_counter()

        person2 = Person(age=30, sex='female', geographical_unit=mock_geo_unit)
        assert person2.id == 0  # Reset to 0

    def test_id_unique_across_many_people(self, mock_geo_unit):
        """Test ID uniqueness with many people."""
        people = [Person(age=25, sex='male', geographical_unit=mock_geo_unit) for _ in range(100)]
        ids = [p.id for p in people]

        # All IDs should be unique
        assert len(ids) == len(set(ids))
        # IDs should be sequential
        assert ids == list(range(100))


class TestActivityManagement:
    """Test activity-related methods."""

    def test_add_activity(self, mock_geo_unit):
        """Test adding a new activity."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home'])

        person.add_activity('work')

        assert 'work' in person.activities
        assert len(person.activities) == 2

    def test_add_activity_duplicate_ignored(self, mock_geo_unit):
        """Test that adding duplicate activity doesn't create duplicates."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home'])

        person.add_activity('home')

        assert len(person.activities) == 1

    def test_add_multiple_activities(self, mock_geo_unit):
        """Test adding multiple activities."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        activities_to_add = ['home', 'work', 'shop', 'exercise']
        for activity in activities_to_add:
            person.add_activity(activity)

        assert len(person.activities) == 4
        assert set(activities_to_add).issubset(person.activities)

    def test_remove_activity(self, mock_geo_unit):
        """Test removing an activity."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home', 'work'])

        person.remove_activity('work')

        assert 'work' not in person.activities
        assert 'home' in person.activities

    def test_remove_activity_not_present(self, mock_geo_unit):
        """Test removing activity that's not in the list."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home'])

        # Should not raise error
        person.remove_activity('work')

        assert person.activities == set(['home'])

    def test_remove_all_activities(self, mock_geo_unit):
        """Test removing all activities."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home', 'work', 'shop'])

        person.remove_activity('home')
        person.remove_activity('work')
        person.remove_activity('shop')

        assert person.activities == set()

    def test_has_activity_true(self, mock_geo_unit):
        """Test has_activity returns True for existing activity."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home', 'work'])

        assert person.has_activity('home') is True
        assert person.has_activity('work') is True

    def test_has_activity_false(self, mock_geo_unit):
        """Test has_activity returns False for non-existing activity."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home'])

        assert person.has_activity('work') is False
        assert person.has_activity('shop') is False

    def test_has_activity_empty_list(self, mock_geo_unit):
        """Test has_activity with empty activities list."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=[])

        assert person.has_activity('home') is False

    def test_has_activity_case_sensitive(self, mock_geo_unit):
        """Test that has_activity is case sensitive."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['Home'])

        assert person.has_activity('Home') is True
        assert person.has_activity('home') is False


class TestActivityMap:
    """Test activity_map functionality."""

    def test_activity_map_initialized(self, mock_geo_unit):
        """Test that activity_map is initialized as dict."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        assert isinstance(person.activity_map, dict)

    def test_activity_map_default_behavior(self, mock_geo_unit):
        """Test that activity_map returns KeyError for missing keys."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        import pytest
        # Accessing non-existent key should return KeyError
        with pytest.raises(KeyError):
            person.activity_map['nonexistent']

    def test_activity_map_can_store_values(self, mock_geo_unit):
        """Test that activity_map can store nested values."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        # Mock subset
        from unittest.mock import Mock
        mock_subset = Mock()

        person.activity_map['home'] = {'household': [mock_subset]}

        assert len(person.activity_map['home']['household']) == 1
        assert person.activity_map['home']['household'][0] == mock_subset


class TestPersonProperties:
    """Test properties dict functionality."""

    def test_properties_can_be_modified(self, mock_geo_unit):
        """Test that properties can be modified after creation."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, properties={'key': 'value'})

        person.properties['new_key'] = 'new_value'

        assert person.properties['new_key'] == 'new_value'

    def test_properties_can_be_deleted(self, mock_geo_unit):
        """Test that properties can be deleted."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, properties={'key': 'value'})

        del person.properties['key']

        assert 'key' not in person.properties

    def test_properties_supports_various_types(self, mock_geo_unit):
        """Test that properties can store various types."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        person.properties['int'] = 42
        person.properties['float'] = 3.14
        person.properties['str'] = 'text'
        person.properties['list'] = [1, 2, 3]
        person.properties['dict'] = {'nested': 'value'}

        assert person.properties['int'] == 42
        assert person.properties['float'] == 3.14
        assert person.properties['str'] == 'text'
        assert person.properties['list'] == [1, 2, 3]
        assert person.properties['dict'] == {'nested': 'value'}


class TestPersonStringRepresentation:
    """Test string representation methods."""

    def test_repr(self, mock_geo_unit):
        """Test __repr__ method."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home', 'work'])

        repr_str = repr(person)

        assert 'Person' in repr_str
        assert 'id=0' in repr_str
        assert 'age=25' in repr_str
        assert 'sex=male' in repr_str
        assert 'TestSGU' in repr_str
        assert 'home' in repr_str
        assert 'work' in repr_str

    def test_repr_without_geo_unit(self):
        """Test __repr__ when geographical_unit is None."""
        person = Person(age=25, sex='male')

        repr_str = repr(person)

        assert 'None' in repr_str

    def test_str(self, mock_geo_unit):
        """Test __str__ method falls back to __repr__."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        str_repr = str(person)

        assert 'Person(id=0' in str_repr
        assert 'age=25' in str_repr
        assert 'sex=male' in str_repr

    def test_str_different_ids(self, mock_geo_unit):
        """Test __str__ shows different IDs for different people."""
        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=30, sex='female', geographical_unit=mock_geo_unit)

        assert 'id=0' in str(person1)
        assert 'id=1' in str(person2)


class TestPersonEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_age_zero(self, mock_geo_unit):
        """Test with age zero (newborn)."""
        person = Person(age=0, sex='female', geographical_unit=mock_geo_unit)

        assert person.age == 0

    def test_negative_age(self, mock_geo_unit):
        """Test with negative age (should be allowed but unusual)."""
        person = Person(age=-1, sex='male', geographical_unit=mock_geo_unit)

        assert person.age == -1

    def test_very_large_age(self, mock_geo_unit):
        """Test with very large age."""
        person = Person(age=150, sex='female', geographical_unit=mock_geo_unit)

        assert person.age == 150

    def test_empty_sex_string(self, mock_geo_unit):
        """Test with empty sex string."""
        person = Person(age=25, sex='', geographical_unit=mock_geo_unit)

        assert person.sex == ''

    def test_unusual_sex_values(self, mock_geo_unit):
        """Test with unusual sex values."""
        person = Person(age=25, sex='other', geographical_unit=mock_geo_unit)

        assert person.sex == 'other'

    def test_empty_activities_list(self, mock_geo_unit):
        """Test explicitly providing empty activities list."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=[])

        assert person.activities == set()
        assert len(person.activities) == 0

    def test_activities_with_empty_strings(self, mock_geo_unit):
        """Test activities list containing empty strings."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['', 'home', ''])

        assert '' in person.activities
        assert len(person.activities) == 2

    def test_activities_with_special_characters(self, mock_geo_unit):
        """Test activities with special characters."""
        activities = ['home-work', 'shop_groceries', 'go.out', 'exercise!']
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=activities)

        assert person.activities == set(activities)


class TestPersonIntegration:
    """Integration tests for Person class."""

    def test_person_workflow(self, mock_geo_unit):
        """Test typical workflow of creating and modifying person."""
        # Create person
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        # Add activities
        person.add_activity('home')
        person.add_activity('work')

        # Set properties
        person.properties['job'] = 'engineer'
        person.properties['housed'] = False

        # Check activity
        assert person.has_activity('home')
        assert person.has_activity('work')

        # Remove activity
        person.remove_activity('work')
        assert not person.has_activity('work')

        # Verify final state
        assert person.age == 25
        assert person.sex == 'male'
        assert len(person.activities) == 1
        assert person.properties['job'] == 'engineer'

    def test_multiple_people_independent(self, mock_geo_unit):
        """Test that multiple people are independent."""
        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit, activities=['home'])
        person2 = Person(age=30, sex='female', geographical_unit=mock_geo_unit, activities=['work'])

        # Modify person1
        person1.add_activity('work')
        person1.properties['test'] = 'value1'

        # Modify person2
        person2.add_activity('home')
        person2.properties['test'] = 'value2'

        # Verify independence
        assert person1.activities == set(['home', 'work'])
        assert person2.activities == set(['work', 'home'])
        assert person1.properties['test'] == 'value1'
        assert person2.properties['test'] == 'value2'

    def test_person_with_complex_properties(self, mock_geo_unit):
        """Test person with complex nested properties."""
        properties = {
            'demographics': {
                'ethnicity': 'Asian',
                'education': 'Bachelor'
            },
            'health': {
                'conditions': ['diabetes', 'hypertension'],
                'vaccinated': True
            },
            'location_history': []
        }

        person = Person(age=45, sex='female', geographical_unit=mock_geo_unit, properties=properties)

        assert person.properties['demographics']['ethnicity'] == 'Asian'
        assert 'diabetes' in person.properties['health']['conditions']
        assert person.properties['health']['vaccinated'] is True


class TestPersonComparison:
    """Test comparison and equality of Person objects."""

    def test_people_with_same_data_different_objects(self, mock_geo_unit):
        """Test that people with same data are different objects."""
        person1 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        # Should be different objects
        assert person1 is not person2
        # With different IDs
        assert person1.id != person2.id

    def test_person_identity(self, mock_geo_unit):
        """Test that person is identical to itself."""
        person = Person(age=25, sex='male', geographical_unit=mock_geo_unit)

        assert person is person


@pytest.mark.parametrize("age,sex", [
    (0, 'male'),
    (5, 'female'),
    (18, 'male'),
    (25, 'female'),
    (65, 'male'),
    (100, 'female'),
])
def test_person_creation_various_ages_sexes(mock_geo_unit, age, sex):
    """Test creating people with various ages and sexes."""
    person = Person(age=age, sex=sex, geographical_unit=mock_geo_unit)

    assert person.age == age
    assert person.sex == sex
