"""
Unit tests for VenueChildCreator.

Tests the creation of child venues (classrooms, offices, uni_years)
from parent venues based on member grouping and capacity rules.
"""

import pytest
from collections import defaultdict
from may.venue_child_creator.venue_child_creator import VenueChildCreator
from may.population.subset import Subset


# =============================================================================
# Minimal real objects — just the interface VenueChildCreator needs
# =============================================================================

class MinimalPerson:
    """Minimal Person with attributes VenueChildCreator accesses."""
    _next_id = 5000

    def __init__(self, age=25, sex="male", properties=None, residence=None):
        self.id = MinimalPerson._next_id
        MinimalPerson._next_id += 1
        self.age = age
        self.sex = sex
        self.properties = properties if properties is not None else {}
        self.activities = set()
        self.activity_map = {}
        self._residence = residence

    @property
    def residence(self):
        return self._residence

    def add_activity(self, activity):
        if activity not in self.activities:
            self.activities.add(activity)
        if activity not in self.activity_map:
            self.activity_map[activity] = {}

    def __repr__(self):
        return f"<Person id={self.id} age={self.age}>"


class MinimalVenue:
    """Minimal Venue with the interface VenueChildCreator uses."""

    def __init__(self, name="test_venue", venue_type="school", properties=None, parent=None):
        self.id = id(self)
        self.name = name
        self.type = venue_type
        self.properties = properties if properties is not None else {}
        self.subsets = {}
        self.parent = parent
        self.children = []
        self.geographical_unit = None

    def get_all_members(self):
        members = []
        for subset in self.subsets.values():
            members.extend(list(subset.members))
        return members

    def add_to_subset(self, person, subset_key=None, activity_name=None, activity_type=None):
        """Simplified add_to_subset matching Venue's interface."""
        if subset_key is None:
            subset_key = 0

        if subset_key not in self.subsets:
            subset_index = len(self.subsets)
            self.subsets[subset_key] = Subset(
                venue=self,
                subset_index=subset_index,
                subset_name=str(subset_key),
            )

        subset = self.subsets[subset_key]
        subset.add_member(person)

        if activity_name is None:
            activity_name = self.type

        if activity_name not in person.activities:
            person.add_activity(activity_name)

        if not isinstance(person.activity_map.get(activity_name), dict):
            person.activity_map[activity_name] = {}

        venue_type_key = activity_type if activity_type is not None else self.type
        if venue_type_key not in person.activity_map[activity_name]:
            person.activity_map[activity_name][venue_type_key] = []

        person.activity_map[activity_name][venue_type_key].append(subset)

    def add_child_venue(self, child):
        self.children.append(child)
        child.parent = self


class MinimalVenueManager:
    """Minimal VenueManager providing get_venues_by_type and create_child_venue."""

    def __init__(self):
        self.venues_by_type = defaultdict(list)
        self._all_venues = []

    def add_venue(self, venue):
        self.venues_by_type[venue.type].append(venue)
        self._all_venues.append(venue)

    def get_venues_by_type(self, venue_type):
        return self.venues_by_type.get(venue_type, [])

    def create_venue(self, venue_type, geo_unit=None, properties=None):
        venue = MinimalVenue(
            name=f"{venue_type}_{len(self._all_venues)}",
            venue_type=venue_type,
            properties=properties or {},
        )
        venue.geographical_unit = geo_unit
        self.add_venue(venue)
        return venue

    def create_child_venue(self, parent_venue, child_venue_type, properties=None, geo_unit=None):
        if geo_unit is None:
            geo_unit = parent_venue.geographical_unit
        child = self.create_venue(
            venue_type=child_venue_type,
            geo_unit=geo_unit,
            properties=properties,
        )
        parent_venue.add_child_venue(child)
        return child


class MinimalWorld:
    """Minimal World with venues attribute."""

    def __init__(self, venue_manager=None):
        self.venues = venue_manager or MinimalVenueManager()


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_person_counter():
    """Reset person ID counter between tests for deterministic IDs."""
    MinimalPerson._next_id = 5000
    yield


@pytest.fixture
def venue_manager():
    return MinimalVenueManager()


@pytest.fixture
def world(venue_manager):
    return MinimalWorld(venue_manager)


def make_people(count, age=10, sex="male", **extra_props):
    """Helper to create a list of MinimalPerson objects."""
    return [MinimalPerson(age=age, sex=sex, properties=dict(extra_props)) for _ in range(count)]


def populate_venue(venue, people, subset_key="student", activity_name="primary_activity"):
    """Helper to add people to a venue's subset."""
    for person in people:
        venue.add_to_subset(person, subset_key=subset_key, activity_name=activity_name)


# =============================================================================
# Tests: __init__ and defaults
# =============================================================================

class TestInit:

    def test_default_values(self):
        creator = VenueChildCreator(
            parent_venue_type="school",
            child_venue_type="classroom",
        )
        assert creator.parent_venue_type == "school"
        assert creator.child_venue_type == "classroom"
        assert creator.group_by_attribute is None
        assert creator.max_capacity == 30
        assert creator.min_capacity == 1
        assert creator.child_properties == {}
        assert creator.distribution_strategy == "even"
        assert creator.attribute_mapping == {}
        assert creator.activity_map_key is None
        assert creator.subset_key is None
        assert creator.replace_parent_activity is True
        assert creator.remove_from_parent is False
        assert creator.member_filters == []

    def test_custom_values(self):
        creator = VenueChildCreator(
            parent_venue_type="company",
            child_venue_type="office",
            group_by_attribute="sector",
            max_capacity=50,
            min_capacity=5,
            child_properties={"capacity": 50},
            distribution_strategy="fill",
            attribute_mapping={"A": "group_a"},
            activity_map_key="primary_activity",
            subset_key="worker",
            replace_parent_activity=False,
            remove_from_parent=True,
            member_filters=[{"attribute": "age", "type": "numerical", "min": 18}],
        )
        assert creator.max_capacity == 50
        assert creator.min_capacity == 5
        assert creator.distribution_strategy == "fill"
        assert creator.remove_from_parent is True
        assert len(creator.member_filters) == 1

    def test_stats_initialized_to_zero(self):
        creator = VenueChildCreator("school", "classroom")
        for key in ("parents_processed", "children_created", "people_redistributed", "people_filtered_out"):
            assert creator.stats[key] == 0


# =============================================================================
# Tests: from_yaml
# =============================================================================

class TestFromYaml:

    def test_loads_required_fields(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "parent_venue_type: school\n"
            "child_venue_type: classroom\n"
        )
        creator = VenueChildCreator.from_yaml(str(yaml_file))
        assert creator.parent_venue_type == "school"
        assert creator.child_venue_type == "classroom"
        assert creator.max_capacity == 30  # default

    def test_loads_all_optional_fields(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            "parent_venue_type: university\n"
            "child_venue_type: uni_year\n"
            "group_by_attribute: age\n"
            "max_capacity: 25\n"
            "min_capacity: 3\n"
            "child_properties:\n"
            "  capacity: 25\n"
            "distribution_strategy: fill\n"
            "attribute_mapping:\n"
            "  18: '18'\n"
            "  19: '19'\n"
            "  default: '23+'\n"
            "activity_map_key: primary_activity\n"
            "subset_key: student\n"
            "replace_parent_activity: false\n"
            "remove_from_parent: true\n"
            "member_filters:\n"
            "  - attribute: age\n"
            "    type: numerical\n"
            "    min: 18\n"
        )
        creator = VenueChildCreator.from_yaml(str(yaml_file))
        assert creator.group_by_attribute == "age"
        assert creator.max_capacity == 25
        assert creator.min_capacity == 3
        assert creator.distribution_strategy == "fill"
        assert creator.attribute_mapping[18] == "18"
        assert creator.attribute_mapping["default"] == "23+"
        assert creator.replace_parent_activity is False
        assert creator.remove_from_parent is True
        assert len(creator.member_filters) == 1


# =============================================================================
# Tests: _filter_members
# =============================================================================

class TestFilterMembers:

    def test_numerical_filter_min(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "min": 18}
        ])
        people = [MinimalPerson(age=a) for a in [10, 17, 18, 25, 65]]
        result = creator._filter_members(people)
        ages = [p.age for p in result]
        assert ages == [18, 25, 65]

    def test_numerical_filter_max(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "max": 17}
        ])
        people = [MinimalPerson(age=a) for a in [10, 17, 18, 25]]
        result = creator._filter_members(people)
        ages = [p.age for p in result]
        assert ages == [10, 17]

    def test_numerical_filter_min_and_max(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "min": 5, "max": 11}
        ])
        people = [MinimalPerson(age=a) for a in [4, 5, 8, 11, 12]]
        result = creator._filter_members(people)
        ages = [p.age for p in result]
        assert ages == [5, 8, 11]

    def test_categorical_filter(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "sex", "type": "categorical", "values": ["female"]}
        ])
        people = [
            MinimalPerson(sex="male"),
            MinimalPerson(sex="female"),
            MinimalPerson(sex="female"),
        ]
        result = creator._filter_members(people)
        assert len(result) == 2
        assert all(p.sex == "female" for p in result)

    def test_multiple_filters_applied_sequentially(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "min": 18},
            {"attribute": "sex", "type": "categorical", "values": ["female"]},
        ])
        people = [
            MinimalPerson(age=10, sex="female"),
            MinimalPerson(age=25, sex="male"),
            MinimalPerson(age=30, sex="female"),
        ]
        result = creator._filter_members(people)
        assert len(result) == 1
        assert result[0].age == 30

    def test_empty_members_returns_empty(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "min": 18}
        ])
        assert creator._filter_members([]) == []

    def test_no_filters_returns_all(self):
        creator = VenueChildCreator("s", "c", member_filters=[])
        people = make_people(5)
        assert creator._filter_members(people) == people

    def test_numerical_filter_missing_attribute_excludes_person(self):
        """Person missing the filtered attribute should be excluded."""
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "age", "type": "numerical", "max": 100}
        ])
        person_with_age = MinimalPerson(age=25)
        person_without_age = MinimalPerson(age=25)
        # Simulate missing attribute by deleting it
        del person_without_age.__dict__["age"]
        result = creator._filter_members([person_with_age, person_without_age])
        # get_person_attribute returns None for missing attrs → excluded by filter
        assert len(result) == 1

    def test_categorical_filter_missing_attribute_excludes_person(self):
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "sector", "type": "categorical", "values": ["Q", "P"]}
        ])
        people = [MinimalPerson(), MinimalPerson()]
        # Neither person has 'sector' attribute → getattr returns None → not in ["Q","P"]
        result = creator._filter_members(people)
        assert len(result) == 0


# =============================================================================
# Tests: _group_members_by_attribute
# =============================================================================

class TestGroupMembersByAttribute:

    def test_group_by_age(self):
        creator = VenueChildCreator("school", "classroom", group_by_attribute="age")
        people = [MinimalPerson(age=10), MinimalPerson(age=10), MinimalPerson(age=11)]
        groups = creator._group_members_by_attribute(people, "age")
        assert set(groups.keys()) == {10, 11}
        assert len(groups[10]) == 2
        assert len(groups[11]) == 1

    def test_group_by_sex(self):
        creator = VenueChildCreator("s", "c", group_by_attribute="sex")
        people = [
            MinimalPerson(sex="male"),
            MinimalPerson(sex="female"),
            MinimalPerson(sex="male"),
        ]
        groups = creator._group_members_by_attribute(people, "sex")
        assert len(groups["male"]) == 2
        assert len(groups["female"]) == 1

    def test_attribute_mapping_specific_values(self):
        creator = VenueChildCreator("uni", "year", attribute_mapping={
            18: "18", 19: "19", 20: "20", "default": "23+"
        })
        people = [
            MinimalPerson(age=18),
            MinimalPerson(age=19),
            MinimalPerson(age=25),
            MinimalPerson(age=30),
        ]
        groups = creator._group_members_by_attribute(people, "age")
        assert len(groups["18"]) == 1
        assert len(groups["19"]) == 1
        assert len(groups["23+"]) == 2  # ages 25 and 30 both map to default

    def test_attribute_mapping_without_default(self):
        creator = VenueChildCreator("s", "c", attribute_mapping={18: "year1"})
        people = [MinimalPerson(age=18), MinimalPerson(age=19)]
        groups = creator._group_members_by_attribute(people, "age")
        assert len(groups["year1"]) == 1
        assert len(groups[19]) == 1  # unmapped value uses raw value

    def test_missing_attribute_goes_to_unknown(self):
        creator = VenueChildCreator("s", "c")
        person = MinimalPerson()
        del person.__dict__["age"]
        # _get_attribute_value returns None for missing attrs → goes to 'unknown'
        groups = creator._group_members_by_attribute([person], "nonexistent_attr")
        assert "unknown" in groups
        assert len(groups["unknown"]) == 1

    def test_group_by_nested_property(self):
        """Test grouping by properties dict (dot notation: 'properties.ethnicity')."""
        creator = VenueChildCreator("s", "c")
        p1 = MinimalPerson(properties={"ethnicity": "A"})
        p2 = MinimalPerson(properties={"ethnicity": "B"})
        p3 = MinimalPerson(properties={"ethnicity": "A"})
        groups = creator._group_members_by_attribute([p1, p2, p3], "properties.ethnicity")
        assert len(groups["A"]) == 2
        assert len(groups["B"]) == 1


# =============================================================================
# Tests: attribute access via shared utility (used by _group_members_by_attribute)
# =============================================================================

class TestGetAttributeValue:

    def test_simple_attribute(self):
        from may.utils.attribute_access import get_person_attribute
        person = MinimalPerson(age=42)
        assert get_person_attribute(person, "age") == 42

    def test_properties_dict(self):
        from may.utils.attribute_access import get_person_attribute
        person = MinimalPerson(properties={"ethnicity": "X"})
        assert get_person_attribute(person, "properties.ethnicity") == "X"

    def test_none_path_returns_none(self):
        from may.utils.attribute_access import get_person_attribute
        assert get_person_attribute(MinimalPerson(), "") is None
        assert get_person_attribute(MinimalPerson(), None) is None

    def test_residence_path(self):
        from may.utils.attribute_access import get_person_attribute
        residence_venue = MinimalVenue(properties={"region": "north"})
        person = MinimalPerson(residence=residence_venue)
        assert get_person_attribute(person, "residence.properties.region") == "north"

    def test_residence_path_no_residence(self):
        from may.utils.attribute_access import get_person_attribute
        person = MinimalPerson(residence=None)
        assert get_person_attribute(person, "residence.type") is None

    def test_missing_nested_returns_none(self):
        from may.utils.attribute_access import get_person_attribute
        person = MinimalPerson()
        assert get_person_attribute(person, "properties.nonexistent") is None


# =============================================================================
# Tests: _create_children_for_group
# =============================================================================

class TestCreateChildrenForGroup:

    def test_creates_correct_number_of_children(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        people = make_people(90, age=10)

        num_created = creator._create_children_for_group(school, 10, people, world)
        assert num_created == 3  # 90 / 30 = 3
        assert len(school.children) == 3
        assert all(c.type == "classroom" for c in school.children)

    def test_creates_one_child_for_small_group(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        people = make_people(5, age=10)

        num_created = creator._create_children_for_group(school, 10, people, world)
        assert num_created == 1

    def test_ceil_rounding(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        people = make_people(31, age=10)

        num_created = creator._create_children_for_group(school, 10, people, world)
        assert num_created == 2  # ceil(31/30) = 2

    def test_below_min_capacity_skips(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator("school", "classroom", max_capacity=30, min_capacity=10)
        people = make_people(5, age=10)

        num_created = creator._create_children_for_group(school, 10, people, world)
        assert num_created == 0
        assert len(school.children) == 0

    def test_child_properties_include_group_key(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator(
            "school", "classroom",
            group_by_attribute="age",
            child_properties={"capacity": 30},
        )
        people = make_people(10, age=12)
        creator._create_children_for_group(school, 12, people, world)

        child = school.children[0]
        assert child.properties["group_key"] == 12
        assert child.properties["age"] == 12
        assert child.properties["capacity"] == 30

    def test_stats_updated(self, world, venue_manager):
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        people = make_people(60, age=10)
        creator._create_children_for_group(school, 10, people, world)

        assert creator.stats["children_created"] == 2
        assert creator.stats["people_redistributed"] == 60

    def test_child_properties_not_shared_across_children(self, world, venue_manager):
        """Ensure shallow copy doesn't cause property bleed between children."""
        school = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school)

        creator = VenueChildCreator(
            "school", "classroom",
            group_by_attribute="age",
            child_properties={"capacity": 30},
            max_capacity=5,
        )
        people = make_people(10, age=10)
        creator._create_children_for_group(school, 10, people, world)

        # Modify one child's properties — should not affect the other
        school.children[0].properties["extra"] = "modified"
        assert "extra" not in school.children[1].properties


# =============================================================================
# Tests: _distribute_members_to_children (even strategy)
# =============================================================================

class TestDistributeEven:

    def test_even_distribution_exact_split(self):
        creator = VenueChildCreator("s", "c", distribution_strategy="even")
        people = make_people(30)
        venues = [MinimalVenue(venue_type="classroom") for _ in range(3)]

        creator._distribute_members_to_children(people, venues)

        for v in venues:
            assert len(v.get_all_members()) == 10

    def test_even_distribution_with_remainder(self):
        creator = VenueChildCreator("s", "c", distribution_strategy="even")
        people = make_people(32)
        venues = [MinimalVenue(venue_type="classroom") for _ in range(3)]

        creator._distribute_members_to_children(people, venues)

        sizes = [sum(len(s.members) for s in v.subsets.values()) for v in venues]
        assert sorted(sizes, reverse=True) == [11, 11, 10]
        assert sum(sizes) == 32

    def test_even_distribution_single_venue(self):
        creator = VenueChildCreator("s", "c", distribution_strategy="even")
        people = make_people(15)
        venues = [MinimalVenue(venue_type="classroom")]

        creator._distribute_members_to_children(people, venues)

        total = sum(len(s.members) for s in venues[0].subsets.values())
        assert total == 15


# =============================================================================
# Tests: _distribute_members_to_children (fill strategy)
# =============================================================================

class TestDistributeFill:

    def test_fill_strategy_fills_first_then_next(self):
        creator = VenueChildCreator("s", "c", distribution_strategy="fill", max_capacity=10)
        people = make_people(25)
        venues = [MinimalVenue(venue_type="classroom") for _ in range(3)]

        creator._distribute_members_to_children(people, venues)

        sizes = [sum(len(s.members) for s in v.subsets.values()) for v in venues]
        assert sizes == [10, 10, 5]

    def test_fill_strategy_exact_capacity(self):
        creator = VenueChildCreator("s", "c", distribution_strategy="fill", max_capacity=10)
        people = make_people(20)
        venues = [MinimalVenue(venue_type="classroom") for _ in range(2)]

        creator._distribute_members_to_children(people, venues)

        sizes = [sum(len(s.members) for s in v.subsets.values()) for v in venues]
        assert sizes == [10, 10]


# =============================================================================
# Tests: _add_person_to_child
# =============================================================================

class TestAddPersonToChild:

    def test_adds_person_to_child_subset(self):
        creator = VenueChildCreator("s", "c", subset_key="student")
        parent = MinimalVenue(name="school", venue_type="school")
        child = MinimalVenue(name="classroom", venue_type="classroom")
        child.parent = parent

        person = MinimalPerson()
        creator._add_person_to_child(person, child)

        assert "student" in child.subsets
        assert person in child.subsets["student"].members

    def test_activity_map_key_used(self):
        creator = VenueChildCreator(
            "s", "c",
            activity_map_key="primary_activity",
            subset_key="student",
        )
        child = MinimalVenue(name="classroom", venue_type="classroom")
        person = MinimalPerson()
        creator._add_person_to_child(person, child)

        assert "primary_activity" in person.activity_map
        assert "classroom" in person.activity_map["primary_activity"]

    def test_default_activity_name_is_child_venue_type(self):
        """When activity_map_key is None, activity_name defaults to child_venue_type
        (the creator's configured type, NOT the venue instance's type)."""
        creator = VenueChildCreator("school", "classroom", activity_map_key=None)
        child = MinimalVenue(name="classroom_1", venue_type="classroom")
        person = MinimalPerson()
        creator._add_person_to_child(person, child)

        assert "classroom" in person.activity_map

    def test_replace_parent_activity_clears_old(self):
        creator = VenueChildCreator(
            "s", "c",
            activity_map_key="primary_activity",
            replace_parent_activity=True,
        )
        child = MinimalVenue(name="classroom", venue_type="classroom")
        person = MinimalPerson()
        # Simulate existing parent activity
        person.activity_map["primary_activity"] = {"school": ["old_subset"]}
        person.activities.add("primary_activity")

        creator._add_person_to_child(person, child)

        # Old school entry should be gone — replaced with empty dict then repopulated
        assert "school" not in person.activity_map["primary_activity"]
        assert "classroom" in person.activity_map["primary_activity"]

    def test_no_replace_keeps_parent_activity(self):
        creator = VenueChildCreator(
            "s", "c",
            activity_map_key="primary_activity",
            replace_parent_activity=False,
        )
        child = MinimalVenue(name="classroom", venue_type="classroom")
        person = MinimalPerson()
        person.activity_map["primary_activity"] = {"school": ["old_subset"]}
        person.activities.add("primary_activity")

        creator._add_person_to_child(person, child)

        # Both should exist
        assert "school" in person.activity_map["primary_activity"]
        assert "classroom" in person.activity_map["primary_activity"]

    def test_remove_from_parent(self):
        creator = VenueChildCreator("s", "c", remove_from_parent=True, subset_key="student")
        parent = MinimalVenue(name="school", venue_type="school")
        child = MinimalVenue(name="classroom", venue_type="classroom")
        parent.add_child_venue(child)

        person = MinimalPerson()
        parent.add_to_subset(person, subset_key="student", activity_name="primary_activity")
        assert person in parent.subsets["student"].members

        creator._add_person_to_child(person, child)

        assert person not in parent.subsets["student"].members
        assert person in child.subsets["student"].members

    def test_no_remove_from_parent_keeps_in_both(self):
        creator = VenueChildCreator("s", "c", remove_from_parent=False, subset_key="student")
        parent = MinimalVenue(name="school", venue_type="school")
        child = MinimalVenue(name="classroom", venue_type="classroom")
        parent.add_child_venue(child)

        person = MinimalPerson()
        parent.add_to_subset(person, subset_key="student", activity_name="primary_activity")

        creator._add_person_to_child(person, child)

        assert person in parent.subsets["student"].members
        assert person in child.subsets["student"].members


# =============================================================================
# Tests: _process_parent_venue
# =============================================================================

class TestProcessParentVenue:

    def test_empty_venue_skipped(self, world):
        creator = VenueChildCreator("school", "classroom")
        school = MinimalVenue(name="empty_school", venue_type="school")

        creator._process_parent_venue(school, world)
        assert creator.stats["parents_processed"] == 0

    def test_groups_created_by_attribute(self, world, venue_manager):
        creator = VenueChildCreator(
            "school", "classroom",
            group_by_attribute="age",
            max_capacity=30,
        )
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)

        people_age10 = make_people(60, age=10)
        people_age11 = make_people(45, age=11)
        populate_venue(school, people_age10 + people_age11)

        creator._process_parent_venue(school, world)

        assert creator.stats["parents_processed"] == 1
        # age 10: ceil(60/30)=2, age 11: ceil(45/30)=2 → 4 children
        assert creator.stats["children_created"] == 4

    def test_no_grouping_single_group(self, world, venue_manager):
        creator = VenueChildCreator(
            "company", "office",
            group_by_attribute=None,
            max_capacity=50,
        )
        company = MinimalVenue(name="company", venue_type="company")
        venue_manager.add_venue(company)

        people = make_people(120, age=30)
        populate_venue(company, people, subset_key="worker", activity_name="primary_activity")

        creator._process_parent_venue(company, world)

        assert creator.stats["children_created"] == 3  # ceil(120/50)=3

    def test_filters_applied_before_grouping(self, world, venue_manager):
        creator = VenueChildCreator(
            "school", "classroom",
            group_by_attribute="age",
            max_capacity=30,
            member_filters=[{"attribute": "age", "type": "numerical", "min": 10}],
        )
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)

        kids = make_people(20, age=10)
        toddlers = make_people(5, age=3)  # Should be filtered out
        populate_venue(school, kids + toddlers)

        creator._process_parent_venue(school, world)

        assert creator.stats["people_filtered_out"] == 5
        assert creator.stats["people_redistributed"] == 20

    def test_all_filtered_out_skips(self, world, venue_manager):
        creator = VenueChildCreator(
            "school", "classroom",
            member_filters=[{"attribute": "age", "type": "numerical", "min": 100}],
        )
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)

        populate_venue(school, make_people(10, age=25))

        creator._process_parent_venue(school, world)
        assert creator.stats["parents_processed"] == 0
        assert creator.stats["people_filtered_out"] == 10


# =============================================================================
# Tests: create_children (full pipeline)
# =============================================================================

class TestCreateChildren:

    def test_no_parent_venues_returns_empty_stats(self, world):
        creator = VenueChildCreator("nonexistent", "child")
        stats = creator.create_children(world)
        assert stats["parents_processed"] == 0
        assert stats["children_created"] == 0

    def test_school_classrooms_pipeline(self, world, venue_manager):
        """Simulate the school → classroom pipeline from config."""
        creator = VenueChildCreator(
            parent_venue_type="school",
            child_venue_type="classroom",
            group_by_attribute="age",
            max_capacity=30,
            min_capacity=1,
            activity_map_key="primary_activity",
            subset_key="student",
            replace_parent_activity=True,
            remove_from_parent=False,
        )

        # Create 2 schools
        school1 = MinimalVenue(name="school_1", venue_type="school")
        school2 = MinimalVenue(name="school_2", venue_type="school")
        venue_manager.add_venue(school1)
        venue_manager.add_venue(school2)

        # School 1: 60 students age 10, 45 age 11
        populate_venue(school1, make_people(60, age=10) + make_people(45, age=11))

        # School 2: 25 students age 10
        populate_venue(school2, make_people(25, age=10))

        stats = creator.create_children(world)

        assert stats["parents_processed"] == 2
        # school1: ceil(60/30) + ceil(45/30) = 2 + 2 = 4
        # school2: ceil(25/30) = 1
        assert stats["children_created"] == 5
        assert stats["people_redistributed"] == 130

        # Verify children are attached to correct parents
        assert len(school1.children) == 4
        assert len(school2.children) == 1

    def test_company_office_pipeline_no_grouping(self, world, venue_manager):
        """Simulate company → office pipeline (no group_by_attribute)."""
        creator = VenueChildCreator(
            parent_venue_type="company",
            child_venue_type="office",
            group_by_attribute=None,
            max_capacity=50,
            activity_map_key="primary_activity",
            subset_key="worker",
        )

        company = MinimalVenue(name="big_corp", venue_type="company")
        venue_manager.add_venue(company)
        populate_venue(company, make_people(150, age=35), subset_key="worker")

        stats = creator.create_children(world)

        assert stats["parents_processed"] == 1
        assert stats["children_created"] == 3  # ceil(150/50)
        assert stats["people_redistributed"] == 150

    def test_university_year_groups_with_mapping(self, world, venue_manager):
        """Simulate university → uni_year pipeline with attribute_mapping."""
        creator = VenueChildCreator(
            parent_venue_type="university",
            child_venue_type="uni_groups_by_year",
            group_by_attribute="age",
            max_capacity=25,
            attribute_mapping={18: "18", 19: "19", 20: "20", "default": "23+"},
            activity_map_key="primary_activity",
            subset_key="student",
        )

        uni = MinimalVenue(name="uni_1", venue_type="university")
        venue_manager.add_venue(uni)

        students = (
            make_people(50, age=18) +
            make_people(30, age=19) +
            make_people(10, age=25) +  # maps to "23+"
            make_people(5, age=30)     # maps to "23+"
        )
        populate_venue(uni, students)

        stats = creator.create_children(world)

        assert stats["parents_processed"] == 1
        # 18: ceil(50/25)=2, 19: ceil(30/25)=2, 23+: ceil(15/25)=1 → 5
        assert stats["children_created"] == 5
        assert stats["people_redistributed"] == 95

    def test_multiple_parent_venues(self, world, venue_manager):
        creator = VenueChildCreator("school", "classroom", max_capacity=10)

        for i in range(5):
            school = MinimalVenue(name=f"school_{i}", venue_type="school")
            venue_manager.add_venue(school)
            populate_venue(school, make_people(20))

        stats = creator.create_children(world)
        assert stats["parents_processed"] == 5
        assert stats["children_created"] == 10  # 5 * ceil(20/10) = 10
        assert stats["people_redistributed"] == 100


# =============================================================================
# Tests: even vs fill distribution correctness
# =============================================================================

class TestDistributionStrategies:

    def test_even_balances_across_classrooms(self, world, venue_manager):
        """Even strategy should produce balanced class sizes."""
        creator = VenueChildCreator(
            "school", "classroom",
            max_capacity=30,
            distribution_strategy="even",
        )
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(50))

        creator.create_children(world)

        # 2 classrooms, 50 students → 25 each
        sizes = [c.size() if hasattr(c, 'size') else sum(len(s.members) for s in c.subsets.values())
                 for c in school.children]
        assert sorted(sizes) == [25, 25]

    def test_fill_fills_sequentially(self, world, venue_manager):
        """Fill strategy should fill first venue to max before starting next."""
        creator = VenueChildCreator(
            "school", "classroom",
            max_capacity=30,
            distribution_strategy="fill",
        )
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(50))

        creator.create_children(world)

        sizes = [sum(len(s.members) for s in c.subsets.values()) for c in school.children]
        assert sizes == [30, 20]

    def test_even_with_one_student(self, world, venue_manager):
        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(1))

        creator.create_children(world)
        assert len(school.children) == 1
        total = sum(len(s.members) for s in school.children[0].subsets.values())
        assert total == 1


# =============================================================================
# Tests: edge cases
# =============================================================================

class TestEdgeCases:

    def test_max_capacity_one(self, world, venue_manager):
        """Each person gets their own child venue."""
        creator = VenueChildCreator("school", "classroom", max_capacity=1)
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(5))

        stats = creator.create_children(world)
        assert stats["children_created"] == 5

    def test_exactly_at_max_capacity(self, world, venue_manager):
        """Exactly max_capacity people → exactly 1 child venue."""
        creator = VenueChildCreator("school", "classroom", max_capacity=30)
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(30))

        stats = creator.create_children(world)
        assert stats["children_created"] == 1

    def test_exactly_at_min_capacity(self, world, venue_manager):
        """Exactly min_capacity people → 1 child created (not skipped)."""
        creator = VenueChildCreator("school", "classroom", max_capacity=30, min_capacity=10)
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(10))

        stats = creator.create_children(world)
        assert stats["children_created"] == 1

    def test_one_below_min_capacity_skips(self, world, venue_manager):
        creator = VenueChildCreator("school", "classroom", max_capacity=30, min_capacity=10)
        school = MinimalVenue(name="school", venue_type="school")
        venue_manager.add_venue(school)
        populate_venue(school, make_people(9))

        stats = creator.create_children(world)
        assert stats["children_created"] == 0
        assert stats["people_redistributed"] == 0

    def test_child_properties_shallow_copy_safety(self):
        """BUG: __init__ doesn't defensively copy child_properties, so external
        mutations to the original dict bleed into the creator.
        This test documents the current (buggy) behavior."""
        props = {"capacity": 30}
        creator = VenueChildCreator("s", "c", child_properties=props)
        props["extra"] = True
        # BUG: mutation bleeds through because __init__ doesn't copy
        assert "extra" in creator.child_properties  # documents the bug

    def test_repr(self):
        creator = VenueChildCreator("school", "classroom", group_by_attribute="age", max_capacity=30)
        r = repr(creator)
        assert "school" in r
        assert "classroom" in r
        assert "age" in r

    def test_repr_with_filters(self):
        creator = VenueChildCreator("s", "c", member_filters=[{"attribute": "age"}])
        assert "filters=1" in repr(creator)


# =============================================================================
# BUG DETECTION TESTS
# =============================================================================

class TestBugDetection:
    """Tests that expose potential bugs or inconsistencies in the implementation."""

    def test_filter_members_supports_dot_notation(self):
        """_filter_members now uses get_person_attribute which supports
        dot-notation paths like 'properties.ethnicity'."""
        creator = VenueChildCreator("s", "c", member_filters=[
            {"attribute": "properties.ethnicity", "type": "categorical", "values": ["A"]}
        ])
        person = MinimalPerson(properties={"ethnicity": "A"})
        result = creator._filter_members([person])

        assert len(result) == 1  # Dot notation now works correctly

    def test_replace_parent_activity_only_works_with_activity_map_key(self):
        """replace_parent_activity only takes effect when activity_map_key is set.
        If activity_map_key is None, the replace logic is silently skipped even
        when replace_parent_activity=True."""
        creator = VenueChildCreator(
            "s", "c",
            activity_map_key=None,  # No activity_map_key
            replace_parent_activity=True,  # Intended to replace
        )
        child = MinimalVenue(name="classroom", venue_type="classroom")
        person = MinimalPerson()
        person.activity_map["primary_activity"] = {"school": ["old_subset"]}
        person.activities.add("primary_activity")

        creator._add_person_to_child(person, child)

        # The old school entry is NOT cleared because activity_map_key is None,
        # so the condition `self.replace_parent_activity and self.activity_map_key`
        # evaluates to False.
        assert "school" in person.activity_map["primary_activity"]

    def test_child_properties_shallow_copy_in_init(self):
        """The __init__ stores child_properties with `or {}` but does NOT copy
        the dict passed in. Mutations to the original dict after construction
        will affect the creator's child_properties."""
        original = {"capacity": 30}
        creator = VenueChildCreator("s", "c", child_properties=original)

        # Mutate the original dict
        original["injected"] = True

        # The creator's child_properties IS the same dict object
        assert creator.child_properties is original  # BUG: no defensive copy in __init__

    def test_stats_accumulate_across_calls(self, world, venue_manager):
        """Stats are never reset between calls to create_children.
        If create_children is called twice, stats accumulate."""
        creator = VenueChildCreator("school", "classroom", max_capacity=10)

        school1 = MinimalVenue(name="school_1", venue_type="school")
        venue_manager.add_venue(school1)
        populate_venue(school1, make_people(10))

        creator.create_children(world)
        assert creator.stats["parents_processed"] == 1

        # Add another school and run again
        school2 = MinimalVenue(name="school_2", venue_type="school")
        venue_manager.add_venue(school2)
        populate_venue(school2, make_people(10))

        creator.create_children(world)
        # Stats accumulated — not reset
        assert creator.stats["parents_processed"] == 3  # 1 + 2 (both schools processed)
