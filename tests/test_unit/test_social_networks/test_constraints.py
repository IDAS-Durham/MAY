"""
Phase 9: constraints — typed edge constraints enforced during network building.

Toy world ages:
  SGU_1: p0=10, p1=10, p2=60
  SGU_2: p3=12, p4=30, p5=31

With max_difference=5 on age:
  p0↔p1 allowed  (|10-10|=0)
  p0↔p2 blocked  (|10-60|=50)
  p4↔p5 allowed  (|30-31|=1)
  p3↔p4 blocked  (|12-30|=18)
"""
import pytest

from may.social_networks import SocialNetworkBuilder
from may.social_networks.builder_functions.filters_and_constraints.constraints import parse_constraints
from may.social_networks.builder_functions.filters_and_constraints.filters import ConnectionFilter


def _config_with_age_constraint(max_diff, network_type="intra_geo_unit",
                                 pool_type="geographic", pool=None, storage_key="contacts"):
    return {
        "networks": [{
            "name": "test",
            "network_type": network_type,
            "pool_type": pool_type,
            "pool": pool or {"level": "SGU"},
            "algorithm": "random",
            "mean_count": 5,
            "storage_key": storage_key,
            "constraints": [{
                "type": "numerical_attribute_difference",
                "attribute": "age",
                "max_difference": max_diff,
            }],
        }]
    }


# ---------------------------------------------------------------------------
# parse_constraints
# ---------------------------------------------------------------------------

def test_parse_constraints_numerical_attribute_difference():
    constraints = [{"type": "numerical_attribute_difference", "attribute": "age", "max_difference": 10}]
    result = parse_constraints(constraints)
    assert len(result) == 1
    assert isinstance(result[0], ConnectionFilter)
    assert result[0].attribute == "age"
    assert result[0].match == "range"
    assert result[0].range == 10


def test_parse_constraints_empty_list():
    assert parse_constraints([]) == []


def test_parse_constraints_unknown_type_raises():
    with pytest.raises(ValueError, match="constraint type"):
        parse_constraints([{"type": "unknown_type", "attribute": "age"}])


# ---------------------------------------------------------------------------
# intra_geo_unit with age constraint
# ---------------------------------------------------------------------------

def test_age_constraint_enforced_intra_geo_unit(toy_world):
    SocialNetworkBuilder(toy_world, _config_with_age_constraint(max_diff=5)).build_all()
    for person in toy_world.population.people:
        for contact in person.properties.get("contacts", set()):
            assert abs(person.age - contact.age) <= 5


def test_age_constraint_blocks_large_age_gap(toy_world):
    # p2 (age 60) must not appear in p0's (age 10) contacts with max_diff=5
    SocialNetworkBuilder(toy_world, _config_with_age_constraint(max_diff=5)).build_all()
    people = toy_world.population.people
    p0_contact_ids = {c.id for c in people[0].properties["contacts"]}
    assert people[2].id not in p0_contact_ids


def test_loose_age_constraint_allows_connections(toy_world):
    # With max_diff=60 everyone can connect to everyone in their SGU
    SocialNetworkBuilder(toy_world, _config_with_age_constraint(max_diff=60)).build_all()
    total = sum(len(p.properties["contacts"]) for p in toy_world.population.people)
    assert total > 0


def test_no_constraint_same_as_no_age_filter(toy_world):
    # Without constraints, p2 (age 60) may appear in p0's contacts
    config = {
        "networks": [{
            "name": "test", "network_type": "intra_geo_unit",
            "pool_type": "geographic", "pool": {"level": "SGU"},
            "algorithm": "random", "mean_count": 5, "storage_key": "contacts",
        }]
    }
    SocialNetworkBuilder(toy_world, config).build_all()
    people = toy_world.population.people
    # p0 and p2 are in the same SGU with no age filter — connection is possible
    # (stochastic, but with mean_count=5 and only 2 others, very likely)
    p0_contact_ids = {c.id for c in people[0].properties["contacts"]}
    assert people[2].id in p0_contact_ids


# ---------------------------------------------------------------------------
# activity_peers with age constraint
# ---------------------------------------------------------------------------

def test_age_constraint_enforced_activity_peers(toy_world):
    config = _config_with_age_constraint(
        max_diff=5,
        network_type="activity_peers",
        pool_type="activity",
        pool={"activity": "primary_activity"},
        storage_key="work_contacts",
    )
    SocialNetworkBuilder(toy_world, config).build_all()
    for person in toy_world.population.people:
        for contact in person.properties.get("work_contacts", set()):
            assert abs(person.age - contact.age) <= 5
