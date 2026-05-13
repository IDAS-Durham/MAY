"""
Builder implementations for spatial and local Watts-Strogatz social networks.

Implements local_social_network, spatial_social_network, bounded_distance network types.
"""

from .spatial_kernels import (
    _build_local_social_network,
    _build_spatial_social_network,
    _build_bounded_distance_social_network,
)


def build_local_social_network(world, network_config: dict) -> None:
    """
    Watts-Strogatz social network within the smallest geo units.

    Required network_config keys:
        mean_count       – mean connections per person
    Optional:
        pool.level       – geo unit level (defaults to geography.levels[0])
        clustering_level – rewiring probability (default 0.8)
        assign_activity  – dict with contact_activity_key and activity_key
    """
    pool_config = network_config.get("pool", {})
    geo_unit_level = pool_config.get("level", None)
    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.8)
    storage_key = network_config["storage_key"]
    activity_config = network_config.get("assign_activity", None)

    _build_local_social_network(
        world.geography,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=storage_key,
        activity_config=activity_config,
    )


def build_spatial_social_network(world, network_config: dict) -> None:
    """
    Spatial Watts-Strogatz between geo units in an annulus.

    Required network_config keys:
        mean_count   – mean connections per person
        pool.min_km  – inner radius (km)
        pool.max_km  – outer radius (km)
    Optional:
        clustering_level  – rewiring probability (default 0.9)
        pool.level        – geo unit level (defaults to smallest)
        assign_activity   – dict with contact_activity_key and activity_key
    """
    pool_config = network_config.get("pool", {})
    mean_count = network_config["mean_count"]
    clustering_level = network_config.get("clustering_level", 0.9)
    min_km = pool_config.get("min_km", 0.0)
    max_km = pool_config.get("max_km", 10.0)
    geo_unit_level = pool_config.get("level", None)
    storage_key = network_config["storage_key"]
    activity_config = network_config.get("assign_activity", None)

    _build_spatial_social_network(
        world.geography,
        min_radius_km=min_km,
        max_radius_km=max_km,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=storage_key,
        activity_config=activity_config,
    )


def build_bounded_distance(world, network_config: dict) -> None:
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
    storage_key = network_config["storage_key"]

    _build_bounded_distance_social_network(
        world.geography,
        radius_km=max_km,
        mean_connections_per_person=mean_count,
        clustering_level=clustering_level,
        geo_unit_level=geo_unit_level,
        storage_key=storage_key,
    )
