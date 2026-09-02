"""
Configuration loader for world serialization.

Loads YAML configuration specifying which properties and attributes
to include when exporting world state to HDF5.
"""

import logging
import os
from may.utils import path_resolver as pr
from may.utils.yaml_loader import load_yaml

logger = logging.getLogger("serialization_config")


class SerializationConfig:
    """
    Loads and validates serialization configuration from YAML.

    The config file specifies which properties to include for:
    - Population (person.properties)
    - Geography (geographical_unit.properties)
    - Venues (venue.properties, per-type)
    - Subsets (subset properties)
    - Relationships (activity_map, hierarchies)
    """

    def __init__(self, config_file):
        """
        Initialize SerializationConfig.

        Args:
            config_file: Path to YAML configuration file
        """
        self.config_file = pr.resolve(config_file)
        self.config = None

        # Parsed configuration sections
        self.population_properties = []
        self.geography_include_coordinates = True
        self.geography_properties = []
        self.venue_global_settings = {}
        self.venue_type_properties = {}
        self.relationships = {}
        self.output_settings = {}

        self._load_config()

    def _load_config(self):
        """Load and parse the YAML configuration file."""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Serialization config not found: {self.config_file}"
            )

        logger.info(f"Loading serialization config from {self.config_file}")

        self.config = load_yaml(self.config_file)

        if not self.config:
            raise ValueError(f"Empty serialization config: {self.config_file}")

        # Parse each section
        self._parse_population()
        self._parse_geography()
        self._parse_venues()
        self.relationships = self.config.get("relationships", {})
        self.output_settings = self.config.get("output", {})

    def _parse_population(self):
        """Parse population configuration section."""
        pop_config = self.config.get("population", {})
        self.population_properties = pop_config.get("properties", [])

        logger.info(
            f"Population: {len(self.population_properties)} additional properties to serialize"
        )
        if self.population_properties:
            logger.info(f"  Properties: {self.population_properties}")

    def _parse_geography(self):
        """Parse geography configuration section."""
        geo_config = self.config.get("geography", {})
        self.geography_include_coordinates = geo_config.get("include_coordinates", True)
        self.geography_properties = geo_config.get("properties", [])

        logger.info(
            f"Geography: coordinates={self.geography_include_coordinates}, "
            f"{len(self.geography_properties)} additional properties"
        )

    def _parse_venues(self):
        """Parse venues configuration section."""
        venues_config = self.config.get("venues", {})

        # Global settings
        self.venue_global_settings = venues_config.get("global", {})

        # Per-type properties
        types_config = venues_config.get("types", {})
        for venue_type, type_config in types_config.items():
            properties = type_config.get("properties", [])
            self.venue_type_properties[venue_type] = properties

            if properties:
                logger.info(
                    f"Venue '{venue_type}': {len(properties)} properties to serialize"
                )
                logger.info(f"  Properties: {properties}")
            else:
                logger.debug(
                    f"Venue '{venue_type}': minimal serialization (core attributes only)"
                )
