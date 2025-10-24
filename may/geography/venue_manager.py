import logging
import pandas as pd
import os
from collections import defaultdict
from .venue import Venue

logger = logging.getLogger("venuemanager")

class VenueManager:
    """
    Manages venues and their relationship to geographical units.
    """
    def __init__(self, geography, data_dir="data/venues", filter_by_geography=True):
        self.geography = geography      # Reference to Geography object
        self.data_dir = data_dir
        self.venues = {}                # All venues by name: {name: Venue}
        self.venues_by_id = {}          # All venues by ID: {id: Venue}
        self.venues_by_type = defaultdict(list)        # Venues grouped by type: {type: [Venue, ...]}

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
        self._next_id += 1
        return self._next_id

    def add_venue(self, venue, geo_unit):
        """ Adds a venue to the VenueManager in the appropriate place and relates it with the geography object """
        self.venues[venue.name] = venue
        self.venues_by_id[venue.id] = venue
        # Group by type
        self.venues_by_type[venue.type].append(venue)
        # Add venue to its geographical unit
        geo_unit.add_venue(venue)       

    def load_venue_type_from_df(self, venue_type, venue_df):
        """ Creates venues from a given dataframe """
        # Required columns
        required_cols = ['name', 'geo_unit']
        for col in required_cols:
            if col not in venue_df.columns:
                raise ValueError(f"Missing required column '{col}' in file for {venue_type}")

        # Optional coordinate columns
        has_coords = 'latitude' in venue_df.columns and 'longitude' in venue_df.columns

        # Get additional property columns
        reserved_cols = {'name', 'geo_unit', 'latitude', 'longitude'}
        property_cols = [col for col in venue_df.columns if col not in reserved_cols]
        properties={}

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

            # Add additional properties
            properties = {}
            for prop_col in property_cols:
                if pd.notna(row[prop_col]):
                    properties[prop_col] = row[prop_col]
                
            # Generate ID and create venue
            venue = Venue(name=name,
                          venue_type=venue_type,
                          geographical_unit=geo_unit,
                          coordinates=coordinates,
                          properties=properties,
                          )
            
            # Store venue
            self.add_venue(venue, geo_unit)

            venues_created += 1

        if venues_skipped > 0:
            logger.info(f"Created {venues_created} {venue_type} venues ({venues_skipped} skipped due to geography filter)")
        else:
            logger.info(f"Created {venues_created} {venue_type} venues")
        

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

        self.load_venue_type_from_df(venue_type, venue_df)


    def load_from_csv(self, venue_types=None):
        """
        Load venues from multiple CSV files.

        Each venue type has its own CSV file with type-specific columns.
        For example:
          hospitals.csv for hospital venues
          schools.csv for school venues
          prisons.csv for prison venues

        Only venues in loaded geographical units will be created if filter_by_geography=True.

        Args:
            venue_types: List of venue types to load. If None, attempts to load all
                        CSV files in data_dir (excluding those starting with '_')
        """
        if venue_types is None:
            # Auto-discover CSV files in data directory
            if not os.path.exists(self.data_dir):
                logger.warning(f"Venue directory not found: {self.data_dir}")
                return

            csv_files = [f for f in os.listdir(self.data_dir)
                        if f.endswith('.csv') and not f.startswith('_')]

            if not csv_files:
                logger.warning(f"No venue CSV files found in {self.data_dir}")
                return

            # Infer venue types from filenames (singularize)
            venue_types = []
            for filename in csv_files:
                # companies.csv -> company, universities.csv -> university
                # hospitals.csv -> hospital, schools.csv -> school
                venue_type = filename.replace('.csv', '')

                # Handle common irregular plurals
                if venue_type.endswith('ies'):
                    venue_type = venue_type[:-3] + 'y'  # companies -> company
                elif venue_type.endswith('s'):
                    venue_type = venue_type[:-1]  # hospitals -> hospital

                venue_types.append((venue_type, filename))

            logger.info(f"Auto-discovered {len(venue_types)} venue types: {[vt[0] for vt in venue_types]}")
        else:
            # Use provided venue types
            venue_types = [(vt, None) for vt in venue_types]

        # Load each venue type
        for venue_type, filename in venue_types:
            self.load_venue_type_from_csv(venue_type, filename)

        logger.info(f"Total venues created: {len(self.venues)}")
        self._log_summary()

    def extend(self, other: "VenueManager"):
        """Adds all the venues from another instance of the VenueManager class into this instance.

        Created so that if multiple VenueManager child classes are made (e.g. to change the specifics of how they load venues)
        it is easy to combine them into one single object at the end.

        Args:
          other (VenueManager): another instance of the VenueManager class. 
        
        """
        # Should add something to check that self.geography and other.geography are equal.
        self.venues.update(other.venues)
        self.venues_by_id.update(other.venues)
        for venue_type, venue_list in other.venues_by_type.items():
            self.venues_by_type[venue_type] = self.venues_by_type.get(venue_type, []) + venue_list

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
