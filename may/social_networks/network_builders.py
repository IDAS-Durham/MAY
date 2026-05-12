"""
Registered network_type builders for SocialNetworkBuilder.

Each builder has the signature:
    (world, network_config: dict) -> dict[person_id, list[Person]]

network_config is the full YAML entry for this network, so each builder
reads its own required keys from it.

To add a new network_type:
    1. Write a function with the signature above.
    2. Decorate with @register_network_type("your_type_name").
    3. Document required network_config keys in the docstring.
    No other files need modification.

Phases:
    5-6: intra_geo_unit, activity_peers  (Numba random, wraps friendship_builder)
    8:   local_social_network, spatial_social_network, bounded_distance
         (Watts-Strogatz, wraps create_networks.py — added in Phase 8)
"""

import numpy as np
import logging

from may.social_networks.social_networks import register_network_type
from may.social_networks.filters import build_pool
from may.relationships.friendship_builder import _process_all_groups_numba

logger = logging.getLogger("network_builders")


# ============================================================================
# SHARED HELPERS
# ============================================================================

def _groups_to_csr(groups: list, person_id_to_idx: dict):
    """Convert list-of-person-groups to CSR index arrays for Numba."""
    n_groups = len(groups)
    total_size = sum(len(g) for g in groups)

    starts = np.zeros(n_groups, dtype=np.int32)
    ends = np.zeros(n_groups, dtype=np.int32)
    people_flat = np.zeros(total_size, dtype=np.int32)

    offset = 0
    for i, group in enumerate(groups):
        starts[i] = offset
        for person in group:
            people_flat[offset] = person_id_to_idx[person.id]
            offset += 1
        ends[i] = offset

    return starts, ends, people_flat


def _run_random_numba(world, groups: list, mean_count: int) -> dict:
    """
    Run the Numba random-connection builder over pre-built groups.
    Returns dict[person_id, list[Person]].
    """
    people = list(world.population.people)
    n_people = len(people)

    idx_to_person = {i: p for i, p in enumerate(people)}
    person_id_to_idx = {p.id: i for i, p in enumerate(people)}

    starts, ends, people_flat = _groups_to_csr(groups, person_id_to_idx)

    ages = np.array([p.age for p in people], dtype=np.int32)
    subsets = np.zeros(n_people, dtype=np.int32)

    connection_counts = np.full(n_people, min(mean_count, 127), dtype=np.int8)
    max_connections = int(connection_counts.max())

    all_connections = np.full((n_people, max_connections), -1, dtype=np.int32)
    current_counts = np.zeros(n_people, dtype=np.int8)

    _process_all_groups_numba(
        starts, ends, people_flat,
        ages, subsets,
        all_connections, current_counts, connection_counts,
        np.float64(1.0), np.int32(-1), False, True,
    )

    results = {}
    for i, person in enumerate(people):
        n_conn = int(current_counts[i])
        results[person.id] = [
            idx_to_person[int(idx)]
            for idx in all_connections[i, :n_conn]
            if idx >= 0
        ]
    return results


# ============================================================================
# NUMBA-BACKED BUILDERS (wrap friendship_builder Numba path)
# ============================================================================

@register_network_type("intra_geo_unit")
def _build_intra_geo_unit(world, network_config: dict) -> dict:
    """
    Random connections within geographic units at a specified level.

    Required network_config keys:
        pool_type   – must be "geographic"
        pool.level  – e.g. "SGU", "MGU"
        mean_count  – target mean connections per person
        algorithm   – "random" (only supported value)
    """
    pool_config = network_config.get("pool", {})
    pool_type = network_config["pool_type"]
    mean_count = network_config["mean_count"]

    groups = build_pool(world, pool_type, pool_config)
    return _run_random_numba(world, groups, mean_count)


@register_network_type("activity_peers")
def _build_activity_peers(world, network_config: dict) -> dict:
    """
    Random connections among people sharing an activity venue.

    Required network_config keys:
        pool_type        – must be "activity"
        pool.activity    – activity key in person.activity_map
        mean_count       – target mean connections per person
        algorithm        – "random" (only supported value)
    """
    pool_config = network_config.get("pool", {})
    pool_type = network_config["pool_type"]
    mean_count = network_config["mean_count"]

    groups = build_pool(world, pool_type, pool_config)
    return _run_random_numba(world, groups, mean_count)


# ============================================================================
# PHASE 8: local_social_network, spatial_social_network, bounded_distance
# (wrapping create_networks.py — added in Phase 8)
# ============================================================================
