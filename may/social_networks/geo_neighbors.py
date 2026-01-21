"""
Find neighboring geographical units within a specified radius.

Two approaches provided:
1. Using scipy BallTree with haversine distance (accurate for lat/lon)
2. Using libpysal DistanceBand (fast, requires projected coordinates for accuracy)
"""

import numpy as np
import logging
from typing import Optional

logger = logging.getLogger("geo_neighbors")

# Earth's radius in kilometers
EARTH_RADIUS_KM = 6371.0

from typing import Callable, Any
from functools import wraps
import logging

type GraphCreator = Callable[[Any],Any]

neighbour_finders: dict[str, GraphCreator] = {}
def register_neighbour_finder(name: str):
    """
    Used to catalog the different graph creation methods and their defaults. 
    """
    def decorator(func: GraphCreator):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        neighbour_finders[name] = wrapper
        return wrapper
    return decorator

@register_neighbour_finder('libpysal')
def find_neighbours_libpysal(
    geo_units: list,
    radius_km: float,
    coordinate_attr: str = "coordinates"
) -> dict[str, list[str]]:
    """
    Find neighbouring geographical units using libpysal DistanceBand.

    Note: This uses Euclidean distance. For lat/lon coordinates, consider
    projecting to a local CRS first, or use find_neighbours_balltree for
    accurate great-circle distances.

    Args:
        geo_units: List of GeographicalUnit objects with coordinates
        radius_km: Search radius in kilometers (converted to degrees approximately)
        coordinate_attr: Attribute name for coordinates tuple (lat, lon)

    Returns:
        Dict mapping unit name -> list of neighbour unit names
    """
    from libpysal import weights

    # Filter units with valid coordinates
    units_with_coords = []
    for unit in geo_units:
        coords = getattr(unit, coordinate_attr, None)
        if coords is not None and not (np.isnan(coords[0]) or np.isnan(coords[1])):
            units_with_coords.append(unit)

    if len(units_with_coords) < 2:
        logger.warning("Need at least 2 units with coordinates")
        return {}

    # Extract coordinates as (lon, lat) - note: libpysal expects (x, y) = (lon, lat)
    coordinates = np.array([
        [unit.coordinates[1], unit.coordinates[0]]  # (lon, lat)
        for unit in units_with_coords
    ])

    # Approximate conversion: 1 degree ≈ 111 km at equator
    # This is imprecise - use BallTree for accuracy
    threshold_degrees = radius_km / 111.0

    # Build distance band weights
    dist_weights = weights.DistanceBand.from_array(coordinates, threshold=threshold_degrees)

    # Build neighbour dict
    neighbours = {}
    for i, unit in enumerate(units_with_coords):
        neighbour_indices = dist_weights.neighbors.get(i, [])
        neighbours[unit.name] = [units_with_coords[idx].name for idx in neighbour_indices]

    logger.info(f"Found neighbours for {len(neighbours)} units within ~{radius_km}km radius")
    avg_neighbours = np.mean([len(n) for n in neighbours.values()])
    logger.info(f"Average neighbours per unit: {avg_neighbours:.1f}")

    return neighbours

#@register_neighbour_finder('balltree')
# def find_neighbours_balltree(
#     geo_units: list,
#     radius_km: float,
#     coordinate_attr: str = "coordinates"
# ) -> dict[str, list[str]]:
#     """
#     Find neighbouring geographical units within a radius using scipy BallTree.

#     Uses haversine distance for accurate great-circle calculations on lat/lon.

#     Args:
#         geo_units: List of GeographicalUnit objects with coordinates (lat, lon)
#         radius_km: Search radius in kilometers
#         coordinate_attr: Attribute name for coordinates tuple (lat, lon)

#     Returns:
#         Dict mapping unit name -> list of neighbour unit names
#     """
#     from sklearn.neighbors import BallTree

#     # Filter units with valid coordinates
#     units_with_coords = []
#     for unit in geo_units:
#         coords = getattr(unit, coordinate_attr, None)
#         if coords is not None and not (np.isnan(coords[0]) or np.isnan(coords[1])):
#             units_with_coords.append(unit)

#     if len(units_with_coords) < 2:
#         logger.warning("Need at least 2 units with coordinates")
#         return {}

#     # Extract coordinates as (lat, lon) in radians for haversine
#     coords_rad = np.array([
#         [np.radians(unit.coordinates[0]), np.radians(unit.coordinates[1])]
#         for unit in units_with_coords
#     ])

#     # Build BallTree with haversine metric
#     tree = BallTree(coords_rad, metric='haversine')

#     # Convert radius to radians (radius_km / earth_radius)
#     radius_rad = radius_km / EARTH_RADIUS_KM

#     # Query all neighbours within radius
#     indices = tree.query_radius(coords_rad, r=radius_rad)

#     # Build neighbour dict
#     neighbours = {}
#     for i, unit in enumerate(units_with_coords):
#         # Exclude self from neighbours
#         neighbour_indices = [idx for idx in indices[i] if idx != i]
#         neighbours[unit.name] = [units_with_coords[idx].name for idx in neighbour_indices]

#     logger.info(f"Found neighbours for {len(neighbours)} units within {radius_km}km radius")
#     avg_neighbours = np.mean([len(n) for n in neighbours.values()])
#     logger.info(f"Average neighbours per unit: {avg_neighbours:.1f}")

#     return neighbours


def find_neighbours(*args, method='libpysal', **kwargs):
    """
    Build a NetworkX graph of neighbouring geographical units.

    Args:
        geo_units: List of GeographicalUnit objects with coordinates
        radius_km: Search radius in kilometers
        method: "balltree" (accurate) or "libpysal" (fast)

    Returns:
        NetworkX Graph with units as nodes and neighbour relationships as edges
    """

    find_neighbours_method = neighbour_finders[method]
    if find_neighbours_method is None:
        raise ValueError(f"Unknown method: {method}")
    return find_neighbours_method(*args, **kwargs)


def build_neighbour_network(
        neighbours: dict[str, str]
        ) -> "nx.Graph":
    import networkx as nx

    # Build graph
    G = nx.Graph()

    # Add all nodes
    for unit_name in neighbours.keys():
        G.add_node(unit_name)

    # Add edges (undirected, so only add once)
    for unit_name, unit_neighbours in neighbours.items():
        for neighbour_name in unit_neighbours:
            if not G.has_edge(unit_name, neighbour_name):
                G.add_edge(unit_name, neighbour_name)

    logger.info(f"Built network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    return G


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example with MAY geography
    from may.geography import Geography

    # Load medieval geography
    geo = Geography(
        data_dir="world_specific_code/MedievalYaml/data/geography",
        levels=["MBD_Temp_ID", "County", "Country"]
    )
    geo.load_from_csv()

    # Get the most granular units (MBD_Temp_ID level)
    sgu_units = list(geo.get_units_by_level("MBD_Temp_ID").values())
    logger.info(f"Loaded {len(sgu_units)} geographical units")

    # Find neighbours within 10km radius
    radius = 10.0  # km
    neighbours = find_neighbours(sgu_units, method="libpysal", radius_km=radius)
    
    # Build network
    logger.info(f"\n--- Building neighbour network ---")
    G = build_neighbour_network(neighbours)

    # Network statistics
    import networkx as nx
    logger.info(f"Network statistics:")
    logger.info(f"  Nodes: {G.number_of_nodes()}")
    logger.info(f"  Edges: {G.number_of_edges()}")
    logger.info(f"  Average degree: {2 * G.number_of_edges() / G.number_of_nodes():.1f}")
    logger.info(f"  Connected components: {nx.number_connected_components(G)}")
