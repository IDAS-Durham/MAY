import logging
import pandas as pd
import os
import yaml
from collections import defaultdict
from .venue import Venue
from may.utils import path_resolver as pr

logger = logging.getLogger("venuemanager")


class VenueError(Exception):
    """Raised when venue configuration or data is missing/invalid. Mirrors
    PopulationError: the engine works on complete data or fails loudly."""


class VenueManager:
    """
    Manages venues and their relationship to geographical units.
    """
    def __init__(self, geography, data_dir="data/venues", filter_by_geography=True):
        self.geography = geography      # Reference to Geography object
        self.data_dir = data_dir
        self.venues = {}                # All venues by name: {name: Venue}
        self.venues_by_type_and_id = defaultdict(dict)  # Venues by type and ID: {type: {id: Venue}}
        self.venues_by_type_and_name = defaultdict(dict)  # Lossless name lookup scoped by type: {type: {name: Venue}}
        self.venues_by_type = defaultdict(list)        # Venues grouped by type: {type: [Venue, ...]}

        self.filter_by_geography = filter_by_geography  # Only load venues in loaded geo units

        # ID counter per venue type for generating type-scoped unique IDs
        self._next_id_by_type = defaultdict(int)  # {venue_type: next_id}

        # Get set of loaded geographical unit names for filtering
        self._loaded_geo_units = set(self.geography.get_all_units().keys())

        # Store full venue type configurations from YAML
        self.venue_configs = {}         # {venue_type: full_config_dict}

        # Capacity configurations per venue type — lazily populated by
        # allocation steps (residence venue_allocator) at runtime. The
        # venues_config.yaml itself no longer carries capacity rules.
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
        # Lossless type-scoped name lookup
        self.venues_by_type_and_name[venue.type][venue.name] = venue
        # Group by type
        self.venues_by_type[venue.type].append(venue)
        # Keep the per-type ID counter ahead of any externally-set IDs
        if venue.id >= self._next_id_by_type[venue.type]:
            self._next_id_by_type[venue.type] = venue.id + 1
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

        # Required columns - 'geo_unit' or any level label defined in geography
        geo_levels = set(self.geography.levels)
        geo_cols = {'geo_unit'}.union(geo_levels)
        actual_geo_col = next((col for col in venue_df.columns if col in geo_cols), None)

        if actual_geo_col is None:
            raise ValueError(f"Missing required geographical column ('geo_unit' or one of {sorted(geo_levels)}) in file for {venue_type}")

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

        # Detect a 'name' column (case-insensitive) — only treat the column as the venue name
        # if it actually exists. Without this check, getattr(row, 'name', None) returns None
        # and downstream code synthesizes a name from row.Index, producing meaningless numeric
        # "names" that collide across files (e.g. grocery row 12537 vs pub row 12537).
        name_col = next((col for col in venue_df.columns if col.lower() == 'name'), None)

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
            # Only treat 'name' as a CSV-supplied venue name when the column truly exists
            # AND the value is non-null. Otherwise the venue keeps its auto-generated
            # `{venue_type}_{id}` name. We never synthesise names from row.Index — that
            # produced numeric strings that spuriously collide across venue types.
            csv_name = None
            if name_col is not None:
                raw = getattr(row, name_col, None)
                if raw is not None and pd.notna(raw):
                    csv_name = str(raw)

            geo_unit = None
            if actual_geo_col:
                geo_unit_name = getattr(row, actual_geo_col)
                geo_unit = self.geography.get_unit(geo_unit_name)

            if not geo_unit:
                logger.warning(
                    f"Geographical unit not found for {venue_type} venue "
                    f"'{csv_name if csv_name else f'<row {row.Index}>'}'. Skipping."
                )
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

            # Override name if the CSV provided one
            if csv_name is not None:
                # Drop the auto-generated name from the flat lookup; the type-scoped
                # name index will be re-keyed below.
                auto_name = venue.name
                if auto_name in self.venues and self.venues[auto_name] is venue:
                    del self.venues[auto_name]
                self.venues_by_type_and_name[venue.type].pop(auto_name, None)

                # Distinguish same-type duplication (real source-data duplication)
                # from cross-type collision (different venue types sharing a name).
                # Same-type takes precedence: get_venue_by_type_and_name can't
                # disambiguate same-type duplicates, only get_venue_by_type_and_id can.
                same_type_prior = self.venues_by_type_and_name[venue.type].get(csv_name)
                if same_type_prior is not None:
                    logger.warning(
                        f"Duplicate {venue_type} name '{csv_name}' in source data: "
                        f"existing id={same_type_prior.id} will be shadowed in name lookup by id={venue.id}. "
                        f"Both venues remain accessible via get_venue_by_type_and_id."
                    )
                elif csv_name in self.venues:
                    existing = self.venues[csv_name]
                    logger.warning(
                        f"Venue name collision: '{csv_name}' already exists as "
                        f"type='{existing.type}' (id={existing.id}). "
                        f"Flat lookup will return type='{venue_type}' (id={venue.id}); "
                        f"use get_venue_by_type_and_name for unambiguous access."
                    )

                venue.name = csv_name
                self.venues[csv_name] = venue
                self.venues_by_type_and_name[venue.type][csv_name] = venue

            # Set coordinates if available
            if coordinates:
                venue.coordinates = coordinates

        logger.info(f"Created {venues_created} {venue_type} venues")
        

    def load_venue_type_from_csv(self, venue_type, filename, filter_column=None, filter_values=None):
        """
        Load venues of a specific type from a CSV file (relative to data_dir).

        Expected columns:
        - name (optional): Name of the venue
        - a geographical column ('geo_unit' or any configured level label)
        - latitude / longitude (optional): coordinates
        - All other columns become properties specific to this venue type

        A missing file is a hard error (VenueError) — callers that tolerate
        absent files (e.g. batch mode) must check existence before calling.
        """
        venue_path = os.path.join(self.data_dir, filename)

        if not os.path.exists(venue_path):
            raise VenueError(f"Venue file not found: {venue_path}")

        venue_df = pd.read_csv(venue_path)
        logger.info(f"Loading {venue_type} venues from {venue_path}")

        self.load_venue_type_from_df(
            venue_type,
            venue_df,
            filter_column=filter_column,
            filter_values=filter_values
        )

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
            config_file: Path to YAML config file. ${...} templating is applied
                first; an absolute result is used as-is. A relative path is tried
                against the current working directory, then against data_dir.
        """
        config_path = pr.resolve(config_file)
        if not os.path.isabs(config_path) and not os.path.exists(config_path):
            # Relative path not found from CWD — try data_dir-relative.
            config_path = os.path.join(self.data_dir, config_path)
        if not os.path.exists(config_path):
            raise VenueError(f"Venue config file not found: {config_path}")

        logger.info(f"Loading venue configuration from {config_path}")
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        if not config:
            raise VenueError(f"Empty venue configuration file: {config_path}")
        if 'venue_types' not in config:
            raise VenueError(f"Venue config has no 'venue_types' key: {config_path}")

        # Parse settings if provided
        settings = config.get('settings', {})
        if 'filter_by_geography' in settings:
            self.filter_by_geography = settings['filter_by_geography']
            self._loaded_geo_units = set(self.geography.get_all_units().keys())

        venue_types_config = config['venue_types']

        # An explicit empty mapping is a valid "this world has no venues"
        # declaration; a *missing* venue_types key (above) is a config error.
        if not venue_types_config:
            logger.info("venue_types is empty; loading no venues.")
            return

        enabled_types = []
        disabled_types = []
        for venue_type, type_config in venue_types_config.items():
            self.venue_configs[venue_type] = type_config
            if not type_config.get('enabled', True):
                disabled_types.append(venue_type)
                continue
            enabled_types.append(venue_type)

        if disabled_types:
            logger.info(f"Skipping disabled venue types: {disabled_types}")
        logger.info(f"Loading {len(enabled_types)} venue types from YAML config")

        for venue_type in enabled_types:
            type_config = self.venue_configs[venue_type]
            filename = type_config.get('filename')
            if not filename:
                raise VenueError(
                    f"Venue type '{venue_type}' is enabled but has no 'filename'."
                )
            filter_column = type_config.get('filter_column')
            filter_values = type_config.get('filter_values')

            if type_config.get('batch_mode', False):
                # One file per batch-partition-level (levels[1]; adr/0002) unit,
                # named by substituting {unit} into the filename. Absent per-unit
                # files are skipped (partial geographies are routine), but an
                # enabled batch type matching zero files is a hard error.
                if '{unit}' not in filename:
                    raise VenueError(
                        f"Batch venue type '{venue_type}' filename must contain "
                        f"the '{{unit}}' placeholder; got {filename!r}."
                    )
                units = self.geography.get_units_by_level(self.geography.levels[1])
                matched = 0
                for unit_name in units.keys():
                    unit_filename = filename.replace('{unit}', unit_name)
                    if not os.path.exists(os.path.join(self.data_dir, unit_filename)):
                        continue
                    self.load_venue_type_from_csv(
                        venue_type, unit_filename,
                        filter_column=filter_column, filter_values=filter_values,
                    )
                    matched += 1
                if matched == 0:
                    raise VenueError(
                        f"Batch venue type '{venue_type}' matched no files in "
                        f"{self.data_dir} (pattern {filename!r})."
                    )
            else:
                self.load_venue_type_from_csv(
                    venue_type, filename,
                    filter_column=filter_column, filter_values=filter_values,
                )

        self._log_total_created()
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

        # Merge venues_by_type_and_name
        for venue_type, name_dict in other.venues_by_type_and_name.items():
            self.venues_by_type_and_name[venue_type].update(name_dict)

        # Merge venues_by_type
        for venue_type, venue_list in other.venues_by_type.items():
            self.venues_by_type[venue_type] = self.venues_by_type.get(venue_type, []) + venue_list

        # Advance per-type ID counters past every imported venue so future
        # create_venue calls don't reuse an existing ID.
        for venue_type, id_dict in other.venues_by_type_and_id.items():
            if not id_dict:
                continue
            highest = max(id_dict.keys())
            if highest >= self._next_id_by_type[venue_type]:
                self._next_id_by_type[venue_type] = highest + 1

    def get_venue(self, name):
        """
        Get a venue by its name (flat lookup across all types).

        Note: venue names are not guaranteed unique across types — different
        venue types can legitimately share a name (e.g. a school and a
        boarding school of the same institution). On collision this returns
        the most recently registered venue. Use ``get_venue_by_type_and_name``
        or ``get_venue_by_type_and_id`` for unambiguous access.
        """
        return self.venues.get(name)

    def get_venue_by_type_and_name(self, venue_type, name):
        """
        Get a venue by its type and name. Lossless across types: a school and
        a boarding_school sharing a name are both retrievable here.

        Within a single type, source data may still contain duplicate names;
        this returns the most recently registered venue of that (type, name).
        Use get_venue_by_type_and_id to address every venue unambiguously.
        """
        return self.venues_by_type_and_name.get(venue_type, {}).get(name)

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
        """Get all venues as a flat list from venues_by_type (authoritative source)."""
        all_venues = []
        for venue_list in self.venues_by_type.values():
            all_venues.extend(venue_list)
        return all_venues

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

    def _log_total_created(self):
        """Log the true total venue count, plus the unique-name count if it
        differs (which signals collisions in the flat name dict)."""
        total = sum(len(vs) for vs in self.venues_by_type.values())
        unique_names = len(self.venues)
        if total == unique_names:
            logger.info(f"Total venues created: {total}")
        else:
            shadowed = total - unique_names
            logger.info(
                f"Total venues created: {total} "
                f"({unique_names} unique names; {shadowed} shadowed by name collisions, "
                f"still accessible via get_venue_by_type_and_id)"
            )

    def _log_summary(self):
        """Log summary statistics about venues"""
        for venue_type in sorted(self.venues_by_type.keys()):
            count = len(self.venues_by_type[venue_type])
            logger.info(f"  {venue_type}: {count} venues")

    def __repr__(self):
        return f"<VenueManager: {len(self.venues)} venues, {len(self.venues_by_type)} types>"
