"""
File with functions designed to build networks of contacts (usually social contacts, but could be any form of contact).
"""

import logging
from typing import TYPE_CHECKING

from .graph_relationship_builder import GraphRelationshipBuilder
from .geo_neighbors import find_neighbours, _extract_coordinates, _km_to_degrees_adjusted, EARTH_RADIUS_KM

from debug_output import export_relationships

import random
import numpy as np
import numba as nb

if TYPE_CHECKING:
    from may.geography import Geography, GeographicalUnit
    from may.world import World
    from may.population import Person

logger = logging.getLogger("create networks")


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


def build_local_social_network(
        geography: "Geography",
        mean_connections_per_person: float, # e.g. 0.6
        clustering_level: float, # e.g. 0.8
        storage_key: str = f"social_contacts_local",
        store: bool = True,
        export:bool = False,
        **kwargs,
) -> None:
    """
    Build a social network using a clustered graph.

    Creates social contact networks within each smallest geographical unit (SGU).
    Each person in an SGU is connected to others in the same SGU based on the
    specified clustering parameters.

    Args:
        geography (Geography): geography object containing geo_units and population.
        mean_connections_per_person (float): Average number of social connections per person.
        clustering_level (float): Clustering coefficient from 0.0 (random) to 1.0 (high clustering).
        storage_key (str): Key used to store connections in person.properties.
        store (bool): If True, store relationships in person.properties[storage_key].
        export (bool): If True, export relationships to CSV file.

    Returns:
        None: Relationships are stored in person.properties[storage_key].

    Example:
        >>> from may.world import World
        >>> world = World(geography, population)
        >>> build_local_social_network(world, mean_connections_per_person=6, clustering_level=0.8)
        >>> # Access contacts for a person
        >>> contacts = world.population.people[0].properties['social_contacts_local']
    """
    # Go through all geo units
    geo_units = geography.get_units_by_level(geography.levels[0])
    for geo_unit in geo_units.values():
        people = geo_unit.people
        logger.debug(f"Geo unit name - {geo_unit.name}, with {len(people)} people")
        
        relationships = GraphRelationshipBuilder.build_graph_relationships(
            people,
            mean_connections_per_person=mean_connections_per_person,
            clustering_level=clustering_level,
            storage_key=storage_key,
            store=store,
            **kwargs,
        )

    if export:
        # Export relationships to CSV
        #storage_key = builder.config.get('storage', {}).get('key', builder.name)
        export_relationships(world, 'social_contacts_local', f"social_contacts_local.csv")

def allocate_random_bounded_distance_contacts(
        geography: "Geography",
        radius_km: float,
        mean_connections_per_person: float,
        geo_unit_level = None,
        storage_key: str=None,
        store: bool=True,
        method: str='libpysal',
        **kwargs,
        ) -> None:
    """
    Allocates contacts randomly to people within a specified radius.

    Faster than build_bounded_distance_social_network, as it does not make a graph for everyone. Only creating connections with those outside the area. Simply gathers all people from within the set radius, and sets random contacts. No filters applied. Need to add capacity to filter.

    geography (Geography): Geography object. Contains all the geo_units.
    radius_km (float): The cut-off radius within which to assign contacts.
    mean_connections_per_person (float): The mean number of contacts to assign each person.
    """
    if storage_key is None:
        storage_key = f'social_contacts_radius_{radius_km}'
    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]

    # Create the geo_units_distance_network
    geo_units = geography.get_units_by_level(geo_unit_level)

    # Get geo_unit neighbours
    geo_unit_neighbours = find_neighbours(list(geo_units.values()), radius_km = radius_km)    

    # Go through each geographical unit, collect people and randomly assign contacts.
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

def build_bounded_distance_social_network(
        geography: "Geography",
        radius_km: float,
        mean_connections_per_person: float,
        clustering_level: float,
        geo_unit_level: str = None,

        storage_key: str=None,
        store: bool=True,
        method: str='libpysal',
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

    Example:
        >>> from may.geography import Geography
        >>> geography = Geography(data_dir="data/geography")
        >>> geography.load_from_csv()
        >>> build_bounded_distance_social_network(
        ...     geography,
        ...     radius_km=10.0,
        ...     mean_connections_per_person=4,
        ...     clustering_level=0.7
        ... )
    """
    if storage_key is None:
        storage_key = f"social_contacts_radius_km_{radius_km}"

    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]

    # Create the geo_units distance network
    geo_units = geography.get_units_by_level(geo_unit_level)

    # Get geo_unit neighbours
    geo_unit_neighbours = find_neighbours(list(geo_units.values()), radius_km = radius_km, method=method)

    # Go through each geographical unit, collect people and make a network.
    for geo_unit_id, connected_ids in geo_unit_neighbours.items():
        people_in_network = _collate_people_in_geo_units(geography, connected_ids)
        relationships = GraphRelationshipBuilder.build_graph_relationships(
            people_in_network,
            mean_connections_per_person=mean_connections_per_person / 2,  # the /2 is because this process will happen twice due to double-counting.
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


def build_spatial_social_network(
        geography: "Geography",
        min_radius_km: float,
        max_radius_km: float,
        mean_connections_per_person: int = 6,
        clustering_level: float = 0.7,
        geo_unit_level: str = None,
        storage_key: str = None,
        store: bool = True,
) -> None:
    """
    Build an inter-geo-unit social network using a Spatial Watts-Strogatz algorithm.

    Each person is connected to `mean_connections_per_person` people from other geo_units
    whose centroids lie within `[min_radius_km, max_radius_km]` of their own unit's centroid.
    A W-S rewiring step (controlled by `clustering_level`) introduces spatial shortcuts
    while preserving high clustering.

    Args:
        geography: Geography object containing geo_units and population.
        min_radius_km: Exclusive lower distance bound — connections to same-unit or
            immediately-adjacent units below this distance are excluded.
        max_radius_km: Hard upper cutoff — no connections beyond this distance.
        mean_connections_per_person: Target mean degree k (default 6).
        clustering_level: 1.0 = no rewiring (pure lattice); 0.0 = full random rewire.
        geo_unit_level: Level of geo_units to use. Defaults to the smallest level.
        storage_key: Key for person.properties storage. Auto-generated if None.
        store: If True, store contacts in person.properties[storage_key].

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
    # Use degree-based KDTree for candidate search (1.2× safety margin), then
    # filter with exact haversine distances in [min_radius_km, max_radius_km].
    max_deg = _km_to_degrees_adjusted(max_radius_km, coordinates) * 1.2
    tree = cKDTree(coordinates)

    all_neighbors = []   # list of sorted unit-index lists
    for i in range(U):
        candidate_indices = tree.query_ball_point(coordinates[i], max_deg)
        neighbors_with_dist = []
        for j in candidate_indices:
            if j == i:
                continue
            dist = _haversine_km(
                coordinates[i, 0], coordinates[i, 1],
                coordinates[j, 0], coordinates[j, 1],
            )
            if min_radius_km <= dist <= max_radius_km:
                neighbors_with_dist.append((dist, j))
        neighbors_with_dist.sort()
        all_neighbors.append([j for _, j in neighbors_with_dist])

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

    # ---- Collect people, build people-per-unit CSR and person_unit map ------------
    all_people = []
    unit_people_lists = []
    for unit in units_with_coords:
        people_in_unit = list(unit.get_people())
        start_idx = len(all_people)
        all_people.extend(people_in_unit)
        unit_people_lists.append(list(range(start_idx, len(all_people))))

    N = len(all_people)
    if N == 0:
        logger.warning("build_spatial_social_network: no people found — skipping")
        return

    total_unit_people = sum(len(p) for p in unit_people_lists)
    unit_starts_arr = np.zeros(U, dtype=np.int32)
    unit_ends_arr = np.zeros(U, dtype=np.int32)
    unit_people_flat = np.zeros(total_unit_people, dtype=np.int32)
    person_unit = np.zeros(N, dtype=np.int32)

    offset = 0
    for unit_idx, ppl_indices in enumerate(unit_people_lists):
        unit_starts_arr[unit_idx] = offset
        for pid in ppl_indices:
            unit_people_flat[offset] = pid
            person_unit[pid] = unit_idx
            offset += 1
        unit_ends_arr[unit_idx] = offset

    logger.info(f"  {N:,} people across {U} geo_units")

    # ---- Phase 1: Build spatial lattice -------------------------------------------
    k = mean_connections_per_person
    all_connections = np.full((N, k), -1, dtype=np.int32)
    _spatial_ws_build_lattice(
        neighbor_starts, neighbor_ends, neighbor_flat,
        unit_starts_arr, unit_ends_arr, unit_people_flat,
        person_unit, all_connections, np.int32(k),
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

    # ---- Symmetrize and store -----------------------------------------------------
    if store:
        # Build symmetric adjacency (directed → undirected)
        adj = [set() for _ in range(N)]
        for i in range(N):
            for j_idx in range(k):
                j = int(all_connections[i, j_idx])
                if j < 0 or j == i:
                    continue
                adj[i].add(j)
                adj[j].add(i)

        total_connections = 0
        for i, person in enumerate(all_people):
            contacts = [all_people[j] for j in adj[i]]
            if storage_key in person.properties:
                person.properties[storage_key].extend(contacts)
            else:
                person.properties[storage_key] = contacts
            total_connections += len(contacts)

        avg_deg = total_connections / N if N > 0 else 0.0
        logger.info(f"Built spatial social network: {total_connections:,} connections, "
                    f"avg ~{avg_deg:.1f} per person")
