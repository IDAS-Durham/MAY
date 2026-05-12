"""
Tests for SocialNetworkBuilder storage logic:
  - connections written to correct storage_key
  - deduplication within a single key
  - duplicates allowed across different keys
"""
import pytest

from may.social_networks import (
    SocialNetworkBuilder,
    register_network_type,
    register_pool_type,
)
from may.social_networks.builder_functions.store import store_contacts


# ---------------------------------------------------------------------------
# Stub builders registered once for this module
# ---------------------------------------------------------------------------

@register_pool_type("_storage_test_pool")
def _stub_pool(world, config):
    return [world.population.people]


@register_network_type("_connects_first_two")
def _connects_first_two(world, network_config):
    """Person 0 ↔ Person 1 only."""
    people = world.population.people
    if len(people) < 2:
        return
    p0, p1 = people[0], people[1]
    storage_key = network_config["storage_key"]
    store_contacts(p0, [p1], storage_key)
    store_contacts(p1, [p0], storage_key)


@register_network_type("_connects_all_to_first")
def _connects_all_to_first(world, network_config):
    """Everyone connected to person 0 (with an intentional duplicate for person 1)."""
    people = world.population.people
    p0 = people[0]
    storage_key = network_config["storage_key"]
    for person in people[1:]:
        store_contacts(person, [p0, p0], storage_key)  # deliberate duplicate


@register_network_type("_empty_network")
def _empty_network(world, network_config):
    pass


def _make_config(*entries):
    return {"networks": list(entries)}


def _entry(network_type, storage_key, pool_type="_storage_test_pool"):
    return {
        "name": storage_key,
        "network_type": network_type,
        "pool_type": pool_type,
        "pool": {},
        "mean_count": 2,
        "storage_key": storage_key,
    }


# ---------------------------------------------------------------------------
# Basic storage
# ---------------------------------------------------------------------------

def test_storage_key_written_to_person_properties(toy_world):
    SocialNetworkBuilder(toy_world, _make_config(
        _entry("_connects_first_two", "test_contacts")
    )).build_all()

    people = toy_world.population.people
    # Only persons 0 and 1 are connected; absent key = no connections
    assert "test_contacts" in people[0].properties
    assert "test_contacts" in people[1].properties


def test_connected_persons_appear_in_properties(toy_world):
    SocialNetworkBuilder(toy_world, _make_config(
        _entry("_connects_first_two", "test_contacts")
    )).build_all()

    people = toy_world.population.people
    p0_contacts = people[0].properties["test_contacts"]
    p1_contacts = people[1].properties["test_contacts"]

    assert people[1] in p0_contacts
    assert people[0] in p1_contacts


# ---------------------------------------------------------------------------
# Deduplication within a single key
# ---------------------------------------------------------------------------

def test_no_duplicates_within_single_key(toy_world):
    SocialNetworkBuilder(toy_world, _make_config(
        _entry("_connects_all_to_first", "dedup_key")
    )).build_all()

    people = toy_world.population.people
    for person in people[1:]:
        contacts = person.properties["dedup_key"]
        contact_ids = [c.id for c in contacts]
        assert len(contact_ids) == len(set(contact_ids))


# ---------------------------------------------------------------------------
# Duplicates allowed across different keys
# ---------------------------------------------------------------------------

def test_same_person_can_appear_in_two_different_keys(toy_world):
    SocialNetworkBuilder(toy_world, _make_config(
        _entry("_connects_first_two", "key_a"),
        _entry("_connects_first_two", "key_b"),
    )).build_all()

    people = toy_world.population.people
    # person 1 should appear in both key_a and key_b contacts of person 0
    assert people[1] in people[0].properties["key_a"]
    assert people[1] in people[0].properties["key_b"]


def test_two_keys_are_independent(toy_world):
    SocialNetworkBuilder(toy_world, _make_config(
        _entry("_connects_first_two", "key_a"),
        _entry("_empty_network", "key_b"),
    )).build_all()

    people = toy_world.population.people
    # key_a has connections; key_b (empty network) leaves no key at all
    assert len(people[0].properties["key_a"]) > 0
    assert "key_b" not in people[0].properties


# ---------------------------------------------------------------------------
# Shared storage key — multiple networks appended into one set
# ---------------------------------------------------------------------------

@register_network_type("_connects_second_and_third")
def _connects_second_and_third(world, network_config):
    """Person 0 ↔ Person 2, Person 1 ↔ Person 3."""
    people = world.population.people
    if len(people) < 4:
        return
    storage_key = network_config["storage_key"]
    store_contacts(people[0], [people[2]], storage_key)
    store_contacts(people[2], [people[0]], storage_key)
    store_contacts(people[1], [people[3]], storage_key)
    store_contacts(people[3], [people[1]], storage_key)


def test_two_networks_same_key_accumulate(toy_world):
    """Two networks writing to the same key — contacts accumulate into one set."""
    config = _make_config(
        _entry("_connects_first_two", "shared_key"),
        _entry("_connects_second_and_third", "shared_key"),
    )
    SocialNetworkBuilder(toy_world, config).build_all()

    people = toy_world.population.people
    # p0 gains p1 from first network, p2 from second network
    p0_contacts = people[0].properties["shared_key"]
    assert people[1] in p0_contacts
    assert people[2] in p0_contacts


def test_two_networks_same_key_no_duplicates(toy_world):
    """Shared key: same contact added by both networks appears only once."""
    config = _make_config(
        _entry("_connects_first_two", "shared_key"),
        _entry("_connects_first_two", "shared_key"),
    )
    SocialNetworkBuilder(toy_world, config).build_all()

    people = toy_world.population.people
    p0_contacts = people[0].properties["shared_key"]
    contact_ids = [c.id for c in p0_contacts]
    assert len(contact_ids) == len(set(contact_ids))
