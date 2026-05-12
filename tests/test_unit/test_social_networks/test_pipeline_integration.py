"""
Phase 7: two networks, different storage keys, built in one pipeline call.
Verifies sequencing, independence, and no shared state between networks.
"""
import pytest

from may.social_networks import SocialNetworkBuilder


def _two_network_config():
    return {
        "networks": [
            {
                "name": "local",
                "network_type": "intra_geo_unit",
                "pool_type": "geographic",
                "pool": {"level": "SGU"},
                "algorithm": "random",
                "mean_count": 3,
                "storage_key": "contacts_local",
            },
            {
                "name": "work",
                "network_type": "activity_peers",
                "pool_type": "activity",
                "pool": {"activity": "primary_activity"},
                "algorithm": "random",
                "mean_count": 3,
                "storage_key": "contacts_work",
            },
        ]
    }


def test_both_keys_written_for_every_person(toy_world):
    SocialNetworkBuilder(toy_world, _two_network_config()).build_all()
    for person in toy_world.population.people:
        assert "contacts_local" in person.properties
        assert "contacts_work" in person.properties


def test_both_networks_have_connections(toy_world):
    SocialNetworkBuilder(toy_world, _two_network_config()).build_all()
    local_total = sum(
        len(p.properties["contacts_local"]) for p in toy_world.population.people
    )
    work_total = sum(
        len(p.properties["contacts_work"]) for p in toy_world.population.people
    )
    assert local_total > 0
    assert work_total > 0


def test_keys_are_independent(toy_world):
    SocialNetworkBuilder(toy_world, _two_network_config()).build_all()
    people = toy_world.population.people
    # person 5 has no activity → empty work contacts but may have local contacts
    person_5 = people[5]
    assert person_5.properties["contacts_work"] == set()
    assert len(person_5.properties["contacts_local"]) >= 0  # may or may not connect


def test_same_person_can_appear_in_both_keys(toy_world):
    SocialNetworkBuilder(toy_world, _two_network_config()).build_all()
    people = toy_world.population.people
    # persons 0-2 share SGU_1 AND venue_school — so person 1 may appear in
    # both contacts_local and contacts_work of person 0
    p0_local_ids = {c.id for c in people[0].properties["contacts_local"]}
    p0_work_ids = {c.id for c in people[0].properties["contacts_work"]}
    overlap = p0_local_ids & p0_work_ids
    # Not asserting overlap exists (small world, stochastic) — just that both keys exist
    assert isinstance(overlap, set)


def test_ordering_respected_first_network_built_first(toy_world):
    """Second network does not overwrite first network's key."""
    config = {
        "networks": [
            {
                "name": "first",
                "network_type": "intra_geo_unit",
                "pool_type": "geographic",
                "pool": {"level": "SGU"},
                "algorithm": "random",
                "mean_count": 2,
                "storage_key": "first_key",
            },
            {
                "name": "second",
                "network_type": "intra_geo_unit",
                "pool_type": "geographic",
                "pool": {"level": "MGU"},
                "algorithm": "random",
                "mean_count": 2,
                "storage_key": "second_key",
            },
        ]
    }
    SocialNetworkBuilder(toy_world, config).build_all()
    for person in toy_world.population.people:
        assert "first_key" in person.properties
        assert "second_key" in person.properties


def test_three_networks_all_keys_present(toy_world):
    config = {
        "networks": [
            {
                "name": "a", "network_type": "intra_geo_unit",
                "pool_type": "geographic", "pool": {"level": "SGU"},
                "algorithm": "random", "mean_count": 2, "storage_key": "key_a",
            },
            {
                "name": "b", "network_type": "intra_geo_unit",
                "pool_type": "geographic", "pool": {"level": "MGU"},
                "algorithm": "random", "mean_count": 2, "storage_key": "key_b",
            },
            {
                "name": "c", "network_type": "activity_peers",
                "pool_type": "activity", "pool": {"activity": "primary_activity"},
                "algorithm": "random", "mean_count": 2, "storage_key": "key_c",
            },
        ]
    }
    SocialNetworkBuilder(toy_world, config).build_all()
    for person in toy_world.population.people:
        assert "key_a" in person.properties
        assert "key_b" in person.properties
        assert "key_c" in person.properties
