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
from may.social_networks.constraints import parse_constraints
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
    connection_filters = parse_constraints(network_config.get("constraints", []))
    return _run_random_numba(world, groups, mean_count, connection_filters)


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
    connection_filters = parse_constraints(network_config.get("constraints", []))
    return _run_random_numba(world, groups, mean_count, connection_filters)


# ============================================================================
# CREATE_NETWORKS BUILDERS  (wrap create_networks.py spatial/W-S functions)
# ============================================================================

_TEMP_KEY = "__network_builder_tmp__"


def _collect_and_pop(world, key: str) -> dict:
    """Read results stored by a create_networks function, then remove the key."""
    results = {}
    for person in world.population.people:
        results[person.id] = person.properties.pop(key, [])
    return results


@register_network_type("local_social_network")
def _build_local_social_network_registered(world, network_config: dict) -> dict:
    """
    Watts-Strogatz social network within the smallest geo units.

    Required network_config keys:
        mean_count       – mean connections per person
    Optional:
        clustering_level – rewiring probability (default 0.8)
    """
    from may.social_networks.create_networks import _build_local_social_network

    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.8)

    _build_local_social_network(
        world.geography,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        storage_key=_TEMP_KEY,
        store=True,
    )
    return _collect_and_pop(world, _TEMP_KEY)


@register_network_type("spatial_social_network")
def _build_spatial_social_network_registered(world, network_config: dict) -> dict:
    """
    Spatial Watts-Strogatz between geo units in an annulus.

    Required network_config keys:
        mean_count   – mean connections per person
        pool.min_km  – inner radius (km)
        pool.max_km  – outer radius (km)
    Optional:
        clustering_level  – rewiring probability (default 0.9)
        pool.level        – geo unit level (defaults to smallest)
    """
    from may.social_networks.create_networks import _build_spatial_social_network

    pool_config = network_config.get("pool", {})
    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.9)
    min_km = pool_config.get("min_km", 0.0)
    max_km = pool_config.get("max_km", 10.0)
    geo_unit_level = pool_config.get("level", None)

    _build_spatial_social_network(
        world.geography,
        min_radius_km=min_km,
        max_radius_km=max_km,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=_TEMP_KEY,
        store=True,
    )
    return _collect_and_pop(world, _TEMP_KEY)


@register_network_type("bounded_distance")
def _build_bounded_distance_registered(world, network_config: dict) -> dict:
    """
    Random contacts within a geographic radius.

    Required network_config keys:
        mean_count   – mean connections per person
        pool.max_km  – search radius (km)
    Optional:
        clustering_level  – clustering coefficient (default 0.7)
        pool.level        – geo unit level (defaults to smallest)
    """
    from may.social_networks.create_networks import _build_bounded_distance_social_network

    pool_config = network_config.get("pool", {})
    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.7)
    max_km = pool_config.get("max_km", 5.0)
    geo_unit_level = pool_config.get("level", None)

    _build_bounded_distance_social_network(
        world.geography,
        radius_km=max_km,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=_TEMP_KEY,
        store=True,
    )
    return _collect_and_pop(world, _TEMP_KEY)
