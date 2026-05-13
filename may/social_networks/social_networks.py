"""
YAML-driven dispatcher for building multiple named social networks.

To add a new network type, decorate a builder function:

    @register_network_type("my_type")
    def build_my_type(world, network_config: dict) -> dict:
        # network_config is the full YAML entry for this network
        # Return: dict mapping person_id -> list[Person]
        ...

Required YAML keys per network entry:
    network_type  – registered builder name
    pool_type     – registered pool builder name (from filters.py)
    pool          – dict of pool-builder-specific config
    mean_count    – target mean connections per person
    storage_key   – key written to person.properties
    constraints   – (optional) list of typed edge constraints
"""

import logging
import yaml
from functools import wraps
from typing import Callable, Any

from may.social_networks.builder_functions.filters_and_constraints.filters import pool_type_builders

logger = logging.getLogger("social_networks")

NetworkTypeBuilder = Callable[[Any, dict], dict]

network_type_builders: dict[str, NetworkTypeBuilder] = {}


def register_network_type(name: str):
    """
    Decorator to register a network builder in the network_type_builders registry.

    Example:
        >>> @register_network_type("my_type")
        ... def build_my_type(world, network_config):
        ...     return {}
        >>> network_type_builders["my_type"](world, config)
    """
    def decorator(func: NetworkTypeBuilder):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        network_type_builders[name] = wrapper
        return wrapper
    return decorator


_REQUIRED_KEYS = ("network_type", "pool_type", "storage_key", "mean_count")


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
                raise ValueError(
                    f"Network '{name}' missing required key '{key}'"
                )
        net_type = entry["network_type"]
        if net_type not in network_type_builders:
            raise ValueError(
                f"Network '{name}': unknown network_type '{net_type}'. "
                f"Registered: {sorted(network_type_builders)}"
            )
        pool_type = entry["pool_type"]
        if pool_type not in pool_type_builders:
            raise ValueError(
                f"Network '{name}': unknown pool_type '{pool_type}'. "
                f"Registered: {sorted(pool_type_builders)}"
            )

    @classmethod
    def from_yaml(cls, world, yaml_path: str) -> "SocialNetworkBuilder":
        with open(yaml_path) as f:
            config = yaml.safe_load(f)
        return cls(world, config)

    def build_all(self) -> None:
        for entry in self.config.get("networks", []):
            network_name = entry.get("name", entry["storage_key"])
            logger.info(f"Building network '{network_name}' "
                        f"(network_type={entry['network_type']}, "
                        f"pool_type={entry['pool_type']}, "
                        f"storage_key={entry['storage_key']})")
            builder_fn = network_type_builders[entry["network_type"]]
            builder_fn(self.world, entry)
            logger.info(f"  Stored '{network_name}' → '{entry['storage_key']}'")
