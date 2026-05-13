"""
Phase 8: local_social_network, spatial_social_network, bounded_distance builders.

local_social_network is tested end-to-end (no coordinates needed).
spatial_social_network and bounded_distance require geo coordinates —
tested only for registration; their underlying algorithms are covered
by existing create_networks tests.
"""
import pytest

from may.social_networks import network_type_builders, SocialNetworkBuilder


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_local_social_network_registered():
    assert "local_social_network" in network_type_builders


def test_spatial_social_network_registered():
    assert "spatial_social_network" in network_type_builders


def test_bounded_distance_registered():
    assert "bounded_distance" in network_type_builders


# ---------------------------------------------------------------------------
# local_social_network end-to-end
# ---------------------------------------------------------------------------

def _local_config(storage_key="contacts_local", mean_count=2):
    return {
        "networks": [{
            "name": "local",
            "network_type": "local_social_network",
            "pool_type": "geographic",
            "pool": {"level": "SGU"},
            "algorithm": "watts_strogatz",
            "mean_count": mean_count,
            "storage_key": storage_key,
        }]
    }


def test_local_social_network_populates_properties(toy_world_local_net):
    SocialNetworkBuilder(toy_world_local_net, _local_config()).build_all()
    total = sum(
        len(p.properties.get("contacts_local", []))
        for p in toy_world_local_net.population.people
    )
    assert total > 0


def test_local_social_network_key_written_for_every_person(toy_world_local_net):
    SocialNetworkBuilder(toy_world_local_net, _local_config()).build_all()
    for person in toy_world_local_net.population.people:
        assert "contacts_local" in person.properties


def test_local_social_network_no_self_connections(toy_world_local_net):
    SocialNetworkBuilder(toy_world_local_net, _local_config()).build_all()
    for person in toy_world_local_net.population.people:
        ids = [c.id for c in person.properties["contacts_local"]]
        assert person.id not in ids


def test_local_social_network_contacts_are_person_objects(toy_world_local_net):
    SocialNetworkBuilder(toy_world_local_net, _local_config()).build_all()
    for person in toy_world_local_net.population.people:
        for contact in person.properties["contacts_local"]:
            assert hasattr(contact, "id")
            assert hasattr(contact, "age")


def test_local_social_network_custom_storage_key(toy_world_local_net):
    SocialNetworkBuilder(toy_world_local_net, _local_config(storage_key="my_key")).build_all()
    for person in toy_world_local_net.population.people:
        assert "my_key" in person.properties
        assert "contacts_local" not in person.properties
