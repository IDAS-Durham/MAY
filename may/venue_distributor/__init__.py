"""
Venue Distributor Module

This module provides a flexible, YAML-driven system for distributing people to venues.
The system reads configuration from YAML files in yaml/distributors/ and allocates
people to venues based on attributes, distance, and capacity constraints.

Classes:
    VenueDistributor: Main class for single-venue allocation
    MultiVenueDistributor: Class for multi-venue allocation (multiple venues per person)

Functions:
    distributor_from_yaml: Factory function to load the appropriate distributor from YAML
"""

import yaml
from pathlib import Path

from .venue_distributor import VenueDistributor
from .multi_venue_distributor import MultiVenueDistributor

__all__ = ['VenueDistributor', 'MultiVenueDistributor', 'distributor_from_yaml']


def distributor_from_yaml(yaml_path: str):
    """
    Factory function to create the appropriate distributor based on YAML configuration.

    Reads the 'distributor_type' field from the YAML and instantiates the correct class:
    - distributor_type: "multi_venue" -> MultiVenueDistributor
    - distributor_type: "single_venue" or missing -> VenueDistributor (default)

    Args:
        yaml_path: Path to distributor YAML file

    Returns:
        Instance of VenueDistributor or MultiVenueDistributor

    Examples:
        >>> distributor = distributor_from_yaml('yaml/distributors/school_distributor.yaml')
        >>> distributor.allocate(world)

        >>> distributor = distributor_from_yaml('yaml/distributors/multi_venue_distributor.yaml')
        >>> distributor.allocate(world)
    """
    # Read YAML to check distributor_type
    yaml_path = Path(yaml_path)
    with open(yaml_path, 'r') as f:
        config = yaml.safe_load(f)

    distributor_type = config.get('distributor_type', 'single_venue')

    # Instantiate appropriate class
    if distributor_type == 'multi_venue':
        return MultiVenueDistributor(yaml_path)
    else:
        # Default to single-venue distributor
        return VenueDistributor(yaml_path)
