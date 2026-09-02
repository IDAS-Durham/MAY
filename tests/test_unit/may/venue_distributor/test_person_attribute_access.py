"""
Person attributes named by config are read through `get_attribute`.

`Person` has `__slots__` and no `__getattr__`, and every assigned attribute lands in
`person.properties`. A `getattr(person, name, None)` therefore returns None for anything
an attribute step assigned, so a gate written that way excludes everybody while the run
reports success. Three sites read a config-supplied name and had drifted off the canonical
resolver: the distributor's `required_person_attributes` gate, the residence allocator's
`value_by_attribute` variation, and the venue matcher's per-person prefetch.
"""
import pytest
import yaml
from types import SimpleNamespace

from may.population.person import Person
from may.residence.venue_allocator import _get_eligible_people
from may.venue_distributor.base_distributor import BaseDistributor
from may.venue_distributor.venue_distributor import VenueDistributor


def _person(age=30, sex="m", **properties):
    p = Person(age=age, sex=sex)
    p.properties.update(properties)
    return p


class _Population:
    def __init__(self, people):
        self._people = people

    def get_all_people(self):
        return self._people


class _HouseholdDistributor:
    allocated_people = frozenset()


class _World:
    def __init__(self, people):
        self.people = people


# --- required_person_attributes -------------------------------------------------


def _distributor(required):
    return VenueDistributor(config_dict={
        "venue_type": "company",
        "activity_map_key": "primary_activity",
        "validation": {"required_person_attributes": required},
    })


def test_assigned_attribute_satisfies_the_gate():
    """The regression: work_sector lives in properties, not in a slot."""
    d = _distributor(["work_sector"])
    assert d._has_required_attributes(_person(work_sector="G"), ["work_sector"])


def test_slot_attribute_still_satisfies_the_gate():
    """The five shipped uses name age / sex / geographical_unit, which are real slots."""
    d = _distributor(["age", "sex"])
    assert d._has_required_attributes(_person(), ["age", "sex"])


def test_absent_attribute_fails_the_gate():
    d = _distributor(["work_sector"])
    assert not d._has_required_attributes(_person(), ["work_sector"])


def test_dotted_path_resolves():
    d = _distributor(["properties.work_sector"])
    assert d._has_required_attributes(_person(work_sector="G"), ["properties.work_sector"])


def test_gate_selects_people_through_the_real_eligibility_path():
    """`_get_unassigned_people` is where the gate is actually applied."""
    d = _distributor(["work_sector"])
    has, has_not = _person(work_sector="G"), _person()
    for p in (has, has_not):
        p.activity_map = {}

    assert d._get_unassigned_people(_World([has, has_not])) == [has]


# --- value_by_attribute ---------------------------------------------------------


def test_value_by_attribute_reads_an_assigned_attribute():
    """
    The variation attribute picks which value of the main attribute qualifies. Read
    through getattr it resolved to None, `values.get(None)` was None, and the criterion
    became a no-op that admitted everyone.
    """
    criteria = [{
        "attribute": "age",
        "value_by_attribute": {
            "attribute": "care_band",
            "values": {"high": 80, "low": 70},
        },
    }]
    matches = _person(age=80, care_band="high")
    mismatches = _person(age=70, care_band="high")

    eligible = _get_eligible_people(
        _Population([matches, mismatches]), _HouseholdDistributor(), criteria
    )

    assert eligible == [matches]


# --- the matcher's per-person prefetch ------------------------------------------


@pytest.mark.parametrize("rel", [
    "configs/2021/distributors/company_distributor.yaml",
    "configs/2021/distributors/school_distributor.yaml",
])
def test_venue_filtering_without_prefetched_attributes(rel):
    """
    `allocate_individual` calls this with no prefetched attributes. The prefetch loop it
    used to hit keyed on `rule['attribute']`, while every shipped `eligibility.attributes`
    entry names its person attribute in `name`, so the call raised KeyError before it
    could resolve anything. Resolution now happens in `_get_person_attr`, which reads
    through the canonical accessor.
    """
    d = VenueDistributor(config_dict=yaml.safe_load(open(rel)))

    assert d.allocation.filter_venues_by_person(
        _person(work_sector="G"), [], person_attrs=None
    ) == []


def test_person_location_uses_configured_source():
    home = SimpleNamespace(coordinates=(1.0, 2.0))
    workplace = SimpleNamespace(coordinates=(3.0, 4.0))
    person = _person(geographical_unit=home, workplace_mgu="WORK")
    distributor = BaseDistributor(config_dict={
        "venue_selection": {"locate_person_by": "properties.workplace_mgu"},
    })
    distributor.world = SimpleNamespace(
        geography=SimpleNamespace(
            get_unit=lambda name: workplace if name == "WORK" else None
        )
    )

    assert distributor._get_person_location(person) == (3.0, 4.0)
    person.properties.pop("workplace_mgu")
    assert distributor._get_person_location(person) is None
