"""
Extended unit tests for assigner.py — covers orchestration methods
not tested in test_assigner.py.

Covers:
- _assign_household(): end-to-end household assignment with context propagation,
  stats tracking, structure classification, role assignment, strategy execution
- assign_all(): routing by assignment_level, unknown level error
- _assign_all_residences(): separation of households from other venues,
  stats calculation, unassigned_people accounting
- _assign_household list return handling (ProbabilisticConditionsStrategy)
- assigned_people counter tracking in household mode
"""
import pytest
import logging
import numpy as np
from collections import defaultdict

from may.attribute_assignment.assigner import AttributeAssigner, AttributeAssignmentError
from may.attribute_assignment.assignment_config import (
    AssignmentRule,
    Role,
    StructureAssignmentRules,
    HouseholdStructure,
    MatchingRule,
    AttributeAssignmentConfig,
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
    _next_id = 7000

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

    def __repr__(self):
        return f"Person(id={self.id}, age={self.age})"


class MinimalVenue:
    _next_id = 8000

    def __init__(self, venue_type="household", geographical_unit=None,
                 members=None, original_pattern=""):
        self.id = MinimalVenue._next_id
        MinimalVenue._next_id += 1
        self.type = venue_type
        self.geographical_unit = geographical_unit
        self.properties = {}
        self._members = members or []
        if original_pattern:
            self.properties["original_pattern"] = original_pattern

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
        # Pair form: (geo_unit_str, first_value).
        if args and isinstance(args[0], str):
            if len(args) == 2:
                geo, val = args
                return self._lookup_data.get(geo, {}).get(val, self._fallback)
            return self._lookup_data.get(args[0], self._fallback)
        # Draw form: (person, household, context) — resolve residence geo like
        # the real GeoDistribution source (adr/0007).
        person = args[0] if args else None
        household = args[1] if len(args) > 1 else None
        geo_unit = None
        if household is not None and getattr(household, 'geographical_unit', None):
            geo_unit = household.geographical_unit.name
        if not geo_unit and getattr(person, 'geographical_unit', None):
            geo_unit = person.geographical_unit.name
        if not geo_unit:
            raise KeyError("no residence geographical_unit for person")
        return self._lookup_data.get(geo_unit, self._fallback)


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
    """Config object matching what AttributeAssigner needs."""
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

    # Bind real methods
    get_person_role = AttributeAssignmentConfig.get_person_role
    get_household_structure = AttributeAssignmentConfig.get_household_structure
    get_assignment_rule = AttributeAssignmentConfig.get_assignment_rule


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_ids():
    MinimalPerson._next_id = 7000
    MinimalVenue._next_id = 8000


@pytest.fixture
def geo_unit():
    return MinimalGeoUnit("E00001234")


def _build_family_config(geo_source, pair_source=None):
    """
    Build a complete config for a Family household with:
    - primary_adult: probabilistic (geo_distribution)
    - secondary_adult: partnership (pair_probabilities)
    - children: inheritance (from adults)
    - Structure: Family (>=1 kids, any adults)
    - Structure: Independents (catch-all)
    """
    config = MinimalConfig(attribute_name="ethnicity", settings={})

    # Roles
    config.roles = {
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

    # Household structures
    config.household_structures = {
        "Family": HouseholdStructure(
            name="Family", description="", inheritance=True,
            matching_rules=[MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"])],
        ),
        "Independents": HouseholdStructure(
            name="Independents", description="", inheritance=False,
            matching_rules=[MatchingRule(actual_patterns=["0 >=0 >=0 >=0"])],
        ),
    }

    # Assignment rules
    primary_assignment = {"strategy": "probabilistic", "data_source": "geo_distribution"}
    secondary_assignment = {
        "strategy": "partnership",
        "data_source": "pair_probabilities",
        "partner_role": "primary_adult",
    }
    children_assignment = {
        "strategy": "inheritance",
        "inherit_from": {"roles": ["primary_adult", "secondary_adult"]},
        "logic": [
            {"when": {"unique_count": 1}, "then": "values[0]"},
            {"when": {"unique_count_at_least": 2}, "then": "M"},
        ],
    }

    config.assignment_rules = {
        "Family": StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(
                    role="primary_adult", priority=1, description="",
                    assignment=primary_assignment,
                ),
                AssignmentRule(
                    role="secondary_adult", priority=2, description="",
                    assignment=secondary_assignment,
                    dependencies=["primary_adult"],
                ),
                AssignmentRule(
                    role="children", priority=3, description="",
                    assignment=children_assignment,
                    dependencies=["primary_adult", "secondary_adult"],
                ),
            ],
        ),
        "Independents": StructureAssignmentRules(
            structure_name="Independents",
            description="",
            rules=[
                AssignmentRule(
                    role=["primary_adult", "secondary_adult"],
                    priority=1, description="",
                    assignment=primary_assignment,
                ),
            ],
        ),
    }

    return config


# =============================================================================
# _assign_household() Tests
# =============================================================================

class TestAssignHousehold:
    """
    Tests the core household assignment orchestration:
    1. Structure classification
    2. Member ordering (dependency-aware)
    3. Role assignment
    4. Strategy execution
    5. Context propagation between members
    6. Stats tracking
    """

    def _make_family_household(self, geo, adults, children):
        """Build a household with real members."""
        all_members = adults + children
        hh = MinimalVenue(
            venue_type="household",
            geographical_unit=geo,
            members=all_members,
        )
        # Set the cached actual pattern
        n_kids = len(children)
        n_adults = len(adults)
        hh.properties["_cached_actual_pattern"] = f"{n_kids} 0 {n_adults} 0"
        return hh

    def test_family_household_end_to_end(self, geo_unit):
        """
        Full Family household: 2 adults + 1 child.
        Expected flow:
        1. Household classified as "Family"
        2. Adult 1 → primary_adult → probabilistic → gets "W" (deterministic source)
        3. Adult 2 → secondary_adult → partnership → gets "W" (deterministic source)
        4. Child → children → inheritance → W+W = W
        """
        geo_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": 1.0}}
        )
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": {"W": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        adult1 = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        adult2 = MinimalPerson(age=33, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)

        household = self._make_family_household(geo_unit, [adult1, adult2], [child])

        assigner._assign_household(household)

        # All should be assigned "W"
        assert adult1.properties["ethnicity"] == "W"
        assert adult2.properties["ethnicity"] == "W"
        assert child.properties["ethnicity"] == "W"

    def test_family_mixed_ethnicity_child_gets_mixed(self, geo_unit):
        """
        Two parents with different ethnicities → child gets "M" (Mixed).
        """
        geo_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": 1.0}}
        )
        # Partnership: W partner → A with p=1.0
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": {"A": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        adult1 = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        adult2 = MinimalPerson(age=33, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)

        household = self._make_family_household(geo_unit, [adult1, adult2], [child])

        assigner._assign_household(household)

        assert adult1.properties["ethnicity"] == "W"
        assert adult2.properties["ethnicity"] == "A"
        assert child.properties["ethnicity"] == "M"

    def test_context_propagation_between_members(self, geo_unit):
        """
        Verify that the context dict carries person references across members.
        After primary_adult is assigned, context["primary_adult_person"] must
        point to that person — the partnership strategy depends on this.
        """
        geo_source = SimpleGeoSource(lookup_data={"E00001234": {"W": 1.0}})
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": {"W": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        adult1 = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        adult2 = MinimalPerson(age=33, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)

        household = self._make_family_household(geo_unit, [adult1, adult2], [child])

        assigner._assign_household(household)

        # If context propagation failed, secondary_adult's partnership strategy
        # would have fallen back to geo_distribution instead of using pair probs.
        # Both adults would get "W" regardless, but the assignment path matters.
        # The real signal here is that the child inherited correctly (not fallback).
        assert child.properties["ethnicity"] == "W"

    def test_dependency_ordering_adults_before_children(self, geo_unit):
        """
        Even if children are passed first in the members list,
        dependency-aware ordering must assign adults first.
        """
        geo_source = SimpleGeoSource(lookup_data={"E00001234": {"B": 1.0}})
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"B": {"B": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        # Put child FIRST in the list
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)
        adult1 = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        adult2 = MinimalPerson(age=33, category="Adults", geographical_unit=geo_unit)

        # Members with child first — ordering must be corrected
        household = self._make_family_household(geo_unit, [adult1, adult2], [child])
        household._members = [child, adult1, adult2]  # override to put child first

        assigner._assign_household(household)

        # Child should inherit from adults, not fall back
        assert child.properties["ethnicity"] == "B"

    def test_stats_tracked_correctly(self, geo_unit):
        """Verify stats counters after household assignment."""
        geo_source = SimpleGeoSource(lookup_data={"E00001234": {"W": 1.0}})
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": {"W": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        adult1 = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        adult2 = MinimalPerson(age=33, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)

        household = self._make_family_household(geo_unit, [adult1, adult2], [child])
        assigner._assign_household(household)

        assert assigner.stats['households_processed'] == 1
        assert assigner.stats['people_in_households'] == 3
        assert assigner.stats['household_structure_counts']['Family'] == 1
        assert assigner.stats['assignments_by_role']['primary_adult'] == 1
        assert assigner.stats['assignments_by_role']['secondary_adult'] == 1
        assert assigner.stats['assignments_by_role']['children'] == 1
        assert assigner.stats['attribute_distribution']['W'] == 3
        assert assigner.stats['unassigned_people'] == 0

    def test_empty_household_skipped(self, geo_unit):
        """Household with no members should be skipped entirely."""
        config = _build_family_config(SimpleGeoSource())
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource()})
        assigner = AttributeAssigner(config, dm)

        household = MinimalVenue(venue_type="household", members=[])
        assigner._assign_household(household)

        assert assigner.stats['households_processed'] == 0
        assert assigner.stats['people_in_households'] == 0

    def test_unclassifiable_household_counts_all_as_unassigned(self, geo_unit):
        """If household structure can't be determined, all members are unassigned."""
        config = _build_family_config(SimpleGeoSource())
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource()})
        assigner = AttributeAssigner(config, dm)

        person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        # No cached_actual_pattern and no age_categories → can't classify
        household = MinimalVenue(venue_type="household", members=[person])

        assigner._assign_household(household)

        assert assigner.stats['unassigned_people'] == 1
        assert 'ethnicity' not in person.properties

    def test_single_parent_family(self, geo_unit):
        """Single adult + child: child inherits from sole parent."""
        geo_source = SimpleGeoSource(lookup_data={"E00001234": {"A": 1.0}})

        config = _build_family_config(geo_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": SimpleGeoSource(),
        })
        assigner = AttributeAssigner(config, dm)

        adult = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)

        household = self._make_family_household(geo_unit, [adult], [child])

        assigner._assign_household(household)

        assert adult.properties["ethnicity"] == "A"
        assert child.properties["ethnicity"] == "A"

    # ---- BUG DETECTION ----

    def test_assigned_people_counter_incremented(self, geo_unit):
        """
        assigned_people is now incremented in _assign_household alongside
        assignments_by_role and assignments_by_strategy.
        """
        geo_source = SimpleGeoSource(lookup_data={"E00001234": {"W": 1.0}})
        pair_source = SimpleGeoSource(
            lookup_data={"E00001234": {"W": {"W": 1.0}}}
        )

        config = _build_family_config(geo_source, pair_source)
        dm = SimpleDataManager(sources={
            "geo_distribution": geo_source,
            "pair_probabilities": pair_source,
        })
        assigner = AttributeAssigner(config, dm)

        adult = MinimalPerson(age=35, category="Adults", geographical_unit=geo_unit)
        child = MinimalPerson(age=8, category="Kids", geographical_unit=geo_unit)
        household = self._make_family_household(geo_unit, [adult], [child])

        assigner._assign_household(household)

        assert adult.properties["ethnicity"] == "W"
        assert child.properties["ethnicity"] == "W"
        assert assigner.stats['assignments_by_role']['primary_adult'] == 1
        assert assigner.stats['assignments_by_role']['children'] == 1
        assert assigner.stats['assigned_people'] == 2

    def test_list_return_value_handled_in_attribute_distribution(self, geo_unit):
        """
        Strategies that return lists (like ProbabilisticConditionsStrategy) are now
        handled correctly: the list is converted to str() for the distribution counter.
        """
        config = MinimalConfig(
            attribute_name="comorbidities",
            settings={},
        )
        config.roles = {
            "primary_adult": Role(
                name="primary_adult", description="", subsets=["Adults"], role_type="primary"
            ),
        }
        config.household_structures = {
            "Independents": HouseholdStructure(
                name="Independents", description="", inheritance=False,
                matching_rules=[MatchingRule(actual_patterns=["0 >=0 >=0 >=0"])],
            ),
        }

        list_assignment = {"strategy": "constant", "value": ["cvd", "crd"]}

        config.assignment_rules = {
            "Independents": StructureAssignmentRules(
                structure_name="Independents",
                description="",
                rules=[
                    AssignmentRule(
                        role="primary_adult", priority=1, description="",
                        assignment=list_assignment,
                    ),
                ],
            ),
        }

        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource()})
        assigner = AttributeAssigner(config, dm)

        person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        household = MinimalVenue(venue_type="household", members=[person])
        household.properties["_cached_actual_pattern"] = "0 0 1 0"

        assigner._assign_household(household)

        # Attribute stored correctly
        assert person.properties["comorbidities"] == ["cvd", "crd"]

        # Stats are now consistent
        assert assigner.stats['assigned_people'] == 1
        assert assigner.stats['assignments_by_role']['primary_adult'] == 1
        assert assigner.stats['attribute_distribution']["['cvd', 'crd']"] == 1
        assert assigner.stats['unassigned_people'] == 0


# =============================================================================
# assign_all() Tests
# =============================================================================

class TestAssignAll:
    """Tests for the main entry point routing logic."""

    def test_routes_to_person_assignment(self):
        """assignment_level='person' routes to _assign_all_people."""
        config = MinimalConfig(
            attribute_name="test_attr",
            assignment_level="person",
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        # person-level needs get_person_assignment_rule
        config.get_person_assignment_rule = lambda: None

        venue = MinimalVenue(venue_type="household", members=[])
        vm = MinimalVenueManager([venue])

        # Should not crash — just finds no people
        stats = assigner.assign_all(vm)
        assert stats['total_people'] == 0

    def test_routes_to_residence_assignment(self):
        """assignment_level='person_by_residence' routes to _assign_all_residences."""
        config = MinimalConfig(
            attribute_name="test_attr",
            assignment_level="person_by_residence",
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        venue = MinimalVenue(venue_type="household", members=[])
        vm = MinimalVenueManager([venue])

        stats = assigner.assign_all(vm)
        assert stats is not None

    def test_routes_person_by_residence_to_residences(self):
        """assignment_level='person_by_residence' also routes to _assign_all_residences."""
        config = MinimalConfig(
            attribute_name="test_attr",
            assignment_level="person_by_residence",
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        venue = MinimalVenue(venue_type="household", members=[])
        vm = MinimalVenueManager([venue])

        stats = assigner.assign_all(vm)
        assert stats is not None

    def test_unknown_assignment_level_raises(self):
        """Unknown assignment_level raises ValueError."""
        config = MinimalConfig(
            attribute_name="test_attr",
            assignment_level="invalid_level",
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        vm = MinimalVenueManager([])
        with pytest.raises(ValueError, match="Unknown assignment_level"):
            assigner.assign_all(vm)

    def test_unassigned_person_fails_loud(self, geo_unit):
        """A full run that leaves anyone unassigned aborts (adr/0010), instead
        of returning stats with unassigned_people > 0 and a green build."""
        config = _build_family_config(SimpleGeoSource())
        dm = SimpleDataManager(sources={"geo_distribution": SimpleGeoSource()})
        assigner = AttributeAssigner(config, dm)

        # 1-member household with no pattern → unclassifiable → 1 unassigned.
        person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        vm = MinimalVenueManager([MinimalVenue(venue_type="household", members=[person])])

        with pytest.raises(AttributeAssignmentError, match="unassigned"):
            assigner.assign_all(vm)


# =============================================================================
# _assign_all_residences() — Stats accounting Tests
# =============================================================================

class TestAssignAllResidencesStats:
    """
    Tests the stats accounting in _assign_all_residences, particularly
    the unassigned_people calculation.
    """

    def test_unassigned_people_accumulated_not_overwritten(self, geo_unit):
        """
        unassigned_people is now accumulated incrementally from both
        _assign_household and _assign_other_residences, not overwritten.
        """
        config = _build_family_config(SimpleGeoSource(fallback={"W": 1.0}))
        config.household_structures["Independents"] = HouseholdStructure(
            name="Independents", description="", inheritance=False,
            matching_rules=[MatchingRule(actual_patterns=[">=0 >=0 >=0 >=0"])],
        )
        config.venue_assignment_rules = [
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'A'}}
        ]
        dm = SimpleDataManager(sources={
            "geo_distribution": SimpleGeoSource(fallback={"W": 1.0}),
            "pair_probabilities": SimpleGeoSource(),
        })
        assigner = AttributeAssigner(config, dm)

        # Unclassifiable household (no pattern → structure=None → 1 unassigned)
        lost_person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        bad_hh = MinimalVenue(venue_type="household", members=[lost_person],
                              geographical_unit=geo_unit)

        # Classifiable household
        ok_person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        good_hh = MinimalVenue(venue_type="household", members=[ok_person],
                               geographical_unit=geo_unit)
        good_hh.properties["_cached_actual_pattern"] = "0 0 1 0"

        # Care home — succeeds
        ch_person = MinimalPerson(age=80, geographical_unit=geo_unit)
        ch = MinimalVenue(venue_type="care_home", members=[ch_person],
                          geographical_unit=geo_unit)

        vm = MinimalVenueManager([bad_hh, good_hh, ch])
        assigner._assign_all_residences(vm)

        assert "ethnicity" not in lost_person.properties
        assert ok_person.properties["ethnicity"] == "W"
        assert ch_person.properties["ethnicity"] == "A"

        # unassigned_people correctly reflects the 1 person from bad_hh
        assert assigner.stats['unassigned_people'] == 1
        assert assigner.stats['total_people'] == 3
        assert assigner.stats['people_in_households'] == 1

    def test_total_people_incremental_vs_final(self, geo_unit):
        """
        _assign_household increments total_people per household (line 689).
        _assign_all_residences then overwrites with venue.size() sum (line 209).
        The final value is correct but the incremental work is wasted.
        """
        config = _build_family_config(SimpleGeoSource(fallback={"W": 1.0}))
        config.household_structures["Independents"] = HouseholdStructure(
            name="Independents", description="", inheritance=False,
            matching_rules=[MatchingRule(actual_patterns=[">=0 >=0 >=0 >=0"])],
        )
        dm = SimpleDataManager(sources={
            "geo_distribution": SimpleGeoSource(fallback={"W": 1.0}),
            "pair_probabilities": SimpleGeoSource(),
        })
        assigner = AttributeAssigner(config, dm)

        person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        hh = MinimalVenue(venue_type="household", members=[person],
                          geographical_unit=geo_unit)
        hh.properties["_cached_actual_pattern"] = "0 0 1 0"

        vm = MinimalVenueManager([hh])
        assigner._assign_all_residences(vm)

        # total_people should be 1 regardless of the incremental/overwrite path
        assert assigner.stats['total_people'] == 1

    def test_households_separated_from_other_venues(self, geo_unit):
        """Verify that household and non-household venues are processed separately."""
        config = _build_family_config(SimpleGeoSource(fallback={"W": 1.0}))
        config.venue_assignment_rules = [
            {'venue_types': ['care_home'], 'assignment': {'strategy': 'constant', 'value': 'A'}}
        ]
        config.household_structures["Independents"] = HouseholdStructure(
            name="Independents", description="", inheritance=False,
            matching_rules=[MatchingRule(actual_patterns=[">=0 >=0 >=0 >=0"])],
        )
        dm = SimpleDataManager(sources={
            "geo_distribution": SimpleGeoSource(fallback={"W": 1.0}),
            "pair_probabilities": SimpleGeoSource(),
        })
        assigner = AttributeAssigner(config, dm)

        hh_person = MinimalPerson(age=30, category="Adults", geographical_unit=geo_unit)
        hh = MinimalVenue(venue_type="household", members=[hh_person],
                          geographical_unit=geo_unit)
        hh.properties["_cached_actual_pattern"] = "0 0 1 0"

        ch_person = MinimalPerson(age=80, geographical_unit=geo_unit)
        ch = MinimalVenue(venue_type="care_home", members=[ch_person],
                          geographical_unit=geo_unit)

        vm = MinimalVenueManager([hh, ch])
        assigner._assign_all_residences(vm)

        # Household person gets geo distribution
        assert hh_person.properties["ethnicity"] == "W"
        # Care home person gets constant "A"
        assert ch_person.properties["ethnicity"] == "A"
        assert assigner.stats['households_processed'] == 1
        assert assigner.stats['other_residences_processed'] == 1


# =============================================================================
# _check_required_attributes() Tests
# =============================================================================

class TestCheckRequiredAttributes:
    """Tests logging/warning behavior for required attribute checking."""

    def test_logs_missing_attributes(self, caplog):
        config = MinimalConfig(
            required_attributes={'ethnicity': {'required': True}}
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        people = [
            MinimalPerson(properties={'ethnicity': 'W'}),
            MinimalPerson(properties={}),  # missing
            MinimalPerson(properties={}),  # missing
        ]

        with caplog.at_level(logging.WARNING):
            assigner._check_required_attributes(people)

        assert any("2 people missing" in msg for msg in caplog.messages)

    def test_no_required_attributes_is_noop(self):
        config = MinimalConfig(required_attributes={})
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        # Should not crash
        assigner._check_required_attributes([MinimalPerson()])

    def test_optional_attributes_not_warned(self, caplog):
        config = MinimalConfig(
            required_attributes={'ethnicity': {'required': False}}
        )
        dm = SimpleDataManager()
        assigner = AttributeAssigner(config, dm)

        with caplog.at_level(logging.WARNING):
            assigner._check_required_attributes([MinimalPerson(properties={})])

        assert not any("missing" in msg.lower() for msg in caplog.messages)
