"""
local_social_network, spatial_social_network, bounded_distance builders.

local_social_network is tested end-to-end (no coordinates needed).
spatial_social_network and bounded_distance require geo coordinates and are
tested only for registration; their underlying algorithms are covered
by the create_networks tests.
"""
import pytest

from may.social_networks import SocialNetworkBuilder
from may.social_networks import social_networks


@pytest.mark.parametrize("network_type", [
    "activity_peers",
    "intra_geo_unit",
    "local_social_network",
    "spatial_social_network",
    "bounded_distance",
])
def test_builtin_network_type_dispatch(monkeypatch, network_type):
    called = []
    builder_name = {
        "activity_peers": "build_activity_peers",
        "intra_geo_unit": "build_intra_geo_unit",
        "local_social_network": "build_local_social_network",
        "spatial_social_network": "build_spatial_social_network",
        "bounded_distance": "build_bounded_distance",
    }[network_type]
    monkeypatch.setattr(
        social_networks,
        builder_name,
        lambda world, config: called.append(config["network_type"]),
    )
    pool_type = "activity" if network_type == "activity_peers" else "geographic"
    config = {
        "networks": [{
            "network_type": network_type,
            "pool_type": pool_type,
            "pool": {},
            "mean_count": 1,
            "storage_key": "contacts",
        }]
    }
    SocialNetworkBuilder(None, config).build_all()
    assert called == [network_type]


# local_social_network end-to-end

def _local_config(storage_key="contacts_local", mean_count=2):
    return {
        "networks": [{
            "name": "local",
            "network_type": "local_social_network",
            "pool_type": "geographic",
            "pool": {"level": "SGU"},
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
