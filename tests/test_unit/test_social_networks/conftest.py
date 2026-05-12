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


class _Geography:
    def __init__(self, levels):
        self.levels = levels


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
