"""
Two networks, different storage keys, built in one pipeline call.
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
    people = toy_world.population.people
    # All people are in an SGU — contacts_local always present.
    # Person 5 has no primary_activity — contacts_work key is absent for them.
    for person in people:
        assert "contacts_local" in person.properties
    for person in people[:5]:
        assert "contacts_work" in person.properties
    assert "contacts_work" not in people[5].properties


def test_both_networks_have_connections(toy_world):
    SocialNetworkBuilder(toy_world, _two_network_config()).build_all()
    local_total = sum(
        len(p.properties["contacts_local"]) for p in toy_world.population.people
    )
    work_total = sum(
        len(p.properties.get("contacts_work", set())) for p in toy_world.population.people
    )
    assert local_total > 0
    assert work_total > 0


def test_ordering_respected_first_network_built_first(toy_world):
    """Each network keeps its own storage key when built in sequence."""
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
    people = toy_world.population.people
    for person in people:
        assert "key_a" in person.properties
        assert "key_b" in person.properties
    # key_c: persons with primary_activity only; person 5 has none
    for person in people[:5]:
        assert "key_c" in person.properties
    assert "key_c" not in people[5].properties
