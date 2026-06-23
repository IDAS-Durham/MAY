"""
Unit tests for assignment_config.py:
- _pattern_matches_cached: operator matching (exact, >=, <=)
- MatchingRule.matches(): actual-only, original-only, both, edge cases
- HouseholdStructure.matches(): first-match-wins
- get_person_role(): primary → secondary → extra escalation
- get_household_structure(): classification + caching
"""
import pytest
from may.attribute_assignment.assignment_config import (
    _pattern_matches_cached,
    MatchingRule,
    HouseholdStructure,
    Role,
    AssignmentRule,
    StructureAssignmentRules,
    AttributeAssignmentConfig,
)
from may.residence.composition_pattern import CompositionPattern


# =============================================================================
# Minimal real objects (matching the interfaces used by assignment_config)
# =============================================================================

class MinimalSubset:
    """Mimics the Subset object that person.activity_map references."""
    def __init__(self, subset_name, venue=None):
        self.subset_name = subset_name
        self.venue = venue

    def __len__(self):
        return 1  # Subset has __len__, Role.matches checks `is not None` not truthiness


class MinimalCategory:
    """Mimics an age category object used in _compute_actual_pattern."""
    def __init__(self, name):
        self.name = name


class MinimalPerson:
    """Matches the interface assignment_config accesses on Person."""
    _next_id = 2000

    def __init__(self, category="Adults"):
        self.id = MinimalPerson._next_id
        MinimalPerson._next_id += 1
        self.activity_map = {}
        if category:
            subset = MinimalSubset(category)
            self.activity_map = {"residence": {"household": [subset]}}


class MinimalHousehold:
    """Matches the interface MatchingRule and get_household_structure access."""
    def __init__(self, original_pattern="", members=None, age_categories=None):
        self.id = id(self)
        self.properties = {}
        self._members = members or []

        if original_pattern:
            self.properties["original_pattern"] = original_pattern

        if age_categories:
            self.properties["_age_categories"] = age_categories

    def get_all_members(self):
        return self._members


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_person_ids():
    MinimalPerson._next_id = 2000


@pytest.fixture(autouse=True)
def clear_pattern_cache():
    """Clear the lru_cache between tests for isolation."""
    _pattern_matches_cached.cache_clear()


AGE_CATEGORIES = [
    MinimalCategory("Kids"),
    MinimalCategory("Young Adults"),
    MinimalCategory("Adults"),
    MinimalCategory("Old Adults"),
]


def make_household_with_actual_pattern(actual_pattern_str, original_pattern=""):
    """
    Build a household where _compute_actual_pattern returns the given pattern.
    We use the _cached_actual_pattern shortcut so we don't need full members.
    """
    h = MinimalHousehold(original_pattern=original_pattern)
    h.properties["_cached_actual_pattern"] = actual_pattern_str
    return h


def make_household_from_members(member_categories, original_pattern=""):
    """
    Build a household with real members so _compute_actual_pattern computes
    the pattern from scratch.
    """
    members = []
    for cat in member_categories:
        p = MinimalPerson(category=cat)
        members.append(p)
    h = MinimalHousehold(
        original_pattern=original_pattern,
        members=members,
        age_categories=AGE_CATEGORIES,
    )
    return h


# =============================================================================
# _pattern_matches_cached Tests
# =============================================================================

class TestPatternMatchesCached:
    """
    Tests the core pattern matching function.
    Format: "Kids YoungAdults Adults OldAdults"
    Operators: exact number, >=N (at least), <=N (at most)
    """

    # --- Exact matching ---

    def test_exact_match_all_zeros(self):
        assert _pattern_matches_cached("0 0 0 0", "0 0 0 0") is True

    def test_exact_match_with_counts(self):
        assert _pattern_matches_cached("2 0 2 0", "2 0 2 0") is True

    def test_exact_mismatch(self):
        assert _pattern_matches_cached("2 0 2 0", "2 0 1 0") is False

    def test_exact_mismatch_single_category(self):
        assert _pattern_matches_cached("0 0 1 0", "0 0 2 0") is False

    # --- >= (gte) operator ---

    def test_gte_exact_boundary(self):
        """>=1 matches count of exactly 1."""
        assert _pattern_matches_cached("1 0 0 0", ">=1 0 0 0") is True

    def test_gte_above_boundary(self):
        """>=1 matches count of 3."""
        assert _pattern_matches_cached("3 0 0 0", ">=1 0 0 0") is True

    def test_gte_below_boundary(self):
        """>=1 does NOT match count of 0."""
        assert _pattern_matches_cached("0 0 0 0", ">=1 0 0 0") is False

    def test_gte_zero_matches_anything(self):
        """>=0 matches any count (0, 1, 5, ...)."""
        for count in [0, 1, 5, 99]:
            assert _pattern_matches_cached(f"{count} 0 0 0", ">=0 0 0 0") is True

    def test_gte_combined_with_exact(self):
        """Mixed operators in same pattern."""
        # Template: >=1 kids, any young adults, exactly 2 adults, 0 old
        assert _pattern_matches_cached("2 0 2 0", ">=1 >=0 2 0") is True
        assert _pattern_matches_cached("0 1 2 0", ">=1 >=0 2 0") is False  # 0 kids < >=1

    # --- <= (lte) operator ---

    def test_lte_exact_boundary(self):
        """<=2 matches count of exactly 2."""
        assert _pattern_matches_cached("0 0 0 2", "0 0 0 <=2") is True

    def test_lte_below_boundary(self):
        """<=2 matches count of 0."""
        assert _pattern_matches_cached("0 0 0 0", "0 0 0 <=2") is True

    def test_lte_above_boundary(self):
        """<=2 does NOT match count of 3."""
        assert _pattern_matches_cached("0 0 0 3", "0 0 0 <=2") is False

    def test_lte_combined_with_gte(self):
        """Pattern: 0 kids, >=1 young adults, 1 adult, <=2 old adults."""
        assert _pattern_matches_cached("0 1 1 1", "0 >=1 1 <=2") is True
        assert _pattern_matches_cached("0 1 1 2", "0 >=1 1 <=2") is True
        assert _pattern_matches_cached("0 1 1 3", "0 >=1 1 <=2") is False  # 3 > <=2

    # --- Edge cases ---

    def test_empty_actual_returns_false(self):
        assert _pattern_matches_cached("", "0 0 0 0") is False

    def test_empty_template_returns_false(self):
        assert _pattern_matches_cached("0 0 0 0", "") is False

    def test_both_empty_returns_false(self):
        assert _pattern_matches_cached("", "") is False

    def test_mismatched_length_returns_false(self):
        """3-element actual vs 4-element template."""
        assert _pattern_matches_cached("0 0 0", "0 0 0 0") is False

    def test_non_numeric_actual_returns_false(self):
        assert _pattern_matches_cached("a b c d", "0 0 0 0") is False

    def test_single_category_pattern(self):
        """Patterns with just one category."""
        assert _pattern_matches_cached("5", ">=3") is True
        assert _pattern_matches_cached("2", ">=3") is False

    # --- Real YAML patterns from attribute_assignment.yaml ---

    def test_yaml_family_rule1_kids_present(self):
        """Family Rule 1: >=1 kids, any others."""
        template = ">=1 >=0 >=0 >=0"
        assert _pattern_matches_cached("2 0 2 0", template) is True
        assert _pattern_matches_cached("1 0 1 0", template) is True
        assert _pattern_matches_cached("0 0 2 0", template) is False  # no kids

    def test_yaml_family_rule2_young_adult_families(self):
        """Family Rule 2: young adults with 1-2 adults."""
        template = "0 >=1 1 <=2"
        assert _pattern_matches_cached("0 1 1 0", template) is True
        assert _pattern_matches_cached("0 2 1 1", template) is True
        assert _pattern_matches_cached("0 1 1 3", template) is False  # 3 > <=2
        assert _pattern_matches_cached("1 1 1 0", template) is False  # has kids

    def test_yaml_couple_adult(self):
        """Couple: exactly 0 0 2 0."""
        template = "0 0 2 0"
        assert _pattern_matches_cached("0 0 2 0", template) is True
        assert _pattern_matches_cached("0 0 1 0", template) is False
        assert _pattern_matches_cached("0 0 2 1", template) is False

    def test_yaml_independents_catch_all(self):
        """Independents catch-all: 0 >=0 >=0 >=0 (any combo without kids)."""
        template = "0 >=0 >=0 >=0"
        assert _pattern_matches_cached("0 0 1 0", template) is True
        assert _pattern_matches_cached("0 3 0 0", template) is True
        assert _pattern_matches_cached("0 0 0 5", template) is True
        assert _pattern_matches_cached("1 0 1 0", template) is False  # has kids


# =============================================================================
# MatchingRule.matches() Tests
# =============================================================================

class TestMatchingRule:
    """
    MatchingRule.matches() has three branches:
    1. actual_patterns only → flexible operator matching on computed pattern
    2. original_patterns only → plain string `in` check
    3. both → both must match (AND)
    4. neither → always True
    """

    # --- Actual patterns only ---

    def test_actual_only_matches(self):
        rule = MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"])
        h = make_household_with_actual_pattern("2 0 2 0")
        assert rule.matches(h) is True

    def test_actual_only_no_match(self):
        rule = MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"])
        h = make_household_with_actual_pattern("0 0 2 0")
        assert rule.matches(h) is False

    def test_actual_multiple_patterns_any_can_match(self):
        """If ANY actual pattern matches, rule matches."""
        rule = MatchingRule(actual_patterns=["0 0 1 0", "0 0 0 1"])
        h = make_household_with_actual_pattern("0 0 0 1")
        assert rule.matches(h) is True

    # --- Original patterns only ---

    def test_original_only_matches_exact_string(self):
        rule = MatchingRule(original_patterns=[">=2 >=0 1 0", "0 0 2 0"])
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern=">=2 >=0 1 0")
        assert rule.matches(h) is True

    def test_original_only_no_match(self):
        rule = MatchingRule(original_patterns=[">=2 >=0 1 0"])
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern="0 0 2 0")
        assert rule.matches(h) is False

    def test_original_pattern_uses_plain_string_comparison(self):
        """
        Original patterns use `in` (plain string equality check), NOT
        flexible operator matching. This is correct because the stored
        original_pattern is the raw template string from the CSV config.

        "2 0 1 0" (a concrete count) does NOT match ">=2 >=0 1 0" (a template)
        because it's a string comparison, not pattern matching.
        """
        rule = MatchingRule(original_patterns=[">=2 >=0 1 0"])
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern="2 0 1 0")
        # "2 0 1 0" != ">=2 >=0 1 0" as strings
        assert rule.matches(h) is False

    # --- Both actual AND original (conditional matching) ---

    def test_both_actual_and_original_must_match(self):
        """Family Rule 2: actual matches AND original matches."""
        rule = MatchingRule(
            actual_patterns=["0 >=1 1 <=2"],
            original_patterns=[">=2 >=0 1 0", "1 >=0 1 0"],
        )
        # Actual matches template, original is in the list
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern=">=2 >=0 1 0")
        assert rule.matches(h) is True

    def test_actual_matches_but_original_does_not(self):
        rule = MatchingRule(
            actual_patterns=["0 >=1 1 <=2"],
            original_patterns=[">=2 >=0 1 0"],
        )
        # Actual matches, but original "0 0 2 0" is NOT in the list
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern="0 0 2 0")
        assert rule.matches(h) is False

    def test_original_matches_but_actual_does_not(self):
        rule = MatchingRule(
            actual_patterns=["0 >=1 1 <=2"],
            original_patterns=[">=2 >=0 1 0"],
        )
        # Original matches, but actual "1 1 1 0" has kids (doesn't match "0 >=1 1 <=2")
        h = make_household_with_actual_pattern("1 1 1 0", original_pattern=">=2 >=0 1 0")
        assert rule.matches(h) is False

    # --- No patterns (empty rule) ---

    def test_no_patterns_always_matches(self):
        rule = MatchingRule()
        h = make_household_with_actual_pattern("99 99 99 99")
        assert rule.matches(h) is True

    # --- _compute_actual_pattern from real members ---

    def test_compute_actual_pattern_from_members(self):
        """
        When no cached pattern exists, _compute_actual_pattern counts
        members by their activity_map subset category.
        """
        rule = MatchingRule(actual_patterns=["2 0 2 0"])
        h = make_household_from_members(
            ["Kids", "Kids", "Adults", "Adults"],
            original_pattern="2 0 2 0",
        )
        assert rule.matches(h) is True

    def test_compute_actual_pattern_empty_household(self):
        """Empty household → pattern is '0 0 0 0'."""
        rule = MatchingRule(actual_patterns=["0 0 0 0"])
        h = make_household_from_members([], original_pattern="0 0 0 0")
        assert rule.matches(h) is True

    def test_compute_actual_pattern_no_age_categories(self):
        """No _age_categories on household → empty string → no match."""
        rule = MatchingRule(actual_patterns=["0 0 1 0"])
        h = MinimalHousehold()  # no age_categories, no cached pattern
        assert rule.matches(h) is False

    def test_cached_actual_pattern_takes_priority(self):
        """If _cached_actual_pattern is set, members are NOT counted."""
        h = make_household_from_members(
            ["Kids", "Kids", "Adults"],  # would be "2 0 1 0"
        )
        # Override with a different cached pattern
        h.properties["_cached_actual_pattern"] = "0 0 2 0"
        rule = MatchingRule(actual_patterns=["0 0 2 0"])
        assert rule.matches(h) is True  # uses cached "0 0 2 0", not computed "2 0 1 0"

    # --- Missing original_pattern property ---

    def test_missing_original_pattern_defaults_to_empty_string(self):
        """If household has no 'original_pattern' property, defaults to ''."""
        rule = MatchingRule(original_patterns=[">=2 >=0 1 0"])
        h = MinimalHousehold()  # no original_pattern
        h.properties["_cached_actual_pattern"] = "0 0 1 0"
        assert rule.matches(h) is False  # '' not in original_patterns


# =============================================================================
# HouseholdStructure.matches() Tests
# =============================================================================

class TestHouseholdStructure:
    """HouseholdStructure matches if ANY of its MatchingRules match."""

    def test_first_rule_matches(self):
        structure = HouseholdStructure(
            name="Family",
            description="",
            inheritance=True,
            matching_rules=[
                MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"]),
                MatchingRule(actual_patterns=["0 >=1 1 <=2"]),
            ],
        )
        h = make_household_with_actual_pattern("2 0 2 0")
        assert structure.matches(h) is True

    def test_second_rule_matches(self):
        structure = HouseholdStructure(
            name="Family",
            description="",
            inheritance=True,
            matching_rules=[
                MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"]),
                MatchingRule(
                    actual_patterns=["0 >=1 1 <=2"],
                    original_patterns=["0 >=1 1 0"],
                ),
            ],
        )
        # Doesn't match first rule (0 kids), matches second
        h = make_household_with_actual_pattern("0 1 1 0", original_pattern="0 >=1 1 0")
        assert structure.matches(h) is True

    def test_no_rules_match(self):
        structure = HouseholdStructure(
            name="Couple",
            description="",
            inheritance=False,
            matching_rules=[
                MatchingRule(actual_patterns=["0 0 2 0"]),
            ],
        )
        h = make_household_with_actual_pattern("0 0 1 0")
        assert structure.matches(h) is False

    def test_empty_matching_rules(self):
        structure = HouseholdStructure(
            name="Empty",
            description="",
            inheritance=False,
            matching_rules=[],
        )
        h = make_household_with_actual_pattern("0 0 1 0")
        assert structure.matches(h) is False


# =============================================================================
# get_person_role() Tests
# =============================================================================

class TestGetPersonRole:
    """
    Tests the role escalation logic:
    - primary: assigned first (count == 0)
    - secondary: only if a primary for the same subset was already assigned
    - extra: only if both primary AND secondary for same subset were assigned
    - general: always assigned (no prerequisite)

    The roles are tried in YAML definition order. The first matching role wins.
    """

    def _build_config(self):
        """
        Build a minimal AttributeAssignmentConfig-like object with roles
        and assignment rules matching the real ethnicity YAML.
        """
        config = _MinimalConfig()
        config.roles = {
            "primary_adult": Role(
                name="primary_adult", description="", subsets=["Adults"], role_type="primary"
            ),
            "secondary_adult": Role(
                name="secondary_adult", description="", subsets=["Adults"], role_type="secondary"
            ),
            "extra_adult": Role(
                name="extra_adult", description="", subsets=["Adults"], role_type="extra"
            ),
            "primary_elder": Role(
                name="primary_elder", description="", subsets=["Old Adults"], role_type="primary"
            ),
            "secondary_elder": Role(
                name="secondary_elder", description="", subsets=["Old Adults"], role_type="secondary"
            ),
            "independent_young": Role(
                name="independent_young", description="", subsets=["Young Adults"], role_type="general"
            ),
            "children": Role(
                name="children", description="", subsets=["Kids", "Young Adults"], role_type="general"
            ),
        }

        # Build assignment rules for "Family" structure that use all adult/elder/children roles
        family_rules = StructureAssignmentRules(
            structure_name="Family",
            description="",
            rules=[
                AssignmentRule(role="primary_adult", priority=1, description="", assignment={}),
                AssignmentRule(role="secondary_adult", priority=2, description="", assignment={}),
                AssignmentRule(role="extra_adult", priority=3, description="", assignment={}),
                AssignmentRule(role="children", priority=4, description="", assignment={}),
                AssignmentRule(role="primary_elder", priority=5, description="", assignment={}),
                AssignmentRule(role="secondary_elder", priority=6, description="", assignment={}),
            ],
        )
        # Independents structure uses independent_young and all adult/elder roles
        independents_rules = StructureAssignmentRules(
            structure_name="Independents",
            description="",
            rules=[
                AssignmentRule(
                    role=["primary_adult", "secondary_adult", "extra_adult",
                          "primary_elder", "secondary_elder", "independent_young"],
                    priority=1, description="", assignment={},
                ),
                AssignmentRule(role="children", priority=1, description="", assignment={}),
            ],
        )
        config.assignment_rules = {
            "Family": family_rules,
            "Independents": independents_rules,
        }
        config._valid_roles_cache = {}

        return config

    # --- Primary role assignment ---

    def test_first_adult_gets_primary(self):
        config = self._build_config()
        person = MinimalPerson("Adults")
        role = config.get_person_role(person, "Family", [], person_category="Adults")
        assert role == "primary_adult"

    def test_first_elder_gets_primary(self):
        config = self._build_config()
        person = MinimalPerson("Old Adults")
        role = config.get_person_role(person, "Family", [], person_category="Old Adults")
        assert role == "primary_elder"

    # --- Secondary requires primary first ---

    def test_second_adult_gets_secondary(self):
        config = self._build_config()
        person = MinimalPerson("Adults")
        assigned = ["primary_adult"]
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        assert role == "secondary_adult"

    def test_second_adult_without_primary_gets_nothing(self):
        """
        BUG DETECTION: If no primary_adult was assigned, can a secondary_adult
        be assigned? The code checks for a primary with overlapping subsets.

        If assigned_roles is empty, secondary should NOT be assigned because
        its prerequisite (primary for same subset) isn't met.

        But wait — the code iterates roles in YAML order. primary_adult comes
        first. If the person category matches "Adults" and primary_adult count
        is 0, it SHOULD return primary_adult, not secondary.

        The scenario where secondary is attempted without primary only happens
        if primary_adult was already assigned once (count > 0) — then the code
        skips primary and tries secondary. Secondary checks has_primary which
        would be True. So the flow is correct.

        Let's test the case where primary was assigned to DIFFERENT subset.
        """
        config = self._build_config()
        person = MinimalPerson("Adults")
        # primary_elder was assigned (Old Adults), but no primary for Adults
        assigned = ["primary_elder"]
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        # Should get primary_adult (count == 0, so primary is available)
        assert role == "primary_adult"

    def test_second_elder_gets_secondary(self):
        config = self._build_config()
        person = MinimalPerson("Old Adults")
        assigned = ["primary_elder"]
        role = config.get_person_role(person, "Family", assigned, person_category="Old Adults")
        assert role == "secondary_elder"

    # --- Extra requires both primary AND secondary ---

    def test_third_adult_gets_extra(self):
        config = self._build_config()
        person = MinimalPerson("Adults")
        assigned = ["primary_adult", "secondary_adult"]
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        assert role == "extra_adult"

    def test_third_adult_without_secondary_skips_extra(self):
        """Extra requires both primary AND secondary. Only primary exists → no extra."""
        config = self._build_config()
        person = MinimalPerson("Adults")
        assigned = ["primary_adult"]  # secondary missing
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        # primary_adult count is 1, so it's skipped. secondary_adult checks
        # has_primary (True), count == 0, so secondary is assigned instead.
        assert role == "secondary_adult"

    def test_fourth_adult_also_gets_extra(self):
        """Extra can be assigned multiple times (no count == 0 check)."""
        config = self._build_config()
        person = MinimalPerson("Adults")
        assigned = ["primary_adult", "secondary_adult", "extra_adult"]
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        assert role == "extra_adult"

    # --- General role (no prerequisites) ---

    def test_child_gets_general_role_immediately(self):
        config = self._build_config()
        person = MinimalPerson("Kids")
        role = config.get_person_role(person, "Family", [], person_category="Kids")
        assert role == "children"

    def test_young_adult_in_family_gets_children_role(self):
        """Young Adults in Family structure → children role (subsets include Young Adults)."""
        config = self._build_config()
        person = MinimalPerson("Young Adults")
        role = config.get_person_role(person, "Family", [], person_category="Young Adults")
        assert role == "children"

    def test_young_adult_in_independents_gets_independent_young(self):
        """Young Adults in Independents → independent_young (general role)."""
        config = self._build_config()
        person = MinimalPerson("Young Adults")
        role = config.get_person_role(
            person, "Independents", [], person_category="Young Adults"
        )
        assert role == "independent_young"

    # --- Subset mismatch ---

    def test_wrong_category_returns_none(self):
        """Person category doesn't match any role → None."""
        config = self._build_config()
        person = MinimalPerson("Babies")  # not in any role's subsets
        role = config.get_person_role(person, "Family", [], person_category="Babies")
        assert role is None

    # --- Unknown structure ---

    def test_unknown_structure_returns_none(self):
        config = self._build_config()
        person = MinimalPerson("Adults")
        role = config.get_person_role(person, "UnknownStructure", [], person_category="Adults")
        assert role is None

    # --- Role escalation sequence (full household) ---

    def test_full_escalation_sequence_family(self):
        """
        Simulate assigning roles to a household with:
        3 Adults, 2 Kids, 2 Old Adults — in order.
        """
        config = self._build_config()
        assigned = []

        # Adult 1 → primary_adult
        role = config.get_person_role(
            MinimalPerson("Adults"), "Family", assigned, person_category="Adults"
        )
        assert role == "primary_adult"
        assigned.append(role)

        # Adult 2 → secondary_adult
        role = config.get_person_role(
            MinimalPerson("Adults"), "Family", assigned, person_category="Adults"
        )
        assert role == "secondary_adult"
        assigned.append(role)

        # Adult 3 → extra_adult
        role = config.get_person_role(
            MinimalPerson("Adults"), "Family", assigned, person_category="Adults"
        )
        assert role == "extra_adult"
        assigned.append(role)

        # Kid 1 → children
        role = config.get_person_role(
            MinimalPerson("Kids"), "Family", assigned, person_category="Kids"
        )
        assert role == "children"
        assigned.append(role)

        # Kid 2 → children (general, repeatable)
        role = config.get_person_role(
            MinimalPerson("Kids"), "Family", assigned, person_category="Kids"
        )
        assert role == "children"
        assigned.append(role)

        # Elder 1 → primary_elder
        role = config.get_person_role(
            MinimalPerson("Old Adults"), "Family", assigned, person_category="Old Adults"
        )
        assert role == "primary_elder"
        assigned.append(role)

        # Elder 2 → secondary_elder
        role = config.get_person_role(
            MinimalPerson("Old Adults"), "Family", assigned, person_category="Old Adults"
        )
        assert role == "secondary_elder"
        assigned.append(role)

        assert assigned == [
            "primary_adult", "secondary_adult", "extra_adult",
            "children", "children",
            "primary_elder", "secondary_elder",
        ]

    # --- BUG DETECTION: secondary without primary for same subset ---

    def test_secondary_adult_not_assigned_if_only_elder_primary_exists(self):
        """
        Secondary requires a primary with OVERLAPPING subsets. A primary_elder
        (Old Adults) should not satisfy the requirement for secondary_adult (Adults).
        """
        config = self._build_config()
        person = MinimalPerson("Adults")
        # Only primary_elder in assigned — different subset
        assigned = ["primary_elder"]
        role = config.get_person_role(person, "Family", assigned, person_category="Adults")
        # primary_adult has count==0 → should be assigned as primary, not secondary
        assert role == "primary_adult"

    def test_secondary_elder_not_assigned_if_only_adult_primary_exists(self):
        """
        Symmetric check: primary_adult (Adults subset) should not satisfy
        the prerequisite for secondary_elder (Old Adults subset).
        """
        config = self._build_config()
        person = MinimalPerson("Old Adults")
        assigned = ["primary_adult"]  # different subset
        role = config.get_person_role(person, "Family", assigned, person_category="Old Adults")
        # primary_elder has count==0 → should get primary_elder
        assert role == "primary_elder"


# =============================================================================
# get_household_structure() Tests
# =============================================================================

class TestGetHouseholdStructure:
    """
    Tests structure classification: first match wins.
    Uses HouseholdStructure objects directly (not full config loading).
    """

    def _build_config(self):
        """Build config with Family > Couple > Independents ordering."""
        config = _MinimalConfig()
        config.household_structures = {
            "Family": HouseholdStructure(
                name="Family", description="", inheritance=True,
                matching_rules=[
                    MatchingRule(actual_patterns=[">=1 >=0 >=0 >=0"]),
                ],
            ),
            "Couple": HouseholdStructure(
                name="Couple", description="", inheritance=False,
                matching_rules=[
                    MatchingRule(
                        actual_patterns=["0 0 2 0"],
                        original_patterns=["0 0 2 0"],
                    ),
                ],
            ),
            "Independents": HouseholdStructure(
                name="Independents", description="", inheritance=False,
                matching_rules=[
                    MatchingRule(actual_patterns=["0 >=0 >=0 >=0"]),
                ],
            ),
        }
        return config

    def test_family_matched_first(self):
        config = self._build_config()
        h = make_household_with_actual_pattern("2 0 2 0")
        assert config.get_household_structure(h) == "Family"

    def test_couple_matched(self):
        config = self._build_config()
        h = make_household_with_actual_pattern("0 0 2 0", original_pattern="0 0 2 0")
        assert config.get_household_structure(h) == "Couple"

    def test_couple_pattern_without_original_falls_to_independents(self):
        """
        Actual "0 0 2 0" matches Couple's actual pattern, but Couple also
        requires original == "0 0 2 0". Without original, it falls through
        to Independents (catch-all).
        """
        config = self._build_config()
        h = make_household_with_actual_pattern("0 0 2 0", original_pattern=">=2 >=0 2 0")
        # Couple requires original "0 0 2 0", but household has ">=2 >=0 2 0"
        # → Couple doesn't match → falls to Independents ("0 >=0 >=0 >=0" matches)
        assert config.get_household_structure(h) == "Independents"

    def test_independents_catch_all(self):
        config = self._build_config()
        h = make_household_with_actual_pattern("0 0 1 0")
        assert config.get_household_structure(h) == "Independents"

    def test_no_match_returns_none(self):
        config = self._build_config()
        # All patterns require >=0 kids, but we have -1? No — patterns can't have negative.
        # A real "no match" requires empty actual_pattern.
        h = MinimalHousehold()  # no cached pattern, no age_categories → empty
        assert config.get_household_structure(h) is None

    def test_first_match_wins_order_matters(self):
        """
        A household with kids matches BOTH Family and Independents catch-all.
        Family must win because it's checked first.
        """
        config = self._build_config()
        h = make_household_with_actual_pattern("1 0 1 0")
        assert config.get_household_structure(h) == "Family"

    # --- Caching ---

    def test_structure_is_cached_on_household(self):
        config = self._build_config()
        h = make_household_with_actual_pattern("0 0 1 0")
        result1 = config.get_household_structure(h)
        assert result1 == "Independents"
        assert h.properties["_cached_household_structure"] == "Independents"

        # Second call uses cache — even if we tamper with the actual pattern
        h.properties["_cached_actual_pattern"] = "2 0 2 0"  # would match Family
        result2 = config.get_household_structure(h)
        assert result2 == "Independents"  # still cached

    def test_none_result_is_also_cached(self):
        config = self._build_config()
        h = MinimalHousehold()
        result = config.get_household_structure(h)
        assert result is None
        assert h.properties["_cached_household_structure"] is None


# =============================================================================
# Helper: Minimal config object for tests that don't need full YAML loading
# =============================================================================

class _MinimalConfig:
    """
    Bare-bones config object that has the attributes get_person_role()
    and get_household_structure() access.
    """
    def __init__(self):
        self.roles = {}
        self.assignment_rules = {}
        self.household_structures = {}
        self._valid_roles_cache = {}

    # Delegate to the real methods from AttributeAssignmentConfig
    get_person_role = AttributeAssignmentConfig.get_person_role
    get_household_structure = AttributeAssignmentConfig.get_household_structure
    get_assignment_rule = AttributeAssignmentConfig.get_assignment_rule


# =============================================================================
# _parse_required_attributes — canonical list form (adr/0006)
# =============================================================================

class _RawOnly:
    """Carries just raw_config so the unbound parser can run in isolation."""
    def __init__(self, raw_config):
        self.raw_config = raw_config

    _parse_required_attributes = AttributeAssignmentConfig._parse_required_attributes


class TestParseRequiredAttributes:
    def test_list_form_keyed_by_name(self):
        obj = _RawOnly({"required_attributes": [
            {"name": "ethnicity", "required": True, "mapping": {"O": "CO"}},
        ]})
        result = obj._parse_required_attributes()
        assert result == {"ethnicity": {"required": True, "mapping": {"O": "CO"}}}

    def test_missing_section_is_empty(self):
        assert _RawOnly({})._parse_required_attributes() == {}

    def test_mapping_form_rejected(self):
        """The retired `name: {...}` mapping form fails loudly (adr/0006)."""
        obj = _RawOnly({"required_attributes": {"ethnicity": {"required": True}}})
        with pytest.raises(ValueError, match="must be a list"):
            obj._parse_required_attributes()

    def test_entry_without_name_raises(self):
        obj = _RawOnly({"required_attributes": [{"required": True}]})
        with pytest.raises(ValueError, match="missing 'name'"):
            obj._parse_required_attributes()
