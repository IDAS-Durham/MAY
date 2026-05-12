"""
Registered network_type builders for SocialNetworkBuilder.

Each builder has the signature:
    (world, network_config: dict) -> dict[person_id, list[Person]]

network_config is the full YAML entry for this network, so each builder
reads its own required keys from it.

To add a new network_type:
    1. Write a builder function in builder_functions/ with the signature above.
    2. Import it here and call register_network_type("your_type_name")(fn).
    No other files need modification.
"""

from .social_networks import register_network_type
from .builder_functions.numba_random import build_intra_geo_unit, build_activity_peers
from .builder_functions.spatial import (
    build_local_social_network,
    build_spatial_social_network,
    build_bounded_distance,
)

register_network_type("intra_geo_unit")(build_intra_geo_unit)
register_network_type("activity_peers")(build_activity_peers)
register_network_type("local_social_network")(build_local_social_network)
register_network_type("spatial_social_network")(build_spatial_social_network)
register_network_type("bounded_distance")(build_bounded_distance)
