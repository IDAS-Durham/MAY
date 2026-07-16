"""Bounded candidate sampling for large per-geo-unit pools.

Sampling is opt-in via selection_strategy.candidate_sample_size in the
relationship rules file. Without the key, role preparation returns the whole
pool (the UK case, and the historical behavior); with it, pools larger than
the cap are sampled uniformly (the Mexico case, where a municipio pool holds
hundreds of thousands of people and full materialization per role per
household made builds take hours).
"""
import numpy as np
from dataclasses import dataclass, field

from may.residence.household_distributor import HouseholdDistributor


@dataclass
class MockPerson:
    id: int
    age: int = 30
    sex: str = 'female'
    properties: dict = field(default_factory=dict)


class MockRules:
    def __init__(self, cap):
        self.selection_strategy = {'candidate_sample_size': cap} if cap else {}


def bare_distributor(cap=None):
    d = object.__new__(HouseholdDistributor)
    d._sample_lists = {}
    d._warned_large_pool = False
    d.relationship_rules = MockRules(cap)
    return d


def make_pools(n_per_cat, n_cats=2):
    return [{i + cat * n_per_cat: MockPerson(i + cat * n_per_cat)
             for i in range(n_per_cat)} for cat in range(n_cats)]


def test_no_cap_returns_whole_pool():
    d = bare_distributor(cap=None)
    pools = make_pools(5000)
    out = d._prepare_role_candidates(pools, [0, 1], 0, 0, set(), False, False, False,
                                     geo_unit_code='G1')
    assert len(out) == 10000


def test_small_pool_returned_whole_under_cap():
    d = bare_distributor(cap=200)
    pools = make_pools(50)
    out = d._prepare_role_candidates(pools, [0, 1], 0, 0, set(), False, False, False,
                                     geo_unit_code='G1')
    assert len(out) == 100


def test_large_pool_sampled_to_cap():
    d = bare_distributor(cap=200)
    pools = make_pools(5000)
    out = d._prepare_role_candidates(pools, [0, 1], 0, 0, set(), False, False, False,
                                     geo_unit_code='G1')
    assert len(out) <= 200
    assert len(out) >= 180  # proportional quotas can round slightly under cap
    ids = [p.id for p in out]
    assert len(ids) == len(set(ids))  # no duplicates
    alive = set(pools[0]) | set(pools[1])
    assert all(i in alive for i in ids)


def test_sampling_skips_removed_people():
    np.random.seed(7)
    d = bare_distributor(cap=500)
    pools = make_pools(5000, n_cats=1)
    d._sample_candidates('G1', pools, [0], 500)  # builds the companion list
    for pid in list(pools[0])[:4500]:  # allocate away 90% of the pool
        del pools[0][pid]
    out = d._sample_candidates('G1', pools, [0], 500)
    assert len(out) == 500
    assert all(p.id in pools[0] for p in out)


def test_large_pool_without_cap_warns_once(caplog):
    d = bare_distributor(cap=None)
    pools = make_pools(6000)
    with caplog.at_level('WARNING', logger='household'):
        d._prepare_role_candidates(pools, [0, 1], 0, 0, set(), False, False, False,
                                   geo_unit_code='G1')
        d._prepare_role_candidates(pools, [0, 1], 0, 0, set(), False, False, False,
                                   geo_unit_code='G1')
    hits = [r for r in caplog.records if 'candidate_sample_size' in r.message]
    assert len(hits) == 1
