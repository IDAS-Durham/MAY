"""
Algorithm-based social network source for FriendshipBuilder.

AlgorithmSourceProcessor owns all pool-filter and graph-build logic for
sources that carry an 'algorithm' key in the YAML. FriendshipBuilder
instantiates this and passes its CSR arrays; everything else happens here.
"""

import logging
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .filters import (
    PoolFilter,
    ConnectionFilter,
    parse_pool_filter,
    parse_connection_filter,
    apply_pool_filters,
)
from .graph_relationship_builder import GraphRelationshipBuilder

logger = logging.getLogger("algorithm_source")


# ============================================================================
# CONFIG DATACLASSES
# ============================================================================

@dataclass
class AlgorithmConfig:
    type: str                           # key in graph_creators registry, e.g. 'watts_strogatz'
    mean_connections_per_person: int
    clustering_level: float
    pre_sort_by: Optional[str]          # attribute path, e.g. 'age'
    max_rewire_attempts: int = 10


@dataclass
class AlgorithmSourceConfig:
    name: str
    pool_filters: list = field(default_factory=list)       # list[PoolFilter]
    connection_filters: list = field(default_factory=list) # list[ConnectionFilter]
    algorithm: Optional[AlgorithmConfig] = None
    symmetric: bool = True


# ============================================================================
# PARSING
# ============================================================================

def parse_algorithm_config(d: dict) -> AlgorithmConfig:
    return AlgorithmConfig(
        type=d.get('type', 'watts_strogatz'),
        mean_connections_per_person=int(d.get('mean_connections_per_person', 6)),
        clustering_level=float(d.get('clustering_level', 0.7)),
        pre_sort_by=d.get('pre_sort_by'),
        max_rewire_attempts=int(d.get('max_rewire_attempts', 10)),
    )


def parse_algorithm_source_config(source_dict: dict) -> AlgorithmSourceConfig:
    """Parse a YAML source dict that contains an 'algorithm' key."""
    pool_filters = [
        parse_pool_filter(pf) for pf in source_dict.get('pool_filters', [])
    ]
    connection_filters = [
        parse_connection_filter(cf) for cf in source_dict.get('connection_filters', [])
    ]
    algorithm = parse_algorithm_config(source_dict['algorithm'])
    return AlgorithmSourceConfig(
        name=source_dict.get('name', 'unnamed'),
        pool_filters=pool_filters,
        connection_filters=connection_filters,
        algorithm=algorithm,
        symmetric=source_dict.get('symmetric', True),
    )


def collect_pool_filters(sources: list) -> list:
    """
    Extract all PoolFilter objects from a list of raw source dicts.
    Used by FriendshipBuilder._build_arrays() to pre-compute attribute arrays.
    """
    filters = []
    for source in sources:
        if 'algorithm' not in source:
            continue
        for pf_dict in source.get('pool_filters', []):
            filters.append(parse_pool_filter(pf_dict))
    return filters


# ============================================================================
# PROCESSOR
# ============================================================================

class AlgorithmSourceProcessor:
    """
    Processes one algorithm source across a set of groups (geo units or venues).

    Instantiated by FriendshipBuilder with:
    - world: World object (for people lookup)
    - source_config: AlgorithmSourceConfig
    - attr_arrays: pre-computed from filters.build_attribute_arrays()

    Call run() with the CSR arrays for the relevant pool.
    """

    def __init__(self, world, source_config: AlgorithmSourceConfig, attr_arrays: dict):
        self.world = world
        self.config = source_config
        self.attr_arrays = attr_arrays

    def run(
        self,
        csr_starts: np.ndarray,
        csr_ends: np.ndarray,
        csr_people_flat: np.ndarray,
    ) -> dict:
        """
        Process all groups in the CSR structure.
        Returns dict[person.id -> list[person.id]].
        """
        results = defaultdict(list)
        algo = self.config.algorithm
        n_groups = len(csr_starts)
        skipped = 0

        logger.info(f"  Algorithm source '{self.config.name}': processing {n_groups} groups")

        for g in range(n_groups):
            positions = csr_people_flat[csr_starts[g]:csr_ends[g]].astype(np.int32)

            if self.config.pool_filters:
                positions = apply_pool_filters(
                    positions, self.config.pool_filters, self.attr_arrays
                )

            if len(positions) < 2:
                skipped += 1
                continue

            if algo.pre_sort_by and algo.pre_sort_by in self.attr_arrays:
                attr_arr, _ = self.attr_arrays[algo.pre_sort_by]
                order = np.argsort(attr_arr[positions])
                positions = positions[order]

            people_subset = [self.world.population.people[int(p)] for p in positions]

            builder = GraphRelationshipBuilder(
                people=people_subset,
                mean_connections_per_person=algo.mean_connections_per_person,
                clustering_level=algo.clustering_level,
                connection_filters=self.config.connection_filters,
                symmetric=self.config.symmetric,
                max_rewire_attempts=algo.max_rewire_attempts,
                algorithm=algo.type,
                store=False,
            )
            group_result = builder.build_all(store=False)
            for pid, conns in group_result.items():
                results[pid].extend(conns)

        if skipped:
            logger.debug(f"    Skipped {skipped}/{n_groups} groups (fewer than 2 people after filtering)")

        return dict(results)
