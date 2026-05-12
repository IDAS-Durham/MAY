"""
Builder implementations for spatial and local Watts-Strogatz social networks.

Implements local_social_network, spatial_social_network, bounded_distance network types.
"""

from .spatial_kernels import (
    _build_local_social_network,
    _build_spatial_social_network,
    _build_bounded_distance_social_network,
)

_TEMP_KEY = "__network_builder_tmp__"


def _collect_and_pop(world, key: str) -> dict:
    """Read results stored by a spatial_kernels function, then remove the key."""
    results = {}
    for person in world.population.people:
        results[person.id] = person.properties.pop(key, [])
    return results


def build_local_social_network(world, network_config: dict) -> dict:
    """
    Watts-Strogatz social network within the smallest geo units.

    Required network_config keys:
        mean_count       – mean connections per person
    Optional:
        pool.level       – geo unit level (defaults to geography.levels[0])
        clustering_level – rewiring probability (default 0.8)
    """
    pool_config = network_config.get("pool", {})
    geo_unit_level = pool_config.get("level", None)
    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.8)

    _build_local_social_network(
        world.geography,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=_TEMP_KEY,
        store=True,
    )
    return _collect_and_pop(world, _TEMP_KEY)


def build_spatial_social_network(world, network_config: dict) -> dict:
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


def build_bounded_distance(world, network_config: dict) -> dict:
    """
    Random contacts within a geographic radius.

    Required network_config keys:
        mean_count   – mean connections per person
        pool.max_km  – search radius (km)
    Optional:
        clustering_level  – clustering coefficient (default 0.7)
        pool.level        – geo unit level (defaults to smallest)
    """
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
