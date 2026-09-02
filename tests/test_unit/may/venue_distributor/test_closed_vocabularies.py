"""
Config keys that select behaviour from a fixed set of strings reject anything outside it.

Each of these dispatched on string literals and ended in a bare else, so a misspelled
value was carried out as an instruction: the default distributor, the first venue in the
pool, a criterion that compared nothing, a step that never ran. None raised, and every one
of them produced a build that reported success having done the wrong thing or nothing.
"""
import pytest
import yaml

from may.population.person import Person
from may.venue_distributor import DISTRIBUTOR_TYPES, distributor_from_yaml
from may.venue_distributor._allocation import (
    FALLBACK_STRATEGIES, SELECT_VENUE_STRATEGIES, SPECIAL_CASE_STRATEGIES,
)
from may.venue_distributor.venue_distributor import VenueDistributor


class _Venue:
    def __init__(self, name, coordinates=None, capacity=10):
        self.name = name
        self.coordinates = coordinates
        self.properties = {"capacity": capacity}


def _write(tmp_path, config):
    path = tmp_path / "distributor.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


# --- #8: distributor_type ---------------------------------------------------------


def test_unknown_distributor_type_raises(tmp_path):
    path = _write(tmp_path, {"distributor_type": "multivenue", "venue_type": "company"})

    with pytest.raises(ValueError, match="Unknown distributor_type 'multivenue'"):
        distributor_from_yaml(str(path))


def test_error_lists_every_dispatched_type(tmp_path):
    """Six, counting the `single_venue` default that reaching deliberately is fine."""
    path = _write(tmp_path, {"distributor_type": "nonesuch", "venue_type": "company"})

    with pytest.raises(ValueError) as excinfo:
        distributor_from_yaml(str(path))

    assert len(DISTRIBUTOR_TYPES) == 6
    for name in DISTRIBUTOR_TYPES:
        assert name in str(excinfo.value)


def test_absent_distributor_type_still_means_single_venue(tmp_path):
    path = _write(tmp_path, {"venue_type": "company"})

    assert type(distributor_from_yaml(str(path))) is VenueDistributor


# --- #12: allocation.strategy -----------------------------------------------------


def _selector(strategy):
    d = VenueDistributor(config_dict={
        "venue_type": "company",
        "allocation": {"strategy": strategy},
    })
    return d.allocation


def test_unknown_allocation_strategy_raises():
    venues = [_Venue("A", (0.0, 0.0)), _Venue("B", (1.0, 1.0))]

    with pytest.raises(ValueError, match="is not available on this allocation path"):
        _selector("clsest").select_venue(Person(age=30, sex="m"), venues, (0.0, 0.0))


def test_capacity_proportional_is_rejected_here_by_name():
    """
    It is a per-cohort batch draw. Falling through to venues[0] put
    everyone in the first venue of the pool; the message says where it does work.
    """
    venues = [_Venue("A", (0.0, 0.0)), _Venue("B", (1.0, 1.0))]

    with pytest.raises(ValueError, match="capacity_proportional"):
        _selector("capacity_proportional").select_venue(
            Person(age=30, sex="m"), venues, (0.0, 0.0)
        )

    assert "capacity_proportional" not in SELECT_VENUE_STRATEGIES


@pytest.mark.parametrize("strategy", ["closest", "proportional"])
def test_distance_strategy_without_coordinates_raises(strategy):
    """Silently becoming "first venue" is the same defect as the terminal fallthrough."""
    venues = [_Venue("A"), _Venue("B")]

    with pytest.raises(ValueError, match="needs venue coordinates"):
        _selector(strategy).select_venue(Person(age=30, sex="m"), venues, (0.0, 0.0))


def test_known_strategy_still_selects():
    near, far = _Venue("near", (0.0, 0.0)), _Venue("far", (50.0, 50.0))

    chosen = _selector("closest").select_venue(
        Person(age=30, sex="m"), [far, near], (0.0, 0.0)
    )

    assert chosen is near


# --- #14: special-case allocation rules -------------------------------------------


def _special_case(rule):
    d = VenueDistributor(config_dict={
        "venue_type": "company",
        "special_cases": {"enabled": True, "cases": [{"name": "c", "allocation_rule": rule}]},
    })
    return d.allocation


def test_unknown_special_case_strategy_raises():
    case = {"name": "c", "allocation_rule": {"strategy": "nearest"}}

    with pytest.raises(ValueError, match="Unknown special-case allocation strategy"):
        _special_case(case["allocation_rule"]).allocate_special_case(
            Person(age=30, sex="m"), case, []
        )

    assert SPECIAL_CASE_STRATEGIES == {"closest", "random"}


def test_setting_both_strategy_and_match_by_raises():
    """The if/elif chain read one and dropped the other without a word."""
    rule = {
        "strategy": "closest",
        "match_by": [{"source": "person.employer", "target": "venue.name"}],
    }
    case = {"name": "c", "allocation_rule": rule}

    with pytest.raises(ValueError, match="sets both"):
        _special_case(rule).allocate_special_case(Person(age=30, sex="m"), case, [])


def test_unknown_match_type_raises():
    """
    Guarding the comparison on `match_type == 'exact'` meant any other value compared
    nothing, so every venue satisfied the criterion and the person went to the first.
    """
    rule = {"match_by": [{
        "source": "person.employer", "target": "venue.name", "match_type": "fuzzy",
    }]}
    case = {"name": "c", "allocation_rule": rule}
    person = Person(age=30, sex="m")
    person.properties["employer"] = "HQ"

    with pytest.raises(ValueError, match="Unknown match_by match_type 'fuzzy'"):
        _special_case(rule).allocate_special_case(person, case, [_Venue("Branch")])


def test_exact_match_still_matches_and_rejects():
    rule = {"match_by": [{"source": "person.employer", "target": "venue.name"}]}
    case = {"name": "c", "allocation_rule": rule}
    person = Person(age=30, sex="m")
    person.properties["employer"] = "HQ"
    manager = _special_case(rule)

    assert manager._venue_matches_criteria(person, _Venue("HQ"), rule["match_by"])
    assert not manager._venue_matches_criteria(person, _Venue("Branch"), rule["match_by"])


# --- #23: fallback.strategy -------------------------------------------------------


def test_unknown_fallback_strategy_raises():
    d = VenueDistributor(config_dict={
        "venue_type": "company",
        "fallback": {"strategy": "relax_evrything"},
    })

    with pytest.raises(ValueError, match="Unknown fallback.strategy"):
        d.allocation.handle_fallbacks([Person(age=30, sex="m")], [], world=None)


def test_skip_is_still_a_no_op():
    d = VenueDistributor(config_dict={
        "venue_type": "company",
        "fallback": {"strategy": "skip"},
    })
    people = [Person(age=30, sex="m")]

    assert d.allocation.handle_fallbacks(people, [], world=None) == people
    assert "skip" in FALLBACK_STRATEGIES
