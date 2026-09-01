"""Unit tests for the capacity_proportional allocation strategy.

Drives the real VenueAllocation.allocate_by_geo_unit through a minimal stub
distributor (mirrors the minimal-real-objects style of
test_venue_child_creator.py). The bug this fixes: a person stream sorted by age
then sex was packed into venues sequentially, so each venue held one contiguous
age/sex cohort. capacity_proportional must instead let composition emerge -
every venue mirrors the catchment's age/sex mix, totals reconcile, and no venue
overflows.
"""

import numpy as np
import pytest

from may.venue_distributor._allocation import (
    VenueAllocation,
    _multinomial_capacity_draw,
)


# Minimal real objects covering just the interface allocate_by_geo_unit touches.

class Geo:
    def __init__(self, name, level="SGU", coordinates=(21.0, -102.0)):
        self.name = name
        self.level = level
        self.coordinates = coordinates

    def get_ancestor_by_level(self, level):
        return self if level == self.level else None


class Venue:
    def __init__(self, name, geo, capacity):
        self.id = id(self)
        self.name = name
        self.type = "school"
        self.geographical_unit = geo
        self.properties = {"capacity": capacity}
        self.subsets = {}

    def add_to_subset(self, person, subset_key=None, activity_name=None, activity_type=None):
        self.subsets.setdefault(subset_key, []).append(person)

    def members(self):
        return [p for members in self.subsets.values() for p in members]


class Person:
    _next = 0

    def __init__(self, age, sex):
        self.age = age
        self.sex = sex
        self.id = Person._next
        Person._next += 1


class Matcher:
    """Every venue serves every person in this SGU (single school level)."""

    def filter_venues_by_person(self, person, pool, person_attrs=None):
        return list(pool)


class StubDistributor:
    def __init__(self, geo, config):
        self.config = config
        self.verbose = False
        self.world = None
        self.batch_geo_level = "SGU"
        self.venue_geo_level = "SGU"
        self.subset_key = "student"
        self.activity_map_key = "primary_activity"
        self.activity_type = "school"
        self.matcher = Matcher()
        self.allocated_this_run = 0
        self._geo = geo
        self.venue_capacity_tracker = {}

    def _get_geo_unit_at_level(self, person, world, target_level=None):
        return self._geo

    def _require_venue_geo_level(self):
        return "SGU"

    def _get_person_attribute(self, name, person):
        return getattr(person, name)

    def _increment_venue_count(self, venue):
        self.venue_capacity_tracker[id(venue)] = self.venue_capacity_tracker.get(id(venue), 0) + 1

    def _get_venue_capacity(self, venue):
        return venue.properties["capacity"]

    def _get_remaining_capacity(self, venue):
        used = self.venue_capacity_tracker.get(id(venue), 0)
        return max(0, venue.properties["capacity"] - used)


def make_engine(venues, geo):
    config = {
        "eligibility": {"attributes": [{"name": "age"}]},
        "allocation": {"strategy": "capacity_proportional"},
        "venue_selection": {"consider_by": "geo_unit", "respect_capacity": True},
    }
    return VenueAllocation(StubDistributor(geo, config)), config


def sorted_cohort(ages, per_age):
    """Age-sorted, sex-sorted-within-age, the stream shape that triggered the bug."""
    people = []
    for age in ages:
        people += [Person(age, "male") for _ in range(per_age)]
        people += [Person(age, "female") for _ in range(per_age)]
    return people


# _multinomial_capacity_draw

class TestMultinomialDraw:

    def setup_method(self):
        np.random.seed(0)

    def test_places_all_when_capacity_suffices(self):
        placed, residual = _multinomial_capacity_draw(np.array([100, 100, 100]), 90)
        assert residual == 0
        assert placed.sum() == 90
        assert (placed <= 100).all()

    def test_no_venue_exceeds_remaining_capacity(self):
        remaining = np.array([10, 5, 3])
        placed, residual = _multinomial_capacity_draw(remaining, 20)
        assert (placed <= remaining).all()
        assert placed.sum() == 18          # total capacity
        assert residual == 2               # genuine shortfall, reported not relaxed

    def test_exact_fill(self):
        remaining = np.array([4, 6])
        placed, residual = _multinomial_capacity_draw(remaining, 10)
        assert residual == 0
        assert placed.tolist() == [4, 6]

    def test_all_full_returns_everyone_as_residual(self):
        placed, residual = _multinomial_capacity_draw(np.array([0, 0]), 5)
        assert placed.sum() == 0
        assert residual == 5

    def test_weighting_favours_larger_capacity(self):
        # 900-seat venue should attract ~9x the 100-seat venue over many people.
        placed, residual = _multinomial_capacity_draw(np.array([900, 100]), 500)
        assert residual == 0
        assert placed[0] > placed[1] * 4


# allocate_by_geo_unit end to end

class TestCapacityProportionalAllocation:

    def setup_method(self):
        np.random.seed(1)
        Person._next = 0

    def test_composition_mirrors_pool_not_mono_cohort(self):
        geo = Geo("MX01001")
        # Two roomy venues, one cohort spanning several ages and both sexes.
        venues = [Venue("A", geo, 400), Venue("B", geo, 400)]
        engine, _ = make_engine(venues, geo)
        people = sorted_cohort(ages=[15, 16, 17], per_age=50)  # 300 people, 6 blocks

        unallocated = engine.allocate_by_geo_unit(people, venues)

        assert unallocated == []
        for v in venues:
            members = v.members()
            assert len(members) > 0
            ages = {p.age for p in members}
            sexes = {p.sex for p in members}
            # Emergent mix: not a single age, not a single sex.
            assert ages == {15, 16, 17}, f"{v.name} ages={ages}"
            assert sexes == {"male", "female"}, f"{v.name} sexes={sexes}"

    def test_totals_reconcile_and_no_overflow(self):
        geo = Geo("MX01001")
        # Capacity (60+40=100) below demand (150): 50 must go unallocated.
        venues = [Venue("A", geo, 60), Venue("B", geo, 40)]
        engine, _ = make_engine(venues, geo)
        people = sorted_cohort(ages=[15, 16, 17], per_age=25)  # 150 people

        unallocated = engine.allocate_by_geo_unit(people, venues)

        placed = sum(len(v.members()) for v in venues)
        assert placed + len(unallocated) == len(people)   # reconciles
        assert placed == 100                              # every seat filled
        assert len(unallocated) == 50                     # loud shortfall
        for v in venues:
            assert len(v.members()) <= v.properties["capacity"]  # never over
