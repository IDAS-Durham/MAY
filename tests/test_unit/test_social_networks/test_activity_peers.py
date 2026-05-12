"""Phase 6: activity_peers builder end-to-end."""
import pytest

from may.social_networks import SocialNetworkBuilder


def _config(storage_key="work_contacts", mean_count=3, activity="primary_activity"):
    return {
        "networks": [{
            "name": "work",
            "network_type": "activity_peers",
            "pool_type": "activity",
            "pool": {"activity": activity},
            "algorithm": "random",
            "mean_count": mean_count,
            "storage_key": storage_key,
        }]
    }


def test_activity_peers_populates_properties(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    total = sum(
        len(p.properties.get("work_contacts", []))
        for p in toy_world.population.people
    )
    assert total > 0


def test_activity_peers_no_self_connections(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    for person in toy_world.population.people:
        ids = [c.id for c in person.properties["work_contacts"]]
        assert person.id not in ids


def test_activity_peers_connects_same_venue(toy_world):
    SocialNetworkBuilder(toy_world, _config()).build_all()
    people = toy_world.population.people

    def venue_ids(person):
        result = set()
        for subsets in person.activity_map.get("primary_activity", {}).values():
            for s in subsets:
                result.add(s.venue.id)
        return result

    for person in toy_world.population.people:
        if not person.activity_map.get("primary_activity"):
            continue
        person_venues = venue_ids(person)
        for contact in person.properties["work_contacts"]:
            assert venue_ids(contact) & person_venues


def test_activity_peers_excludes_person_without_activity(toy_world):
    # person 5 has no primary_activity — should have no work contacts
    SocialNetworkBuilder(toy_world, _config()).build_all()
    person_5 = toy_world.population.people[5]
    assert person_5.properties["work_contacts"] == set()


def test_activity_peers_no_duplicates(toy_world):
    SocialNetworkBuilder(toy_world, _config(mean_count=10)).build_all()
    for person in toy_world.population.people:
        ids = [c.id for c in person.properties["work_contacts"]]
        assert len(ids) == len(set(ids))
