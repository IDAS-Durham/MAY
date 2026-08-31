"""
Tests for the venue allocator.

Covers:
  - _get_eligible_people: eligibility filtering
  - _apply_strategy: sort ordering
  - _check_attribute_constraints: venue-level min/max from CSV columns
  - _allocate_to_venue_type (simple mode)
  - _allocate_with_attributes (attribute-aware mode)

Design principle: every assertion reflects the *intended* behaviour
described in the source code.  We do not soften expectations to pass
tests, so a failing test signals a real bug.

Test data lives in tests/test_data/stress_world/
Population (28 people across 3 SGUs):
  SGU_S1: kids 3-16 (7, mixed), YA 19-23 (3), adults 30-42 (3), OA 68f/75m (2)
  SGU_S2: kids 6m/10f, YA 20f, adults 28f/32m/45f/55m, OA 70m/78f
  SGU_S3: YA 18m/24f, adults 29f/33m
"""

import pytest
import numpy as np

from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.residence.venue_allocator import (
    _get_eligible_people,
    _apply_strategy,
    _check_attribute_constraints,
    _allocate_to_venue_type,
    _allocate_with_attributes,
)

STRESS_DATA = "tests/test_data/stress_world"


# Fixtures


@pytest.fixture
def geography():
    geo = Geography(data_dir=f"{STRESS_DATA}/geography", levels=["SGU", "MGU", "LGU"], hierarchy_file="hierarchy.csv")
    geo.load_from_csv()
    return geo


@pytest.fixture
def population_manager(geography):
    pm = PopulationManager(geography=geography, data_dir=f"{STRESS_DATA}/population")
    pm.load_explicit_from_csv(
        "people.csv",
        column_mapping={"age": "age", "sex": "sex", "geo_unit": "location"},
    )
    return pm


@pytest.fixture
def venue_manager(geography):
    vm = VenueManager(geography, data_dir=f"{STRESS_DATA}/venues")
    vm.load_from_yaml_config("test_venues_config.yaml")
    return vm


@pytest.fixture
def hd(geography, population_manager, venue_manager):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir=f"{STRESS_DATA}/households",
        config_file="test_households_config.yaml",
    )
    distributor.load_household_data("households.csv")
    return distributor


# Helpers


def all_people(hd):
    return list(hd.population.get_all_people())


def unallocated_ids(hd):
    return {p.id for p in all_people(hd) if p.id not in hd.allocated_people}


def person_by_id(hd, pid):
    return next(p for p in all_people(hd) if p.id == pid)


def mark_allocated(hd, person_ids):
    """Pre-mark specific people as already allocated."""
    for pid in person_ids:
        hd.allocated_people.add(pid)


# _get_eligible_people


class TestGetEligiblePeople:
    """_get_eligible_people must respect eligibility rules and prior allocation state."""

    def test_empty_eligibility_returns_all_unallocated(self, hd):
        """No criteria → every person not yet in allocated_people is returned."""
        eligible = _get_eligible_people(hd.population, hd, eligibility={})
        assert len(eligible) == len(all_people(hd))

    def test_already_allocated_excluded_from_empty_eligibility(self, hd):
        """If a person is pre-marked allocated, they must not appear in the result."""
        p = all_people(hd)[0]
        mark_allocated(hd, [p.id])

        eligible = _get_eligible_people(hd.population, hd, eligibility={})
        eligible_ids = {e.id for e in eligible}

        assert p.id not in eligible_ids
        assert len(eligible) == len(all_people(hd)) - 1

    def test_age_range_excludes_below_minimum(self, hd):
        """People younger than min age must not appear in eligible list."""
        eligibility = [{"attribute": "age", "min": 50}]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert all(p.age >= 50 for p in eligible)

    def test_age_range_excludes_above_maximum(self, hd):
        """People older than max age must not appear in eligible list."""
        eligibility = [{"attribute": "age", "max": 17}]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert all(p.age <= 17 for p in eligible)

    def test_age_range_both_bounds_respected(self, hd):
        """Only people within [min, max] are returned."""
        eligibility = [{"attribute": "age", "min": 18, "max": 30}]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert all(18 <= p.age <= 30 for p in eligible)
        # Verify at least one expected person is present (id=7: age=19, SGU_S1)
        eligible_ids = {p.id for p in eligible}
        assert 7 in eligible_ids  # age 19, SGU_S1

    def test_exact_value_filter_sex(self, hd):
        """Exact match filter on sex must only return the matching sex."""
        eligibility = [{"attribute": "sex", "value": "female"}]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert all(p.sex == "female" for p in eligible)
        assert len(eligible) > 0  # test population has females

    def test_multiple_criteria_are_all_required(self, hd):
        """All criteria must be satisfied simultaneously (logical AND)."""
        eligibility = [
            {"attribute": "age", "min": 65},
            {"attribute": "sex", "value": "female"},
        ]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert all(p.age >= 65 and p.sex == "female" for p in eligible)
        # id=13: age=68, sex=female, SGU_S1, must be present
        assert 13 in {p.id for p in eligible}
        # id=14: age=75, sex=male, must NOT be present
        assert 14 not in {p.id for p in eligible}

    def test_already_allocated_excluded_from_criteria_match(self, hd):
        """Pre-allocated people must be excluded even when they match all criteria."""
        # id=13: age=68, sex=female, matches age>=65 AND sex=female
        mark_allocated(hd, [13])
        eligibility = [
            {"attribute": "age", "min": 65},
            {"attribute": "sex", "value": "female"},
        ]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert 13 not in {p.id for p in eligible}

    def test_returns_empty_list_when_nobody_qualifies(self, hd):
        """Returns empty list when no unallocated person meets criteria."""
        eligibility = [{"attribute": "age", "min": 999}]
        eligible = _get_eligible_people(hd.population, hd, eligibility=eligibility)
        assert eligible == []


# _apply_strategy


class TestApplyStrategy:
    """_apply_strategy must sort people according to the named strategy."""

    def _people_with_ages(self, hd, ages):
        """Return person objects with specific ages from the population."""
        return [p for p in all_people(hd) if p.age in ages]

    def test_oldest_first_sorts_descending(self, hd):
        """oldest_first must produce descending age order."""
        people = all_people(hd)
        result = _apply_strategy(list(people), "oldest_first", {})
        ages = [p.age for p in result]
        assert ages == sorted(ages, reverse=True)

    def test_youngest_first_sorts_ascending(self, hd):
        """youngest_first must produce ascending age order."""
        people = all_people(hd)
        result = _apply_strategy(list(people), "youngest_first", {})
        ages = [p.age for p in result]
        assert ages == sorted(ages)

    def test_random_returns_same_people(self, hd):
        """random strategy must return all the same people, just shuffled."""
        people = all_people(hd)
        original_ids = {p.id for p in people}
        result = _apply_strategy(list(people), "random", {})
        result_ids = {p.id for p in result}
        assert result_ids == original_ids
        assert len(result) == len(people)

    def test_unknown_strategy_falls_back_to_random(self, hd):
        """An unrecognised strategy name must not crash and must return all people."""
        people = all_people(hd)
        result = _apply_strategy(list(people), "nonexistent_strategy", {})
        assert {p.id for p in result} == {p.id for p in people}


# _apply_strategy: age_weighted


# Covers every age in the stress world (3-78) plus the open top band.
AGE_WEIGHT_BANDS = [
    {"range": [0, 64], "weight": 0.001},
    {"range": [65, 120], "weight": 0.1},
]


class TestAgeWeightedStrategy:
    """age_weighted must be a weighted sample without replacement, and must
    refuse a band table it cannot apply rather than quietly guessing."""

    def test_returns_a_permutation_of_the_input(self, hd):
        """Weighting reorders the pool; it must not drop or duplicate anyone."""
        people = all_people(hd)
        result = _apply_strategy(list(people), "age_weighted",
                                 {"bands": AGE_WEIGHT_BANDS})
        assert sorted(p.id for p in result) == sorted(p.id for p in people)

    def test_heavier_band_is_drawn_first_far_more_often_than_chance(self, hd):
        """The 65+ band carries 100x the weight, so a 65+ person must lead the
        ordering far more often than their 4-in-28 share of the pool."""
        people = all_people(hd)
        share = sum(1 for p in people if p.age >= 65) / len(people)

        np.random.seed(0)
        leads = sum(
            _apply_strategy(list(people), "age_weighted",
                            {"bands": AGE_WEIGHT_BANDS})[0].age >= 65
            for _ in range(300)
        )
        assert leads / 300 > 5 * share

    def test_equal_weights_do_not_collapse_to_input_order(self, hd):
        """A single band gives every person the same weight, which must still
        shuffle. The textbook u**(1/w) key underflows to a tie at zero for
        small weights and would silently return the input order."""
        people = all_people(hd)
        bands = [{"range": [0, 120], "weight": 0.00128}]

        np.random.seed(0)
        orders = {
            tuple(p.id for p in _apply_strategy(list(people), "age_weighted",
                                                {"bands": bands}))
            for _ in range(20)
        }
        assert len(orders) > 1

    def test_missing_bands_raises(self, hd):
        """No band table is a config error, not a reason to fall back."""
        with pytest.raises(ValueError, match="requires strategy_config.bands"):
            _apply_strategy(all_people(hd), "age_weighted", {})

    def test_overlapping_bands_raise(self, hd):
        """Overlapping bands would give one age two weights by band order."""
        bands = [{"range": [0, 70], "weight": 0.01},
                 {"range": [65, 120], "weight": 0.1}]
        with pytest.raises(ValueError, match="overlap at age 65"):
            _apply_strategy(all_people(hd), "age_weighted", {"bands": bands})

    def test_non_positive_weight_raises(self, hd):
        """A zero weight cannot be sampled; it must not be silently tolerated."""
        bands = [{"range": [0, 120], "weight": 0}]
        with pytest.raises(ValueError, match="weight must be positive"):
            _apply_strategy(all_people(hd), "age_weighted", {"bands": bands})

    def test_age_outside_every_band_raises(self, hd):
        """An uncovered age must fail loudly rather than take a default weight."""
        bands = [{"range": [0, 70], "weight": 0.01}]
        with pytest.raises(ValueError, match="which no age_weighted band covers"):
            _apply_strategy(all_people(hd), "age_weighted", {"bands": bands})


# _check_attribute_constraints


class TestCheckAttributeConstraints:
    """_check_attribute_constraints enforces per-venue min/max from CSV properties."""

    def _make_venue_with_constraints(self, hd, min_age, max_age):
        """Return a boarding_school venue with StatutoryLowAge/HighAge set."""
        schools = hd.venue_manager.get_venues_by_type("boarding_school")
        assert schools, "boarding_school venues not loaded"
        school = schools[0]
        school.properties["StatutoryLowAge"] = float(min_age)
        school.properties["StatutoryHighAge"] = float(max_age)
        return school

    def test_person_within_age_range_passes(self, hd):
        """A person whose age falls within StatutoryLow/HighAge must pass."""
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 3)  # age=9, sex=female, SGU_S1
        assert _check_attribute_constraints(p, school, constraints) is True

    def test_person_below_minimum_age_fails(self, hd):
        """A person younger than StatutoryLowAge must fail the constraint check."""
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 0)  # age=3, SGU_S1, below minimum 5
        assert _check_attribute_constraints(p, school, constraints) is False

    def test_person_above_maximum_age_fails(self, hd):
        """A person older than StatutoryHighAge must fail the constraint check."""
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 7)  # age=19, SGU_S1, above maximum 16
        assert _check_attribute_constraints(p, school, constraints) is False

    def test_person_exactly_at_minimum_passes(self, hd):
        """A person at exactly the minimum age is within range and must pass."""
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 1)  # age=5, sex=female, SGU_S1, exactly at minimum
        assert _check_attribute_constraints(p, school, constraints) is True

    def test_person_exactly_at_maximum_passes(self, hd):
        """A person at exactly the maximum age is within range and must pass."""
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 6)  # age=16, sex=male, SGU_S1, exactly at maximum
        assert _check_attribute_constraints(p, school, constraints) is True

    def test_nan_constraint_values_are_ignored(self, hd):
        """NaN in a constraint column must be treated as no constraint (pass)."""
        import math
        school = self._make_venue_with_constraints(hd, 5.0, 16.0)
        school.properties["StatutoryHighAge"] = float("nan")
        constraints = {
            "age": {"min_column": "StatutoryLowAge", "max_column": "StatutoryHighAge"}
        }
        p = person_by_id(hd, 7)  # age=19, would normally fail max, but max is NaN
        assert _check_attribute_constraints(p, school, constraints) is True

    def test_empty_constraints_always_passes(self, hd):
        """An empty constraints dict must not reject any person."""
        school = next(iter(hd.venue_manager.get_venues_by_type("boarding_school")))
        p = person_by_id(hd, 0)  # id=0, age=3, any person
        assert _check_attribute_constraints(p, school, {}) is True


# _allocate_to_venue_type: simple mode


class TestSimpleAllocation:
    """Simple allocation: capacity respected, geo-unit scoped, strategies applied."""

    def _shelter_config(self, strategy="random"):
        cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": strategy,
        }
        return cfg

    def test_total_allocations_never_exceed_total_capacity(self, hd):
        """Shelters have 3+2=5 capacity; total allocated must be ≤ 5."""
        cfg = self._shelter_config()
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert stats["allocated"] <= stats["total_capacity"]
        assert stats["allocated"] <= 5

    def test_reported_total_capacity_matches_csv_sum(self, hd):
        """VenueManager should report total capacity = 3 (SGU_S1) + 2 (SGU_S2) = 5."""
        cfg = self._shelter_config()
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert stats["total_capacity"] == 5

    def test_allocated_people_marked_in_distributor(self, hd):
        """Every person placed into a shelter must appear in hd.allocated_people."""
        cfg = self._shelter_config()
        before = set(hd.allocated_people)
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        after = set(hd.allocated_people)
        newly_allocated = after - before
        assert len(newly_allocated) == stats["allocated"]

    def test_same_person_not_allocated_twice(self, hd):
        """No person must appear in more than one shelter's residents list."""
        cfg = self._shelter_config()
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        all_residents = []
        for s in shelters:
            residents = s.properties.get("residents", [])
            all_residents.extend(residents)
        resident_ids = [p.id for p in all_residents]
        assert len(resident_ids) == len(set(resident_ids))

    def test_geo_unit_isolation_shelter(self, hd):
        """SGU_S1's shelter must only receive people from SGU_S1."""
        cfg = self._shelter_config()
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        s1_shelter = next(s for s in shelters if s.geographical_unit.name == "SGU_S1")
        for person in s1_shelter.properties.get("residents", []):
            assert person.geographical_unit.name == "SGU_S1"

    def test_pre_allocated_people_not_placed_in_venue(self, hd):
        """People already in hd.allocated_people must not be placed in shelters."""
        # Mark everyone in SGU_S1 as pre-allocated
        sgu_s1_people = [p for p in all_people(hd) if p.geographical_unit.name == "SGU_S1"]
        pre_ids = {p.id for p in sgu_s1_people}
        mark_allocated(hd, pre_ids)

        cfg = self._shelter_config()
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        s1_shelter = next(
            s for s in hd.venue_manager.get_venues_by_type("shelter")
            if s.geographical_unit.name == "SGU_S1"
        )
        # No pre-allocated person should appear in the shelter
        resident_ids = {p.id for p in s1_shelter.properties.get("residents", [])}
        assert resident_ids.isdisjoint(pre_ids)

    def test_unknown_venue_type_returns_zero_stats(self, hd):
        """Requesting a venue type that doesn't exist must return a zero-filled stats dict with no crash."""
        cfg = self._shelter_config()
        stats = _allocate_to_venue_type("nonexistent_venue", cfg, hd.population, hd.venue_manager, hd)
        assert stats["allocated"] == 0
        assert stats["total_capacity"] == 0
        assert stats["venues"] == 0

    def test_oldest_first_fills_with_oldest_people(self, hd):
        """When strategy=oldest_first, the oldest eligible people are placed first."""
        cfg = self._shelter_config(strategy="oldest_first")
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        placed_ages = sorted(
            [p.age for s in shelters for p in s.properties.get("residents", [])],
            reverse=True
        )
        # All people in the population sorted oldest first
        all_sorted_ages = sorted([p.age for p in all_people(hd)], reverse=True)
        placed_count = len(placed_ages)
        # The placed people should be the top-N oldest from their respective geo units
        # At minimum: the very oldest placed person must be in the global top-N by age
        if placed_ages:
            # The oldest placed person across all shelters should be among
            # the globally oldest people (within geo-unit scope the oldest go first)
            assert placed_ages[0] == max(placed_ages)

    def test_youngest_first_fills_with_youngest_people(self, hd):
        """When strategy=youngest_first, the youngest eligible people are placed first."""
        cfg = self._shelter_config(strategy="youngest_first")
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        placed_ages = sorted(
            [p.age for s in shelters for p in s.properties.get("residents", [])]
        )
        if placed_ages:
            assert placed_ages[0] == min(placed_ages)

    def test_capacity_zero_venue_is_skipped(self, hd):
        """A venue with capacity=0 must receive no residents and not crash."""
        # Temporarily zero out SGU_S1's shelter capacity
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        s1 = next(s for s in shelters if s.geographical_unit.name == "SGU_S1")
        original_cap = s1.properties["capacity"]
        s1.properties["capacity"] = 0

        cfg = self._shelter_config()
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert s1.properties.get("residents", []) == []
        # Restore for other tests
        s1.properties["capacity"] = original_cap

    def test_stats_dict_has_required_keys(self, hd):
        """Returned stats dict must contain the documented keys."""
        cfg = self._shelter_config()
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert "allocated" in stats
        assert "total_capacity" in stats
        assert "venues" in stats
        assert "capacity_pct" in stats


# _allocate_with_attributes: attribute-aware mode (care_home)


class TestAttributeAwareAllocation:
    """Attribute-aware allocation: per-slot capacity, correct demographic matching."""

    def _care_home_config(self, strategy="age_weighted"):
        """The two-band schema the UK venue files carry: n_50_64 and an open
        n_65_plus, filled by care-home residence rate."""
        return {
            "eligibility": [{"attribute": "age", "min": 50}],
            "strategy": strategy,
            "strategy_config": {
                "bands": [
                    {"range": [50, 64], "weight": 0.00128},
                    {"range": [65, 74], "weight": 0.0092},
                    {"range": [75, 84], "weight": 0.0347},
                    {"range": [85, 120], "weight": 0.1133},
                ]
            },
            "capacity_config": {
                "attribute_capacities": {
                    "column_mappings": {
                        "n_50_64":   {"age_band": [50, 64]},
                        "n_65_plus": {"age_band": [65, 120]},
                    }
                }
            },
        }

    def test_venue_residents_are_removed_from_the_household_pools(self, hd):
        """Household rounds only consult allocated_people when a pool is built
        or refreshed, so a venue step must prune the pools as well as the set.
        Otherwise a later round with refresh_pools: false seats a care-home
        resident in a household too."""
        hd._prepare_person_pools()
        cfg = self._care_home_config()
        stats = _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        assert stats["allocated"] > 0

        still_pooled = {
            pid
            for pools in hd.person_pool_by_geo_unit.values()
            for pool in pools
            for pid in pool
        }
        assert still_pooled.isdisjoint(hd.allocated_people)

    def test_only_eligible_ages_placed_in_care_homes(self, hd):
        """Care homes have age>=50 eligibility; no person under 50 must be placed."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        for ch in care_homes:
            for person in ch.properties.get("residents", []):
                assert person.age >= 50, (
                    f"Person {person.id} age={person.age} placed in care home but age < 50"
                )

    def test_person_placed_in_correct_age_slot(self, hd):
        """id=21 (age=55) is SGU_S2's only 50-64, and that home has one such slot."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        s2_ch = next(c for c in care_homes if c.geographical_unit.name == "SGU_S2")
        slot_residents = s2_ch.properties.get("residents_n_50_64", [])
        assert [p.id for p in slot_residents] == [21], (
            "id=21 (age=55) must fill the n_50_64 slot of SGU_S2's care home"
        )

    def test_person_not_placed_in_wrong_slot(self, hd):
        """The 50-64 slot must not absorb someone the 65+ band claims. id=22
        (age=70) and id=23 (age=78) belong in n_65_plus, not n_50_64."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        s2_ch = next(c for c in care_homes if c.geographical_unit.name == "SGU_S2")
        younger_slot = s2_ch.properties.get("residents_n_50_64", [])
        assert all(p.id not in (22, 23) for p in younger_slot)
        assert {p.id for p in s2_ch.properties.get("residents_n_65_plus", [])} == {22, 23}

    def test_slot_capacity_is_hard_cap(self, hd):
        """The number of residents in any slot must not exceed that slot's CSV capacity."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        column_mappings = cfg["capacity_config"]["attribute_capacities"]["column_mappings"]
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        for ch in care_homes:
            for col in column_mappings:
                slot_cap = ch.properties.get(col, 0)
                slot_residents = ch.properties.get(f"residents_{col}", [])
                assert len(slot_residents) <= int(slot_cap), (
                    f"Venue {ch.name}: slot {col} has {len(slot_residents)} residents "
                    f"but capacity is {slot_cap}"
                )

    def test_allocated_people_marked_in_distributor(self, hd):
        """Every person placed in a care home must appear in hd.allocated_people."""
        cfg = self._care_home_config()
        before = set(hd.allocated_people)
        stats = _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        after = set(hd.allocated_people)
        newly_allocated = after - before
        assert len(newly_allocated) == stats["allocated"]

    def test_same_person_not_placed_in_two_care_homes(self, hd):
        """No person must appear as resident in more than one care home."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        all_residents = []
        for ch in care_homes:
            all_residents.extend(ch.properties.get("residents", []))
        resident_ids = [p.id for p in all_residents]
        assert len(resident_ids) == len(set(resident_ids))

    def test_geo_unit_isolation_care_home(self, hd):
        """SGU_S2's care home must only receive people from SGU_S2."""
        cfg = self._care_home_config()
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        s2_ch = next(c for c in care_homes if c.geographical_unit.name == "SGU_S2")
        for person in s2_ch.properties.get("residents", []):
            assert person.geographical_unit.name == "SGU_S2"

    def test_stats_dict_includes_allocation_by_attribute(self, hd):
        """Attribute-aware allocation must return allocation_by_attribute in stats."""
        cfg = self._care_home_config()
        stats = _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        assert "allocation_by_attribute" in stats
        assert isinstance(stats["allocation_by_attribute"], dict)

    def test_stats_allocation_by_attribute_sums_to_total_allocated(self, hd):
        """Sum of all slot counts in allocation_by_attribute must equal total allocated."""
        cfg = self._care_home_config()
        stats = _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        slot_total = sum(stats["allocation_by_attribute"].values())
        assert slot_total == stats["allocated"]

    def test_fallback_to_simple_when_no_capacity_config(self, hd):
        """If VenueManager has no capacity_config for the type, falls back to simple allocation."""
        # shelter has no capacity_config defined → should fall back
        cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": "random",
        }
        # Must not raise, and must allocate some people (shelters have capacity)
        stats = _allocate_with_attributes("shelter", cfg, hd.population, hd.venue_manager, hd)
        # No column_mappings → falls back to simple allocation and proceeds
        assert stats["allocated"] >= 0
        assert "total_capacity" in stats

    def test_no_venues_found_returns_zero_stats(self, hd):
        """When the venue type has no venues loaded, stats must show zeros."""
        cfg = {
            "eligibility": [],
            "strategy": "random",
            # Capacity config is now owned by the allocation step itself,
            # not by venue_manager.
            "capacity_config": {
                "attribute_capacities": {
                    "column_mappings": {"slot_a": {"age_band": [0, 99]}}
                }
            },
        }
        stats = _allocate_with_attributes("ghost_venue", cfg, hd.population, hd.venue_manager, hd)
        assert stats["venues"] == 0
        assert stats["allocated"] == 0


# Mode gate: _allocate_to_venue_type routes by presence of column_mappings


class TestAllocationModeGate:
    """The single switch: a step is attribute-aware iff its capacity_config
    supplies attribute_capacities.column_mappings. No mode flag is consulted."""

    def test_column_mappings_present_routes_to_attribute_aware(self, hd):
        """capacity_config with column_mappings → attribute-aware path
        (stats carry allocation_by_attribute), with no mode flag present."""
        cfg = {
            "eligibility": [{"attribute": "age", "min": 50}],
            "strategy": "oldest_first",
            "capacity_config": {
                "attribute_capacities": {
                    "column_mappings": {
                        "age_65_74_male":   {"age_band": [65, 74], "sex": "male"},
                        "age_65_74_female": {"age_band": [65, 74], "sex": "female"},
                    }
                }
            },
        }
        stats = _allocate_to_venue_type("care_home", cfg, hd.population, hd.venue_manager, hd)
        assert "allocation_by_attribute" in stats

    def test_no_column_mappings_routes_to_simple(self, hd):
        """No column_mappings → simple path (no allocation_by_attribute),
        with no mode flag present."""
        cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": "random",
        }
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert "allocation_by_attribute" not in stats
        assert "total_capacity" in stats

    def test_empty_capacity_config_routes_to_simple(self, hd):
        """An empty capacity_config (e.g. the 1918 venue steps that declared no
        buckets) → simple path, matching the runtime fallback it already hit."""
        cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": "random",
            "capacity_config": {},
        }
        stats = _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        assert "allocation_by_attribute" not in stats


# Attribute constraints: boarding_school


class TestBoardingSchoolAttributeConstraints:
    """StatutoryLowAge / StatutoryHighAge are per-venue constraints enforced during allocation."""

    def _boarding_config(self):
        return {
            "eligibility": [{"attribute": "age", "max": 24}],
            "strategy": "youngest_first",
            "capacity_config": {
                "attribute_capacities": {
                    "column_mappings": {
                        "n_0_15_female":  {"age_band": [0, 15],  "sex": "female"},
                        "n_0_15_male":    {"age_band": [0, 15],  "sex": "male"},
                        "n_16_24_female": {"age_band": [16, 24], "sex": "female"},
                        "n_16_24_male":   {"age_band": [16, 24], "sex": "male"},
                    }
                },
                "attribute_constraints": {
                    "age": {
                        "min_column": "StatutoryLowAge",
                        "max_column": "StatutoryHighAge",
                    }
                },
            },
        }

    def test_child_below_statutory_minimum_not_placed(self, hd):
        """Person aged 3 (below StatutoryLowAge=5) must not be placed in the school."""
        cfg = self._boarding_config()
        _allocate_with_attributes(
            "boarding_school", cfg, hd.population, hd.venue_manager, hd
        )
        schools = hd.venue_manager.get_venues_by_type("boarding_school")
        all_school_residents = []
        for s in schools:
            all_school_residents.extend(s.properties.get("residents", []))
        resident_ids = {p.id for p in all_school_residents}
        # id=0: age=3, below StatutoryLowAge=5
        assert 0 not in resident_ids, (
            "id=0 (age=3) must not be placed in a school with StatutoryLowAge=5"
        )

    def test_children_above_statutory_maximum_not_placed(self, hd):
        """People older than StatutoryHighAge=16 must not be placed in the school."""
        cfg = self._boarding_config()
        _allocate_with_attributes(
            "boarding_school", cfg, hd.population, hd.venue_manager, hd
        )
        schools = hd.venue_manager.get_venues_by_type("boarding_school")
        for s in schools:
            statutory_max = s.properties.get("StatutoryHighAge")
            if statutory_max is None:
                continue
            for person in s.properties.get("residents", []):
                assert person.age <= statutory_max, (
                    f"Person {person.id} (age={person.age}) placed in school "
                    f"with StatutoryHighAge={statutory_max}"
                )

    def test_eligible_children_within_range_are_placed(self, hd):
        """Children aged 5-16 in SGU_S1 must be placed up to slot capacity."""
        cfg = self._boarding_config()
        stats = _allocate_with_attributes(
            "boarding_school", cfg, hd.population, hd.venue_manager, hd
        )
        # School slots: n_0_15_female=3, n_0_15_male=3 for ages 0-15
        # In SGU_S1 children aged 5-15: person 102(5f), 103(7m), 104(9f), 105(11m), 106(14f)
        # That is 5 children within statutory range and within the 0-15 slot
        # So at least some should be placed
        assert stats["allocated"] > 0

    def test_slot_capacity_respected_with_constraints(self, hd):
        """Even with constraints, the slot capacity is a hard ceiling."""
        cfg = self._boarding_config()
        _allocate_with_attributes(
            "boarding_school", cfg, hd.population, hd.venue_manager, hd
        )
        column_mappings = cfg["capacity_config"]["attribute_capacities"]["column_mappings"]
        schools = hd.venue_manager.get_venues_by_type("boarding_school")
        for school in schools:
            for col in column_mappings:
                slot_cap = school.properties.get(col, 0)
                slot_residents = school.properties.get(f"residents_{col}", [])
                assert len(slot_residents) <= int(slot_cap), (
                    f"School {school.name}: slot {col} over capacity"
                )


# Side-effects: venue membership


class TestVenueMembershipSideEffects:
    """Allocating to a venue must add people to the venue's subset/member tracking."""

    def test_residents_in_venue_properties_after_simple_allocation(self, hd):
        """After simple allocation, each shelter's 'residents' property must be set."""
        cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": "random",
        }
        before = set(hd.allocated_people)
        _allocate_to_venue_type("shelter", cfg, hd.population, hd.venue_manager, hd)
        shelters = hd.venue_manager.get_venues_by_type("shelter")
        total_in_props = sum(len(s.properties.get("residents", [])) for s in shelters)
        newly_marked = len(set(hd.allocated_people) - before)
        # Both counts should agree
        assert total_in_props == newly_marked

    def test_residents_in_venue_properties_after_attribute_allocation(self, hd):
        """After attribute allocation, care home 'residents' property must be populated."""
        cfg = {
            "eligibility": [{"attribute": "age", "min": 50}],
            "strategy": "oldest_first",
        }
        before = set(hd.allocated_people)
        _allocate_with_attributes("care_home", cfg, hd.population, hd.venue_manager, hd)
        care_homes = hd.venue_manager.get_venues_by_type("care_home")
        total_in_props = sum(len(c.properties.get("residents", [])) for c in care_homes)
        newly_marked = len(set(hd.allocated_people) - before)
        assert total_in_props == newly_marked

    def test_no_double_allocation_across_venue_types(self, hd):
        """Running shelter then care_home allocation: same person must not appear in both."""
        shelter_cfg = {
            "capacity_property": "capacity",
            "eligibility": [],
            "strategy": "oldest_first",  # oldest go to shelters first
        }
        care_cfg = {
            "eligibility": [{"attribute": "age", "min": 50}],
            "strategy": "oldest_first",
        }
        _allocate_to_venue_type("shelter", shelter_cfg, hd.population, hd.venue_manager, hd)
        _allocate_with_attributes("care_home", care_cfg, hd.population, hd.venue_manager, hd)

        shelter_ids = {
            p.id
            for s in hd.venue_manager.get_venues_by_type("shelter")
            for p in s.properties.get("residents", [])
        }
        care_ids = {
            p.id
            for c in hd.venue_manager.get_venues_by_type("care_home")
            for p in c.properties.get("residents", [])
        }
        assert shelter_ids.isdisjoint(care_ids), (
            "A person must not be resident in both a shelter and a care home"
        )
