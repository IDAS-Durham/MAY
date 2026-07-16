"""Structure mixture (docs/adr/0030): interpretation quotas over a pattern's
census count, loaded from a per-geo-unit shares CSV. Opt-in via the strategy's
`mixture:` block; strategies without it are untouched.
"""
import pytest
from dataclasses import dataclass, field
from typing import Optional

from may.residence.allocation_strategy import (
    _setup_structure_mixture, _resolve_pattern_selectors)
from may.residence.household_distributor import HouseholdDistributor, HouseholdError


@dataclass
class Unit:
    name: str
    level: str
    parent: Optional['Unit'] = None


@dataclass
class MockGeo:
    levels: tuple = ('SGU', 'MGU')
    units: dict = field(default_factory=dict)

    def get_unit(self, name):
        return self.units[name]


def bare_distributor():
    d = object.__new__(HouseholdDistributor)
    mgu = Unit('MX01', 'MGU')
    d.geography = MockGeo(units={'MX01001': Unit('MX01001', 'SGU', mgu), 'MX01': mgu})
    d.structure_mixture = None
    d._mixture_quota_cache = {}
    return d


MIX = {('MX01', '0 1 1 0'): {'couple': 0.236, 'parent_child': 0.682, 'other': 0.082}}


def test_quota_split_sums_exactly_and_is_deterministic():
    d = bare_distributor()
    d.structure_mixture = {'geo_level': 'MGU', 'shares': MIX}
    quotas = {i: d._mixture_quota('MX01001', '0 1 1 0', i, 100)
              for i in ('couple', 'parent_child', 'other')}
    assert sum(quotas.values()) == 100
    assert quotas == {'couple': 24, 'parent_child': 68, 'other': 8}
    # cached: same answer again
    assert d._mixture_quota('MX01001', '0 1 1 0', 'couple', 100) == 24


def test_quota_missing_geo_row_fails_loud():
    d = bare_distributor()
    d.structure_mixture = {'geo_level': 'MGU', 'shares': {}}
    with pytest.raises(HouseholdError, match='No mixture shares'):
        d._mixture_quota('MX01001', '0 1 1 0', 'couple', 10)


def write_mixture(tmp_path, rows):
    p = tmp_path / 'mix.csv'
    p.write_text('geo_unit,pattern,interpretation,share\n'
                 + '\n'.join(','.join(map(str, r)) for r in rows) + '\n')
    return str(p)


def steps_for(path_steps):
    return [dict(s, type='household') for s in path_steps]


def test_setup_validates_and_stores(tmp_path):
    d = bare_distributor()
    f = write_mixture(tmp_path, [('MX01', '0 1 1 0', 'couple', 0.24),
                                 ('MX01', '0 1 1 0', 'other', 0.76)])
    steps = steps_for([
        {'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
        {'name': 'o', 'patterns': ['0 1 1 0'], 'interpretation': 'other'},
    ])
    _setup_structure_mixture({'file': f, 'geo_level': 'MGU'}, steps, d)
    assert d.structure_mixture['geo_level'] == 'MGU'


def test_interpretation_without_mixture_block_fails(tmp_path):
    d = bare_distributor()
    steps = steps_for([{'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'}])
    with pytest.raises(HouseholdError, match="no\\s+'mixture:' block"):
        _setup_structure_mixture(None, steps, d)


def test_unclaimed_interpretation_fails(tmp_path):
    d = bare_distributor()
    f = write_mixture(tmp_path, [('MX01', '0 1 1 0', 'couple', 0.24),
                                 ('MX01', '0 1 1 0', 'other', 0.76)])
    steps = steps_for([{'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'}])
    with pytest.raises(HouseholdError, match='unclaimed interpretation'):
        _setup_structure_mixture({'file': f, 'geo_level': 'MGU'}, steps, d)


def test_shares_not_summing_fails(tmp_path):
    d = bare_distributor()
    f = write_mixture(tmp_path, [('MX01', '0 1 1 0', 'couple', 0.5),
                                 ('MX01', '0 1 1 0', 'other', 0.3)])
    steps = steps_for([{'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
                       {'name': 'o', 'patterns': ['0 1 1 0'], 'interpretation': 'other'}])
    with pytest.raises(HouseholdError, match='sum to'):
        _setup_structure_mixture({'file': f, 'geo_level': 'MGU'}, steps, d)


# claims: interpretation steps may share a pattern; plain + interpretation may not

@dataclass
class Cat:
    name: str


CATS = [Cat('Kids'), Cat('Young Adults'), Cat('Adults'), Cat('Old Adults')]
VOCAB = {'0 1 1 0', '0 0 2 0'}


def test_two_interpretations_of_one_pattern_coexist():
    steps = steps_for([
        {'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
        {'name': 'o', 'patterns': ['0 1 1 0'], 'interpretation': 'other'},
    ])
    _resolve_pattern_selectors(steps, VOCAB, CATS)  # must not raise


def test_plain_claim_conflicts_with_interpretation_claim():
    steps = steps_for([
        {'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
        {'name': 'whole', 'patterns': ['0 1 1 0']},
    ])
    with pytest.raises(HouseholdError, match='claimed by both'):
        _resolve_pattern_selectors(steps, VOCAB, CATS)


def test_same_interpretation_twice_conflicts():
    steps = steps_for([
        {'name': 'a', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
        {'name': 'b', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
    ])
    with pytest.raises(HouseholdError, match='claimed by both'):
        _resolve_pattern_selectors(steps, VOCAB, CATS)


def test_null_remainder_excludes_interpretation_managed_patterns():
    steps = steps_for([
        {'name': 'c', 'patterns': ['0 1 1 0'], 'interpretation': 'couple'},
        {'name': 'rest', 'patterns': None},
    ])
    _resolve_pattern_selectors(steps, VOCAB, CATS)
    assert steps[1]['patterns'] == ['0 0 2 0']
