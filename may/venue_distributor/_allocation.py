"""Unified private venue allocation implementation."""

import numpy as np
from typing import Tuple

__all__ = "FALLBACK_STRATEGIES", "SPECIAL_CASE_STRATEGIES", "SELECT_VENUE_STRATEGIES"


def _multinomial_capacity_draw(remaining: np.ndarray, n: int) -> Tuple[np.ndarray, int]:
    """Place n people across venues, weighted by remaining capacity.

    One multinomial draw per round, O(venues) and independent of n. Any venue drawn
    over its remaining capacity is capped and the excess re-drawn over the
    still-open venues; repeats until placed or every venue is full. Returns the
    per-venue placed counts and the residual that did not fit: the caller reports
    it as unallocated, capacity is never relaxed.
    """
    placed = np.zeros(len(remaining), dtype=np.int64)
    caps = remaining.astype(np.int64).copy()
    to_place = n
    while to_place > 0:
        idx = np.where(caps > 0)[0]
        if idx.size == 0:
            break
        cap_available = int(caps[idx].sum())
        if to_place >= cap_available:
            # Demand exceeds every open seat: fill them all, the rest is residual.
            placed[idx] += caps[idx]
            caps[idx] = 0
            to_place -= cap_available
            break
        draw = np.random.multinomial(to_place, caps[idx] / cap_available)
        take = np.minimum(draw, caps[idx])
        placed[idx] += take
        caps[idx] -= take
        to_place -= int(take.sum())
    return placed, to_place


from ._filtering import _FilteringMixin
from ._fallbacks import FALLBACK_STRATEGIES, _FallbackMixin
from ._special_cases import SPECIAL_CASE_STRATEGIES, _SpecialCasesMixin
from ._matching import SELECT_VENUE_STRATEGIES, _MatchingMixin
from ._strategies import _AllocationMixin
from ._reporting import _ReportingMixin
from may.utils.attribute_access import get_attribute


class VenueAllocation(
    _FilteringMixin,
    _FallbackMixin,
    _SpecialCasesMixin,
    _MatchingMixin,
    _AllocationMixin,
    _ReportingMixin,
):
    """Single internal owner for venue allocation state and behavior."""

    def __init__(self, owner):
        self.owner = owner
        self.config = owner.config
        self.verbose = owner.verbose
        self.venue_attribute_cache = {}
        self.categorical_index = {}
        self.num_constraints = {}
        self.numerical_match_rules = []
        self.categorical_match_rules = []
        self.attribute_index_built = False
        self.venue_id_to_idx = {}
        eligibility = self.config.get("eligibility", {})
        self.attribute_names = [
            r.get("name") for r in eligibility.get("attributes", [])
        ]
        self.attr_getters = [
            lambda p, attr=name: get_attribute(p, attr)
            for name in self.attribute_names
            if name
        ]
