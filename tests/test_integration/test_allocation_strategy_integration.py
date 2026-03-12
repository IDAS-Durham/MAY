import pytest
import numpy as np
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.residence.composition_pattern import CompositionPattern
from may.residence.allocation_strategy import execute_allocation_strategy


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

STRESS_DATA = "tests/test_data/stress_world"


@pytest.fixture
def geography():
    geo = Geography(data_dir=f"{STRESS_DATA}/geography")
    geo.load_from_csv()
    return geo


@pytest.fixture
def venue_manager(geography):
    vm = VenueManager(geography, data_dir=f"{STRESS_DATA}/venues")
    vm.load_from_yaml_config("test_venues_config.yaml")
    return vm


@pytest.fixture
def population_manager(geography):
    pm = PopulationManager(geography=geography, data_dir=f"{STRESS_DATA}/population")
    pm.load_explicit_from_csv(
        "people.csv",
        column_mapping={"age": "age", "sex": "sex", "geo_unit": "location"}
    )
    return pm


@pytest.fixture
def hd(geography, population_manager, venue_manager):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir=f"{STRESS_DATA}/households",
        config_file="test_households_config.yaml"
    )
    distributor.load_household_data("households.csv")
    return distributor


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def get_households_by_geo_unit(hd, geo_unit_code):
    """Get all households in a specific geo unit."""
    all_hh = hd.venue_manager.get_venues_by_type("household")
    return [h for h in all_hh if h.geographical_unit.name == geo_unit_code]


def get_household_composition(household, categories):
    """Get composition dict for a household."""
    return household.get_composition(categories)


def get_all_allocated_ids(hd):
    """Get set of all allocated person IDs."""
    return set(hd.allocated_people)


def get_remaining_count(hd):
    """Get number of people not yet allocated."""
    return hd.get_available_people_count()


def count_people_by_category(hd, geo_unit_code):
    """Count people in a geo unit by category."""
    pools = hd.person_pool_by_geo_unit.get(geo_unit_code, [])
    result = {}
    for idx, cat in enumerate(hd.categories):
        result[cat.name] = len(pools[idx]) if idx < len(pools) else 0
    return result


def count_all_people_in_households(hd):
    """Count total people across all households (detects double-counting)."""
    all_hh = hd.venue_manager.get_venues_by_type("household")
    return sum(h.size() for h in all_hh)


# ──────────────────────────────────────────────────────────────────────
# Test 1: Stress world data loads correctly
# ──────────────────────────────────────────────────────────────────────

class TestStressWorldSetup:
    """Verify the stress_world fixture loads as expected."""

    def test_population_size(self, hd):
        total = len(hd.population.get_all_people())
        assert total == 28, f"Expected 28 people, got {total}"

    def test_sgu_s1_pool_composition(self, hd):
        """SGU_S1 must have 7 kids, 3 YA, 3 adults, 2 OA."""
        hd._prepare_person_pools()
        counts = count_people_by_category(hd, "SGU_S1")
        assert counts["Kids"] == 7
        assert counts["Young Adults"] == 3
        assert counts["Adults"] == 3
        assert counts["Old Adults"] == 2

    def test_sgu_s2_pool_composition(self, hd):
        """SGU_S2 must have 2 kids, 1 YA, 4 adults, 2 OA."""
        hd._prepare_person_pools()
        counts = count_people_by_category(hd, "SGU_S2")
        assert counts["Kids"] == 2
        assert counts["Young Adults"] == 1
        assert counts["Adults"] == 4
        assert counts["Old Adults"] == 2

    def test_sgu_s3_pool_composition(self, hd):
        """SGU_S3 must have 0 kids, 2 YA, 2 adults, 0 OA."""
        hd._prepare_person_pools()
        counts = count_people_by_category(hd, "SGU_S3")
        assert counts["Kids"] == 0
        assert counts["Young Adults"] == 2
        assert counts["Adults"] == 2
        assert counts["Old Adults"] == 0

    def test_household_requests_loaded(self, hd):
        """Household counts per geo unit loaded from CSV."""
        assert hd.household_counts_by_geo_unit["SGU_S1"][">=2 >=0 2 0"] == 3
        assert hd.household_counts_by_geo_unit["SGU_S1"]["0 0 0 2"] == 1
        assert hd.household_counts_by_geo_unit["SGU_S2"]["1 >=0 2 0"] == 1
        assert hd.household_counts_by_geo_unit["SGU_S2"]["0 0 2 0"] == 1
        assert hd.household_counts_by_geo_unit["SGU_S2"]["0 0 0 2"] == 1
        assert hd.household_counts_by_geo_unit["SGU_S3"]["0 0 2 0"] == 1
        assert hd.household_counts_by_geo_unit["SGU_S3"]["0 >=0 0 0"] == 1

    def test_demotion_config(self, hd):
        """Demotion is enabled with correct priority order."""
        assert hd.config['demotion']['enabled'] is True
        assert hd.config['demotion']['max_attempts'] == 10
        assert hd.config['demotion']['min_household_size'] == 1
        # Priority: Kids(1) > YA(2) > OA(3) > Adults(4) → [0, 1, 3, 2]
        assert hd.fallback_priority == [0, 1, 3, 2]

    def test_promotion_config(self, hd):
        """Promotion is enabled with correct priority order."""
        assert hd.config['promotion']['enabled'] is True
        assert hd.config['promotion']['max_attempts'] == 4


# ──────────────────────────────────────────────────────────────────────
# Test 2: Demotion behavior under resource pressure
# ──────────────────────────────────────────────────────────────────────

class TestDemotionUnderPressure:
    """
    SGU_S1 requests 3 households of ">=2 >=0 2 0" but only has 3 adults.
    The system MUST demote at least one household to ">=2 >=0 1 0".

    Intended allocation sequence:
      H1: 2 kids + 2 adults ✓ (1 adult left)
      H2: needs 2 adults, only 1 → demote to ">=2 >=0 1 0" → 2 kids + 1 adult ✓
      H3: needs 2 adults, 0 left → demote to ">=2 >=0 0 0" → BLOCKED by validation
    Result: exactly 2 households, exactly 1 demotion, exactly 3 adults consumed.
    """

    def test_demotion_exact_household_count(self, hd):
        """Exactly 2 of 3 requested households should be created."""
        np.random.seed(42)
        hd._prepare_person_pools()

        stats = hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
                "1 >=0 1 0": "Single-adult family with kids",
            },
        )

        assert stats['households_requested'] == 3
        # Exactly 2: first succeeds with 2 adults, second demotes to 1 adult,
        # third fails because 0 adults + kids violates validation
        assert stats['households_created'] == 2, (
            f"Expected exactly 2 households (3 adults for 2+1 split), "
            f"got {stats['households_created']}"
        )

    def test_demotion_exact_count(self, hd):
        """Exactly 1 household should be demoted."""
        np.random.seed(42)
        hd._prepare_person_pools()

        stats = hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        assert stats['households_with_demotion'] == 1, (
            f"Expected exactly 1 demotion (second household), "
            f"got {stats['households_with_demotion']}"
        )

    def test_all_adults_consumed(self, hd):
        """All 3 SGU_S1 adults should be consumed by the 2 family households."""
        np.random.seed(42)
        hd._prepare_person_pools()

        stats = hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        # Count adults placed across all SGU_S1 households
        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        total_adults = sum(
            get_household_composition(h, hd.categories)["Adults"]
            for h in sgu_s1_hh
        )
        assert total_adults == 3, (
            f"All 3 SGU_S1 adults should be in households, found {total_adults}"
        )

        # Adult pool should be empty
        pools = hd.person_pool_by_geo_unit["SGU_S1"]
        adults_remaining = len(pools[2])  # idx 2 = Adults
        assert adults_remaining == 0, (
            f"Adult pool should be empty after family allocation, "
            f"but has {adults_remaining}"
        )

    def test_demoted_household_has_fewer_adults_than_requested(self, hd):
        """
        The demoted household should have fewer adults than the original ">=2 >=0 2 0"
        pattern requested (2 adults). Due to intelligent demotion, the system may also
        demote kids if the age-difference constraint (parent must be 16-50 years older
        than kid) cannot be satisfied with remaining pool members.
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        demoted = [
            h for h in sgu_s1_hh
            if h.properties.get('actual_pattern') != h.properties.get('original_pattern')
        ]
        assert len(demoted) == 1, f"Expected exactly 1 demoted household, got {len(demoted)}"

        comp = get_household_composition(demoted[0], hd.categories)
        # Must have fewer than 2 adults (original asked for 2)
        assert comp["Adults"] < 2, (
            f"Demoted household must have fewer than 2 adults, got {comp['Adults']}"
        )
        # Must still have at least 1 adult (validation: kids need supervision)
        assert comp["Adults"] >= 1, (
            f"Demoted household must have at least 1 adult (kids supervision), got {comp['Adults']}"
        )
        # Must have at least 1 kid
        assert comp["Kids"] >= 1, (
            f"Demoted household should have at least 1 kid, got {comp['Kids']}"
        )
        # Total size must be >= min_household_size (1)
        total = sum(comp.values())
        assert total >= 1, f"Demoted household is too small: {total}"

    def test_non_demoted_household_has_two_adults(self, hd):
        """The non-demoted household should have exactly 2 adults with romantic coupling."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        non_demoted = [
            h for h in sgu_s1_hh
            if h.properties.get('actual_pattern') == h.properties.get('original_pattern')
        ]
        assert len(non_demoted) == 1, f"Expected exactly 1 non-demoted household"

        comp = get_household_composition(non_demoted[0], hd.categories)
        assert comp["Adults"] == 2, f"Non-demoted should have 2 adults, got {comp['Adults']}"

        # The 2 adults should be a romantic couple (Two-adult family rule has pair_matching)
        adults = [p for p in non_demoted[0].get_all_members() if p.age >= 25 and p.age <= 64]
        assert len(adults) == 2
        for adult in adults:
            assert "cohabiting_couple" in adult.properties, (
                f"Adult {adult.id} in two-adult family should be tagged as cohabiting_couple"
            )

    def test_demotion_rule_switching_no_couple_on_single_adult(self, hd):
        """When demoted to single-adult, NO cohabiting_couple property should exist."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        demoted = [
            h for h in sgu_s1_hh
            if h.properties.get('actual_pattern') != h.properties.get('original_pattern')
        ]
        for h in demoted:
            for person in h.get_all_members():
                assert "cohabiting_couple" not in person.properties, (
                    f"Person {person.id} in single-adult household {h.id} should NOT "
                    f"have cohabiting_couple (rule should have switched to Single-adult)"
                )

    def test_validation_blocks_kids_without_adults(self, hd):
        """
        No household with kids should ever have 0 adults.
        The validation rule "Kids require adult supervision" must block
        demotion to ">=2 >=0 0 0".
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        for h in sgu_s1_hh:
            comp = get_household_composition(h, hd.categories)
            if comp["Kids"] >= 1:
                assert comp["Adults"] >= 1, (
                    f"VALIDATION FAILURE: Household {h.id} has {comp['Kids']} kid(s) "
                    f"but {comp['Adults']} adult(s). Pattern: {h.properties.get('actual_pattern')}"
                )

    def test_pool_state_after_demotion_round(self, hd):
        """After the demotion round, pool counts must be exactly correct."""
        np.random.seed(42)
        hd._prepare_person_pools()

        stats = hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={
                ">=2 >=0 1 0": "Single-adult family with kids",
            },
        )

        # SGU_S1 started with 7 kids, 3 YA, 3 adults, 2 OA
        # 2 households created, all 3 adults consumed
        counts = count_people_by_category(hd, "SGU_S1")

        # ALL adults must be consumed (3 out of 3)
        assert counts["Adults"] == 0, f"Expected 0 adults remaining, got {counts['Adults']}"
        # YA should be untouched (pattern doesn't require YA)
        assert counts["Young Adults"] == 3, f"Expected 3 YA remaining, got {counts['Young Adults']}"
        # OA should be untouched
        assert counts["Old Adults"] == 2, f"Expected 2 OA remaining, got {counts['Old Adults']}"

        # Kids consumed = sum of kids in the two created households
        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        kids_used = sum(get_household_composition(h, hd.categories)["Kids"] for h in sgu_s1_hh)
        assert counts["Kids"] == 7 - kids_used, (
            f"Expected {7 - kids_used} kids remaining (7 - {kids_used} used), "
            f"got {counts['Kids']}"
        )

        # Total allocated = sum of household sizes
        total_hh_size = sum(h.size() for h in sgu_s1_hh)
        assert stats['people_allocated_this_round'] == total_hh_size, (
            f"people_allocated should match total household sizes: "
            f"expected {total_hh_size}, got {stats['people_allocated_this_round']}"
        )


# ──────────────────────────────────────────────────────────────────────
# Test 3: Couple matching (romantic pair creation)
# ──────────────────────────────────────────────────────────────────────

class TestCoupleMatchingIntegration:
    """
    Test that rule-based pair matching creates realistic couples.
    Adult couples and elderly couples should be opposite-sex (95% probability)
    with appropriate age differences.
    """

    def test_adult_couple_is_opposite_sex(self, hd):
        """Adult pair matching creates male/female couple in SGU_S2."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # SGU_S2 adults: 28f, 32m, 45f, 55m → good m/f pair options
        household, _ = hd._allocate_household_with_rules(
            "SGU_S2",
            CompositionPattern.from_string("0 0 2 0"),
            rule_name="Adult pair"
        )

        assert household is not None
        members = household.get_all_members()
        assert len(members) == 2
        sexes = {p.sex for p in members}
        assert sexes == {"male", "female"}, f"Expected m/f pair, got {sexes}"

    def test_adult_couple_has_bidirectional_cohabiting_property(self, hd):
        """Adult couple members must have correct bidirectional cohabiting_couple refs."""
        np.random.seed(42)
        hd._prepare_person_pools()

        household, _ = hd._allocate_household_with_rules(
            "SGU_S2",
            CompositionPattern.from_string("0 0 2 0"),
            rule_name="Adult pair"
        )

        assert household is not None
        p0, p1 = household.get_all_members()

        # Both must have the property
        assert "cohabiting_couple" in p0.properties, f"Person {p0.id} missing cohabiting_couple"
        assert "cohabiting_couple" in p1.properties, f"Person {p1.id} missing cohabiting_couple"

        # Cross-references must be bidirectional and correct
        assert p0.properties["cohabiting_couple"] == [p1.id], (
            f"p0.cohabiting_couple should be [{p1.id}], got {p0.properties['cohabiting_couple']}"
        )
        assert p1.properties["cohabiting_couple"] == [p0.id], (
            f"p1.cohabiting_couple should be [{p0.id}], got {p1.properties['cohabiting_couple']}"
        )

    def test_elderly_couple_created_with_correct_ages(self, hd):
        """Elderly pair should have both members aged 65+, opposite sex."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # SGU_S1: 68f, 75m → only valid elderly pair
        household, _ = hd._allocate_household_with_rules(
            "SGU_S1",
            CompositionPattern.from_string("0 0 0 2"),
            rule_name="Elderly pair"
        )

        assert household is not None
        members = household.get_all_members()
        assert len(members) == 2

        ages = sorted([p.age for p in members])
        assert ages == [68, 75], f"Expected elderly pair ages [68, 75], got {ages}"

        sexes = {p.sex for p in members}
        assert sexes == {"male", "female"}, f"Expected m/f elderly pair, got {sexes}"

    def test_adult_couple_reasonable_age_gap(self, hd):
        """Adult pair should have age difference within configured max (19 years)."""
        np.random.seed(42)
        hd._prepare_person_pools()

        household, _ = hd._allocate_household_with_rules(
            "SGU_S2",
            CompositionPattern.from_string("0 0 2 0"),
            rule_name="Adult pair"
        )

        assert household is not None
        members = household.get_all_members()
        age_diff = abs(members[0].age - members[1].age)
        assert age_diff <= 19, (
            f"Adult couple age gap {age_diff} exceeds configured max of 19. "
            f"Ages: {[p.age for p in members]}"
        )

    def test_adult_couple_removes_from_pool(self, hd):
        """After creating an adult couple, both members must be removed from pool."""
        np.random.seed(42)
        hd._prepare_person_pools()

        adults_before = len(hd.person_pool_by_geo_unit["SGU_S2"][2])  # Adults pool
        household, _ = hd._allocate_household_with_rules(
            "SGU_S2",
            CompositionPattern.from_string("0 0 2 0"),
            rule_name="Adult pair"
        )

        assert household is not None
        adults_after = len(hd.person_pool_by_geo_unit["SGU_S2"][2])
        assert adults_after == adults_before - 2, (
            f"Adult pool should shrink by 2: {adults_before} -> {adults_after}"
        )

        # Both members should be in allocated_people
        for p in household.get_all_members():
            assert p.id in hd.allocated_people, (
                f"Person {p.id} should be in allocated_people"
            )


# ──────────────────────────────────────────────────────────────────────
# Test 4: Pattern assumptions
# ──────────────────────────────────────────────────────────────────────

class TestPatternAssumptions:
    """
    Test that pattern assumptions override the census pattern during allocation
    while preserving the original pattern for tracking.
    """

    def test_assumption_allocates_exact_count(self, hd):
        """
        Pattern '0 >=0 0 0' with assumption '0 2 0 0' should allocate
        exactly 2 YA — not more (flexible), not fewer.
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        stats = hd.round_distributor.distribute_households_round(
            pattern_filter=["0 >=0 0 0"],
            pattern_assumptions={"0 >=0 0 0": "0 2 0 0"},
        )

        sgu_s3_hh = get_households_by_geo_unit(hd, "SGU_S3")
        ya_households = [
            h for h in sgu_s3_hh
            if h.properties.get('original_pattern') == "0 >=0 0 0"
        ]

        assert len(ya_households) == 1, f"Expected 1 YA household, got {len(ya_households)}"

        comp = get_household_composition(ya_households[0], hd.categories)
        assert comp["Young Adults"] == 2, (
            f"With assumption '0 2 0 0', must have exactly 2 YA, got {comp['Young Adults']}"
        )
        # No other categories should be present
        assert comp["Kids"] == 0, f"No kids expected, got {comp['Kids']}"
        assert comp["Adults"] == 0, f"No adults expected, got {comp['Adults']}"
        assert comp["Old Adults"] == 0, f"No OA expected, got {comp['Old Adults']}"

    def test_assumption_preserves_census_pattern_for_tracking(self, hd):
        """
        The household's original_pattern should be the CENSUS pattern ("0 >=0 0 0"),
        not the assumption ("0 2 0 0"). This is critical for excess allocation targeting.
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=["0 >=0 0 0"],
            pattern_assumptions={"0 >=0 0 0": "0 2 0 0"},
        )

        sgu_s3_hh = get_households_by_geo_unit(hd, "SGU_S3")
        ya_households = [
            h for h in sgu_s3_hh
            if h.properties.get('original_pattern') == "0 >=0 0 0"
        ]
        assert len(ya_households) == 1

        # original_pattern must be census pattern for excess targeting
        assert ya_households[0].properties['original_pattern'] == "0 >=0 0 0"
        # actual_pattern should reflect what was actually allocated
        actual = ya_households[0].properties['actual_pattern']
        assert actual == "0 2 0 0", (
            f"actual_pattern should be '0 2 0 0' (the assumption), got '{actual}'"
        )

    def test_assumption_consumes_correct_pool(self, hd):
        """YA pool in SGU_S3 should be empty after assumption-based allocation."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=["0 >=0 0 0"],
            pattern_assumptions={"0 >=0 0 0": "0 2 0 0"},
        )

        ya_remaining = len(hd.person_pool_by_geo_unit["SGU_S3"][1])  # YA pool
        assert ya_remaining == 0, (
            f"SGU_S3 YA pool should be empty after allocating 2 YA, has {ya_remaining}"
        )


# ──────────────────────────────────────────────────────────────────────
# Test 5: Excess allocation
# ──────────────────────────────────────────────────────────────────────

class TestExcessAllocation:
    """
    After initial household creation, remaining kids should be added
    to existing family households via excess allocation.
    """

    def test_excess_adds_remaining_kids(self, hd):
        """After initial allocation, excess round places remaining kids into family households."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # Create family households (multiple SGUs)
        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0", "1 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        remaining_before = hd.get_available_people_by_category()
        kids_remaining_before = remaining_before.get("Kids", 0)
        assert kids_remaining_before > 0, (
            f"Expected some kids remaining after family round, got {kids_remaining_before}"
        )

        # Add excess kids to family households
        stats = hd.allocate_excess_to_households(
            target_patterns=[">=2 >=0 2 0", ">=2 >=0 1 0", ">=1 >=0 1 0",
                           "1 >=0 2 0", "1 >=0 1 0"],
            add_category="Kids",
            constraints=[{"category_sum": ["Kids"], "max": 5}],
            add_distribution={"type": "weighted", "probabilities": {"1": 1.0}},
        )

        assert stats['people_added'] > 0, "Excess must place at least 1 kid"
        remaining_after = hd.get_available_people_by_category()
        kids_remaining_after = remaining_after.get("Kids", 0)
        assert kids_remaining_after < kids_remaining_before, (
            f"Kids must decrease: {kids_remaining_before} -> {kids_remaining_after}"
        )
        # Verify people_added matches the actual decrease
        actual_decrease = kids_remaining_before - kids_remaining_after
        assert stats['people_added'] == actual_decrease, (
            f"Reported people_added ({stats['people_added']}) doesn't match "
            f"actual decrease ({actual_decrease})"
        )

    def test_excess_respects_category_sum_constraint(self, hd):
        """No household should exceed the max=5 kids constraint after excess."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # Create family households
        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        # Add excess kids with constraint: max 5 kids per household
        stats = hd.allocate_excess_to_households(
            target_patterns=[">=2 >=0 2 0", ">=2 >=0 1 0"],
            add_category="Kids",
            constraints=[{"category_sum": ["Kids"], "max": 5}],
            add_distribution={"type": "weighted", "probabilities": {"1": 1.0}},
        )

        # Verify constraint is enforced on EVERY household
        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        for h in sgu_s1_hh:
            comp = get_household_composition(h, hd.categories)
            assert comp["Kids"] <= 5, (
                f"CONSTRAINT VIOLATION: Household {h.id} has {comp['Kids']} kids (max 5). "
                f"Pattern: {h.properties.get('actual_pattern')}"
            )

    def test_excess_people_tracked_in_allocated_set(self, hd):
        """People added via excess must be in allocated_people."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        allocated_before = len(hd.allocated_people)

        stats = hd.allocate_excess_to_households(
            target_patterns=[">=2 >=0 2 0", ">=2 >=0 1 0"],
            add_category="Kids",
            constraints=[{"category_sum": ["Kids"], "max": 5}],
            add_distribution={"type": "weighted", "probabilities": {"1": 1.0}},
        )

        allocated_after = len(hd.allocated_people)
        people_added = stats['people_added']
        assert allocated_after == allocated_before + people_added, (
            f"allocated_people should grow by {people_added}: "
            f"{allocated_before} -> {allocated_after} (expected {allocated_before + people_added})"
        )


# ──────────────────────────────────────────────────────────────────────
# Test 6: Overflow allocation (desperation round)
# ──────────────────────────────────────────────────────────────────────

class TestOverflowAllocation:
    """
    Overflow is the "desperation round" that distributes ALL remaining people
    of a category across existing households, ignoring max size constraints.
    """

    def test_overflow_places_all_ya_in_geo_unit(self, hd):
        """Overflow should place ALL remaining YA in SGU_S1."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # Create initial households
        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        ya_before = len(hd.person_pool_by_geo_unit["SGU_S1"][1])  # YA pool
        assert ya_before == 3, f"SGU_S1 should have 3 YA before overflow, got {ya_before}"

        stats = hd.allocate_overflow_to_households(
            target_patterns=[">=2 >=0 2 0", ">=2 >=0 1 0"],
            add_category="Young Adults",
        )

        # ALL 3 YA from SGU_S1 should be placed
        assert stats['people_added'] >= 3, (
            f"Overflow should place all 3 SGU_S1 YA, placed {stats['people_added']}"
        )

        ya_after = len(hd.person_pool_by_geo_unit["SGU_S1"][1])
        assert ya_after == 0, (
            f"SGU_S1 YA pool should be empty after overflow, has {ya_after}"
        )

    def test_overflow_distributes_balancedly_across_households(self, hd):
        """
        Overflow should spread people across households, not dump all into one.
        With 3 YA and 2 target households, the split should be balanced (2+1 or 1+2).
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        # Create 2 households in SGU_S1
        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        sgu_s1_hh = get_households_by_geo_unit(hd, "SGU_S1")
        assert len(sgu_s1_hh) == 2, f"Need 2 households for balance test, got {len(sgu_s1_hh)}"

        hd.allocate_overflow_to_households(
            target_patterns=[">=2 >=0 2 0", ">=2 >=0 1 0"],
            add_category="Young Adults",
        )

        # Check YA distribution across the 2 SGU_S1 households
        ya_counts = []
        for h in get_households_by_geo_unit(hd, "SGU_S1"):
            comp = get_household_composition(h, hd.categories)
            ya_counts.append(comp.get("Young Adults", 0))

        total_ya = sum(ya_counts)
        assert total_ya == 3, f"All 3 YA should be placed, got {total_ya}"

        # Balance check: difference between most and least should be at most 1
        if len(ya_counts) >= 2:
            assert max(ya_counts) - min(ya_counts) <= 1, (
                f"Overflow should distribute balancedly: got distribution {ya_counts} "
                f"(diff {max(ya_counts) - min(ya_counts)} > 1)"
            )


# ──────────────────────────────────────────────────────────────────────
# Test 7: Promotion
# ──────────────────────────────────────────────────────────────────────

class TestPromotionAllocation:
    """
    Promotion changes household patterns from exact to flexible,
    allowing them to accept additional people from new categories.
    """

    def test_promotion_places_people(self, hd):
        """Promotion should actually add people to households."""
        np.random.seed(42)
        hd._prepare_person_pools()

        # Run initial allocation (leaves kids, YA unallocated)
        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )
        hd.round_distributor.distribute_households_round(
            pattern_filter=["0 0 0 2"],
            rule_name="Elderly pair",
        )

        remaining_before = get_remaining_count(hd)
        assert remaining_before > 0, "Need remaining people to test promotion"

        stats = hd.promote_and_allocate(
            target_categories=["Kids", "Young Adults", "Adults", "Old Adults"],
            refresh_pools=True,
        )

        remaining_after = get_remaining_count(hd)
        assert stats['people_added'] > 0, (
            f"Promotion should add people, added {stats['people_added']}"
        )
        assert remaining_after < remaining_before, (
            f"Promotion should reduce remaining: {remaining_before} -> {remaining_after}"
        )

    def test_promotion_changes_household_patterns(self, hd):
        """Promoted households should have their actual_pattern updated."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )
        hd.round_distributor.distribute_households_round(
            pattern_filter=["0 0 0 2"],
            rule_name="Elderly pair",
        )

        # Record patterns before promotion
        all_hh = hd.venue_manager.get_venues_by_type("household")
        patterns_before = {h.id: h.properties.get('actual_pattern') for h in all_hh}

        stats = hd.promote_and_allocate(
            target_categories=["Kids", "Young Adults"],
            refresh_pools=True,
        )

        if stats['households_promoted'] > 0:
            # At least one household should have a different (promoted) pattern
            changed = 0
            for h in all_hh:
                if h.properties.get('actual_pattern') != patterns_before.get(h.id):
                    changed += 1
                    # Promoted patterns should contain ">=" (flexible)
                    new_pattern = h.properties.get('actual_pattern', '')
                    assert ">=" in new_pattern, (
                        f"Promoted pattern should be flexible (contain '>='), "
                        f"got '{new_pattern}'"
                    )
            assert changed == stats['households_promoted'], (
                f"Expected {stats['households_promoted']} pattern changes, got {changed}"
            )

    def test_promotion_respects_validation_rules(self, hd):
        """
        Promotion must not add kids to households without adults.

        The validation rule says "Kids >= 1 → Adults >= 1". When an elderly couple
        household (0 0 0 2 → has 2 OA but 0 Adults) is promoted to accept kids,
        the pattern becomes ">=0 >=0 >=0 >=2" which passes pattern validation.
        The fix ensures that before adding people, the actual household composition
        is checked against the validation rules — not just the promoted pattern.
        """
        np.random.seed(42)
        hd._prepare_person_pools()

        # Create an elderly couple household (0 0 0 2) → has 2 OA, 0 Adults
        hd.round_distributor.distribute_households_round(
            pattern_filter=["0 0 0 2"],
            rule_name="Elderly pair",
        )

        # Promote to accept kids — should NOT add kids to elderly household
        # because validation rule requires Adults >= 1 when Kids >= 1
        _ = hd.promote_and_allocate(
            target_categories=["Kids"],
            refresh_pools=True,
        )

        # Verify no household got kids without adults
        all_hh = hd.venue_manager.get_venues_by_type("household")
        for h in all_hh:
            comp = get_household_composition(h, hd.categories)
            if comp["Kids"] >= 1 and comp["Adults"] == 0:
                pytest.fail(
                    f"VALIDATION FAILURE: Household {h.id} has {comp['Kids']} kids "
                    f"and 0 adults after promotion. Pattern: {h.properties.get('actual_pattern')}. "
                    f"Full composition: {comp}"
                )


# ──────────────────────────────────────────────────────────────────────
# Test 8: Pool management (no double allocation)
# ──────────────────────────────────────────────────────────────────────

class TestPoolManagement:
    """
    People allocated in one round must not appear in subsequent rounds.
    No person should ever be in two households.
    """

    def test_allocated_people_removed_from_pools(self, hd):
        """After allocation, pools must not contain any allocated person."""
        np.random.seed(42)
        hd._prepare_person_pools()

        hd.round_distributor.distribute_households_round(
            pattern_filter=[">=2 >=0 2 0"],
            rule_name="Two-adult family with kids",
            demotion_rules={">=2 >=0 1 0": "Single-adult family with kids"},
        )

        allocated = get_all_allocated_ids(hd)
        assert len(allocated) > 0, "Should have allocated someone"

        for geo_unit_code, pools in hd.person_pool_by_geo_unit.items():
            for cat_idx, pool in enumerate(pools):
                for pid in pool:
                    assert pid not in allocated, (
                        f"Person {pid} is allocated but still in pool "
                        f"{geo_unit_code}/{hd.categories[cat_idx].name}"
                    )

    def test_no_person_in_two_households_after_full_pipeline(self, hd, population_manager, venue_manager):
        """After full pipeline, every person must appear in at most one household."""
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        all_hh = venue_manager.get_venues_by_type("household")
        seen_people = {}
        for h in all_hh:
            for person in h.get_all_members():
                if person.id in seen_people:
                    pytest.fail(
                        f"DOUBLE ALLOCATION: Person {person.id} (age={person.age}) "
                        f"in both household {seen_people[person.id]} and {h.id}"
                    )
                seen_people[person.id] = h.id

    def test_household_member_count_equals_allocated_count(self, hd, population_manager, venue_manager):
        """
        Total people across all households must equal len(allocated_people).
        A mismatch means either ghost members or missing tracking.
        """
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        total_in_households = count_all_people_in_households(hd)
        tracked_allocated = len(hd.allocated_people)

        assert total_in_households == tracked_allocated, (
            f"People in households ({total_in_households}) != "
            f"tracked allocated ({tracked_allocated}). "
            f"Mismatch of {abs(total_in_households - tracked_allocated)} people."
        )


# ──────────────────────────────────────────────────────────────────────
# Test 9: Full pipeline integration
# ──────────────────────────────────────────────────────────────────────

class TestFullPipelineIntegration:
    """
    Run the complete allocation strategy and verify the overall outcome.
    This is the top-level integration test that exercises all code paths.
    """

    def test_full_pipeline_runs_without_error(self, hd, population_manager, venue_manager):
        """The full allocation strategy should complete without exceptions."""
        np.random.seed(42)

        stats = execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        assert stats is not None
        assert len(stats) == 7, f"Expected 7 steps, got {len(stats)}"

    def test_full_pipeline_step_names(self, hd, population_manager, venue_manager):
        """All configured steps should appear in results with correct types."""
        np.random.seed(42)

        stats = execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        expected = {
            "Two-Adult Families with Children": "household",
            "Elderly Couples": "household",
            "Adult Couples": "household",
            "YA Pairs": "household",
            "Add Excess Kids to Families": "household_excess",
            "Overflow Young Adults": "household_overflow",
            "Promote and Allocate Remaining": "household_promotion",
        }
        for step_name, step_type in expected.items():
            assert step_name in stats, f"Missing step '{step_name}'"
            assert stats[step_name]['type'] == step_type, (
                f"Step '{step_name}' should be type '{step_type}', "
                f"got '{stats[step_name]['type']}'"
            )

    def test_full_pipeline_high_allocation_rate(self, hd, population_manager, venue_manager):
        """
        With demotion + excess + overflow + promotion, allocation rate
        should be very high. This is a 28-person world with sufficient
        household slots — any failure to place people is a bug.
        """
        np.random.seed(42)
        total_population = len(population_manager.get_all_people())

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        allocated = len(hd.allocated_people)
        remaining = total_population - allocated
        allocation_rate = allocated / total_population

        assert allocation_rate >= 0.90, (
            f"Allocation rate {allocation_rate:.1%} too low. "
            f"Allocated {allocated}/{total_population}, remaining {remaining}. "
            f"Remaining by category: {hd.get_available_people_by_category()}"
        )

    def test_full_pipeline_no_empty_households(self, hd, population_manager, venue_manager):
        """Every household must have at least 1 member."""
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        all_hh = venue_manager.get_venues_by_type("household")
        for h in all_hh:
            assert h.size() > 0, (
                f"Empty household {h.id}! Pattern: {h.properties.get('actual_pattern')}"
            )

    def test_full_pipeline_households_in_all_sgus(self, hd, population_manager, venue_manager):
        """Households should be created in all 3 SGUs."""
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        for sgu in ["SGU_S1", "SGU_S2", "SGU_S3"]:
            hh = get_households_by_geo_unit(hd, sgu)
            assert len(hh) > 0, f"No households created in {sgu}"

    def test_full_pipeline_demotion_occurred(self, hd, population_manager, venue_manager):
        """
        The Two-Adult Families step must report demotion.
        SGU_S1 has 3 adults but requests 3x ">=2 >=0 2 0" (needs 6 adults).
        SGU_S2 has "1 >=0 2 0" which also matches the step filter.
        Result: 3 total households (2 SGU_S1 + 1 SGU_S2), with 1 demotion in SGU_S1.
        """
        np.random.seed(42)

        stats = execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        family_step = stats["Two-Adult Families with Children"]
        assert family_step['households_with_demotion'] >= 1, (
            f"Expected at least 1 demotion, got {family_step['households_with_demotion']}"
        )
        # SGU_S1 creates 2, SGU_S2 creates 1 = 3 total
        assert family_step['households_created'] == 3, (
            f"Expected 3 family households (2 SGU_S1 + 1 SGU_S2), "
            f"got {family_step['households_created']}"
        )
        # Requested: SGU_S1 has 3x ">=2 >=0 2 0", SGU_S2 has 1x "1 >=0 2 0" = 4
        assert family_step['households_requested'] == 4, (
            f"Expected 4 requested (3 SGU_S1 + 1 SGU_S2), "
            f"got {family_step['households_requested']}"
        )

    def test_full_pipeline_elderly_couples_both_sgus(self, hd, population_manager, venue_manager):
        """Both SGU_S1 and SGU_S2 should have exactly 1 elderly couple each."""
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        for sgu in ["SGU_S1", "SGU_S2"]:
            hh = get_households_by_geo_unit(hd, sgu)
            elderly_hh = [
                h for h in hh
                if h.properties.get('original_pattern') == "0 0 0 2"
                or h.properties.get('actual_pattern') == "0 0 0 2"
            ]
            assert len(elderly_hh) == 1, (
                f"Expected exactly 1 elderly couple in {sgu}, got {len(elderly_hh)}"
            )
            # Verify it has 2 OA members
            comp = get_household_composition(elderly_hh[0], hd.categories)
            assert comp["Old Adults"] == 2, (
                f"Elderly household in {sgu} should have 2 OA, got {comp['Old Adults']}"
            )

    def test_full_pipeline_sgu_s2_no_demotion_needed(self, hd, population_manager, venue_manager):
        """
        SGU_S2 is balanced: 2 kids, 1 YA, 4 adults, 2 OA for 3 households.
        No demotion should be needed. Verify exact compositions.
        """
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        sgu_s2_hh = get_households_by_geo_unit(hd, "SGU_S2")
        # 3 initial households: "1 >=0 2 0", "0 0 2 0", "0 0 0 2"
        # Check none were demoted
        for h in sgu_s2_hh:
            original = h.properties.get('original_pattern', '')
            actual = h.properties.get('actual_pattern', '')
            if original in ("1 >=0 2 0", "0 0 2 0", "0 0 0 2"):
                # For initial households, actual should match original
                # (demotion would change it)
                assert actual == original or ">=" in original, (
                    f"SGU_S2 household {h.id} was demoted: "
                    f"'{original}' -> '{actual}' (should not need demotion)"
                )

    def test_full_pipeline_sgu_s3_both_households(self, hd, population_manager, venue_manager):
        """SGU_S3 should have exactly 2 households: adult couple + YA pair."""
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        sgu_s3_hh = get_households_by_geo_unit(hd, "SGU_S3")
        assert len(sgu_s3_hh) == 2, (
            f"SGU_S3 should have exactly 2 households, got {len(sgu_s3_hh)}"
        )

        patterns = {h.properties.get('original_pattern') for h in sgu_s3_hh}
        assert "0 0 2 0" in patterns, "SGU_S3 should have adult couple household"
        assert "0 >=0 0 0" in patterns, "SGU_S3 should have YA pair household"

        # Adult couple: 2 adults
        adult_hh = [h for h in sgu_s3_hh if h.properties.get('original_pattern') == "0 0 2 0"][0]
        comp = get_household_composition(adult_hh, hd.categories)
        assert comp["Adults"] == 2

        # YA pair: 2 young adults (from assumption)
        ya_hh = [h for h in sgu_s3_hh if h.properties.get('original_pattern') == "0 >=0 0 0"][0]
        comp = get_household_composition(ya_hh, hd.categories)
        assert comp["Young Adults"] == 2

    def test_full_pipeline_kids_supervision_invariant(self, hd, population_manager, venue_manager):
        """
        After the FULL pipeline, every household with kids must have supervision.

        Note: The isolated promotion test (test_promotion_respects_validation_rules)
        catches a bug where promotion adds kids to elderly-only households. In the
        full pipeline this doesn't manifest because excess/overflow steps place kids
        first. But this test guards against the invariant being broken by any
        combination of steps.
        """
        np.random.seed(42)

        execute_allocation_strategy(
            population=population_manager,
            venues=venue_manager,
            household_distributor=hd,
            strategy_file=f"{STRESS_DATA}/households/test_allocation_strategy.yaml",
        )

        all_hh = venue_manager.get_venues_by_type("household")
        for h in all_hh:
            comp = get_household_composition(h, hd.categories)
            if comp["Kids"] >= 1:
                # Validation rule: "Kids >= 1 → Adults >= 1"
                assert comp["Adults"] >= 1, (
                    f"SUPERVISION VIOLATION: Household {h.id} has {comp['Kids']} kids "
                    f"but {comp['Adults']} adults. Full composition: {comp}. "
                    f"Pattern: {h.properties.get('actual_pattern')}"
                )
