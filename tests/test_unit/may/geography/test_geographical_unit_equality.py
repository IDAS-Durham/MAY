"""
Unit tests for GeographicalUnit.__eq__ and GeographicalUnit.__hash__ methods.

Tests equality comparison and hashing functionality for GeographicalUnit objects.
"""

import pytest
from may.geography import GeographicalUnit


# ============================================================================
# GeographicalUnit Equality Tests
# ============================================================================

class TestGeographicalUnitEquality:
    """Test GeographicalUnit.__eq__ method."""

    def test_equality_same_basic_attributes(self):
        """Test equality when all basic attributes match."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        assert unit1 == unit2

    def test_equality_different_ids(self):
        """Test inequality when IDs differ."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=2, name='E00001', level='SGU')

        assert unit1 != unit2

    def test_equality_different_names(self):
        """Test inequality when names differ."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00002', level='SGU')

        assert unit1 != unit2

    def test_equality_different_levels(self):
        """Test inequality when levels differ."""
        unit1 = GeographicalUnit(id=1, name='London', level='LGU')
        unit2 = GeographicalUnit(id=1, name='London', level='MGU')

        assert unit1 != unit2

    def test_equality_with_same_coordinates(self):
        """Test equality when coordinates match."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(51.5, -0.1))
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(51.5, -0.1))

        assert unit1 == unit2

    def test_equality_with_different_coordinates(self):
        """Test inequality when coordinates differ."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(51.5, -0.1))
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(52.0, -0.2))

        assert unit1 != unit2

    def test_equality_both_coordinates_none(self):
        """Test equality when both units have no coordinates."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=None)
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=None)

        assert unit1 == unit2

    def test_equality_one_coordinate_none(self):
        """Test inequality when only one unit has coordinates."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(51.5, -0.1))
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=None)

        assert unit1 != unit2

    def test_equality_with_same_properties(self):
        """Test equality when properties dictionaries match."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit1.properties = {'population': 5000, 'area': 2.5}

        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2.properties = {'population': 5000, 'area': 2.5}

        assert unit1 == unit2

    def test_equality_with_different_properties(self):
        """Test inequality when properties differ."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit1.properties = {'population': 5000}

        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2.properties = {'population': 6000}

        assert unit1 != unit2

    def test_equality_empty_properties(self):
        """Test equality when both have empty properties."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        # Both should have empty dict by default
        assert unit1.properties == {}
        assert unit2.properties == {}
        assert unit1 == unit2

    def test_equality_with_same_parent_different_objects(self):
        """Test equality when parents have same id/name but are different objects."""
        parent1 = GeographicalUnit(id=100, name='London', level='LGU')
        parent2 = GeographicalUnit(id=100, name='London', level='LGU')

        child1 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=parent1)
        child2 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=parent2)

        # Verify parents are different objects
        assert parent1 is not parent2
        # But children should be equal (parents compared by id/name)
        assert child1 == child2

    def test_equality_with_different_parents(self):
        """Test inequality when parents differ."""
        parent_a = GeographicalUnit(id=100, name='London', level='LGU')
        parent_b = GeographicalUnit(id=101, name='Manchester', level='LGU')

        child1 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=parent_a)
        child2 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=parent_b)

        assert child1 != child2

    def test_equality_both_parents_none(self):
        """Test equality when both units have no parent."""
        unit1 = GeographicalUnit(id=1, name='London', level='LGU', parent=None)
        unit2 = GeographicalUnit(id=1, name='London', level='LGU', parent=None)

        assert unit1 == unit2

    def test_equality_one_parent_none(self):
        """Test inequality when only one unit has parent."""
        parent = GeographicalUnit(id=100, name='London', level='LGU')
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=parent)
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU', parent=None)

        assert unit1 != unit2

    def test_equality_ignores_children(self):
        """Test that equality does NOT compare children collections."""
        parent1 = GeographicalUnit(id=1, name='London', level='LGU')
        parent2 = GeographicalUnit(id=1, name='London', level='LGU')

        # Add different children to each parent
        child1 = GeographicalUnit(id=10, name='E00001', level='SGU')
        child2 = GeographicalUnit(id=20, name='E00002', level='SGU')
        parent1.add_child(child1)
        parent2.add_child(child2)

        # Parents should still be equal (children not compared)
        assert parent1 == parent2

    def test_equality_ignores_venues(self):
        """Test that equality does NOT compare venues collections."""
        from may.geography.venue import Venue

        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        # Add venue to only one unit
        venue = Venue(name='hospital_1', venue_type='hospital', geographical_unit=unit1)
        unit1.add_venue(venue)

        # Units should still be equal (venues not compared)
        assert unit1 == unit2

    def test_equality_ignores_people(self):
        """Test that equality does NOT compare people collections."""
        from may.population import Person

        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        # Add person to only one unit
        person = Person(age=30, sex='male', geographical_unit=unit1)
        unit1.add_person(person)

        # Units should still be equal (people not compared)
        assert unit1 == unit2

    def test_equality_non_geographical_unit_object(self):
        """Test that GeographicalUnit is not equal to non-GeographicalUnit objects."""
        unit = GeographicalUnit(id=1, name='E00001', level='SGU')

        assert unit != "E00001"
        assert unit != 1
        assert unit != None
        assert unit != {'id': 1, 'name': 'E00001', 'level': 'SGU'}

    def test_equality_comprehensive(self):
        """Comprehensive test with all attributes."""
        parent1 = GeographicalUnit(id=100, name='London', level='LGU')
        parent2 = GeographicalUnit(id=100, name='London', level='LGU')

        unit1 = GeographicalUnit(
            id=1,
            name='E00001',
            level='SGU',
            coordinates=(51.5074, -0.1278),
            parent=parent1
        )
        unit1.properties = {'population': 5000, 'area': 2.5, 'density': 2000}

        unit2 = GeographicalUnit(
            id=1,
            name='E00001',
            level='SGU',
            coordinates=(51.5074, -0.1278),
            parent=parent2
        )
        unit2.properties = {'population': 5000, 'area': 2.5, 'density': 2000}

        assert unit1 == unit2


# ============================================================================
# GeographicalUnit Hash Tests
# ============================================================================

class TestGeographicalUnitHash:
    """Test GeographicalUnit.__hash__ method."""

    def test_hash_same_id_and_name(self):
        """Test that units with same id and name have same hash."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        assert hash(unit1) == hash(unit2)

    def test_hash_different_ids(self):
        """Test that units with different ids have different hashes."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=2, name='E00001', level='SGU')

        assert hash(unit1) != hash(unit2)

    def test_hash_different_names(self):
        """Test that units with different names have different hashes."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00002', level='SGU')

        assert hash(unit1) != hash(unit2)

    def test_hash_consistency(self):
        """Test that hash is consistent across multiple calls."""
        unit = GeographicalUnit(id=1, name='E00001', level='SGU')

        hash1 = hash(unit)
        hash2 = hash(unit)
        hash3 = hash(unit)

        assert hash1 == hash2 == hash3

    def test_hash_ignores_other_attributes(self):
        """Test that hash only depends on id and name, not other attributes."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU', coordinates=(51.5, -0.1))
        unit2 = GeographicalUnit(id=1, name='E00001', level='LGU', coordinates=(52.0, -0.2))

        # Different level and coordinates, but same id/name
        assert hash(unit1) == hash(unit2)

    def test_geographical_unit_in_set(self):
        """Test that GeographicalUnit objects can be used in sets."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit3 = GeographicalUnit(id=2, name='E00002', level='SGU')

        units_set = {unit1, unit2, unit3}

        # Should have 2 units (unit1 and unit2 are equal)
        assert len(units_set) == 2

    def test_geographical_unit_in_set_different_units(self):
        """Test that different units remain separate in sets."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=2, name='E00002', level='SGU')
        unit3 = GeographicalUnit(id=3, name='E00003', level='SGU')

        units_set = {unit1, unit2, unit3}

        assert len(units_set) == 3

    def test_geographical_unit_as_dict_key(self):
        """Test that GeographicalUnit objects can be used as dictionary keys."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=2, name='E00002', level='SGU')

        unit_data = {
            unit1: 'data_for_E00001',
            unit2: 'data_for_E00002'
        }

        assert unit_data[unit1] == 'data_for_E00001'
        assert unit_data[unit2] == 'data_for_E00002'
        assert len(unit_data) == 2

    def test_geographical_unit_dict_key_same_id_name(self):
        """Test that units with same id/name map to same dict key."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        unit_dict = {}
        unit_dict[unit1] = 'first_value'
        unit_dict[unit2] = 'second_value'

        # unit2 should overwrite unit1's value (same key)
        assert len(unit_dict) == 1
        assert unit_dict[unit1] == 'second_value'
        assert unit_dict[unit2] == 'second_value'


# ============================================================================
# Integration Tests
# ============================================================================

class TestGeographicalUnitEqualityIntegration:
    """Integration tests for equality and hashing."""

    def test_equality_and_hash_contract(self):
        """Test that equal objects have equal hashes (Python invariant)."""
        unit1 = GeographicalUnit(id=1, name='E00001', level='SGU')
        unit2 = GeographicalUnit(id=1, name='E00001', level='SGU')

        # If equal, hashes must be equal
        if unit1 == unit2:
            assert hash(unit1) == hash(unit2)

    def test_hierarchical_equality(self):
        """Test equality in a simple geographical hierarchy."""
        # Create hierarchy 1
        lgu1 = GeographicalUnit(id=1, name='England', level='LGU')
        mgu1 = GeographicalUnit(id=10, name='London', level='MGU', parent=lgu1)
        sgu1 = GeographicalUnit(id=100, name='E00001', level='SGU', parent=mgu1)

        # Create hierarchy 2 (different objects, same structure)
        lgu2 = GeographicalUnit(id=1, name='England', level='LGU')
        mgu2 = GeographicalUnit(id=10, name='London', level='MGU', parent=lgu2)
        sgu2 = GeographicalUnit(id=100, name='E00001', level='SGU', parent=mgu2)

        # All levels should be equal
        assert lgu1 == lgu2
        assert mgu1 == mgu2
        assert sgu1 == sgu2

    def test_mutable_unit_in_set(self):
        """Test that mutating a unit after adding to set doesn't break set."""
        unit = GeographicalUnit(id=1, name='E00001', level='SGU')
        units_set = {unit}

        # Mutate unit (add properties, venues, people)
        unit.properties['population'] = 5000
        from may.geography.venue import Venue
        venue = Venue(name='hospital_1', venue_type='hospital', geographical_unit=unit)
        unit.add_venue(venue)

        # Should still be in set (hash based on immutable id/name)
        assert unit in units_set
        assert len(units_set) == 1

    def test_equality_with_circular_parent_reference(self):
        """Test that equality handles circular parent-child relationships correctly."""
        parent = GeographicalUnit(id=1, name='London', level='LGU')
        child = GeographicalUnit(id=10, name='E00001', level='SGU', parent=parent)
        parent.add_child(child)

        parent2 = GeographicalUnit(id=1, name='London', level='LGU')
        child2 = GeographicalUnit(id=10, name='E00001', level='SGU', parent=parent2)
        parent2.add_child(child2)

        # Should not cause infinite recursion
        assert parent == parent2
        assert child == child2
