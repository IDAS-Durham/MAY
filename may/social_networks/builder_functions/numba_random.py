"""
Numba-accelerated random connection builder for intra-group social networks.

Implements the intra_geo_unit and activity_peers network types.
"""

import numpy as np
import numba as nb

from ..filters import build_pool
from ..constraints import parse_constraints


# ============================================================================
# NUMBA KERNELS
# ============================================================================

@nb.njit(cache=True)
def _process_group_numba(group_people, group_ages, group_subsets,
                         all_connections, current_counts, target_counts,
                         weight_fraction, age_range, require_same_subset,
                         check_duplicates):
    """
    Process a single group (venue or geo unit) with Numba acceleration.

    Args:
        group_people: Array of person IDs in this group
        group_ages: Array of ages for people in this group
        group_subsets: Array of subset indices for people in this group
        all_connections: Output array (n_people, max_connections)
        current_counts: Current connection count per person
        target_counts: Target connection count per person
        weight_fraction: Fraction of connections from this source
        age_range: Max age difference allowed (-1 for no filter)
        require_same_subset: Whether to require same subset
        check_duplicates: Whether to check for duplicate connections
    """
    n_group = len(group_people)
    if n_group < 2:
        return

    max_conn = all_connections.shape[1]

    for local_idx in range(n_group):
        person_id = group_people[local_idx]
        target = target_counts[person_id]
        current = current_counts[person_id]

        n_needed = int(round(target * weight_fraction))
        if n_needed <= 0 or current >= target:
            continue

        n_to_add = min(n_needed, target - current)

        person_age = group_ages[local_idx]
        person_subset = group_subsets[local_idx]

        candidates = np.empty(n_group, dtype=np.int32)
        n_candidates = 0

        for j in range(n_group):
            if j == local_idx:
                continue

            cand_id = group_people[j]

            if age_range >= 0:
                if abs(group_ages[j] - person_age) > age_range:
                    continue

            if require_same_subset:
                if group_subsets[j] != person_subset:
                    continue

            if check_duplicates:
                is_dup = False
                for k in range(current):
                    if all_connections[person_id, k] == cand_id:
                        is_dup = True
                        break
                if is_dup:
                    continue

            candidates[n_candidates] = j
            n_candidates += 1

        if n_candidates == 0:
            continue

        n_sample = min(n_to_add, n_candidates)

        for i in range(n_sample):
            rand_idx = i + int(np.random.random() * (n_candidates - i))
            candidates[i], candidates[rand_idx] = candidates[rand_idx], candidates[i]

        for i in range(n_sample):
            if current_counts[person_id] >= target_counts[person_id]:
                break
            if current_counts[person_id] >= max_conn:
                break

            conn_id = group_people[candidates[i]]
            idx = current_counts[person_id]
            all_connections[person_id, idx] = conn_id
            current_counts[person_id] += 1


@nb.njit(parallel=True, cache=True)
def _process_all_groups_numba(group_starts, group_ends, group_people_flat,
                               ages, subsets, all_connections, current_counts,
                               target_counts, weight_fraction, age_range,
                               require_same_subset, check_duplicates):
    """
    Process all groups in parallel using Numba.

    Args:
        group_starts: Start index of each group in group_people_flat
        group_ends: End index of each group in group_people_flat
        group_people_flat: Flattened array of all person IDs by group
        ages: Ages array for all people
        subsets: Subset indices for all people
        all_connections: Output array
        current_counts: Current counts
        target_counts: Target counts
        weight_fraction: Weight fraction
        age_range: Age range filter
        require_same_subset: Subset filter flag
        check_duplicates: Duplicate check flag
    """
    n_groups = len(group_starts)

    for g in nb.prange(n_groups):
        start = group_starts[g]
        end = group_ends[g]

        if end <= start + 1:
            continue

        group_people = group_people_flat[start:end]
        n_group = len(group_people)

        group_ages = np.empty(n_group, dtype=np.int32)
        group_subsets = np.empty(n_group, dtype=np.int32)

        for i in range(n_group):
            pid = group_people[i]
            group_ages[i] = ages[pid]
            group_subsets[i] = subsets[pid]

        _process_group_numba(
            group_people, group_ages, group_subsets,
            all_connections, current_counts, target_counts,
            weight_fraction, age_range, require_same_subset,
            check_duplicates
        )


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


def _extract_age_range(connection_filters: list) -> np.int32:
    """Extract age max_difference from parsed ConnectionFilters (-1 = no filter)."""
    for cf in connection_filters:
        if cf.attribute == "age" and cf.match == "range":
            return np.int32(cf.range)
    return np.int32(-1)


def _run_random_numba(world, groups: list, mean_count: int,
                      connection_filters: list | None = None) -> dict:
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

    age_range = _extract_age_range(connection_filters or [])

    _process_all_groups_numba(
        starts, ends, people_flat,
        ages, subsets,
        all_connections, current_counts, connection_counts,
        np.float64(1.0), age_range, False, True,
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
# BUILDER IMPLEMENTATIONS
# ============================================================================

def build_intra_geo_unit(world, network_config: dict) -> dict:
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
    connection_filters = parse_constraints(network_config.get("constraints", []))
    return _run_random_numba(world, groups, mean_count, connection_filters)


def build_activity_peers(world, network_config: dict) -> dict:
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
    connection_filters = parse_constraints(network_config.get("constraints", []))
    return _run_random_numba(world, groups, mean_count, connection_filters)
