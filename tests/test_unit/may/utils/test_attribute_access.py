"""
Unit tests for the shared attribute access utility.
"""

import pytest
from may.utils.attribute_access import get_attribute


# Minimal test objects

class FakeVenue:
    def __init__(self, properties=None, **kwargs):
        self.properties = properties or {}
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeGeoUnit:
    def __init__(self, name="TestGeo", coordinates=(0.0, 0.0)):
        self.name = name
        self.coordinates = coordinates


class FakePerson:
    def __init__(self, age=30, sex="male", properties=None,
                 residence=None, geographical_unit=None):
        self.age = age
        self.sex = sex
        self.properties = properties if properties is not None else {}
        self._residence = residence
        self.geographical_unit = geographical_unit or FakeGeoUnit()

    @property
    def residence(self):
        return self._residence


# get_attribute tests

class TestGetNestedValue:
    def test_direct_attribute(self):
        person = FakePerson(age=25)
        assert get_attribute(person, "age") == 25

    def test_properties_dict(self):
        person = FakePerson(properties={"workplace_sgu": "SGU_01"})
        assert get_attribute(person, "workplace_sgu") == "SGU_01"

    def test_properties_takes_precedence_over_attribute(self):
        """If 'foo' is in properties AND on the object, properties wins."""
        person = FakePerson(properties={"age": 99})
        assert get_attribute(person, "age") == 99

    def test_dot_notation_attribute(self):
        person = FakePerson()
        assert get_attribute(person, "geographical_unit.name") == "TestGeo"

    def test_dot_notation_deep(self):
        person = FakePerson()
        result = get_attribute(person, "geographical_unit.coordinates")
        assert result == (0.0, 0.0)

    def test_dict_access(self):
        data = {"a": {"b": {"c": 42}}}
        assert get_attribute(data, "a.b.c") == 42

    def test_none_obj(self):
        assert get_attribute(None, "anything") is None

    def test_missing_attribute(self):
        person = FakePerson()
        assert get_attribute(person, "nonexistent") is None

    def test_missing_intermediate(self):
        person = FakePerson()
        assert get_attribute(person, "nonexistent.deep.path") is None

    def test_properties_nested_in_venue(self):
        venue = FakeVenue(properties={"original_pattern": "2 0 1 0"})
        assert get_attribute(venue, "original_pattern") == "2 0 1 0"

    def test_explicit_none_is_not_missing(self):
        assert get_attribute(FakePerson(properties={"value": None}), "value", 7) is None

    def test_missing_uses_default(self):
        assert get_attribute(FakePerson(), "missing", 7) == 7

    def test_callable_is_returned(self):
        function = lambda: 1
        assert get_attribute(FakePerson(properties={"value": function}), "value") is function

    def test_invalid_path_is_missing(self):
        assert get_attribute(FakePerson(), "missing..path", 7) == 7


# person-access tests

class TestGetPersonAttribute:
    def test_none_person(self):
        assert get_attribute(None, "age") is None

    def test_empty_path(self):
        person = FakePerson()
        assert get_attribute(person, "") is None
        assert get_attribute(person, None) is None

    def test_direct_attribute(self):
        person = FakePerson(age=42, sex="female")
        assert get_attribute(person, "age") == 42
        assert get_attribute(person, "sex") == "female"

    def test_properties_path(self):
        person = FakePerson(properties={"work_sector": "agriculture"})
        assert get_attribute(person, "work_sector") == "agriculture"

    def test_dot_notation_properties(self):
        """properties.X resolves through the shared properties check."""
        person = FakePerson(properties={"workplace_sgu": "SGU_05"})
        assert get_attribute(person, "properties.workplace_sgu") == "SGU_05"

    def test_residence_type(self):
        venue = FakeVenue(type="household")
        person = FakePerson(residence=venue)
        assert get_attribute(person, "residence.type") == "household"

    def test_residence_properties(self):
        venue = FakeVenue(properties={"original_pattern": "2 0 1 0"})
        person = FakePerson(residence=venue)
        assert get_attribute(person, "residence.properties.original_pattern") == "2 0 1 0"

    def test_residence_missing(self):
        person = FakePerson(residence=None)
        assert get_attribute(person, "residence.type") is None

    def test_geographical_unit(self):
        geo = FakeGeoUnit(name="MyGeo", coordinates=(1.0, 2.0))
        person = FakePerson(geographical_unit=geo)
        assert get_attribute(person, "geographical_unit.name") == "MyGeo"
        assert get_attribute(person, "geographical_unit.coordinates") == (1.0, 2.0)

    def test_missing_attribute(self):
        person = FakePerson()
        assert get_attribute(person, "nonexistent") is None

    def test_residence_nested_property(self):
        venue = FakeVenue(properties={"capacity": 4, "district": "north"})
        person = FakePerson(residence=venue)
        assert get_attribute(person, "residence.capacity") == 4
        assert get_attribute(person, "residence.district") == "north"
