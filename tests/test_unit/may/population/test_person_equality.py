"""
Unit tests for Person.__eq__ and Person.__hash__ methods.

Tests equality comparison and hashing functionality for Person objects.
"""

import pytest
from may.population import Person
from may.geography import GeographicalUnit
from may.geography.venue import Venue
from may.population.subset import Subset


@pytest.fixture
def mock_geo_unit():
    """Create a mock geographical unit."""
    return GeographicalUnit(id=100, name='E00001', level='SGU')


@pytest.fixture
def mock_geo_unit_alt():
    """Create an alternative mock geographical unit with same id/name."""
    return GeographicalUnit(id=100, name='E00001', level='SGU')


@pytest.fixture(autouse=True)
def reset_person_counter():
    """Reset Person ID counter before each test."""
    Person.reset_counter()
    yield
    Person.reset_counter()


# ============================================================================
# Person Equality Tests
# ============================================================================

class TestPersonEquality:
    """Test Person.__eq__ method."""

    def test_equality_different_ids_same_attributes(self):
        """Test that persons with different IDs but same attributes are equal.

        Person.__eq__ intentionally ignores IDs — two persons with identical
        attributes are considered equal regardless of ID.
        """
        person1 = Person(age=30, sex='male')
        person2 = Person(age=30, sex='male')

        assert person1.id != person2.id
        assert person1 == person2

    def test_equality_same_basic_attributes(self):
        """Test equality when all basic attributes match."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=30, sex='male')
        person2.id = person1.id  # Force same ID

        assert person1 == person2

    def test_equality_different_ages(self):
        """Test that persons with different ages are not equal."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=25, sex='male')
        person2.id = person1.id

        assert person1 != person2

    def test_equality_different_sex(self):
        """Test that persons with different sex are not equal."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=30, sex='female')
        person2.id = person1.id

        assert person1 != person2

    def test_equality_with_none_geo_units(self):
        """Test equality when both persons have no geographical unit."""
        person1 = Person(age=30, sex='male', geographical_unit=None)
        person2 = Person(age=30, sex='male', geographical_unit=None)
        person2.id = person1.id

        assert person1 == person2

    def test_equality_one_none_geo_unit(self):
        """Test inequality when only one person has geographical unit."""
        geo_unit = GeographicalUnit(id=100, name='E00001', level='SGU')
        person1 = Person(age=30, sex='male', geographical_unit=geo_unit)
        person2 = Person(age=30, sex='male', geographical_unit=None)
        person2.id = person1.id

        assert person1 != person2

    def test_equality_same_geo_unit_different_objects(self, mock_geo_unit, mock_geo_unit_alt):
        """Test equality when geo units have same name/id but are different objects."""
        person1 = Person(age=40, sex='female', geographical_unit=mock_geo_unit)
        person2 = Person(age=40, sex='female', geographical_unit=mock_geo_unit_alt)
        person2.id = person1.id

        # Verify they're different objects
        assert mock_geo_unit is not mock_geo_unit_alt
        # But persons should be equal
        assert person1 == person2

    def test_equality_different_geo_units(self):
        """Test inequality when geo units have different name/id."""
        geo_unit1 = GeographicalUnit(id=100, name='E00001', level='SGU')
        geo_unit2 = GeographicalUnit(id=101, name='E00002', level='SGU')

        person1 = Person(age=40, sex='female', geographical_unit=geo_unit1)
        person2 = Person(age=40, sex='female', geographical_unit=geo_unit2)
        person2.id = person1.id

        assert person1 != person2

    def test_equality_with_activities_same_order(self):
        """Test equality when activities are in same order."""
        person1 = Person(age=25, sex='male')
        person1.add_activity('work')
        person1.add_activity('leisure')

        person2 = Person(age=25, sex='male')
        person2.id = person1.id
        person2.add_activity('work')
        person2.add_activity('leisure')

        assert person1 == person2

    def test_equality_with_activities_different_order(self):
        """Test equality when activities are in different order (set comparison)."""
        person1 = Person(age=25, sex='male')
        person1.add_activity('work')
        person1.add_activity('leisure')

        person2 = Person(age=25, sex='male')
        person2.id = person1.id
        person2.add_activity('leisure')
        person2.add_activity('work')

        assert person1 == person2

    def test_equality_different_activities(self):
        """Test inequality when activities differ."""
        person1 = Person(age=25, sex='male')
        person1.add_activity('work')

        person2 = Person(age=25, sex='male')
        person2.id = person1.id
        person2.add_activity('leisure')

        assert person1 != person2

    def test_equality_with_same_properties(self):
        """Test equality when properties dictionaries match."""
        person1 = Person(age=35, sex='female', properties={'occupation': 'teacher', 'salary': 50000})
        person2 = Person(age=35, sex='female', properties={'occupation': 'teacher', 'salary': 50000})
        person2.id = person1.id

        assert person1 == person2

    def test_equality_different_properties(self):
        """Test inequality when properties differ."""
        person1 = Person(age=35, sex='female', properties={'occupation': 'teacher', 'salary': 50000})
        person2 = Person(age=35, sex='female', properties={'occupation': 'teacher', 'salary': 60000})
        person2.id = person1.id

        assert person1 != person2

    def test_equality_with_activity_map(self, mock_geo_unit):
        """Test equality when activity_map structures match."""
        # Create venue and subset
        venue = Venue(name='home_0', venue_type='household', geographical_unit=mock_geo_unit)
        subset1 = Subset(venue=venue, subset_index=0, subset_name='adults')
        subset2 = Subset(venue=venue, subset_index=0, subset_name='adults')

        person1 = Person(age=30, sex='male')
        person1.add_activity('residence')
        person1.activity_map['residence']['household'] = [subset1]

        person2 = Person(age=30, sex='male')
        person2.id = person1.id
        person2.add_activity('residence')
        person2.activity_map['residence']['household'] = [subset2]

        assert person1 == person2

    def test_equality_different_activity_map_venue(self, mock_geo_unit):
        """Test inequality when activity_map venues differ."""
        venue1 = Venue(name='home_0', venue_type='household', geographical_unit=mock_geo_unit)
        venue2 = Venue(name='home_1', venue_type='household', geographical_unit=mock_geo_unit)
        subset1 = Subset(venue=venue1, subset_index=0, subset_name='adults')
        subset2 = Subset(venue=venue2, subset_index=0, subset_name='adults')

        person1 = Person(age=30, sex='male')
        person1.add_activity('residence')
        person1.activity_map['residence']['household'] = [subset1]

        person2 = Person(age=30, sex='male')
        person2.id = person1.id
        person2.add_activity('residence')
        person2.activity_map['residence']['household'] = [subset2]

        assert person1 != person2

    def test_equality_non_person_object(self):
        """Test that Person is not equal to non-Person objects."""
        person = Person(age=30, sex='male')

        assert person != "person"
        assert person != 123
        assert person != None
        assert person != {'id': person.id, 'age': 30}


# ============================================================================
# Person Hash Tests
# ============================================================================

class TestPersonHash:
    """Test Person.__hash__ method."""

    def test_hash_same_id(self):
        """Test that persons with same ID have same hash."""
        person1 = Person(age=28, sex='male')
        person2 = Person(age=50, sex='female')
        person2.id = person1.id

        assert hash(person1) == hash(person2)

    def test_hash_different_ids(self):
        """Test that persons with different IDs have different hashes."""
        person1 = Person(age=28, sex='male')
        person2 = Person(age=28, sex='male')

        assert hash(person1) != hash(person2)

    def test_hash_consistency(self):
        """Test that hash is consistent across multiple calls."""
        person = Person(age=30, sex='male')

        hash1 = hash(person)
        hash2 = hash(person)
        hash3 = hash(person)

        assert hash1 == hash2 == hash3

    def test_person_in_set(self):
        """Test that Person objects can be used in sets."""
        person1 = Person(age=20, sex='male')
        person2 = Person(age=20, sex='male')
        person2.id = person1.id  # Same ID

        people_set = set()
        people_set.add(person1)
        people_set.add(person2)

        # Should only have one person (same hash, same ID)
        assert len(people_set) == 1

    def test_person_in_set_different_ids(self):
        """Test that Person objects with different IDs are separate in sets."""
        person1 = Person(age=20, sex='male')
        person2 = Person(age=20, sex='male')

        people_set = set()
        people_set.add(person1)
        people_set.add(person2)

        # Should have two persons (different IDs)
        assert len(people_set) == 2

    def test_person_as_dict_key(self):
        """Test that Person objects can be used as dictionary keys."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=25, sex='female')

        person_dict = {
            person1: 'person1_data',
            person2: 'person2_data'
        }

        assert person_dict[person1] == 'person1_data'
        assert person_dict[person2] == 'person2_data'
        assert len(person_dict) == 2

    def test_person_dict_key_same_id(self):
        """Test that persons with same ID map to same dict key."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=30, sex='male')
        person2.id = person1.id

        person_dict = {}
        person_dict[person1] = 'first_value'
        person_dict[person2] = 'second_value'

        # person2 should overwrite person1's value (same key)
        assert len(person_dict) == 1
        assert person_dict[person1] == 'second_value'
        assert person_dict[person2] == 'second_value'


# ============================================================================
# Integration Tests
# ============================================================================

class TestPersonEqualityIntegration:
    """Integration tests for equality and hashing."""

    def test_equality_and_hash_contract(self):
        """Test that equal objects have equal hashes (Python invariant)."""
        person1 = Person(age=30, sex='male')
        person2 = Person(age=30, sex='male')
        person2.id = person1.id

        # If equal, hashes must be equal
        if person1 == person2:
            assert hash(person1) == hash(person2)

    def test_mutable_person_in_set(self):
        """Test that mutating a person after adding to set doesn't break set."""
        person = Person(age=30, sex='male')
        people_set = {person}

        # Mutate person
        person.age = 40
        person.add_activity('work')
        person.properties['occupation'] = 'teacher'

        # Should still be in set (hash based on immutable id)
        assert person in people_set
        assert len(people_set) == 1

    def test_equality_comprehensive(self, mock_geo_unit):
        """Comprehensive test with all attributes."""
        # Create two persons with all attributes
        person1 = Person(
            age=35,
            sex='female',
            geographical_unit=mock_geo_unit,
            properties={'occupation': 'doctor', 'salary': 80000}
        )
        person1.add_activity('work')
        person1.add_activity('leisure')
        person1.add_activity('residence')

        # Create venue and subset
        venue = Venue(name='home_0', venue_type='household', geographical_unit=mock_geo_unit)
        subset = Subset(venue=venue, subset_index=0, subset_name='adults')
        person1.activity_map['residence']['household'] = [subset]

        # Create duplicate with different object instances
        geo_unit2 = GeographicalUnit(id=100, name='E00001', level='SGU')
        person2 = Person(
            age=35,
            sex='female',
            geographical_unit=geo_unit2,
            properties={'occupation': 'doctor', 'salary': 80000}
        )
        person2.id = person1.id
        person2.add_activity('work')
        person2.add_activity('leisure')
        person2.add_activity('residence')

        venue2 = Venue(name='home_0', venue_type='household', geographical_unit=geo_unit2)
        venue2.id = venue.id  # Same venue ID
        subset2 = Subset(venue=venue2, subset_index=0, subset_name='adults')
        person2.activity_map['residence']['household'] = [subset2]

        # Should be equal despite different object instances
        assert person1 == person2
        assert hash(person1) == hash(person2)
