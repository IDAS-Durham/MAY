"""YAML-driven construction of the built-in social network types."""

import logging
from may.utils.yaml_loader import load_yaml

from may.social_networks.builder_functions.filters_and_constraints.filters import (
    pool_type_builders,
)
from may.social_networks.builder_functions.numba_random import (
    build_activity_peers,
    build_intra_geo_unit,
)
from may.social_networks.builder_functions.spatial import (
    build_bounded_distance,
    build_local_social_network,
    build_spatial_social_network,
)

logger = logging.getLogger("social_networks")

_REQUIRED_KEYS = ("network_type", "pool_type", "storage_key", "mean_count")
_NETWORK_TYPES = (
    "activity_peers",
    "intra_geo_unit",
    "local_social_network",
    "spatial_social_network",
    "bounded_distance",
)


class SocialNetworkBuilder:
    """
    Builds multiple social networks from a YAML config, storing each under
    its own key in person.properties.
    """

    def __init__(self, world, config: dict):
        self.world = world
        self.config = config
        self._validate(config)

    def _validate(self, config: dict) -> None:
        for entry in config.get("networks", []):
            self._validate_network_config(entry)

    def _validate_network_config(self, entry: dict) -> None:
        name = entry.get("name", "<unnamed>")
        for key in _REQUIRED_KEYS:
            if key not in entry:
                raise ValueError(f"Network '{name}' missing required key '{key}'")
        net_type = entry["network_type"]
        if net_type not in _NETWORK_TYPES:
            raise ValueError(
                f"Network '{name}': unknown network_type '{net_type}'. "
                f"Supported: {list(_NETWORK_TYPES)}"
            )
        pool_type = entry["pool_type"]
        if pool_type not in pool_type_builders:
            raise ValueError(
                f"Network '{name}': unknown pool_type '{pool_type}'. "
                f"Registered: {sorted(pool_type_builders)}"
            )

    @classmethod
    def from_yaml(cls, world, yaml_path: str) -> "SocialNetworkBuilder":
        config = load_yaml(yaml_path)
        return cls(world, config)

    def build_all(self) -> None:
        for entry in self.config.get("networks", []):
            network_name = entry.get("name", entry["storage_key"])
            logger.info(
                f"Building network '{network_name}' "
                f"(network_type={entry['network_type']}, "
                f"pool_type={entry['pool_type']}, "
                f"storage_key={entry['storage_key']})"
            )
            if entry["network_type"] == "activity_peers":
                build_activity_peers(self.world, entry)
            elif entry["network_type"] == "intra_geo_unit":
                build_intra_geo_unit(self.world, entry)
            elif entry["network_type"] == "local_social_network":
                build_local_social_network(self.world, entry)
            elif entry["network_type"] == "spatial_social_network":
                build_spatial_social_network(self.world, entry)
            else:
                build_bounded_distance(self.world, entry)
            logger.info(f"  Stored '{network_name}' → '{entry['storage_key']}'")
