"""
Numba-accelerated kernels and Python driver functions for building
local and spatial Watts-Strogatz social networks.
"""

import logging
from typing import TYPE_CHECKING

from ..graph_relationship_builder import GraphRelationshipBuilder
from ..geo_neighbors import find_neighbours, _extract_coordinates, _km_to_degrees_adjusted, EARTH_RADIUS_KM

from debug_output import export_relationships

import random
import numpy as np
import numba as nb

if TYPE_CHECKING:
    from may.geography import Geography, GeographicalUnit
    from may.world import World
    from may.population import Person

logger = logging.getLogger("create networks")


# ============================================================================
# SHARED UTILITIES
# ============================================================================

def _build_people_csr(units):
    """
    Flatten people from a list of geo_units into a contiguous array with per-unit
    CSR (Compressed Sparse Row) indices.

    Args:
        units: list of GeographicalUnit objects.

    Returns:
        Tuple of:
            all_people      — flat list of Person objects across all units
            unit_starts     — (U,) int32 array: start index of each unit in all_people
            unit_ends       — (U,) int32 array: end index (exclusive) of each unit
            unit_people_flat — (N,) int32 array: global person indices [0..N-1]
            person_unit     — (N,) int32 array: unit index for each person

        Returns ([], None, None, None, None) if no people are found.
    """
    all_people = []
    counts = []
    for unit in units:
        people_in_unit = list(unit.get_people())
        all_people.extend(people_in_unit)
        counts.append(len(people_in_unit))

    if not all_people:
        return [], None, None, None, None

    counts_arr = np.array(counts, dtype=np.int32)
    unit_ends = np.cumsum(counts_arr, dtype=np.int32)
    unit_starts = (unit_ends - counts_arr).astype(np.int32)
    unit_people_flat = np.arange(len(all_people), dtype=np.int32)
    person_unit = np.repeat(np.arange(len(units), dtype=np.int32), counts_arr)
    return all_people, unit_starts, unit_ends, unit_people_flat, person_unit


def _store_contacts_from_matrix(all_people, all_connections, storage_key, assign_activity_map=False):
    """
    Symmetrise a directed (N, k) connection matrix and store contacts in person.properties.

    Extracts valid directed edges from all_connections (entries >= 0), removes
    self-loops, adds reciprocal edges, deduplicates, then assigns each person a list
    of Person objects. Optionally populates person.activity_map[storage_key] with
    contacts' residence venue mappings.

    Args:
        all_people:          flat list of Person objects (length N).
        all_connections:     (N, k) int32 array; -1 = empty slot.
        storage_key:         key for person.properties and optionally person.activity_map.
        assign_activity_map: if True, also populate person.activity_map[storage_key].
    """
    N = len(all_people)

    row_idx, col_idx = np.where(all_connections >= 0)
    src = row_idx.astype(np.int64)
    dst = all_connections[row_idx, col_idx].astype(np.int64)

    keep = src != dst
    src, dst = src[keep], dst[keep]
    all_src = np.concatenate([src, dst])
    all_dst = np.concatenate([dst, src])

    order = np.lexsort((all_dst, all_src))
    all_src = all_src[order]
    all_dst = all_dst[order]
    is_dup = (all_src[1:] == all_src[:-1]) & (all_dst[1:] == all_dst[:-1])
    unique_mask = np.concatenate([[True], ~is_dup])
    all_src = all_src[unique_mask]
    all_dst = all_dst[unique_mask]

    edge_counts = np.bincount(all_src.astype(np.intp), minlength=N)
    ends = np.cumsum(edge_counts, dtype=np.int64)
    starts = ends - edge_counts

    total_connections = 0
    for i, person in enumerate(all_people):
        contact_indices = all_dst[starts[i]:ends[i]]
        contacts = [all_people[int(j)] for j in contact_indices]
        person.properties[storage_key] = contacts
        total_connections += len(contacts)

        if assign_activity_map and contacts:
            person.activities.add(storage_key)
            activity_dict = {}
            for contact in contacts:
                if 'residence' in contact.activity_map:
                    activity_dict.update(contact.activity_map['residence'])
            person.activity_map[storage_key] = activity_dict

    avg_deg = total_connections / N if N > 0 else 0.0
    logger.info(f"Stored {storage_key!r}: {total_connections:,} connections, avg ~{avg_deg:.1f} per person")


# ============================================================================
# LOCAL WATTS-STROGATZ SOCIAL NETWORK — NUMBA-ACCELERATED
# ============================================================================

@nb.njit(parallel=True, cache=True)
def _local_ws_build_lattice(
    unit_starts,        # (U,) int32 — start index per geo_unit in the flat people array
    unit_ends,          # (U,) int32 — end index (exclusive)
    unit_people_flat,   # (N,) int32 — global person indices, contiguous per unit
    person_unit,        # (N,) int32 — geo_unit index for each person
    all_connections,    # (N, k) int32 — output; -1 = empty slot
    k,                  # int32 — target connections per person
):
    """
    Build an intra-SGU ring lattice: each person connects to their k nearest
    neighbours in circular order within their geo_unit.

    Slots alternate +/- offsets: slot 0 → +1, slot 1 → -1, slot 2 → +2, …
    k is capped per-unit at unit_size - 1 for small units.
    """
    n_people = len(person_unit)
    for i in nb.prange(n_people):
        g = person_unit[i]
        unit_size = unit_ends[g] - unit_starts[g]
        if unit_size < 2:
            continue
        local_i = i - unit_starts[g]
        effective_k = k if k < unit_size else unit_size - 1
        for slot in range(effective_k):
            offset = slot + 1           # +1, +2, +3, ... (forward-only)
            neighbor_local = (local_i + offset) % unit_size
            all_connections[i, slot] = unit_starts[g] + neighbor_local


@nb.njit(parallel=True, cache=True)
def _local_ws_rewire(
    unit_starts,        # (U,) int32
    unit_ends,          # (U,) int32
    unit_people_flat,   # (N,) int32
    person_unit,        # (N,) int32
    all_connections,    # (N, k) int32 — modified in-place
    rewire_prob,        # float64
):
    """
    Rewire each intra-SGU connection with probability rewire_prob to a random
    person within the same geo_unit (best-effort self-loop avoidance).
    """
    n_people = len(person_unit)
    k = all_connections.shape[1]
    for i in nb.prange(n_people):
        g = person_unit[i]
        unit_size = unit_ends[g] - unit_starts[g]
        if unit_size < 2:
            continue
        for j in range(k):
            if all_connections[i, j] == -1:
                continue
            if np.random.random() < rewire_prob:
                rand_local = int(np.random.random() * unit_size)
                w = unit_starts[g] + rand_local
                if w == i:
                    rand_local = (rand_local + 1) % unit_size
                    w = unit_starts[g] + rand_local
                all_connections[i, j] = w


def _collate_people_in_geo_units(
        geography: "Geography",
        geo_unit_ids: set["GeographicalUnit"]
) -> set["Person"]:
    """
    Collect all people from a set of geographical units.

    Args:
        geography (Geography): Geography object containing the geographical hierarchy.
        geo_unit_ids (set[str]): Set of geographical unit IDs to collect people from.

    Returns:
        set[Person]: Set of Person objects from all specified geographical units.
    """
    people = set()
    for geo_unit_id in geo_unit_ids:
        geo_unit = geography.get_unit_by_id(geo_unit_id)
        people.update(geo_unit.get_people())
    return people


def _build_local_social_network(
        geography: "Geography",
        mean_connections_per_person: float,
        clustering_level: float,
        geo_unit_level: str = None,
        storage_key: str = "social_contacts_local",
        store: bool = True,
        assign_activity_map: bool = False,
        **kwargs,
) -> None:
    """
    Build a Watts-Strogatz social network within each smallest geographical unit.

    Each person connects to their `mean_connections_per_person` nearest neighbours in
    circular order within their unit (ring lattice), then each connection is rewired
    with probability `1 - clustering_level` to a random person in the same unit.

    Args:
        geography (Geography): Geography object containing geo_units and population.
        mean_connections_per_person (float): Target average connections per person (k).
        clustering_level (float): 1.0 = pure ring lattice; 0.0 = fully random rewire.
        geo_unit_level (str): Level to use. Defaults to geography.levels[0].
        storage_key (str): Key used to store connections in person.properties.
        store (bool): If True, store relationships in person.properties[storage_key].
        assign_activity_map: If True (and store=True), also populate person.activities
            and person.activity_map[storage_key] with contacts' residence venue mappings.

    Returns:
        None — relationships stored in person.properties[storage_key].
    """
    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]
    units = list(geography.get_units_by_level(geo_unit_level).values())
    all_people, unit_starts, unit_ends, unit_people_flat, person_unit = _build_people_csr(units)

    if not all_people:
        logger.warning("build_local_social_network: no people found — skipping")
        return

    N = len(all_people)
    k = int(mean_connections_per_person)
    lattice_k = max(1, k // 2)
    logger.info(f"Building local social network: {N:,} people across {len(units)} SGUs, k={k}")

    all_connections = np.full((N, lattice_k), -1, dtype=np.int32)
    _local_ws_build_lattice(unit_starts, unit_ends, unit_people_flat, person_unit,
                            all_connections, np.int32(lattice_k))

    rewire_prob = np.float64(1.0 - clustering_level)
    if rewire_prob > 0.0:
        _local_ws_rewire(unit_starts, unit_ends, unit_people_flat, person_unit,
                         all_connections, rewire_prob)

    if store:
        _store_contacts_from_matrix(all_people, all_connections, storage_key, assign_activity_map)


def _allocate_random_bounded_distance_contacts(
        geography: "Geography",
        radius_km: float,
        mean_connections_per_person: float,
        geo_unit_level=None,
        storage_key: str = None,
        store: bool = True,
        method: str = 'libpysal',
        **kwargs,
) -> None:
    """
    Allocates contacts randomly to people within a specified radius.

    Faster than _build_bounded_distance_social_network — no graph constructed.
    Simply gathers all people from within the set radius and sets random contacts.
    No filters applied.
    """
    if storage_key is None:
        storage_key = f'social_contacts_radius_{radius_km}'
    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]

    geo_units = geography.get_units_by_level(geo_unit_level)
    geo_unit_neighbours = find_neighbours(list(geo_units.values()), radius_km=radius_km)

    if store:
        rng_generator = np.random.default_rng()
        for geo_unit_id, connected_ids in geo_unit_neighbours.items():
            people_to_connect_to = list(_collate_people_in_geo_units(geography, connected_ids))
            people_to_connect_from = geography.units_by_id[geo_unit_id].get_people()
            if people_to_connect_to and people_to_connect_from:
                for person in people_to_connect_from:
                    if storage_key in person.properties:
                        person.properties[storage_key].extend(random.sample(people_to_connect_to,
                            k=rng_generator.poisson(lam=mean_connections_per_person)))
                    else:
                        person.properties[storage_key] = random.sample(people_to_connect_to,
                            k=rng_generator.poisson(lam=mean_connections_per_person))


def _build_bounded_distance_social_network(
        geography: "Geography",
        radius_km: float,
        mean_connections_per_person: float,
        clustering_level: float,
        geo_unit_level: str = None,
        storage_key: str = None,
        store: bool = True,
        method: str = 'libpysal',
        **kwargs,
) -> None:
    """
    Build a network of contacts between people in geo_units within a specified radius.

    For each geo_unit in the given geography, creates a network between its people and
    the people in all other geo_units within the specified radius (km). Contacts are then
    assigned based on this network of people, stored under person.properties[storage_key].

    Args:
        geography (Geography): Geography object containing the geographical hierarchy.
        radius_km (float): Search radius in kilometers for finding neighbouring geo_units.
        mean_connections_per_person (float): Average number of connections per person.
        geo_unit_level (str): Level of geographical units to use. Defaults to smallest level.
        clustering_level (float): Clustering coefficient from 0.0 (random) to 1.0 (high clustering).
        storage_key (str): Key used to store connections in person.properties.
        store (bool): If True, store relationships in person.properties[storage_key].
        method (str): Method for finding neighbours ('libpysal' or 'balltree').

    Returns:
        None: Relationships are stored in person.properties[storage_key].
    """
    if storage_key is None:
        storage_key = f"social_contacts_radius_km_{radius_km}"

    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]

    geo_units = geography.get_units_by_level(geo_unit_level)
    geo_unit_neighbours = find_neighbours(list(geo_units.values()), radius_km=radius_km, method=method)

    for geo_unit_id, connected_ids in geo_unit_neighbours.items():
        people_in_network = _collate_people_in_geo_units(geography, connected_ids)
        GraphRelationshipBuilder.build_graph_relationships(
            people_in_network,
            mean_connections_per_person=mean_connections_per_person / 2,
            clustering_level=clustering_level,
            storage_key=storage_key,
            store=store,
            **kwargs,
        )


# ============================================================================
# SPATIAL WATTS-STROGATZ SOCIAL NETWORK — NUMBA-ACCELERATED
# ============================================================================

@nb.njit(parallel=True, cache=True)
def _spatial_ws_build_lattice(
    neighbor_starts,    # (U,) int32 — start index per geo_unit in neighbor_flat
    neighbor_ends,      # (U,) int32 — end index
    neighbor_flat,      # (M,) int32 — neighbour geo_unit indices, sorted nearest→furthest
    unit_starts,        # (U,) int32 — start index per geo_unit in unit_people_flat
    unit_ends,          # (U,) int32 — end index
    unit_people_flat,   # (N,) int32 — global person indices, contiguous per unit
    person_unit,        # (N,) int32 — geo_unit index for each person
    all_connections,    # (N, k) int32 — output; -1 = empty slot
    k,                  # int32 — connections per person
):
    """Build spatial W-S lattice: each person connects to k nearest inter-unit people."""
    n_people = len(person_unit)
    for i in nb.prange(n_people):
        g = person_unit[i]
        n_assigned = 0
        nb_start = neighbor_starts[g]
        nb_end = neighbor_ends[g]
        for nb_idx in range(nb_start, nb_end):
            if n_assigned >= k:
                break
            h = neighbor_flat[nb_idx]
            p_start = unit_starts[h]
            p_end = unit_ends[h]
            for p_idx in range(p_start, p_end):
                if n_assigned >= k:
                    break
                w = unit_people_flat[p_idx]
                if w == i:
                    continue
                all_connections[i, n_assigned] = w
                n_assigned += 1


@nb.njit(parallel=True, cache=True)
def _spatial_ws_rewire(
    all_connections,    # (N, k) int32 — modified in-place
    neighbor_starts,    # (U,) int32
    neighbor_ends,      # (U,) int32
    neighbor_flat,      # (M,) int32
    unit_starts,        # (U,) int32
    unit_ends,          # (U,) int32
    unit_people_flat,   # (N,) int32
    person_unit,        # (N,) int32
    rewire_prob,        # float64
):
    """Rewire each connection with probability rewire_prob to a random eligible person."""
    n_people = len(person_unit)
    k = all_connections.shape[1]
    for i in nb.prange(n_people):
        g = person_unit[i]
        n_nb_units = neighbor_ends[g] - neighbor_starts[g]
        if n_nb_units == 0:
            continue
        for j in range(k):
            if all_connections[i, j] == -1:
                continue
            if np.random.random() < rewire_prob:
                rand_nb_idx = neighbor_starts[g] + int(np.random.random() * n_nb_units)
                h = neighbor_flat[rand_nb_idx]
                unit_size = unit_ends[h] - unit_starts[h]
                if unit_size == 0:
                    continue
                rand_p_idx = unit_starts[h] + int(np.random.random() * unit_size)
                w = unit_people_flat[rand_p_idx]
                all_connections[i, j] = w


def _haversine_km(lon1_deg, lat1_deg, lon2_deg, lat2_deg):
    """Haversine distance in km between two (lon, lat) points in degrees."""
    lon1, lat1 = np.radians(lon1_deg), np.radians(lat1_deg)
    lon2, lat2 = np.radians(lon2_deg), np.radians(lat2_deg)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _build_spatial_social_network(
        geography: "Geography",
        min_radius_km: float,
        max_radius_km: float,
        mean_connections_per_person: int = 6,
        clustering_level: float = 0.7,
        geo_unit_level: str = None,
        storage_key: str = None,
        store: bool = True,
        assign_activity_map: bool = False,
) -> None:
    """
    Build an inter-geo-unit social network using a Spatial Watts-Strogatz algorithm.

    Each person is connected to `mean_connections_per_person` people from other geo_units
    whose centroids lie within `[min_radius_km, max_radius_km]` of their own unit's centroid.
    A W-S rewiring step (controlled by `clustering_level`) introduces spatial shortcuts
    while preserving high clustering.

    Args:
        geography: Geography object containing geo_units and population.
        min_radius_km: Exclusive lower distance bound.
        max_radius_km: Hard upper cutoff.
        mean_connections_per_person: Target mean degree k (default 6).
        clustering_level: 1.0 = no rewiring (pure lattice); 0.0 = full random rewire.
        geo_unit_level: Level of geo_units to use. Defaults to the smallest level.
        storage_key: Key for person.properties storage. Auto-generated if None.
        store: If True, store contacts in person.properties[storage_key].
        assign_activity_map: If True (and store=True), also populate person.activities and
            person.activity_map[storage_key] with contacts' residence venue mappings.

    Returns:
        None — contacts stored as lists of Person objects in person.properties[storage_key].
    """
    from scipy.spatial import cKDTree

    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]
    if storage_key is None:
        storage_key = f'social_contacts_spatial_{min_radius_km}_{max_radius_km}'

    geo_units_dict = geography.get_units_by_level(geo_unit_level)
    geo_units_list = list(geo_units_dict.values())

    coordinates, units_with_coords = _extract_coordinates(geo_units_list)
    if coordinates is None:
        logger.warning("build_spatial_social_network: no units with valid coordinates — skipping")
        return

    U = len(units_with_coords)
    logger.info(f"Building spatial social network: {U} geo_units, "
                f"annulus [{min_radius_km}, {max_radius_km}] km, k={mean_connections_per_person}")

    # ---- Build neighbor CSR (sorted by haversine distance) -------------------------
    max_deg = _km_to_degrees_adjusted(max_radius_km, coordinates) * 1.2
    tree = cKDTree(coordinates)

    candidates_list = tree.query_ball_point(coordinates, max_deg)
    all_neighbors = []
    for i, raw_cands in enumerate(candidates_list):
        cands = np.array([j for j in raw_cands if j != i], dtype=np.int32)
        if len(cands) == 0:
            all_neighbors.append([])
            continue
        dists = _haversine_km(
            coordinates[i, 0], coordinates[i, 1],
            coordinates[cands, 0], coordinates[cands, 1],
        )
        mask = (dists >= min_radius_km) & (dists <= max_radius_km)
        valid_cands = cands[mask]
        valid_dists = dists[mask]
        order = np.argsort(valid_dists)
        all_neighbors.append(valid_cands[order].tolist())

    # Flatten into CSR
    neighbor_starts = np.zeros(U, dtype=np.int32)
    neighbor_ends = np.zeros(U, dtype=np.int32)
    neighbor_flat = np.zeros(sum(len(n) for n in all_neighbors), dtype=np.int32)
    offset = 0
    for i, nbrs in enumerate(all_neighbors):
        neighbor_starts[i] = offset
        for j in nbrs:
            neighbor_flat[offset] = j
            offset += 1
        neighbor_ends[i] = offset

    avg_nb = np.mean([len(n) for n in all_neighbors])
    logger.info(f"  Neighbour units per geo_unit: avg {avg_nb:.1f}")

    # ---- Collect people and build people-per-unit CSR -------------------------
    all_people, unit_starts_arr, unit_ends_arr, unit_people_flat, person_unit = \
        _build_people_csr(units_with_coords)

    if not all_people:
        logger.warning("build_spatial_social_network: no people found — skipping")
        return

    N = len(all_people)
    logger.info(f"  {N:,} people across {U} geo_units")

    # ---- Phase 1: Build spatial lattice -------------------------------------------
    k = mean_connections_per_person
    lattice_k = max(1, k // 2)
    all_connections = np.full((N, lattice_k), -1, dtype=np.int32)
    _spatial_ws_build_lattice(
        neighbor_starts, neighbor_ends, neighbor_flat,
        unit_starts_arr, unit_ends_arr, unit_people_flat,
        person_unit, all_connections, np.int32(lattice_k),
    )

    # ---- Phase 2: Rewire ----------------------------------------------------------
    rewire_prob = np.float64(1.0 - clustering_level)
    if rewire_prob > 0.0:
        _spatial_ws_rewire(
            all_connections,
            neighbor_starts, neighbor_ends, neighbor_flat,
            unit_starts_arr, unit_ends_arr, unit_people_flat,
            person_unit, rewire_prob,
        )

    # ---- Symmetrize and store (vectorised) ------------------------------------
    if store:
        _store_contacts_from_matrix(all_people, all_connections, storage_key, assign_activity_map)
