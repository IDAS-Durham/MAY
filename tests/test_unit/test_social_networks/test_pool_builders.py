import pytest

from may.social_networks.builder_functions.filters_and_constraints.filters import build_pool


# geographic pool

def test_geographic_pool_sgu_returns_two_groups(toy_world):
    groups = build_pool(toy_world, pool_type="geographic", pool_config={"level": "SGU"})
    assert len(groups) == 2


def test_geographic_pool_sgu_groups_share_same_unit(toy_world):
    groups = build_pool(toy_world, pool_type="geographic", pool_config={"level": "SGU"})
    for group in groups:
        geo_units = {p.geographical_unit for p in group}
        assert len(geo_units) == 1


def test_geographic_pool_sgu_correct_sizes(toy_world):
    groups = build_pool(toy_world, pool_type="geographic", pool_config={"level": "SGU"})
    sizes = sorted(len(g) for g in groups)
    assert sizes == [3, 3]


def test_geographic_pool_mgu_returns_one_group(toy_world):
    groups = build_pool(toy_world, pool_type="geographic", pool_config={"level": "MGU"})
    assert len(groups) == 1
    assert len(groups[0]) == 6


def test_geographic_pool_mgu_contains_all_people(toy_world):
    groups = build_pool(toy_world, pool_type="geographic", pool_config={"level": "MGU"})
    all_ids = {p.id for g in groups for p in g}
    assert all_ids == {0, 1, 2, 3, 4, 5}


def test_geographic_pool_unknown_level_raises(toy_world):
    with pytest.raises(ValueError, match="level"):
        build_pool(toy_world, pool_type="geographic", pool_config={"level": "XLGU"})


# activity pool

def test_activity_pool_returns_two_groups(toy_world):
    groups = build_pool(toy_world, pool_type="activity",
                        pool_config={"activity": "primary_activity"})
    assert len(groups) == 2


def test_activity_pool_groups_share_same_venue(toy_world):
    groups = build_pool(toy_world, pool_type="activity",
                        pool_config={"activity": "primary_activity"})
    for group in groups:
        venue_ids = set()
        for person in group:
            for venue_type, subsets in person.activity_map["primary_activity"].items():
                for s in subsets:
                    venue_ids.add(s.venue.id)
        assert len(venue_ids) == 1


def test_activity_pool_people_without_activity_excluded(toy_world):
    groups = build_pool(toy_world, pool_type="activity",
                        pool_config={"activity": "primary_activity"})
    all_ids = {p.id for g in groups for p in g}
    assert 5 not in all_ids  # person 5 has no primary_activity


def test_activity_pool_correct_sizes(toy_world):
    groups = build_pool(toy_world, pool_type="activity",
                        pool_config={"activity": "primary_activity"})
    sizes = sorted(len(g) for g in groups)
    assert sizes == [2, 3]  # school: 3, office: 2
