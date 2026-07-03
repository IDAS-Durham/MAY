"""
Unit tests for Subset.

Subset wraps a set of Person ``members`` belonging to a Venue.
"""

import pytest

from may.population import Person, Subset
from may.geography import GeographicalUnit, Venue


@pytest.fixture
def mock_geo_unit():
    return GeographicalUnit(id=0, name="TestSGU", level="SGU")


@pytest.fixture
def mock_venue(mock_geo_unit):
    return Venue(
        name="Test Venue",
        venue_type="test_type",
        geographical_unit=mock_geo_unit,
        properties={},
    )


@pytest.fixture(autouse=True)
def reset_person_counter():
    Person.reset_counter()
    yield
    Person.reset_counter()


def _person(age, sex, geo):
    return Person(age=age, sex=sex, geographical_unit=geo)


# Initialization

class TestSubsetInitialization:
    def test_default_members_is_empty_set(self, mock_venue):
        subset = Subset(venue=mock_venue, subset_index=0)
        assert subset.members == set()
        assert subset.venue is mock_venue
        assert subset.subset_index == 0

    def test_subset_name_defaults_to_index_string(self, mock_venue):
        assert Subset(venue=mock_venue, subset_index=5).subset_name == "5"

    def test_explicit_subset_name(self, mock_venue):
        assert Subset(venue=mock_venue, subset_index=0, subset_name="kids").subset_name == "kids"

    def test_init_accepts_existing_members(self, mock_venue, mock_geo_unit):
        members = {_person(25, "male", mock_geo_unit), _person(30, "female", mock_geo_unit)}
        subset = Subset(venue=mock_venue, subset_index=0, members=members)
        assert subset.members == members

    def test_none_members_normalises_to_empty_set(self, mock_venue):
        assert Subset(venue=mock_venue, subset_index=0, members=None).members == set()

    def test_no_people_present_attribute(self, mock_venue):
        """Subset exposes no 'people_present' attribute."""
        subset = Subset(venue=mock_venue, subset_index=0)
        assert not hasattr(subset, "people_present")


# Membership management

class TestMembership:
    def test_add_member(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        person = _person(25, "male", mock_geo_unit)
        subset.add_member(person)
        assert person in subset.members
        assert subset.num_members == 1

    def test_add_member_is_idempotent(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        person = _person(25, "male", mock_geo_unit)
        subset.add_member(person)
        subset.add_member(person)
        assert subset.num_members == 1

    def test_remove_member(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        person = _person(25, "male", mock_geo_unit)
        subset.add_member(person)
        subset.remove_member(person)
        assert subset.num_members == 0

    def test_remove_missing_member_raises(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        with pytest.raises(KeyError):
            subset.remove_member(_person(25, "male", mock_geo_unit))


# Properties / dunder methods backed by members

class TestSubsetProperties:
    def test_spec_returns_venue_type_and_index(self, mock_venue):
        assert Subset(venue=mock_venue, subset_index=5).spec == ("test_type", 5)

    def test_size_property_via_abstract_set(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        assert subset.size == 0
        subset.add_member(_person(25, "male", mock_geo_unit))
        assert subset.size == 1

    def test_contains_people_property(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        assert subset.contains_people is False
        subset.add_member(_person(25, "male", mock_geo_unit))
        assert subset.contains_people is True

    def test_len_returns_member_count(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        assert len(subset) == 0
        subset.add_member(_person(25, "male", mock_geo_unit))
        assert len(subset) == 1

    def test_contains_checks_members(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0)
        inside = _person(25, "male", mock_geo_unit)
        outside = _person(30, "female", mock_geo_unit)
        subset.add_member(inside)
        assert inside in subset
        assert outside not in subset

    def test_iter_yields_all_members_unordered(self, mock_venue, mock_geo_unit):
        people = [_person(25, "male", mock_geo_unit), _person(30, "female", mock_geo_unit)]
        subset = Subset(venue=mock_venue, subset_index=0, members=set(people))
        # members is a set so iteration order is unspecified — assert by content.
        assert set(iter(subset)) == set(people)

    def test_getitem_returns_a_member(self, mock_venue, mock_geo_unit):
        """__getitem__ indexes into list(members); set order is unspecified
        so we only assert membership, not position."""
        people = [_person(25, "male", mock_geo_unit), _person(30, "female", mock_geo_unit)]
        subset = Subset(venue=mock_venue, subset_index=0, members=set(people))
        assert subset[0] in people
        assert subset[1] in people

    def test_str_does_not_crash(self, mock_venue, mock_geo_unit):
        subset = Subset(venue=mock_venue, subset_index=0, subset_name="adults")
        subset.add_member(_person(25, "male", mock_geo_unit))
        rendered = str(subset)
        assert "adults" in rendered
        assert "Test Venue" in rendered


# Collation

class _BoolPerson:
    """Lightweight stand-in. Person uses __slots__ so we can't add ad-hoc
    attributes for the boolean-attribute filter that _collate expects."""

    __slots__ = ("infected",)

    def __init__(self, infected):
        self.infected = infected


class TestCollation:
    def test_collate_returns_truthy_members(self, mock_venue):
        infected = [_BoolPerson(True), _BoolPerson(True)]
        healthy = [_BoolPerson(False)]
        subset = Subset(
            venue=mock_venue,
            subset_index=0,
            members=set(infected + healthy),
        )
        result = subset._collate("infected")
        assert set(result) == set(infected)

    def test_collate_ifnot_returns_falsy_members(self, mock_venue):
        infected = [_BoolPerson(True)]
        healthy = [_BoolPerson(False), _BoolPerson(False)]
        subset = Subset(
            venue=mock_venue,
            subset_index=0,
            members=set(infected + healthy),
        )
        result = subset._collate("infected", ifnot=True)
        assert set(result) == set(healthy)

    def test_collate_on_empty_subset(self, mock_venue):
        subset = Subset(venue=mock_venue, subset_index=0)
        assert subset._collate("infected") == []
