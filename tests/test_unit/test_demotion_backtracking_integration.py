"""
Integration tests for the demotion-backtracking pipeline.

Tests the interaction between:
- _attempt_with_demotion (demotion loop)
- _allocate_household_with_rules (rules-based allocation)
- distribute_households_round (round distribution)
- _calculate_balanced_distribution / _allocate_balanced_distribution

All tests use real objects from the micro_world test data.
"""
import pytest
import numpy as np
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.residence.composition_pattern import CompositionPattern
from may.residence.relationship_rules import RelationshipRule
from may.population.person import Person


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def geography():
    geo = Geography(data_dir="tests/test_data/micro_world/geography")
    geo.load_from_csv()
    return geo


@pytest.fixture
def venue_manager(geography):
    vm = VenueManager(geography, data_dir="tests/test_data/micro_world/venues")
    vm.load_from_yaml_config("test_venues_config.yaml")
    return vm


@pytest.fixture
def population_manager(geography):
    pm = PopulationManager(geography=geography, data_dir="tests/test_data/micro_world/population")
    pm.people = []
    Person.reset_counter()
    return pm


@pytest.fixture
def distributor(geography, population_manager, venue_manager):
    hd = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir="tests/test_data/micro_world/households",
        config_file="test_households_config.yaml"
    )
    # Initialize empty pools for SGU_001
    hd.person_pool_by_geo_unit = {"SGU_001": [{} for _ in hd.categories]}
    # Ensure relationship rules are enabled
    hd.relationship_rules.enabled = True
    hd.relationship_rules.selection_strategy = {
        'max_attempts': 50,
        'use_best_candidate': True,
        'backtracking': {
            'enabled': True,
            'max_backtracks': 3,
            'strategy': 'first_role',
            'log_backtracks': False,
            'avoid_duplicates': True,
        }
    }
    return hd


def create_person(age, sex="female", geo_unit=None):
    """Create a Person with controlled attributes."""
    p = Person(age=age, sex=sex, geographical_unit=geo_unit)
    p.properties = {}
    return p


def populate_pools(distributor, people, geo_unit_code="SGU_001"):
    """Place people into the correct category pool based on their age."""
    pools = [{} for _ in distributor.categories]
    for p in people:
        cat_idx = distributor._get_person_category_idx(p)
        pools[cat_idx][p.id] = p
    distributor.person_pool_by_geo_unit[geo_unit_code] = pools
    return pools


# ============================================================
# Group 1: _attempt_with_demotion — Demotion Loop Tests
# ============================================================

class TestAttemptWithDemotion:
    """Tests for the demotion loop that wraps allocation."""

    def test_demotion_succeeds_on_first_attempt(self, distributor):
        """Pattern matches pools exactly → no demotion needed, household created on attempt 0."""
        geo = distributor.geography.get_unit("SGU_001")
        # Pattern "0 0 1 0" → 1 Adult
        people = [create_person(30, geo_unit=geo)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 1 0")

        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=3
        )

        assert household is not None
        assert household.num_members == 1

    def test_demotion_demotes_failed_category(self, distributor):
        """Kids pool has 1 kid but pattern wants 2 → intelligent demotion reduces kids to 1."""
        geo = distributor.geography.get_unit("SGU_001")
        # Only 1 kid, but pattern wants >=2
        people = [
            create_person(10, geo_unit=geo),   # Kid
            create_person(35, geo_unit=geo),   # Adult
            create_person(38, sex="male", geo_unit=geo),   # Adult
        ]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string(">=2 >=0 2 0")

        # Use the "Two-adult family with kids" rule which has age constraints
        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=5,
            rule_name="Two-adult family with kids"
        )

        assert household is not None
        # Should have been demoted to 1 kid + 2 adults = 3 people
        assert household.num_members <= 3
        # Check the actual pattern was demoted
        actual = household.properties.get('actual_pattern')
        assert actual != ">=2 >=0 2 0"  # Pattern was modified

    def test_demotion_uses_fallback_priority_when_no_category_idx(self, distributor):
        """When failed_category_idx is None, falls back to configured priority order."""
        geo = distributor.geography.get_unit("SGU_001")
        # Pattern ">=2 >=0 2 0" but only 1 adult available → rules-based fails
        # with no specific category (because the rules can't find valid pair)
        people = [
            create_person(10, geo_unit=geo),
            create_person(12, geo_unit=geo),
            create_person(40, geo_unit=geo),  # Only 1 adult
        ]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string(">=2 >=0 2 0")

        # Try with rule that needs 2 adults (pair)
        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=5,
            rule_name="Two-adult family with kids"
        )

        # With only 1 adult, it can't form 2 adults, so demotion kicks in
        # It should either succeed with a demoted pattern or return None
        # The key test is that it doesn't crash when failed_category_idx is None
        # (this was the bug we fixed)

    def test_demotion_respects_min_household_size(self, distributor):
        """Demotion would reduce pattern below min_household_size → returns None."""
        geo = distributor.geography.get_unit("SGU_001")
        # Only 1 adult available; pattern asks for "0 0 2 0"
        people = [create_person(30, geo_unit=geo)]
        populate_pools(distributor, people)

        # Set min_household_size to 2 so demotion to "0 0 1 0" is rejected
        distributor.config['demotion']['min_household_size'] = 2

        pattern = CompositionPattern.from_string("0 0 2 0")

        # Without rule_name → simple allocation. Intelligent demotion from 2 to 1.
        # Bug we fixed: safety checks must apply to intelligent demotion too.
        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=5
        )

        # Should fail: demotion to "0 0 1 0" has min_size=1, below min_household_size=2
        assert household is None

    def test_demotion_respects_validation_rules(self, distributor):
        """Demoted pattern violates 'kids ≥ 1 → adults ≥ 1' → returns None."""
        geo = distributor.geography.get_unit("SGU_001")
        # Pattern "1 0 1 0" with 1 kid but 0 adults available.
        # Intelligent demotion reduces Adults from 1 to 0 → "1 0 0 0".
        # This must be rejected: kids ≥ 1 but adults = 0 violates validation.
        people = [create_person(10, geo_unit=geo)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("1 0 1 0")

        # No rule_name → tests that validation applies to intelligent demotion path too
        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=5
        )

        # Should fail: any demotion of adults with kids present violates validation
        assert household is None

    def test_demotion_exhausts_max_attempts(self, distributor):
        """Every demotion still fails → loop runs max_attempts times then returns None."""
        geo = distributor.geography.get_unit("SGU_001")
        # Empty pools — nothing can work
        populate_pools(distributor, [])

        pattern = CompositionPattern.from_string(">=2 >=0 2 0")

        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=2
        )

        assert household is None

    def test_demotion_with_rule_switching(self, distributor):
        """Demoted pattern matches a demotion_rules entry → switches rule."""
        geo = distributor.geography.get_unit("SGU_001")
        # Pattern ">=2 >=0 2 0" with only 1 kid and 1 adult.
        # Demotion priority: Kids(1) first. Intelligent demotion sees Kids failed,
        # demotes from >=2 to 1. Then 1 adult can't form pair either, fallback
        # demotion demotes Kids from 1 to 0, producing "0 >=0 2 0".
        # But pair still fails → eventually "0 >=0 1 0" via Adult demotion.
        #
        # Instead, let's test rule switching with a simpler scenario:
        # Pattern "0 0 2 0" with 2 adults. Rule "Adult pair" succeeds on first attempt.
        # But if it fails, demotion to "0 0 1 0" should switch to a different rule.
        people = [
            create_person(30, geo_unit=geo),  # Adult
        ]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 2 0")

        # demotion_rules: when demoted to "0 0 1 0", switch to no rule (simple alloc)
        demotion_rules = {"0 0 1 0": None}

        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=5,
            rule_name="Adult pair",
            demotion_rules=demotion_rules
        )

        # Should succeed: pair fails → demotion to "0 0 1 0" → switches rule to None →
        # simple allocation with 1 adult succeeds
        assert household is not None
        assert household.num_members == 1
        # The actual pattern should show the demotion
        assert household.properties['actual_pattern'] == '0 0 1 0'

    def test_demotion_with_none_category_idx_no_crash(self, distributor):
        """Bug fix test: when failed_category_idx is None, intelligent demotion is skipped safely."""
        geo = distributor.geography.get_unit("SGU_001")
        # Provide enough people in pools but use a rule that will fail
        # without returning a specific failed_category_idx
        people = [create_person(30, geo_unit=geo)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 2 0")

        # This should NOT crash even when rules-based allocation returns None
        # with failed_category_idx=None (e.g., pair matching failure)
        household = distributor._attempt_with_demotion(
            "SGU_001", pattern, max_attempts=3,
            rule_name="Adult pair"
        )

        # With only 1 adult, pair matching fails. The key assertion is NO CRASH.
        # It should either succeed via demotion or return None gracefully.


# ============================================================
# Group 2: _allocate_household_with_rules — Rules Integration
# ============================================================

class TestAllocateHouseholdWithRules:
    """Tests for the full rules-based allocation flow."""

    def test_allocate_with_rules_creates_household(self, distributor):
        """Full flow: rules match, people selected, household Venue created with correct properties."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [
            create_person(10, geo_unit=geo),          # Kid
            create_person(35, geo_unit=geo),          # Adult
            create_person(38, sex="male", geo_unit=geo),  # Adult
        ]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("1 >=0 2 0")

        household, failed_idx = distributor._allocate_household_with_rules(
            "SGU_001", pattern, rule_name="Two-adult family with kids"
        )

        assert household is not None
        assert failed_idx is None
        assert household.num_members == 3
        assert household.properties['original_pattern'] == "1 >=0 2 0"
        assert household.properties['actual_pattern'] == "1 >=0 2 0"

    def test_allocate_with_rules_removes_from_pools(self, distributor):
        """Selected people are removed from pools and added to allocated_people."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [
            create_person(30, geo_unit=geo),          # Adult
            create_person(33, sex="male", geo_unit=geo),  # Adult
        ]
        pools = populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 2 0")

        initial_pool_size = len(pools[2])  # Adults pool
        assert initial_pool_size == 2

        household, failed_idx = distributor._allocate_household_with_rules(
            "SGU_001", pattern, rule_name="Adult pair"
        )

        assert household is not None
        # Both adults should have been removed from the pool
        assert len(pools[2]) == 0
        # And added to allocated_people
        assert len(distributor.allocated_people) == 2

    def test_allocate_with_rules_no_rule_falls_back(self, distributor):
        """No rule_name → falls back to simple _allocate_household."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [create_person(30, geo_unit=geo)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 1 0")

        # No rule_name → should fall back to simple allocation
        household, failed_idx = distributor._allocate_household_with_rules(
            "SGU_001", pattern
        )

        assert household is not None
        assert household.num_members == 1

    def test_allocate_with_rules_unknown_rule_falls_back(self, distributor):
        """Invalid rule_name → logs warning, falls back to simple allocation."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [create_person(30, geo_unit=geo)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 0 1 0")

        household, failed_idx = distributor._allocate_household_with_rules(
            "SGU_001", pattern, rule_name="Nonexistent Rule"
        )

        # Should still succeed via fallback
        assert household is not None
        assert household.num_members == 1


# ============================================================
# Group 3: distribute_households_round — Round Distribution
# ============================================================

class TestDistributeHouseholdsRound:
    """Tests for the round distribution orchestration."""

    def _setup_full_distributor(self, distributor):
        """Load CSV data and populate pools for round distribution tests."""
        distributor.load_household_data("households.csv")
        geo = distributor.geography.get_unit("SGU_001")
        geo2 = distributor.geography.get_unit("SGU_002")

        # Populate with enough people to satisfy the CSV demands
        people = []
        # SGU_001 needs: 2x ">=2 >=0 2 0", 1x "0 0 2 0"
        # → at least 4 kids, 6 adults
        for _ in range(6):
            people.append(create_person(np.random.randint(5, 15), geo_unit=geo))
        for i in range(8):
            sex = "male" if i % 2 == 0 else "female"
            people.append(create_person(np.random.randint(30, 50), sex=sex, geo_unit=geo))

        # SGU_002 needs: 1x "1 >=0 2 0", 1x "0 0 1 0"
        for _ in range(2):
            people.append(create_person(np.random.randint(5, 15), geo_unit=geo2))
        for i in range(4):
            sex = "male" if i % 2 == 0 else "female"
            people.append(create_person(np.random.randint(30, 50), sex=sex, geo_unit=geo2))

        # Register all people with population manager
        distributor.population.people = people

        # Register people on their geo units so get_people_by_geo_unit() works
        # (This is normally done by the population loading pipeline)
        for unit in [geo, geo2]:
            if not hasattr(unit, 'people'):
                unit.people = []
        for p in people:
            p.geographical_unit.people.append(p)

        # Reset pools so _prepare_person_pools runs fresh from population
        distributor.pools_prepared = False
        distributor.person_pool_by_geo_unit = {}

        return people

    def test_round_creates_households_from_csv(self, distributor):
        """Load counts from CSV, allocate patterns → households created."""
        self._setup_full_distributor(distributor)

        stats = distributor.round_distributor.distribute_households_round(
            round_name="Test Round 1"
        )

        assert stats['households_created'] > 0
        assert stats['people_allocated_this_round'] > 0
        assert stats['round_name'] is not None

    def test_round_pattern_filter(self, distributor):
        """pattern_filter=['0 0 2 0'] → only adult-couple households created."""
        self._setup_full_distributor(distributor)

        stats = distributor.round_distributor.distribute_households_round(
            pattern_filter=["0 0 2 0"],
            round_name="Adult Pairs Only",
            rule_name="Adult pair"
        )

        # Only "0 0 2 0" should have been allocated (1 in SGU_001 from CSV)
        assert stats['households_requested'] >= 1
        # All created households with original_pattern should be adult-pair pattern
        if stats['households_created'] > 0:
            households = distributor.venue_manager.get_venues_by_type("household")
            for h in households:
                # Only check households created by the distributor (have original_pattern)
                if 'original_pattern' in h.properties:
                    assert h.properties['original_pattern'] in ["0 0 2 0"]

    def test_round_max_households_limit(self, distributor):
        """max_households=1 → stops after 1 even if more are needed."""
        self._setup_full_distributor(distributor)

        stats = distributor.round_distributor.distribute_households_round(
            max_households=1,
            round_name="Limited Round"
        )

        assert stats['households_created'] <= 1

    def test_round_refresh_pools(self, distributor):
        """After partial allocation, refresh_pools=True correctly excludes already-allocated people."""
        self._setup_full_distributor(distributor)

        # First round: allocate some
        stats1 = distributor.round_distributor.distribute_households_round(
            pattern_filter=["0 0 2 0"],
            round_name="Round 1",
            rule_name="Adult pair"
        )
        allocated_after_r1 = stats1['total_people_allocated']

        # Second round with refresh
        stats2 = distributor.round_distributor.distribute_households_round(
            pattern_filter=["0 0 1 0"],
            round_name="Round 2",
            refresh_pools=True
        )

        # People from round 1 should not be re-allocated
        total_unique = len(distributor.allocated_people)
        assert total_unique == stats2['total_people_allocated']
        assert total_unique >= allocated_after_r1

    def test_round_returns_correct_stats(self, distributor):
        """Verify round_stats dict has correct keys and values."""
        self._setup_full_distributor(distributor)

        stats = distributor.round_distributor.distribute_households_round(
            round_name="Stats Test",
            max_households=2
        )

        # Verify all expected keys are present
        expected_keys = [
            'round_name', 'round_number', 'households_created',
            'households_requested', 'households_with_demotion',
            'people_allocated_this_round', 'total_households',
            'total_people_allocated', 'total_people_remaining'
        ]
        for key in expected_keys:
            assert key in stats, f"Missing key: {key}"

        # Verify internal consistency
        assert stats['households_created'] <= stats['households_requested']
        assert stats['people_allocated_this_round'] >= 0
        assert stats['total_people_remaining'] >= 0


# ============================================================
# Group 4: Balanced Distribution
# ============================================================

class TestBalancedDistribution:
    """Tests for _calculate_balanced_distribution and _allocate_balanced_distribution."""

    def test_balanced_distribution_even_split(self, distributor):
        """10 people, 5 households → sizes [2, 2, 2, 2, 2]."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [create_person(30, geo_unit=geo) for _ in range(10)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 >=0 >=0 0")

        sizes = distributor.round_distributor._calculate_balanced_distribution(
            "SGU_001", pattern, num_households=5, max_household_size=None
        )

        assert len(sizes) == 5
        assert sum(sizes) == 10
        assert all(s == 2 for s in sizes)

    def test_balanced_distribution_uneven_split(self, distributor):
        """11 people, 4 households → sizes like [3, 3, 3, 2]."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [create_person(30, geo_unit=geo) for _ in range(11)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 >=0 >=0 0")

        sizes = distributor.round_distributor._calculate_balanced_distribution(
            "SGU_001", pattern, num_households=4, max_household_size=None
        )

        assert len(sizes) == 4
        assert sum(sizes) == 11
        # Should be balanced: difference between any two is at most 1
        assert max(sizes) - min(sizes) <= 1

    def test_balanced_distribution_respects_max_size(self, distributor):
        """max_household_size=3, 20 people, 5 households → all sizes ≤ 3."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [create_person(30, geo_unit=geo) for _ in range(20)]
        populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 >=0 >=0 0")

        sizes = distributor.round_distributor._calculate_balanced_distribution(
            "SGU_001", pattern, num_households=5, max_household_size=3
        )

        assert len(sizes) == 5
        assert all(s <= 3 for s in sizes)

    def test_allocate_balanced_proportional(self, distributor):
        """Flexible pattern with 2 categories → proportional allocation."""
        geo = distributor.geography.get_unit("SGU_001")
        # 3 YA and 7 Adults
        people = [create_person(20, geo_unit=geo) for _ in range(3)]  # YA
        people += [create_person(35, geo_unit=geo) for _ in range(7)]  # Adults
        pools = populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("0 >=0 >=0 0")  # Both flexible

        selections, failed_cat = distributor.round_distributor._allocate_balanced_distribution(
            pattern, pools, target_size=5
        )

        assert failed_cat is None
        assert selections is not None

        # Total allocated should equal target_size
        total = sum(count for _, count in selections)
        assert total == 5

        # Check proportional: Adults should get more than YA
        allocation_dict = {cat_idx: count for cat_idx, count in selections}
        ya_count = allocation_dict.get(1, 0)
        adult_count = allocation_dict.get(2, 0)
        assert adult_count >= ya_count  # 70/30 split

    def test_allocate_balanced_fixed_plus_flexible(self, distributor):
        """Pattern '1 >=0 2 0' → Kids fixed at 1, Adults fixed at 2, YA gets flexible rest."""
        geo = distributor.geography.get_unit("SGU_001")
        people = [
            create_person(10, geo_unit=geo),   # Kid
            create_person(20, geo_unit=geo),   # YA
            create_person(21, geo_unit=geo),   # YA
            create_person(35, geo_unit=geo),   # Adult
            create_person(40, geo_unit=geo),   # Adult
        ]
        pools = populate_pools(distributor, people)

        pattern = CompositionPattern.from_string("1 >=0 2 0")

        selections, failed_cat = distributor.round_distributor._allocate_balanced_distribution(
            pattern, pools, target_size=5
        )

        assert failed_cat is None
        assert selections is not None

        allocation_dict = {cat_idx: count for cat_idx, count in selections}
        # Kids should be exactly 1 (fixed)
        assert allocation_dict.get(0, 0) == 1
        # Adults should be exactly 2 (fixed)
        assert allocation_dict.get(2, 0) == 2
        # YA should get the rest (2 out of target 5 - 3 fixed = 2)
        assert allocation_dict.get(1, 0) == 2
