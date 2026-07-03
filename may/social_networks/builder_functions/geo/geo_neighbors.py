"""
Find neighboring geographical units within a specified radius.

Using libpysal DistanceBand (fast, requires projected coordinates for accuracy).
"""

import numpy as np
import logging
from typing import Optional

import numpy.typing as npt

logger = logging.getLogger("geo_neighbors")

# Earth's radius in kilometers
EARTH_RADIUS_KM = 6371.0

# Approximate km per degree of latitude (constant)
KM_PER_DEGREE_LAT = 111.0


def _km_to_degrees_adjusted(radius_km: float, coordinates: np.ndarray) -> float:
    """
    Convert km to degrees, adjusted for latitude.

    At latitude φ:
    - 1° latitude ≈ 111 km (constant)
    - 1° longitude ≈ 111 * cos(φ) km

    We use the geometric mean to balance both directions, providing
    a more accurate threshold for distance-based queries.

    Args:
        radius_km: Radius in kilometers
        coordinates: Array of (lon, lat) pairs in degrees

    Returns:
        Radius in degrees, adjusted for mean latitude
    """
    mean_lat = np.mean(coordinates[:, 1])  # (lon, lat) format
    lat_rad = np.radians(mean_lat)

    # Geometric mean of lat and lon degree sizes
    # lat: 111 km/deg, lon: 111 * cos(lat) km/deg
    km_per_degree = KM_PER_DEGREE_LAT * np.sqrt(np.cos(lat_rad))

    return radius_km / km_per_degree

from typing import Callable, Any
from functools import wraps
import logging

type GraphCreator = Callable[[Any],Any]

neighbour_finders: dict[str, GraphCreator] = {}
def register_neighbour_finder(name: str):
    """
    Decorator to register a neighbour finding method in the neighbour_finders registry.

    Args:
        name (str): Name to register the neighbour finder under.

    Returns:
        Callable: Decorator function that registers the wrapped function.

    Example:
        >>> @register_neighbour_finder("my_method")
        ... def find_neighbours_my_method(geo_units, radius_km):
        ...     return {}
        >>> neighbours = neighbour_finders["my_method"](units, 10.0)
    """
    def decorator(func: GraphCreator):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        neighbour_finders[name] = wrapper
        return wrapper
    return decorator

def _filter_units_with_valid_coords(geo_units: list['GeographicalUnit']) -> list['GeographicalUnit']:
    """
    Filter geographical units to only those with valid coordinates.

    Args:
        geo_units (list[GeographicalUnit]): List of geographical units to filter.

    Returns:
        list[GeographicalUnit]: Units that have non-null, non-NaN coordinates.
    """
    # Filter units with valid coordinates
    units_with_coords = []
    for unit in geo_units:
        coords = getattr(unit, 'coordinates', None)
        if coords is not None and not (np.isnan(coords[0]) or np.isnan(coords[1])):
            units_with_coords.append(unit)
    return units_with_coords

def _extract_coordinates(geo_units: list['GeographicalUnit']) -> [npt.NDArray, list["GeographicalUnits"]]:
    """
    Extract coordinates from geographical units as a numpy array.

    Args:
        geo_units (list[GeographicalUnit]): List of geographical units with coordinates,
            stored as (latitude, longitude) per GeographicalUnit's docstring.

    Returns:
        np.ndarray: Array of shape (n, 2) with (longitude, latitude) pairs,
            or empty dict if fewer than 2 units have valid coordinates.
    """
    units_with_coords = _filter_units_with_valid_coords(geo_units)

    if not units_with_coords:
        return None, None

    if len(units_with_coords) < 2:
        logger.warning("Need at least 2 units with coordinates")
        return None, None

    # unit.coordinates is (lat, lon); libpysal/cKDTree expect (x, y) = (lon, lat), so swap.
    coordinates = np.array([
        unit.coordinates[::-1]  # (lat, lon) -> (lon, lat)
        for unit in units_with_coords
    ])

    return coordinates, units_with_coords

@register_neighbour_finder('libpysal')
def _find_neighbours_libpysal(
    geo_units: list['GeographicalUnit'],
    radius_km: float,
) -> dict[id, list[id]]:
    """
    Find neighbouring geographical units using libpysal DistanceBand.

    Uses Euclidean distance with latitude-adjusted degree conversion for
    improved accuracy. The km-to-degrees conversion accounts for longitude
    compression at higher latitudes using the geometric mean.

    Args:
        geo_units: List of GeographicalUnit objects with coordinates
        radius_km: Search radius in kilometers

    Returns:
        Dict mapping unit id -> list of neighbour unit ids.
    """
    from libpysal import weights

    # Extract coordinates in the right format
    coordinates, units_with_coords = _extract_coordinates(geo_units)

    if coordinates is None:
        return {}

    # Convert km to degrees, adjusted for latitude
    threshold_degrees = _km_to_degrees_adjusted(radius_km, coordinates)

    # Build distance band weights
    dist_weights = weights.DistanceBand.from_array(coordinates, threshold=threshold_degrees)

    # Build neighbour dict
    neighbours = {}
    for i, unit in enumerate(units_with_coords):
        neighbour_indices = dist_weights.neighbors.get(i, [])
        neighbours[unit.id] = [units_with_coords[idx].id for idx in neighbour_indices]

    logger.info(f"Found neighbours for {len(neighbours)} units within ~{radius_km}km radius")
    avg_neighbours = np.mean([len(n) for n in neighbours.values()])
    logger.info(f"Average neighbours per unit: {avg_neighbours:.1f}")

    return neighbours

def find_neighbours(*args, method='libpysal', **kwargs) -> dict[id, list[id]]:
    """
    Find neighbouring geographical units within a specified radius.

    Args:
        *args: Arguments passed to the underlying neighbour finder method.
        method (str): Method for finding neighbours. Options: 'libpysal' (fast,
            uses Euclidean distance), 'balltree' (accurate, uses haversine).
        **kwargs: Keyword arguments passed to the underlying method, typically:
            - geo_units (list[GeographicalUnit]): Units with coordinates.
            - radius_km (float): Search radius in kilometers.

    Returns:
        dict[str, list[str]]: Mapping of unit ID to list of neighbour unit IDs.

    Example:
        >>> from may.geography import Geography
        >>> geo = Geography(data_dir="data/geography")
        >>> geo.load_from_csv()
        >>> units = list(geo.get_units_by_level("SGU").values())
        >>> neighbours = find_neighbours(units, radius_km=10.0, method='libpysal')
    """
    find_neighbours_method = neighbour_finders[method]
    if find_neighbours_method is None:
        raise ValueError(f"Unknown method: {method}")
    return find_neighbours_method(*args, **kwargs)        

def build_neighbour_network(
        neighbours: dict[str, list[str]]
        ) -> "nx.Graph":
    """
    Build a NetworkX graph from a neighbour dictionary.

    Args:
        neighbours (dict[str, list[str]]): Mapping of unit ID to list of neighbour unit IDs.

    Returns:
        nx.Graph: Undirected graph with units as nodes and neighbour relationships as edges.

    Example:
        >>> neighbours = {"A": ["B", "C"], "B": ["A"], "C": ["A"]}
        >>> G = build_neighbour_network(neighbours)
        >>> print(G.number_of_nodes(), G.number_of_edges())
        3 2
    """
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
