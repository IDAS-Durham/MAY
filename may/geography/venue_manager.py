import logging
import pandas as pd
import os
import yaml
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
        self.venues_by_type_and_id = defaultdict(dict)  # Venues by type and ID: {type: {id: Venue}}
        self.venues_by_type = defaultdict(list)        # Venues grouped by type: {type: [Venue, ...]}

        self.filter_by_geography = filter_by_geography  # Only load venues in loaded geo units

        # ID counter per venue type for generating type-scoped unique IDs
        self._next_id_by_type = defaultdict(int)  # {venue_type: next_id}

        # Get set of loaded geographical unit names for filtering
        self._loaded_geo_units = set(self.geography.get_all_units().keys())

        # Store full venue type configurations from YAML
        self.venue_configs = {}         # {venue_type: full_config_dict}

        # Store capacity configurations by venue type
        self.capacity_configs = {}      # {venue_type: capacity_config_dict}

    def _generate_id(self, venue_type: str) -> int:
        """
        Generate a unique sequential ID for a venue type.

        Args:
            venue_type: Type of venue (e.g., "household", "hospital")

        Returns:
            Unique integer ID within that venue type
        """
        next_id = self._next_id_by_type[venue_type]
        self._next_id_by_type[venue_type] += 1
        return next_id

    def add_venue(self, venue):
        """ Adds a venue to the VenueManager in the appropriate place and relates it with the geography object """
        self.venues[venue.name] = venue
        # Store by type and ID
        self.venues_by_type_and_id[venue.type][venue.id] = venue
        # Group by type
        self.venues_by_type[venue.type].append(venue)
        # Add venue to its geographical unit
        venue.geographical_unit.add_venue(venue)

    def create_venue(self, venue_type, geo_unit, properties=None):
        """
        Create a venue and add it to the manager.
        ID is auto-generated per venue type.

        Args:
            venue_type: Type of venue (e.g., "household", "hospital", "school")
            geo_unit: GeographicalUnit where venue is located
            properties: Venue-specific properties dict

        Returns:
            Venue object
        """
        # Generate type-scoped ID
        venue_id = self._generate_id(venue_type)

        # Prepare properties, adding is_residence from config if available
        venue_properties = properties or {}

        # Add properties from venue_configs if available
        if venue_type in self.venue_configs:
            config = self.venue_configs[venue_type]
            venue_properties['is_residence'] = config.get('is_residence', False)
            
            # Explicitly copy subset configuration
            if 'subset_categories' in config:
                venue_properties['subset_categories'] = config['subset_categories']
            if 'subset_key' in config:
                venue_properties['subset_key'] = config['subset_key']

        venue = Venue(
            name=f"{venue_type}_{venue_id}",
            venue_type=venue_type,
            geographical_unit=geo_unit,
            properties=venue_properties
        )

        # Set the ID on the venue
        venue.id = venue_id

        # Add to manager
        self.add_venue(venue)

        return venue

    def create_child_venue(self, parent_venue, child_venue_type, properties=None, geo_unit=None):
        """
        Create a child venue and attach it to a parent venue.
        The child inherits the geographical_unit from the parent if not specified.

        Args:
            parent_venue: Parent Venue object
            child_venue_type: Type of child venue (e.g., "classroom", "office")
            properties: Venue-specific properties dict
            geo_unit: Optional GeographicalUnit (defaults to parent's geo_unit)

        Returns:
            Child Venue object

        Example:
            >>> school = venue_manager.create_venue("school", some_sgu)
            >>> classroom = venue_manager.create_child_venue(school, "classroom",
            ...                                               properties={'grade': 1, 'capacity': 25})
        """
        # Use parent's geographical_unit if not specified
        if geo_unit is None:
            geo_unit = parent_venue.geographical_unit

        # Create the child venue
        child = self.create_venue(
            venue_type=child_venue_type,
            geo_unit=geo_unit,
            properties=properties
        )

        # Establish parent-child relationship
        parent_venue.add_child_venue(child)

        return child

    def create_venue_with_children(self, parent_type, geo_unit, children_spec, properties=None):
        """
        Create a parent venue with multiple child venues in one call.

        Args:
            parent_type: Type of parent venue (e.g., "school", "company")
            geo_unit: GeographicalUnit where parent venue is located
            children_spec: List of dicts specifying children, each with:
                - 'type': Child venue type (required)
                - 'count': Number of children to create (default: 1)
                - 'properties': Properties dict for the child (optional)
            properties: Properties for the parent venue

        Returns:
            Tuple of (parent_venue, list_of_child_venues)

        Example:
            >>> school, classrooms = venue_manager.create_venue_with_children(
            ...     parent_type="school",
            ...     geo_unit=some_sgu,
            ...     children_spec=[
            ...         {'type': 'classroom', 'count': 20, 'properties': {'capacity': 25}},
            ...         {'type': 'gym', 'count': 1, 'properties': {'capacity': 100}}
            ...     ],
            ...     properties={'capacity': 500}
            ... )
        """
        # Create parent venue
        parent = self.create_venue(
            venue_type=parent_type,
            geo_unit=geo_unit,
            properties=properties
        )

        # Create child venues
        children = []
        for spec in children_spec:
            child_type = spec['type']
            count = spec.get('count', 1)
            child_properties = spec.get('properties', {})

            for i in range(count):
                # Add index to properties if creating multiple of same type
                props = child_properties.copy()
                if count > 1:
                    props['index'] = i

                child = self.create_child_venue(
                    parent_venue=parent,
                    child_venue_type=child_type,
                    properties=props
                )
                children.append(child)

        return parent, children       

    def load_venue_type_from_df(self, venue_type, venue_df, filter_column=None, filter_values=None):
        """ Creates venues from a given dataframe """
        if filter_column and filter_values:
            original_count = len(venue_df)
            # Ensure filtering works regardless of type (strip and stringify, and uppercase for consistency)
            target_values = [str(v).strip().upper() for v in filter_values]
            venue_df = venue_df[venue_df[filter_column].astype(str).str.strip().str.upper().isin(target_values)]
            logger.info(f"Filtered {venue_type} venues by {filter_column}: {len(venue_df)} rows kept (from {original_count})")

        # Required columns - we support SGU, MGU or any levels defined in geography
        geo_levels = set(self.geography.levels)
        geo_cols = {'geo_unit', 'SGU', 'MGU'}.union(geo_levels)
        actual_geo_col = next((col for col in venue_df.columns if col in geo_cols), None)

        if actual_geo_col is None:
            raise ValueError(f"Missing required geographical column (e.g., 'geo_unit', 'SGU', 'MGU') in file for {venue_type}")

        # Optional coordinate columns (check both lowercase and capitalized)
        lat_col = None
        lon_col = None

        # Check for latitude column (case-insensitive)
        for col in venue_df.columns:
            if col.lower() == 'latitude':
                lat_col = col
            elif col.lower() == 'longitude':
                lon_col = col

        has_coords = lat_col is not None and lon_col is not None

        # Get additional property columns
        reserved_cols = {'name', 'geo_unit', 'latitude', 'longitude'}.union(geo_cols)
        property_cols = [col for col in venue_df.columns if col.lower() not in reserved_cols and col not in reserved_cols]

        # Filter DataFrame upfront if geography filtering is enabled
        venues_skipped = 0
        if self.filter_by_geography and actual_geo_col in venue_df.columns:
            original_count = len(venue_df)
            venue_df = venue_df[venue_df[actual_geo_col].isin(self._loaded_geo_units)]
            venues_skipped = original_count - len(venue_df)
            logger.info(f"Pre-filtered {venue_type} venues: {len(venue_df)} venues in loaded geography ({venues_skipped} filtered out using {actual_geo_col})")

        # Create venues
        venues_created = 0
        for row in venue_df.itertuples():
            name = getattr(row, 'name', None) if hasattr(row, 'name') else None
            if name is None or pd.isna(name):
                name = str(row.Index)
            
            geo_unit = None
            if actual_geo_col:
                geo_unit_name = getattr(row, actual_geo_col)
                geo_unit = self.geography.get_unit(geo_unit_name)
            
            if not geo_unit:
                logger.warning(f"Geographical unit not found for venue '{name}'. Skipping.")
                continue

            # Get coordinates if provided
            coordinates = None
            if has_coords:
                lat_val = getattr(row, lat_col, None)
                lon_val = getattr(row, lon_col, None)
                if lat_val is not None and lon_val is not None and pd.notna(lat_val) and pd.notna(lon_val):
                    coordinates = (lat_val, lon_val)

            # Add additional properties
            properties = {}
            for prop_col in property_cols:
                prop_val = getattr(row, prop_col, None)
                if prop_val is not None and pd.notna(prop_val):
                    properties[prop_col] = prop_val

            # Create venue (ID auto-generated per type)
            venue = self.create_venue(
                venue_type=venue_type,
                geo_unit=geo_unit,
                properties=properties
            )
            venues_created += 1

            # Override name if provided
            if name and pd.notna(name):
                venue.name = name

            # Set coordinates if available
            if coordinates:
                venue.coordinates = coordinates

        logger.info(f"Created {venues_created} {venue_type} venues")
        

    def load_venue_type_from_csv(self, venue_type, filename=None, filter_column=None, filter_values=None):
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

        self.load_venue_type_from_df(
            venue_type, 
            venue_df, 
            filter_column=filter_column,
            filter_values=filter_values
        )


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
            # Try relative to current working directory first
            if os.path.exists(config_path):
                config_path = config_path
            else:
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
            # Store full config for this venue type (for later reference)
            self.venue_configs[venue_type] = type_config

            # Check if enabled (default: true)
            if not type_config.get('enabled', True):
                disabled_types.append(venue_type)
                continue

            # Get filename (default: {venue_type}s.csv)
            filename = type_config.get('filename', f"{venue_type}s.csv")

            # Store capacity_config if present
            if 'capacity_config' in type_config:
                self.capacity_configs[venue_type] = type_config['capacity_config']
                logger.info(f"  Loaded capacity_config for {venue_type}")

            enabled_types.append((venue_type, filename))

        if disabled_types:
            logger.info(f"Skipping disabled venue types: {disabled_types}")

        logger.info(f"Loading {len(enabled_types)} venue types from YAML config")

        # Load each enabled venue type
        for venue_type, filename in enabled_types:
            type_config = self.venue_configs.get(venue_type, {})
            filter_column = type_config.get('filter_column')
            filter_values = type_config.get('filter_values')
            batch_mode = type_config.get('batch_mode', False)
            
            if batch_mode:
                # 1. Identify all MGUs in current geography
                mgu_units = self.geography.get_units_by_level("MGU")
                for mgu_name in mgu_units.keys():
                    mgu_filename = f"{mgu_name}_loc.csv"
                    self.load_venue_type_from_csv(
                        venue_type, 
                        mgu_filename, 
                        filter_column=filter_column,
                        filter_values=filter_values
                    )
            else:
                self.load_venue_type_from_csv(
                    venue_type, 
                    filename, 
                    filter_column=filter_column,
                    filter_values=filter_values
                )

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

        # Merge venues_by_type_and_id
        for venue_type, id_dict in other.venues_by_type_and_id.items():
            self.venues_by_type_and_id[venue_type].update(id_dict)

        # Merge venues_by_type
        for venue_type, venue_list in other.venues_by_type.items():
            self.venues_by_type[venue_type] = self.venues_by_type.get(venue_type, []) + venue_list

    def get_venue(self, name):
        """Get a venue by its name"""
        return self.venues.get(name)

    def get_venue_by_type_and_id(self, venue_type, venue_id):
        """
        Get a venue by its type and ID.

        Args:
            venue_type: Type of venue (e.g., "household", "hospital")
            venue_id: ID within that venue type

        Returns:
            Venue object or None if not found
        """
        return self.venues_by_type_and_id.get(venue_type, {}).get(venue_id)

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

    def get_capacity_config(self, venue_type):
        """
        Get capacity configuration for a venue type.

        Args:
            venue_type: Type of venue (e.g., "care_home")

        Returns:
            dict: Capacity configuration or None if not defined
        """
        return self.capacity_configs.get(venue_type)

    def export_venues_to_csv(self, output_file: str = "venue_allocations.csv"):
        """
        Export all venue allocation data to a CSV file.

        Creates a detailed CSV with:
        - Venue ID
        - Venue name
        - Venue type
        - Geographical unit
        - Capacity information
        - Number of residents allocated
        - Breakdown by attribute slots (for attribute-aware venues)
        - List of residents with age and sex

        Args:
            output_file: Path to output CSV file

        Returns:
            str: Path to created CSV file
        """
        logger.info(f"Exporting venue allocation data to {output_file}...")

        rows = []
        for venue in self.get_all_venues_list():
            # Get basic info
            residents = venue.properties.get('residents', [])

            # Get capacity info
            capacity_config = self.get_capacity_config(venue.type)

            # Get total capacity from the correct column based on venue type
            if capacity_config and 'total_capacity_column' in capacity_config:
                capacity_column = capacity_config['total_capacity_column']
                total_capacity = venue.properties.get(capacity_column, 0)
            else:
                # Fallback to 'capacity' for venues without capacity_config
                total_capacity = venue.properties.get('capacity', 0)

            # Prepare resident details
            resident_details = []
            for person in residents:
                resident_details.append(f"Person_{person.id}(age={person.age},sex={person.sex})")
            residents_str = "; ".join(resident_details) if resident_details else ""

            # Calculate age/sex breakdown
            age_sex_breakdown = {}
            for person in residents:
                key = f"age_{person.age}_{person.sex}"
                age_sex_breakdown[key] = age_sex_breakdown.get(key, 0) + 1

            breakdown_str = ", ".join([f"{k}: {v}" for k, v in sorted(age_sex_breakdown.items())])

            # For attribute-aware venues, get slot-level stats
            slot_stats = {}
            if capacity_config and 'attribute_capacities' in capacity_config:
                column_mappings = capacity_config.get('attribute_capacities', {}).get('column_mappings', {})
                for slot_name in column_mappings.keys():
                    slot_residents = venue.properties.get(f'residents_{slot_name}', [])
                    slot_capacity = venue.properties.get(slot_name, 0)
                    if slot_capacity:
                        slot_stats[slot_name] = f"{len(slot_residents)}/{slot_capacity}"

            slot_stats_str = ", ".join([f"{k}: {v}" for k, v in sorted(slot_stats.items())])

            # Create row
            row = {
                'venue_id': venue.id,
                'venue_name': venue.name,
                'venue_type': venue.type,
                'geo_unit': venue.geographical_unit.name if venue.geographical_unit else 'None',
                'total_capacity': total_capacity,
                'num_residents': len(residents),
                'capacity_used_pct': f"{(len(residents) / total_capacity * 100):.1f}" if total_capacity > 0 else "0.0",
                'age_sex_breakdown': breakdown_str,
                'attribute_slots': slot_stats_str if slot_stats_str else "N/A",
                'residents': residents_str
            }
            rows.append(row)

        # Create DataFrame and export
        df = pd.DataFrame(rows)

        # Sort by venue type and ID (only if DataFrame has data)
        if not df.empty:
            df = df.sort_values(['venue_type', 'venue_id'])

        output_path = os.path.join(self.data_dir, output_file)
        
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        df.to_csv(output_path, index=False)

        logger.info(f"Exported {len(rows)} venues to {output_path}")
        return output_path

    def get_residence_types(self):
        """
        Get all venue types marked as residences.

        Returns:
            List of residence type strings (e.g., ['household', 'care_home', ...])

        Example:
            >>> venue_manager.get_residence_types()
            ['household', 'care_home', 'student_dorms', 'boarding_school']
        """
        residence_types = []

        # Get all residence types from venue_configs
        for venue_type, config in self.venue_configs.items():
            if config.get('is_residence', False):
                residence_types.append(venue_type)

        return residence_types

    def is_residence_type(self, venue_type: str) -> bool:
        """
        Check if a venue type is a residence.

        Args:
            venue_type: Venue type string (e.g., 'household', 'school')

        Returns:
            True if this venue type is marked as a residence

        Example:
            >>> venue_manager.is_residence_type('household')
            True
            >>> venue_manager.is_residence_type('school')
            False
        """
        # Check config
        config = self.venue_configs.get(venue_type, {})
        return config.get('is_residence', False)

    def get_all_residences(self):
        """
        Get all residence venues across all residence types.

        Returns:
            List of all residence Venue objects

        Example:
            >>> residences = venue_manager.get_all_residences()
            >>> len(residences)
            15234  # All households, care homes, dorms, etc.
        """
        residences = []
        for venue_type in self.get_residence_types():
            residences.extend(self.get_venues_by_type(venue_type))
        return residences

    def _log_summary(self):
        """Log summary statistics about venues"""
        for venue_type in sorted(self.venues_by_type.keys()):
            count = len(self.venues_by_type[venue_type])
            logger.info(f"  {venue_type}: {count} venues")

    def __repr__(self):
        return f"<VenueManager: {len(self.venues)} venues, {len(self.venues_by_type)} types>"
