"""
Configuration loader for world serialization.

Loads YAML configuration specifying which properties and attributes
to include when exporting world state to HDF5.
"""

import logging
import yaml
import os

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
        self.config_file = config_file
        self.config = None

        # Parsed configuration sections
        self.population_properties = []
        self.geography_include_coordinates = True
        self.geography_properties = []
        self.venue_global_settings = {}
        self.venue_type_properties = {}
        self.subset_properties = []
        self.relationships = {}
        self.output_settings = {}

        self._load_config()

    def _load_config(self):
        """Load and parse the YAML configuration file."""
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"Serialization config not found: {self.config_file}")

        logger.info(f"Loading serialization config from {self.config_file}")

        with open(self.config_file, 'r') as f:
            self.config = yaml.safe_load(f)

        if not self.config:
            raise ValueError(f"Empty serialization config: {self.config_file}")

        # Parse each section
        self._parse_population()
        self._parse_geography()
        self._parse_venues()
        self._parse_subsets()
        self._parse_relationships()
        self._parse_output()

    def _parse_population(self):
        """Parse population configuration section."""
        pop_config = self.config.get('population', {})
        self.population_properties = pop_config.get('properties', [])

        logger.info(f"Population: {len(self.population_properties)} additional properties to serialize")
        if self.population_properties:
            logger.info(f"  Properties: {self.population_properties}")

    def _parse_geography(self):
        """Parse geography configuration section."""
        geo_config = self.config.get('geography', {})
        self.geography_include_coordinates = geo_config.get('include_coordinates', True)
        self.geography_properties = geo_config.get('properties', [])

        logger.info(f"Geography: coordinates={self.geography_include_coordinates}, "
                   f"{len(self.geography_properties)} additional properties")

    def _parse_venues(self):
        """Parse venues configuration section."""
        venues_config = self.config.get('venues', {})

        # Global settings
        self.venue_global_settings = venues_config.get('global', {})

        # Per-type properties
        types_config = venues_config.get('types', {})
        for venue_type, type_config in types_config.items():
            properties = type_config.get('properties', [])
            self.venue_type_properties[venue_type] = properties

            if properties:
                logger.info(f"Venue '{venue_type}': {len(properties)} properties to serialize")
                logger.info(f"  Properties: {properties}")
            else:
                logger.debug(f"Venue '{venue_type}': minimal serialization (core attributes only)")

    def _parse_subsets(self):
        """Parse subsets configuration section."""
        subsets_config = self.config.get('subsets', {})
        self.subset_properties = subsets_config.get('properties', [])

    def _parse_relationships(self):
        """Parse relationships configuration section."""
        self.relationships = self.config.get('relationships', {})

    def _parse_output(self):
        """Parse output settings section."""
        self.output_settings = self.config.get('output', {})

    def get_person_properties(self):
        """
        Get list of person properties to serialize.

        Returns:
            List of property names from person.properties dict
        """
        return self.population_properties

    def get_geography_settings(self):
        """
        Get geography serialization settings.

        Returns:
            Dict with 'include_coordinates' and 'properties' keys
        """
        return {
            'include_coordinates': self.geography_include_coordinates,
            'properties': self.geography_properties
        }

    def get_venue_properties(self, venue_type):
        """
        Get list of properties to serialize for a specific venue type.

        Args:
            venue_type: Type of venue (e.g., "school", "household")

        Returns:
            List of property names to include, or [] if not configured
        """
        return self.venue_type_properties.get(venue_type, [])

    def get_venue_global_settings(self):
        """
        Get global venue serialization settings.

        Returns:
            Dict with global venue settings
        """
        return self.venue_global_settings

    def should_include_activity_map(self):
        """Check if activity_map should be serialized."""
        return self.relationships.get('include_activity_map', True)

    def should_include_venue_hierarchy(self):
        """Check if venue parent-child hierarchy should be serialized."""
        return self.relationships.get('include_venue_hierarchy', True)

    def should_include_geography_hierarchy(self):
        """Check if geography parent-child hierarchy should be serialized."""
        return self.relationships.get('include_geography_hierarchy', True)

    def get_compression_settings(self):
        """
        Get HDF5 compression settings.

        Returns:
            Dict with 'compression' and 'compression_level' keys
        """
        return {
            'compression': self.output_settings.get('compression', 'gzip'),
            'compression_level': self.output_settings.get('compression_level', 4)
        }

    def get_metadata_settings(self):
        """
        Get metadata settings.

        Returns:
            Dict with 'include' and 'fields' keys
        """
        return {
            'include': self.output_settings.get('include_metadata', True),
            'fields': self.output_settings.get('metadata', [])
        }
