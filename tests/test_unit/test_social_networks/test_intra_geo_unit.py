"""
Phase 5 tracer bullet: intra_geo_unit end-to-end through the full pipeline.
YAML → pool → build → store.
"""
import pytest

from may.social_networks import SocialNetworkBuilder


def _config(storage_key="contacts_local", mean_count=3, level="SGU"):
    return {
        "networks": [{
            "name": "local",
            "network_type": "intra_geo_unit",
            "pool_type": "geographic",
            "pool": {"level": level},
            "algorithm": "random",
            "mean_count": mean_count,
            "storage_key": storage_key,
        }]
    }


def test_intra_geo_unit_populates_person_properties(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    total = sum(
        len(p.properties.get("contacts_local", []))
        for p in toy_world.population.people
    )
    assert total > 0


def test_intra_geo_unit_returns_person_objects(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    for person in toy_world.population.people:
        for contact in person.properties["contacts_local"]:
            assert hasattr(contact, "id")
            assert hasattr(contact, "geographical_unit")


def test_intra_geo_unit_no_self_connections(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    for person in toy_world.population.people:
        contact_ids = [c.id for c in person.properties["contacts_local"]]
        assert person.id not in contact_ids


def test_intra_geo_unit_connections_within_same_sgu(toy_world):
    SocialNetworkBuilder(toy_world, _config(level="SGU")).build_all()
    for person in toy_world.population.people:
        for contact in person.properties["contacts_local"]:
            assert contact.geographical_unit is person.geographical_unit


def test_intra_geo_unit_mgu_crosses_sgus(toy_world):
    SocialNetworkBuilder(toy_world, _config(level="MGU", storage_key="contacts_mgu")).build_all()
    people = toy_world.population.people
    # With all 6 people in one MGU pool, cross-SGU connections are possible
    cross_sgu = sum(
        1 for p in people
        for c in p.properties.get("contacts_mgu", [])
        if c.geographical_unit is not p.geographical_unit
    )
    assert cross_sgu > 0


def test_intra_geo_unit_no_duplicates_in_contacts(toy_world):
    SocialNetworkBuilder(toy_world, _config(mean_count=10)).build_all()
    for person in toy_world.population.people:
        contacts = person.properties["contacts_local"]
        ids = [c.id for c in contacts]
        assert len(ids) == len(set(ids))
