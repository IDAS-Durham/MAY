"""
Unit tests for assigner.py — orchestration logic.

Covers:
- _passes_filters(): age, sex, numerical, activity include/exclude, required attributes
- _get_dependency_aware_order(): topological sort, cycle detection, isolated nodes
- _assign_other_residences(): venue matching, empty venue, already-assigned skip
- _assign_all_people_batch() vs _assign_all_people_sequential(): equivalence
- Statistics tracking: counters accuracy
"""
import pytest
import numpy as np
from collections import defaultdict
from unittest.mock import patch

from may.attribute_assignment.assigner import AttributeAssigner
from may.attribute_assignment.assignment_config import (
    AssignmentRule,
    Role,
    StructureAssignmentRules,
    HouseholdStructure,
    MatchingRule,
)


# =============================================================================
# Minimal real objects
# =============================================================================

class MinimalGeoUnit:
    def __init__(self, name, level="SGU", parent=None):
        self.name = name
        self.level = level
        self.parent = parent

    def get_ancestor_by_level(self, level):
        if self.level == level:
            return self
        current = self.parent
        while current is not None:
            if current.level == level:
                return current
            current = current.parent
        return None


class MinimalSubset:
    def __init__(self, subset_name, venue=None):
        self.subset_name = subset_name
        self.venue = venue


class MinimalPerson:
    _next_id = 3000

    def __init__(self, age=30, sex="M", geographical_unit=None,
                 properties=None, activities=None, category="Adults",
                 residence_venue=None):
        self.id = MinimalPerson._next_id
        MinimalPerson._next_id += 1
        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit
        self.properties = properties if properties is not None else {}
        self.activities = activities if activities is not None else set()
        self.activity_map = {}
        if category:
            subset = MinimalSubset(category, venue=residence_venue)
            self.activity_map = {"residence": {"household": [subset]}}


class MinimalVenue:
    _next_id = 5000

    def __init__(self, venue_type="household", geographical_unit=None,
                 members=None):
        self.id = MinimalVenue._next_id
        MinimalVenue._next_id += 1
        self.type = venue_type
        self.geographical_unit = geographical_unit
        self.properties = {}
        self._members = members or []

    def get_all_members(self):
        return self._members

    def size(self):
        return len(self._members)


class MinimalVenueManager:
    def __init__(self, venues):
        self._venues = venues

    def get_all_venues_list(self):
        return self._venues


class SimpleGeoSource:
    def __init__(self, lookup_data=None, fallback=None):
        self._lookup_data = lookup_data or {}
        self._fallback = fallback or {}

    def lookup(self, *args, **kwargs):
        if len(args) == 1:
            return self._lookup_data.get(args[0], self._fallback)
        return self._fallback


class SimpleDataManager:
    def __init__(self, sources=None):
        self._sources = sources or {}

    def get_source(self, name):
        return self._sources.get(name)

    def lookup(self, source_name, *args, **kwargs):
        source = self.get_source(source_name)
        if source:
            return source.lookup(*args, **kwargs)
        return {}


class MinimalConfig:
    """Config with just enough to create an AttributeAssigner."""
    def __init__(self, attribute_name="ethnicity", filters=None,
                 required_attributes=None, settings=None,
                 assignment_level="person_by_residence",
                 residence_venue_types=None,
                 venue_assignment_rules=None):
        self.attribute_name = attribute_name
        self.filters = filters or {}
        self.required_attributes = required_attributes or {}
        self.settings = settings or {}
        self.assignment_level = assignment_level
        self.residence_venue_types = residence_venue_types or ["household"]
        self.venue_assignment_rules = venue_assignment_rules or []
        self.roles = {}
        self.assignment_rules = {}
        self.household_structures = {}
        self._valid_roles_cache = {}
        self.data_sources = {}
        self.categories = {}


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_ids():
    MinimalPerson._next_id = 3000
    MinimalVenue._next_id = 5000


@pytest.fixture
def geo_unit():
    return MinimalGeoUnit("E00001234")


# =============================================================================
# _passes_filters() Tests
# =============================================================================

class TestPassesFilters:
    """
    _passes_filters checks:
    1. Numerical filters (age, sex, custom attributes)
    2. Activity include/exclude
    3. Required attributes
    When no filters configured, only checks required attributes.
    """

    def _make_assigner(self, filters=None, required_attributes=None):
        config = MinimalConfig(
            filters=filters or {},
            required_attributes=required_attributes or {},
        )
        dm = SimpleDataManager()
        return AttributeAssigner(config, dm)

    # --- No filters ---

    def test_no_filters_passes_everyone(self):
        assigner = self._make_assigner()
        person = MinimalPerson()
        assert assigner._passes_filters(person) is True

    # --- Age filter ---

    def test_age_min_filter_passes_above(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 18}}
        })
        person = MinimalPerson(age=25)
        assert assigner._passes_filters(person) is True

    def test_age_min_filter_passes_at_boundary(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 18}}
        })
        person = MinimalPerson(age=18)
        assert assigner._passes_filters(person) is True

    def test_age_min_filter_rejects_below(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 18}}
        })
        person = MinimalPerson(age=17)
        assert assigner._passes_filters(person) is False

    def test_age_max_filter_passes_below(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'max': 65}}
        })
        person = MinimalPerson(age=50)
        assert assigner._passes_filters(person) is True

    def test_age_max_filter_passes_at_boundary(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'max': 65}}
        })
        person = MinimalPerson(age=65)
        assert assigner._passes_filters(person) is True

    def test_age_max_filter_rejects_above(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'max': 65}}
        })
        person = MinimalPerson(age=66)
        assert assigner._passes_filters(person) is False

    def test_age_min_max_range(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 16, 'max': 74}}
        })
        assert assigner._passes_filters(MinimalPerson(age=16)) is True
        assert assigner._passes_filters(MinimalPerson(age=45)) is True
        assert assigner._passes_filters(MinimalPerson(age=74)) is True
        assert assigner._passes_filters(MinimalPerson(age=15)) is False
        assert assigner._passes_filters(MinimalPerson(age=75)) is False

    # --- Sex filter ---

    def test_sex_filter_with_numerical_type_skips_non_numerical(self):
        """Sex uses direct attribute access but 'numerical' type tries min/max."""
        assigner = self._make_assigner(filters={
            'sex_filter': {'attribute': 'sex', 'type': 'numerical', 'numerical': {'min': 0, 'max': 1}}
        })
        # Sex="M" is a string, not comparable to int — should skip gracefully
        # The code tries person_value < vmin which would raise TypeError
        # Let's test this edge case
        person = MinimalPerson(sex="M")
        # This tests whether the code handles type mismatch
        with pytest.raises(TypeError):
            assigner._passes_filters(person)

    # --- Custom numerical attribute from properties ---

    def test_custom_numerical_filter_from_properties(self):
        assigner = self._make_assigner(filters={
            'income': {'attribute': 'income', 'type': 'numerical', 'numerical': {'min': 1000}}
        })
        person = MinimalPerson(properties={'income': 2000})
        assert assigner._passes_filters(person) is True

    def test_custom_numerical_filter_missing_attribute_passes(self):
        """Person without the attribute passes (None value → continue)."""
        assigner = self._make_assigner(filters={
            'income': {'attribute': 'income', 'type': 'numerical', 'numerical': {'min': 1000}}
        })
        person = MinimalPerson(properties={})
        assert assigner._passes_filters(person) is True

    # --- Activity include filter ---

    def test_include_activities_person_has_matching(self):
        assigner = self._make_assigner(filters={
            'activities': {'include': ['work', 'study']}
        })
        person = MinimalPerson(activities={'work', 'commute'})
        assert assigner._passes_filters(person) is True

    def test_include_activities_person_has_none_matching(self):
        assigner = self._make_assigner(filters={
            'activities': {'include': ['work', 'study']}
        })
        person = MinimalPerson(activities={'sleep', 'commute'})
        assert assigner._passes_filters(person) is False

    def test_include_activities_person_has_empty_activities(self):
        assigner = self._make_assigner(filters={
            'activities': {'include': ['work']}
        })
        person = MinimalPerson(activities=set())
        assert assigner._passes_filters(person) is False

    # --- Activity exclude filter ---

    def test_exclude_activities_person_has_excluded(self):
        assigner = self._make_assigner(filters={
            'activities': {'exclude': ['retired']}
        })
        person = MinimalPerson(activities={'work', 'retired'})
        assert assigner._passes_filters(person) is False

    def test_exclude_activities_person_has_no_excluded(self):
        assigner = self._make_assigner(filters={
            'activities': {'exclude': ['retired']}
        })
        person = MinimalPerson(activities={'work', 'commute'})
        assert assigner._passes_filters(person) is True

    # --- Combined include + exclude ---

    def test_include_and_exclude_combined(self):
        assigner = self._make_assigner(filters={
            'activities': {'include': ['work'], 'exclude': ['retired']}
        })
        # Has work but also retired → excluded
        person1 = MinimalPerson(activities={'work', 'retired'})
        assert assigner._passes_filters(person1) is False

        # Has work, no retired → passes
        person2 = MinimalPerson(activities={'work'})
        assert assigner._passes_filters(person2) is True

        # No work → fails include
        person3 = MinimalPerson(activities={'study'})
        assert assigner._passes_filters(person3) is False

    # --- Combined age + activity ---

    def test_age_and_activity_combined(self):
        assigner = self._make_assigner(filters={
            'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 16, 'max': 74}},
            'activities': {'include': ['work']},
        })
        # Too young → fails
        assert assigner._passes_filters(MinimalPerson(age=15, activities={'work'})) is False
        # Right age, right activity → passes
        assert assigner._passes_filters(MinimalPerson(age=30, activities={'work'})) is True
        # Right age, wrong activity → fails
        assert assigner._passes_filters(MinimalPerson(age=30, activities={'study'})) is False

    # --- Required attributes ---
    # required_attributes no longer gates _passes_filters: a missing dependency
    # is enforced at the point of use (strategy/lookup fails loud → assign_all
    # guard, adr/0010), not by silently dropping the person. So presence/absence
    # of a required attribute does not change filtering.

    def test_required_attribute_present_passes(self):
        assigner = self._make_assigner(
            required_attributes={'ethnicity': {'required': True}}
        )
        assert assigner._passes_filters(MinimalPerson(properties={'ethnicity': 'W'})) is True

    def test_required_attribute_missing_no_longer_filters(self):
        """A missing required attribute passes filters now — enforcement is
        downstream, not a silent drop here."""
        assigner = self._make_assigner(
            required_attributes={'ethnicity': {'required': True}}
        )
        assert assigner._passes_filters(MinimalPerson(properties={})) is True

    def test_required_attribute_missing_without_filters_passes(self):
        """No filters dict + missing required attr → still passes (not dropped)."""
        assigner = self._make_assigner(
            required_attributes={'ethnicity': {'required': True}}
        )
        assert assigner._passes_filters(MinimalPerson(properties={})) is True

    def test_required_attribute_does_not_override_real_filter(self):
        """Real filters still apply; required_attributes don't add a gate."""
        assigner = self._make_assigner(
            filters={'age': {'attribute': 'age', 'type': 'numerical', 'numerical': {'min': 18}}},
            required_attributes={'ethnicity': {'required': True}},
        )
        # Fails the age filter regardless of the missing required attribute.
        assert assigner._passes_filters(MinimalPerson(age=10, properties={})) is False
        # Passes the age filter even though the required attribute is missing.
        assert assigner._passes_filters(MinimalPerson(age=25, properties={})) is True

        # Fails age, has ethnicity
        person3 = MinimalPerson(age=10, properties={'ethnicity': 'W'})
        assert assigner._passes_filters(person3) is False


# =============================================================================
# _get_dependency_aware_order() Tests
# =============================================================================

class TestGetDependencyAwareOrder:
    """
    Tests topological sort for household member ordering.

    Dependencies: e.g., inheritance strategy means children must be assigned
    AFTER parents. The topological sort ensures this.
    """

    def _make_assigner_with_rules(self, structure_rules, roles):
        config = MinimalConfig()
        config.roles = roles
        config.assignment_rules = structure_rules
        config._valid_roles_cache = {}
        config.settings = {}

        # Bind the real methods
        from may.attribute_assignment.assignment_config import AttributeAssignmentConfig
        config.get_person_role = AttributeAssignmentConfig.get_person_role.__get__(config)
        config.get_assignment_rule = AttributeAssignmentConfig.get_assignment_rule.__get__(config)

        dm = SimpleDataManager()
        return AttributeAssigner(config, dm)

    def _make_family_config(self):
        """Standard family with: primary_adult → secondary_adult → children (depends on adults)."""
        roles = {
            "primary_adult": Role(
                name="primary_adult", description="", subsets=["Adults"], role_type="primary"
            ),
            "secondary_adult": Role(
                name="secondary_adult", description="", subsets=["Adults"], role_type="secondary"
            ),
            "children": Role(
                name="children", description="", subsets=["Kids"], role_type="general"
            ),
        }
        family_rules = StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(role="primary_adult", priority=1, description="", assignment={}),
                AssignmentRule(role="secondary_adult", priority=2, description="", assignment={}),
                AssignmentRule(
                    role="children", priority=3, description="", assignment={},
                    dependencies=["primary_adult", "secondary_adult"],
                ),
            ],
        )
        return {"Family": family_rules}, roles

    def test_basic_dependency_order(self):
        """Children depend on adults → adults come first."""
        structure_rules, roles = self._make_family_config()
        assigner = self._make_assigner_with_rules(structure_rules, roles)

        adult1 = MinimalPerson(age=35, category="Adults")
        adult2 = MinimalPerson(age=33, category="Adults")
        child = MinimalPerson(age=8, category="Kids")

        person_categories = {
            adult1.id: "Adults",
            adult2.id: "Adults",
            child.id: "Kids",
        }

        result = assigner._get_dependency_aware_order(
            [child, adult1, adult2], "Family", person_categories
        )

        # Adults must come before child
        result_ids = [p.id for p in result]
        child_idx = result_ids.index(child.id)
        adult1_idx = result_ids.index(adult1.id)
        adult2_idx = result_ids.index(adult2.id)
        assert adult1_idx < child_idx, "Primary adult must be assigned before child"
        assert adult2_idx < child_idx, "Secondary adult must be assigned before child"

    def test_no_dependencies_preserves_base_order(self):
        """Without dependencies, the stable base order (by person id) is used."""
        roles = {
            "primary_adult": Role(
                name="primary_adult", description="", subsets=["Adults"], role_type="primary"
            ),
            "children": Role(
                name="children", description="", subsets=["Kids"], role_type="general"
            ),
        }
        family_rules = StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(role="primary_adult", priority=1, description="", assignment={}),
                AssignmentRule(role="children", priority=2, description="", assignment={}),
            ],
        )
        assigner = self._make_assigner_with_rules({"Family": family_rules}, roles)

        adult = MinimalPerson(age=35, category="Adults")
        child = MinimalPerson(age=8, category="Kids")
        person_categories = {adult.id: "Adults", child.id: "Kids"}

        result = assigner._get_dependency_aware_order(
            [child, adult], "Family", person_categories
        )
        # adult was created before child → lower id → comes first in base order
        assert result[0].id == adult.id

    def test_cycle_fails_loud(self):
        """
        If roles A and B depend on each other (cycle), the order can't be
        satisfied — fail loud rather than silently appending in id order
        (adr/0019). Real cycles are caught at config load; reaching the assigner
        with one is a backstop that must still raise.
        """
        roles = {
            "role_a": Role(name="role_a", description="", subsets=["Adults"], role_type="primary"),
            "role_b": Role(name="role_b", description="", subsets=["Kids"], role_type="primary"),
        }
        # role_a depends on role_b AND role_b depends on role_a
        rules = StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(role="role_a", priority=1, description="", assignment={},
                               dependencies=["role_b"]),
                AssignmentRule(role="role_b", priority=2, description="", assignment={},
                               dependencies=["role_a"]),
            ],
        )
        assigner = self._make_assigner_with_rules({"Family": rules}, roles)

        person_a = MinimalPerson(age=35, category="Adults")
        person_b = MinimalPerson(age=8, category="Kids")
        person_categories = {person_a.id: "Adults", person_b.id: "Kids"}

        with pytest.raises(RuntimeError, match="unordered"):
            assigner._get_dependency_aware_order(
                [person_a, person_b], "Family", person_categories
            )

    def test_isolated_node_no_dependencies(self):
        """Person with no dependencies and nobody depends on them."""
        roles = {
            "primary_adult": Role(
                name="primary_adult", description="", subsets=["Adults"], role_type="primary"
            ),
        }
        rules = StructureAssignmentRules(
            structure_name="Independents",
            description="",
            rules=[
                AssignmentRule(role="primary_adult", priority=1, description="", assignment={}),
            ],
        )
        assigner = self._make_assigner_with_rules({"Independents": rules}, roles)

        person = MinimalPerson(age=35, category="Adults")
        person_categories = {person.id: "Adults"}

        result = assigner._get_dependency_aware_order(
            [person], "Independents", person_categories
        )
        assert len(result) == 1
        assert result[0].id == person.id

    def test_multi_dependency_chain(self):
        """A → B → C chain: C depends on B, B depends on A."""
        roles = {
            "role_a": Role(name="role_a", description="", subsets=["Adults"], role_type="primary"),
            "role_b": Role(name="role_b", description="", subsets=["Old Adults"], role_type="primary"),
            "role_c": Role(name="role_c", description="", subsets=["Kids"], role_type="primary"),
        }
        rules = StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(role="role_a", priority=1, description="", assignment={}),
                AssignmentRule(role="role_b", priority=2, description="", assignment={},
                               dependencies=["role_a"]),
                AssignmentRule(role="role_c", priority=3, description="", assignment={},
                               dependencies=["role_b"]),
            ],
        )
        assigner = self._make_assigner_with_rules({"Family": rules}, roles)

        pa = MinimalPerson(age=40, category="Adults")
        pb = MinimalPerson(age=70, category="Old Adults")
        pc = MinimalPerson(age=10, category="Kids")
        person_categories = {pa.id: "Adults", pb.id: "Old Adults", pc.id: "Kids"}

        result = assigner._get_dependency_aware_order(
            [pc, pb, pa], "Family", person_categories
        )
        result_ids = [p.id for p in result]
        assert result_ids.index(pa.id) < result_ids.index(pb.id)
        assert result_ids.index(pb.id) < result_ids.index(pc.id)


# =============================================================================
# _assign_other_residences() Tests
# =============================================================================

class TestAssignOtherResidences:
    """
    Tests venue-based assignment for non-household residences
    (care homes, dorms, etc.)
    """

    def _make_assigner(self, venue_assignment_rules=None):
        config = MinimalConfig(
            attribute_name="ethnicity",
            venue_assignment_rules=venue_assignment_rules or [],
        )
        geo_source = SimpleGeoSource(fallback={"W": 1.0})
        dm = SimpleDataManager(sources={"geo_distribution": geo_source})
        return AttributeAssigner(config, dm)

    def test_empty_venue_list(self):
        assigner = self._make_assigner()
        result = assigner._assign_other_residences([])
        assert result == 0

    def test_venue_with_no_matching_rule(self):
        """Venue type not in any rule → skipped with warning."""
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
        ])
        geo = MinimalGeoUnit("E00001234")
        person = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="dormitory", members=[person], geographical_unit=geo)

        result = assigner._assign_other_residences([venue])
        assert result == 0
        assert 'ethnicity' not in person.properties

    def test_venue_with_matching_rule_assigns(self):
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
        ])
        geo = MinimalGeoUnit("E00001234")
        person = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="care_home", members=[person], geographical_unit=geo)

        result = assigner._assign_other_residences([venue])
        assert result == 1
        assert person.properties['ethnicity'] == 'W'

    def test_already_assigned_person_skipped(self):
        """Person who already has the attribute should not be reassigned."""
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'A'}}
        ])
        geo = MinimalGeoUnit("E00001234")
        person = MinimalPerson(geographical_unit=geo, properties={'ethnicity': 'W'})
        venue = MinimalVenue(venue_type="care_home", members=[person], geographical_unit=geo)

        result = assigner._assign_other_residences([venue])
        assert result == 0
        assert person.properties['ethnicity'] == 'W'  # unchanged

    def test_empty_venue_no_members(self):
        """Venue with no members → skipped."""
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
        ])
        venue = MinimalVenue(venue_type="care_home", members=[])

        result = assigner._assign_other_residences([venue])
        assert result == 0

    def test_multiple_venues_different_types(self):
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}},
            {'venue_types': ['dormitory'], 'assignment': {'strategy': 'constant', 'value': 'A'}},
        ])
        geo = MinimalGeoUnit("E00001234")
        person1 = MinimalPerson(geographical_unit=geo)
        person2 = MinimalPerson(geographical_unit=geo)
        venue1 = MinimalVenue(venue_type="care_home", members=[person1], geographical_unit=geo)
        venue2 = MinimalVenue(venue_type="dormitory", members=[person2], geographical_unit=geo)

        result = assigner._assign_other_residences([venue1, venue2])
        assert result == 2
        assert person1.properties['ethnicity'] == 'W'
        assert person2.properties['ethnicity'] == 'A'

    def test_missing_source_leaves_residents_unassigned(self):
        """A probabilistic rule against an unregistered source produces no
        distribution, so the strategy fails for that resident (adr/0010) — no
        value is invented. The resident is left unassigned, not given a guess."""
        config = MinimalConfig(
            attribute_name="ethnicity",
            venue_assignment_rules=[
                {'venue_types': ['care_home'],
                 'assignment': {'strategy': 'probabilistic', 'data_source': 'missing_source'}}
            ],
        )
        dm = SimpleDataManager(sources={})  # lookup misses → no distribution
        assigner = AttributeAssigner(config, dm)

        geo = MinimalGeoUnit("E00001234")
        person = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="care_home", members=[person], geographical_unit=geo)

        result = assigner._assign_other_residences([venue])
        assert result == 0
        assert 'ethnicity' not in person.properties

    def test_probabilistic_venue_assignment_assigns(self):
        """
        A venue rule with a probabilistic strategy assigns from the geo source.
        No fallbacks (adr/0010) — venue residents are assigned by explicit
        primary logic, not by a constant-with-fallback dance.
        """
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'],
             'assignment': {'strategy': 'probabilistic',
                            'data_source': 'geo_distribution'}}
        ])
        geo = MinimalGeoUnit("E00001234")
        person = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="care_home", members=[person], geographical_unit=geo)

        result = assigner._assign_other_residences([venue])
        assert result == 1
        assert person.properties['ethnicity'] == 'W'

    def test_stats_updated_correctly(self):
        assigner = self._make_assigner(venue_assignment_rules=[
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
        ])
        geo = MinimalGeoUnit("E00001234")
        person1 = MinimalPerson(geographical_unit=geo)
        person2 = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="care_home", members=[person1, person2], geographical_unit=geo)

        assigner._assign_other_residences([venue])

        assert assigner.stats['people_in_other_residences'] == 2
        assert assigner.stats['other_residences_processed'] == 1
        assert assigner.stats['attribute_distribution']['W'] == 2
        assert assigner.stats['assignments_by_venue_type']['care_home'] == 2


# =============================================================================
# Batch vs Sequential equivalence Tests
# =============================================================================

class TestBatchVsSequentialEquivalence:
    """
    Verifies that batch and sequential assignment modes produce
    equivalent results (same distribution, same stats tracking).
    """

    def _make_venue(self, geo):
        return MinimalVenue(venue_type="household", geographical_unit=geo)

    def _make_people(self, n, geo):
        venue = self._make_venue(geo)
        return [MinimalPerson(age=30, geographical_unit=geo,
                              residence_venue=venue) for _ in range(n)]

    def test_batch_and_sequential_produce_same_distribution(self):
        """
        With fixed seed, batch and sequential should assign to same distribution.
        Using ConstantStrategy for deterministic comparison.
        """
        from may.attribute_assignment.strategies import ConstantStrategy

        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager()
        config = MinimalConfig(attribute_name="ethnicity")

        # Batch
        assigner_batch = AttributeAssigner(config, dm)
        strategy = ConstantStrategy({"strategy": "constant", "value": "W"}, dm)
        people_batch = self._make_people(10, geo)
        assigner_batch._assign_all_people_batch(people_batch, strategy)

        # Sequential
        assigner_seq = AttributeAssigner(config, dm)
        strategy_seq = ConstantStrategy({"strategy": "constant", "value": "W"}, dm)
        people_seq = self._make_people(10, geo)
        np.random.seed(99)  # seed for sample tracking randomness
        assigner_seq._assign_all_people_sequential(people_seq, strategy_seq)

        # Both should assign W to all
        for p in people_batch:
            assert p.properties['ethnicity'] == 'W'
        for p in people_seq:
            assert p.properties['ethnicity'] == 'W'

        assert assigner_batch.stats['assigned_people'] == 10
        assert assigner_seq.stats['assigned_people'] == 10

    def test_batch_handles_dict_results(self):
        """Batch should handle strategies that return dicts (multi-attribute)."""
        from may.attribute_assignment.strategies import AssignmentStrategy

        class DictStrategy(AssignmentStrategy):
            def __init__(self):
                self.strategy_type = "dict_test"
            def assign_batch(self, people, households, contexts):
                return [{"workplace_location": "LOC_A", "work_mode": "WFH"}] * len(people)

        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager()
        config = MinimalConfig(attribute_name="workplace_location")
        assigner = AttributeAssigner(config, dm)

        people = self._make_people(3, geo)
        strategy = DictStrategy()
        assigner._assign_all_people_batch(people, strategy)

        for p in people:
            assert p.properties['workplace_location'] == 'LOC_A'
            assert p.properties['work_mode'] == 'WFH'

    def test_sequential_handles_dict_results(self):
        """Sequential should handle strategies that return dicts."""
        from may.attribute_assignment.strategies import AssignmentStrategy

        class DictStrategy(AssignmentStrategy):
            def __init__(self):
                self.strategy_type = "dict_test"
            def assign(self, person, household, context):
                return {"workplace_location": "LOC_B", "work_mode": "OFFICE"}

        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager()
        config = MinimalConfig(attribute_name="workplace_location")
        assigner = AttributeAssigner(config, dm)

        people = self._make_people(3, geo)
        strategy = DictStrategy()
        np.random.seed(42)
        assigner._assign_all_people_sequential(people, strategy)

        for p in people:
            assert p.properties['workplace_location'] == 'LOC_B'
            assert p.properties['work_mode'] == 'OFFICE'

    def test_batch_none_results_counted_as_unassigned(self):
        from may.attribute_assignment.strategies import AssignmentStrategy

        class NoneStrategy(AssignmentStrategy):
            def __init__(self):
                self.strategy_type = "none_test"
            def assign_batch(self, people, households, contexts):
                return [None] * len(people)

        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager()
        config = MinimalConfig(attribute_name="test_attr")
        assigner = AttributeAssigner(config, dm)

        people = self._make_people(5, geo)
        strategy = NoneStrategy()
        assigner._assign_all_people_batch(people, strategy)

        assert assigner.stats['unassigned_people'] == 5
        assert assigner.stats['assigned_people'] == 0

    def test_sequential_exception_counted_as_unassigned(self):
        """If strategy raises, person should be counted as unassigned."""
        from may.attribute_assignment.strategies import AssignmentStrategy

        class FailingStrategy(AssignmentStrategy):
            def __init__(self):
                self.strategy_type = "failing_test"
            def assign(self, person, household, context):
                raise RuntimeError("Strategy failed")

        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager()
        config = MinimalConfig(attribute_name="test_attr")
        assigner = AttributeAssigner(config, dm)

        people = self._make_people(3, geo)
        strategy = FailingStrategy()
        np.random.seed(42)
        assigner._assign_all_people_sequential(people, strategy)

        assert assigner.stats['unassigned_people'] == 3
        assert assigner.stats['assigned_people'] == 0


# =============================================================================
# Statistics tracking Tests
# =============================================================================

class TestStatisticsTracking:
    """Verifies stat counters are accurate during assignment."""

    def test_attribute_distribution_counts(self):
        """Attribute distribution should count each value correctly."""
        config = MinimalConfig(
            attribute_name="ethnicity",
            venue_assignment_rules=[
                {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
            ],
        )
        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        assigner = AttributeAssigner(config, dm)

        people = [MinimalPerson(geographical_unit=geo) for _ in range(5)]
        venue = MinimalVenue(venue_type="care_home", members=people, geographical_unit=geo)
        assigner._assign_other_residences([venue])

        assert assigner.stats['attribute_distribution']['W'] == 5

    def test_strategy_type_tracking(self):
        """Strategy type should be tracked in stats."""
        config = MinimalConfig(
            attribute_name="ethnicity",
            venue_assignment_rules=[
                {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'W'}}
            ],
        )
        geo = MinimalGeoUnit("E00001234")
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource(fallback={"W": 1.0})})
        assigner = AttributeAssigner(config, dm)

        person = MinimalPerson(geographical_unit=geo)
        venue = MinimalVenue(venue_type="care_home", members=[person], geographical_unit=geo)
        assigner._assign_other_residences([venue])

        assert assigner.stats['assignments_by_strategy']['venue_care_home'] == 1


# =============================================================================
# _get_or_create_strategy cache Tests
# =============================================================================

# =============================================================================
# _get_person_residence_venue() Tests
# =============================================================================

class TestGetPersonResidenceVenue:
    """
    Tests residence venue resolution from person's activity_map.
    Regression tests for bug where venue=None on subset caused AttributeError.
    """

    def _make_assigner(self):
        config = MinimalConfig()
        dm = SimpleDataManager()
        return AttributeAssigner(config, dm)

    def test_returns_venue_when_present(self):
        assigner = self._make_assigner()
        venue = MinimalVenue(venue_type="household")
        person = MinimalPerson(residence_venue=venue)
        result = assigner._get_person_residence_venue(person)
        assert result is venue

    def test_returns_none_when_no_activity_map(self):
        assigner = self._make_assigner()
        person = MinimalPerson(category=None)  # no activity_map entries
        result = assigner._get_person_residence_venue(person)
        assert result is None

    def test_returns_none_when_subset_venue_is_none(self):
        """
        Regression test: subset exists in activity_map but venue=None.
        Previously crashed with AttributeError: 'NoneType' has no attribute 'id'.
        """
        assigner = self._make_assigner()
        person = MinimalPerson(residence_venue=None)  # subset exists, venue=None
        result = assigner._get_person_residence_venue(person)
        assert result is None

    def test_returns_none_when_subsets_list_empty(self):
        assigner = self._make_assigner()
        person = MinimalPerson(category=None)
        person.activity_map = {"residence": {"household": []}}
        result = assigner._get_person_residence_venue(person)
        assert result is None


# =============================================================================
# _get_or_create_strategy cache Tests
# =============================================================================

class TestStrategyCache:
    """Tests strategy caching behaviour."""

    def test_same_config_object_returns_same_strategy(self):
        config = MinimalConfig()
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        assignment_config = {"strategy": "constant", "value": "W"}
        s1 = assigner._get_or_create_strategy(assignment_config)
        s2 = assigner._get_or_create_strategy(assignment_config)
        assert s1 is s2

    def test_different_config_objects_same_content_create_different_strategies(self):
        """
        BUG DOCUMENTATION: Strategy cache uses id(assignment_config) as key.
        Two dicts with identical content but different object ids will create
        separate strategy instances. This is by design for performance but
        means inline-constructed fallback configs won't be cached.
        """
        config = MinimalConfig()
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        config1 = {"strategy": "constant", "value": "W"}
        config2 = {"strategy": "constant", "value": "W"}
        s1 = assigner._get_or_create_strategy(config1)
        s2 = assigner._get_or_create_strategy(config2)
        # Different objects → different cache keys → different instances
        assert s1 is not s2
