"""
Venue management for June Zero.
Venues are places where people live, work, learn, or receive services.
"""

import logging
import pandas as pd
import os
import yaml

logger = logging.getLogger("venue")


class Venue:
    """
    Represents a place where people live, work, learn, or receive services.
    Generic design that works for any geography, past or present.
    """
    def __init__(self, id, name, venue_type, geographical_unit, coordinates=None):
        self.id = id                    # Unique numeric ID (generated)
        self.name = name                # Name of the venue (e.g., "St Mary's Hospital")
        self.type = venue_type          # Type of venue (e.g., "hospital", "school")
        self.geographical_unit = geographical_unit  # Reference to GeographicalUnit
        self.coordinates = coordinates  # Optional (latitude, longitude) tuple
        self.properties = {}            # Extensible dict for venue-specific data

    def __repr__(self):
        geo_name = self.geographical_unit.name if self.geographical_unit else "None"
        return f"<Venue #{self.id}: {self.name} ({self.type}) in {geo_name}>"


class VenueManager:
    """
    Manages venues and their relationship to geographical units.
    """
    def __init__(self, geography, data_dir="data/venues", filter_by_geography=True):
        self.geography = geography      # Reference to Geography object
        self.data_dir = data_dir
        self.venues = {}                # All venues by name: {name: Venue}
        self.venues_by_id = {}          # All venues by ID: {id: Venue}
        self.venues_by_type = {}        # Venues grouped by type: {type: [Venue, ...]}
        self.filter_by_geography = filter_by_geography  # Only load venues in loaded geo units

        # ID counter for generating unique IDs
        self._next_id = 0

        # Get set of loaded geographical unit names for filtering
        self._loaded_geo_units = set(self.geography.get_all_units().keys())

    def _generate_id(self):
        """
        Generate a unique sequential ID for a venue.

        Returns:
            Unique integer ID
        """
        id = self._next_id
        self._next_id += 1
        return id

    def load_venue_type_from_csv(self, venue_type, filename=None):
        """
        Load venues of a specific type from a CSV file.

        The venue type is either provided or inferred from filename.
        For example: "hospitals.csv" -> type "hospital"

        Expected columns:
        - name: Name of the venue
        - geo_unit: Name of the geographical unit
        - latitude (optional): Latitude coordinate
        - longitude (optional): Longitude coordinate
        - All other columns become properties specific to this venue type

        Args:
            venue_type: Type of venue (e.g., "hospital", "school")
            filename: CSV filename (defaults to "{venue_type}s.csv")
        """
        if filename is None:
            filename = f"{venue_type}s.csv"

        venue_path = os.path.join(self.data_dir, filename)

        if not os.path.exists(venue_path):
            logger.warning(f"Venue file not found: {venue_path}")
            return

        venue_df = pd.read_csv(venue_path)
        logger.info(f"Loading {venue_type} venues from {venue_path}")

        # Required columns
        required_cols = ['name', 'geo_unit']
        for col in required_cols:
            if col not in venue_df.columns:
                raise ValueError(f"Missing required column '{col}' in {filename}")

        # Optional coordinate columns
        has_coords = 'latitude' in venue_df.columns and 'longitude' in venue_df.columns

        # Get additional property columns
        reserved_cols = {'name', 'geo_unit', 'latitude', 'longitude'}
        property_cols = [col for col in venue_df.columns if col not in reserved_cols]

        # Create venues
        venues_created = 0
        venues_skipped = 0
        for _, row in venue_df.iterrows():
            name = row['name']
            geo_unit_name = row['geo_unit']

            # Check if geo unit is in loaded geography
            if self.filter_by_geography and geo_unit_name not in self._loaded_geo_units:
                venues_skipped += 1
                continue

            # Get geographical unit
            geo_unit = self.geography.get_unit(geo_unit_name)
            if not geo_unit:
                logger.warning(f"Geographical unit '{geo_unit_name}' not found for venue '{name}'. Skipping.")
                venues_skipped += 1
                continue

            # Get coordinates if provided
            coordinates = None
            if has_coords and pd.notna(row['latitude']) and pd.notna(row['longitude']):
                coordinates = (row['latitude'], row['longitude'])

            # Generate ID and create venue
            venue_id = self._generate_id()
            venue = Venue(
                id=venue_id,
                name=name,
                venue_type=venue_type,
                geographical_unit=geo_unit,
                coordinates=coordinates
            )

            # Add additional properties
            for prop_col in property_cols:
                if pd.notna(row[prop_col]):
                    venue.properties[prop_col] = row[prop_col]

            # Store venue
            self.venues[name] = venue
            self.venues_by_id[venue_id] = venue

            # Group by type
            if venue_type not in self.venues_by_type:
                self.venues_by_type[venue_type] = []
            self.venues_by_type[venue_type].append(venue)

            # Add venue to its geographical unit
            geo_unit.add_venue(venue)

            venues_created += 1

        if venues_skipped > 0:
            logger.info(f"Created {venues_created} {venue_type} venues ({venues_skipped} skipped due to geography filter)")
        else:
            logger.info(f"Created {venues_created} {venue_type} venues")

    def load_from_yaml_config(self, config_file="venues_config.yaml"):
        """
        Load venues from a YAML configuration file.

        The YAML file defines which venue types to load and their settings.

        Example YAML structure:
        ```yaml
        venue_types:
          hospital:
            enabled: true
            filename: hospitals.csv
            description: "Healthcare facilities"
          school:
            enabled: false
            filename: schools.csv

        settings:
          filter_by_geography: true
        ```

        Args:
            config_file: Path to YAML config file (can be absolute or relative to data_dir)
        """
        # Try to find config file
        config_path = config_file
        if not os.path.isabs(config_path):
            # Try relative to data_dir
            config_path = os.path.join(self.data_dir, config_file)

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Venue config file not found: {config_path}")

        # Load YAML configuration
        logger.info(f"Loading venue configuration from {config_path}")
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        if not config:
            logger.warning(f"Empty configuration file: {config_path}")
            return

        # Parse settings if provided
        settings = config.get('settings', {})
        if 'filter_by_geography' in settings:
            self.filter_by_geography = settings['filter_by_geography']
            self._loaded_geo_units = set(self.geography.get_all_units().keys())

        # Load venue types
        venue_types_config = config.get('venue_types', {})
        if not venue_types_config:
            logger.warning("No venue types defined in configuration file")
            return

        enabled_types = []
        disabled_types = []

        for venue_type, type_config in venue_types_config.items():
            # Check if enabled (default: true)
            if not type_config.get('enabled', True):
                disabled_types.append(venue_type)
                continue

            # Get filename (default: {venue_type}s.csv)
            filename = type_config.get('filename', f"{venue_type}s.csv")

            enabled_types.append((venue_type, filename))

        if disabled_types:
            logger.info(f"Skipping disabled venue types: {disabled_types}")

        logger.info(f"Loading {len(enabled_types)} venue types from YAML config")

        # Load each enabled venue type
        for venue_type, filename in enabled_types:
            self.load_venue_type_from_csv(venue_type, filename)

        logger.info(f"Total venues created: {len(self.venues)}")
        self._log_summary()

    def get_venue(self, name):
        """Get a venue by its name"""
        return self.venues.get(name)

    def get_venue_by_id(self, id):
        """Get a venue by its numeric ID"""
        return self.venues_by_id.get(id)

    def get_venues_by_type(self, venue_type):
        """Get all venues of a specific type"""
        return self.venues_by_type.get(venue_type, [])

    def get_all_venues(self):
        """Get all venues (returns dict of name -> venue)"""
        return self.venues

    def get_all_venues_list(self):
        """Get all venues as a list, sorted by ID"""
        return sorted(self.venues.values(), key=lambda v: v.id)

    def get_venue_types(self):
        """Get list of all venue types"""
        return list(self.venues_by_type.keys())

    def _log_summary(self):
        """Log summary statistics about venues"""
        for venue_type in sorted(self.venues_by_type.keys()):
            count = len(self.venues_by_type[venue_type])
            logger.info(f"  {venue_type}: {count} venues")

    def __repr__(self):
        return f"<VenueManager: {len(self.venues)} venues, {len(self.venues_by_type)} types>"
