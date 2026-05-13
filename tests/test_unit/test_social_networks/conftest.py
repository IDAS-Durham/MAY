"""
Shared toy world fixture for social_networks unit tests.

World structure:
  MGU_1
  ├── SGU_1: persons 0, 1, 2  (ages 10, 10, 60)
  └── SGU_2: persons 3, 4, 5  (ages 12, 30, 31)

Activity venues:
  venue_school: persons 0, 1, 2
  venue_office: persons 3, 4
  (person 5 has no primary_activity)
"""
import pytest


class _GeoUnit:
    def __init__(self, name, level, parent=None):
        self.name = name
        self.level = level
        self.parent = parent


class _Venue:
    def __init__(self, id_val):
        self.id = id_val


class _Subset:
    def __init__(self, venue):
        self.venue = venue


class _Person:
    def __init__(self, id_val, age, geo_unit):
        self.id = id_val
        self.age = age
        self.geographical_unit = geo_unit
        self.activity_map = {}
        self.properties = {}


class _Population:
    def __init__(self, people):
        self.people = people


class _GeoUnit_WithPeople(_GeoUnit):
    """Extended _GeoUnit that supports get_people() and get_units_by_level()."""
    def __init__(self, name, level, parent=None):
        super().__init__(name, level, parent)
        self.people = []
        self.children = []

    def get_people(self):
        result = set(self.people)
        for child in self.children:
            result.update(child.get_people())
        return result


class _Geography:
    def __init__(self, levels):
        self.levels = levels
        self._units_by_level: dict = {}

    def register_unit(self, unit):
        self._units_by_level.setdefault(unit.level, {})[unit.name] = unit

    def get_units_by_level(self, level):
        return self._units_by_level.get(level, {})


class _World:
    def __init__(self, population, geography):
        self.population = population
        self.geography = geography


@pytest.fixture
def toy_world():
    mgu = _GeoUnit("MGU_1", "MGU")
    sgu_1 = _GeoUnit("SGU_1", "SGU", parent=mgu)
    sgu_2 = _GeoUnit("SGU_2", "SGU", parent=mgu)

    venue_school = _Venue("school_1")
    venue_office = _Venue("office_1")

    people = [
        _Person(0, 10, sgu_1),
        _Person(1, 10, sgu_1),
        _Person(2, 60, sgu_1),
        _Person(3, 12, sgu_2),
        _Person(4, 30, sgu_2),
        _Person(5, 31, sgu_2),
    ]

    school_subset = _Subset(venue_school)
    office_subset = _Subset(venue_office)

    people[0].activity_map["primary_activity"] = {"school": [school_subset]}
    people[1].activity_map["primary_activity"] = {"school": [school_subset]}
    people[2].activity_map["primary_activity"] = {"school": [school_subset]}
    people[3].activity_map["primary_activity"] = {"office": [office_subset]}
    people[4].activity_map["primary_activity"] = {"office": [office_subset]}
    # person 5 has no primary_activity

    geography = _Geography(levels=["SGU", "MGU", "LGU"])
    return _World(_Population(people), geography)


@pytest.fixture
def toy_world_local_net():
    """
    World compatible with create_networks.py functions (unit.people + get_units_by_level).

    Structure:
      SGU_A: persons 0, 1, 2, 3  (need >=4 for W-S k=2)
      SGU_B: persons 4, 5, 6, 7
    """
    geography = _Geography(levels=["SGU", "MGU", "LGU"])

    sgu_a = _GeoUnit_WithPeople("SGU_A", "SGU")
    sgu_b = _GeoUnit_WithPeople("SGU_B", "SGU")
    geography.register_unit(sgu_a)
    geography.register_unit(sgu_b)

    people = [_Person(i, 20 + i, sgu_a if i < 4 else sgu_b) for i in range(8)]

    sgu_a.people = people[:4]
    sgu_b.people = people[4:]

    return _World(_Population(people), geography)
