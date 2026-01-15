"""
Utility functions for romantic relationship distribution.

Provides shared helpers for:
- Progress logging
- Geography-based grouping and candidate selection
"""

import logging
from collections import defaultdict
from typing import Dict, List, Tuple

logger = logging.getLogger("romantic_relationships")


class ProgressLogger:
    """
    Context manager for logging progress through a collection.

    Usage:
        with ProgressLogger(items, "Processing items") as progress:
            for idx, item in enumerate(items):
                progress.update(idx)
                # do work...
    """

    def __init__(self, total: int, description: str, log_interval_pct: int = 10):
        """
        Initialize progress logger.

        Args:
            total: Total number of items to process
            description: Description for log messages
            log_interval_pct: Percentage interval for progress logs (default 10%)
        """
        self.total = total
        self.description = description
        self.interval = max(1, total // (100 // log_interval_pct))
        self.extra_stats = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def update(self, idx: int, **stats):
        """
        Update progress and log if at interval.

        Args:
            idx: Current index (0-based)
            **stats: Additional stats to include in log message
        """
        self.extra_stats.update(stats)

        if idx > 0 and idx % self.interval == 0:
            pct = (idx / self.total) * 100
            msg = f"    Progress: {idx:,} / {self.total:,} ({pct:.1f}%)"

            for key, value in self.extra_stats.items():
                if isinstance(value, int):
                    msg += f", {key}: {value:,}"
                else:
                    msg += f", {key}: {value}"

            logger.info(msg)


def group_by_geography(people: List) -> Tuple[Dict[str, List], Dict[str, List]]:
    """
    Group people by their M.G.U and L.G.U for efficient geographical matching.

    Args:
        people: List of people to group

    Returns:
        Tuple of (by_mgu dict, by_lgu dict) where each maps unit name to list of people
    """
    by_mgu = defaultdict(list)
    by_lgu = defaultdict(list)

    for person in people:
        if not person.geographical_unit:
            continue

        # Get M.G.U (parent of S.G.U)
        mgu = person.geographical_unit.parent if person.geographical_unit.parent else person.geographical_unit
        if mgu:
            by_mgu[mgu.name].append(person)

            # Get L.G.U (parent of M.G.U)
            lgu = mgu.parent if mgu.parent else mgu
            if lgu:
                by_lgu[lgu.name].append(person)

    return dict(by_mgu), dict(by_lgu)


def get_candidates_by_geography_tier(
    person,
    all_seekers: List,
    seekers_by_mgu: Dict[str, List],
    seekers_by_lgu: Dict[str, List]
) -> List:
    """
    Get candidate pool using tiered geographical search.

    Returns candidates from the closest geographical tier available:
    1. Same M.G.U (highest priority)
    2. Same L.G.U (fallback)
    3. All seekers (final fallback)

    Args:
        person: Person seeking a partner
        all_seekers: All people seeking partners (fallback)
        seekers_by_mgu: Dict mapping M.G.U name -> list of seekers
        seekers_by_lgu: Dict mapping L.G.U name -> list of seekers

    Returns:
        List of candidate partners from appropriate geographical tier
    """
    unit = person.geographical_unit
    if not unit:
        return all_seekers

    mgu = unit.parent if unit.parent else unit
    lgu = mgu.parent if mgu and mgu.parent else mgu

    # Tier 1: Same M.G.U
    if mgu and mgu.name in seekers_by_mgu:
        return seekers_by_mgu[mgu.name]

    # Tier 2: Same L.G.U
    if lgu and lgu.name in seekers_by_lgu:
        return seekers_by_lgu[lgu.name]

    # Tier 3: All available
    return all_seekers


def build_residence_cache(adults: List) -> Dict[int, int]:
    """
    Build a cache mapping person ID to residence ID.

    This avoids expensive person.residence property calls during matching.

    Args:
        adults: List of adult persons

    Returns:
        Dict mapping person.id to residence.id
    """
    cache = {}
    for person in adults:
        residence = person.residence
        if residence:
            cache[person.id] = residence.id
    return cache


def build_person_index(people: List) -> Dict[int, any]:
    """
    Build an index mapping person ID to person object for O(1) lookups.

    Args:
        people: List of person objects

    Returns:
        Dict mapping person.id to person object
    """
    return {p.id: p for p in people}
