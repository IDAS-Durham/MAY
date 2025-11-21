"""
World serializer for exporting to HDF5 format.

Exports world state (geography, population, venues) to HDF5 file
for loading in C++ simulation engine.
"""

import logging
import h5py
import numpy as np
from datetime import datetime
from collections import defaultdict
from .serialization_config import SerializationConfig

logger = logging.getLogger("world_serializer")


class WorldSerializer:
    """
    Serializes World object to HDF5 format for C++ consumption.

    Uses SerializationConfig to determine which properties to include.
    Exports data in Structure-of-Arrays (SoA) format for efficient C++ loading.
    """

    def __init__(self, config_file):
        """
        Initialize WorldSerializer.

        Args:
            config_file: Path to serialization YAML configuration
        """
        self.config = SerializationConfig(config_file)
        self.compression_settings = self.config.get_compression_settings()

    def export(self, world, output_file):
        """
        Export world to HDF5 file.

        Args:
            world: World object to serialize
            output_file: Output HDF5 filename

        Returns:
            Dict with export statistics
        """
        logger.info("=" * 60)
        logger.info("Exporting World to HDF5")
        logger.info("=" * 60)
        logger.info(f"Output file: {output_file}")

        stats = {
            'num_people': 0,
            'num_venues': 0,
            'num_geo_units': 0,
            'num_subsets': 0,
        }

        with h5py.File(output_file, 'w') as f:
            # Write metadata
            self._write_metadata(f, world, stats)

            # Write geography
            logger.info("Serializing geography...")
            self._write_geography(f, world)
            stats['num_geo_units'] = len(world.geography.get_all_units())

            # Write population
            logger.info("Serializing population...")
            self._write_population(f, world)
            stats['num_people'] = len(world.population.people)

            # Write venues
            logger.info("Serializing venues...")
            stats['num_subsets'] = self._write_venues(f, world)
            stats['num_venues'] = len(world.venues.get_all_venues())

            # Write relationships
            logger.info("Serializing relationships...")
            self._write_relationships(f, world)

        logger.info("")
        logger.info("Export complete!")
        logger.info(f"  Geography units: {stats['num_geo_units']:,}")
        logger.info(f"  People: {stats['num_people']:,}")
        logger.info(f"  Venues: {stats['num_venues']:,}")
        logger.info(f"  Subsets: {stats['num_subsets']:,}")
        logger.info("=" * 60)

        return stats

    def _write_metadata(self, f, world, stats):
        """Write metadata attributes to root of HDF5 file."""
        metadata_settings = self.config.get_metadata_settings()

        if not metadata_settings['include']:
            return

        logger.info("Writing metadata...")

        # Always include counts
        f.attrs['num_people'] = len(world.population.people)
        f.attrs['num_venues'] = len(world.venues.get_all_venues())
        f.attrs['num_geo_units'] = len(world.geography.get_all_units())

        # Optional metadata fields
        metadata_fields = metadata_settings['fields']

        if 'creation_timestamp' in metadata_fields:
            f.attrs['creation_timestamp'] = datetime.now().isoformat()

        if 'random_seed' in metadata_fields:
            # Try to get seed from world if available
            f.attrs['random_seed'] = 0  # Default

        # Version info
        f.attrs['serialization_version'] = '1.0'
        f.attrs['june_zero_version'] = '0.1.0'

    def _write_geography(self, f, world):
        """Write geography hierarchy to HDF5."""
        geo_group = f.create_group('geography')
        geo_settings = self.config.get_geography_settings()

        # Get all units
        all_units = world.geography.get_all_units()
        units_list = list(all_units.values())

        if not units_list:
            logger.warning("No geographical units to serialize")
            return

        num_units = len(units_list)

        # Create ID → index mapping for efficient lookup
        id_to_index = {unit.id: idx for idx, unit in enumerate(units_list)}

        # Core attributes (always included)
        ids = np.array([unit.id for unit in units_list], dtype=np.int32)
        names = np.array([unit.name for unit in units_list], dtype=h5py.string_dtype())
        levels = np.array([unit.level for unit in units_list], dtype=h5py.string_dtype())

        # Parent IDs (-1 for root units)
        parent_ids = np.array(
            [unit.parent.id if unit.parent else -1 for unit in units_list],
            dtype=np.int32
        )

        # Write core datasets
        self._create_dataset(geo_group, 'ids', ids)
        self._create_dataset(geo_group, 'names', names)
        self._create_dataset(geo_group, 'levels', levels)
        self._create_dataset(geo_group, 'parent_ids', parent_ids)

        # Coordinates (optional)
        if geo_settings['include_coordinates']:
            latitudes = np.array(
                [unit.coordinates[0] if unit.coordinates else np.nan for unit in units_list],
                dtype=np.float32
            )
            longitudes = np.array(
                [unit.coordinates[1] if unit.coordinates else np.nan for unit in units_list],
                dtype=np.float32
            )

            self._create_dataset(geo_group, 'latitudes', latitudes)
            self._create_dataset(geo_group, 'longitudes', longitudes)

        # Additional properties (if configured)
        properties_to_include = geo_settings['properties']
        if properties_to_include:
            props_group = geo_group.create_group('properties')
            for prop_name in properties_to_include:
                self._write_property_array(props_group, prop_name, units_list)

        logger.info(f"  Wrote {num_units} geographical units")

    def _write_population(self, f, world):
        """Write population data to HDF5."""
        pop_group = f.create_group('population')

        people = world.population.people
        if not people:
            logger.warning("No people to serialize")
            return

        num_people = len(people)

        # Core attributes (always included)
        ids = np.array([p.id for p in people], dtype=np.int32)
        ages = np.array([p.age for p in people], dtype=np.float32)
        sexes = np.array([p.sex for p in people], dtype=h5py.string_dtype())

        # Geographical unit IDs (where person lives - SGU level)
        geo_unit_ids = np.array(
            [p.geographical_unit.id if p.geographical_unit else -1 for p in people],
            dtype=np.int32
        )

        # Write core datasets
        self._create_dataset(pop_group, 'ids', ids)
        self._create_dataset(pop_group, 'ages', ages)
        self._create_dataset(pop_group, 'sexes', sexes)
        self._create_dataset(pop_group, 'geo_unit_ids', geo_unit_ids)

        # Properties (configured in YAML)
        properties_to_include = self.config.get_person_properties()
        if properties_to_include:
            props_group = pop_group.create_group('properties')

            for prop_name in properties_to_include:
                self._write_property_array(props_group, prop_name, people)

        logger.info(f"  Wrote {num_people:,} people")
        if properties_to_include:
            logger.info(f"    Including properties: {properties_to_include}")

    def _write_venues(self, f, world):
        """Write venues and subsets to HDF5."""
        venues_group = f.create_group('venues')
        venue_global_settings = self.config.get_venue_global_settings()

        # Get all venues as a list
        all_venues = world.venues.get_all_venues_list()
        if not all_venues:
            logger.warning("No venues to serialize")
            return 0

        num_venues = len(all_venues)

        # CRITICAL: Venue IDs in Python are TYPE-SCOPED (each type has its own ID counter starting at 0)
        # This causes collisions: hospital_0, school_0, office_0 all have id=0
        # For C++, we need GLOBAL unique IDs. Assign sequential global IDs here.

        # Assign global IDs (0, 1, 2, ..., N-1)
        global_ids = np.arange(num_venues, dtype=np.int32)

        # Create mapping: (venue Python object id) -> global_id for subset/activity_map serialization
        self._venue_to_global_id = {id(v): global_id for v, global_id in zip(all_venues, global_ids)}

        # Also store type-scoped IDs for debugging/reference
        type_scoped_ids = np.array([v.id for v in all_venues], dtype=np.int32)

        # Core attributes (always included)
        ids = global_ids  # Use GLOBAL IDs for C++
        names = np.array([v.name for v in all_venues], dtype=h5py.string_dtype())
        types = np.array([v.type for v in all_venues], dtype=h5py.string_dtype())

        # Geographical unit IDs (where venue is located)
        geo_unit_ids = np.array(
            [v.geographical_unit.id if v.geographical_unit else -1 for v in all_venues],
            dtype=np.int32
        )

        # Parent venue IDs (-1 for root venues)
        # IMPORTANT: Use global IDs for parents too!
        parent_ids = np.array(
            [self._venue_to_global_id.get(id(v.parent), -1) if v.parent else -1 for v in all_venues],
            dtype=np.int32
        )

        # Write core datasets
        self._create_dataset(venues_group, 'ids', ids)
        self._create_dataset(venues_group, 'names', names)
        self._create_dataset(venues_group, 'types', types)
        self._create_dataset(venues_group, 'geo_unit_ids', geo_unit_ids)
        self._create_dataset(venues_group, 'parent_ids', parent_ids)

        # Coordinates (optional)
        if venue_global_settings.get('include_coordinates', True):
            latitudes = np.array(
                [v.coordinates[0] if v.coordinates else np.nan for v in all_venues],
                dtype=np.float32
            )
            longitudes = np.array(
                [v.coordinates[1] if v.coordinates else np.nan for v in all_venues],
                dtype=np.float32
            )

            self._create_dataset(venues_group, 'latitudes', latitudes)
            self._create_dataset(venues_group, 'longitudes', longitudes)

        # is_residence flag (optional)
        if venue_global_settings.get('include_is_residence', True):
            is_residence = np.array(
                [v.properties.get('is_residence', False) for v in all_venues],
                dtype=np.bool_
            )
            self._create_dataset(venues_group, 'is_residence', is_residence)

        # Properties (per-type configuration)
        self._write_venue_properties(venues_group, all_venues)

        # Write subsets
        num_subsets = self._write_subsets(venues_group, all_venues)

        logger.info(f"  Wrote {num_venues:,} venues")
        logger.info(f"  Wrote {num_subsets:,} subsets")

        return num_subsets

    def _write_venue_properties(self, venues_group, all_venues):
        """Write venue properties based on per-type configuration."""
        # Group venues by type
        venues_by_type = defaultdict(list)
        for v in all_venues:
            venues_by_type[v.type].append(v)

        # For each type, write configured properties
        props_group = venues_group.create_group('properties')

        for venue_type, venues in venues_by_type.items():
            properties_to_include = self.config.get_venue_properties(venue_type)

            if not properties_to_include:
                continue

            # Create type-specific subgroup
            type_group = props_group.create_group(venue_type)

            for prop_name in properties_to_include:
                # Create array for this property across all venues of this type
                self._write_property_array(type_group, prop_name, venues)

            logger.info(f"    {venue_type}: {len(properties_to_include)} properties ({len(venues)} venues)")

    def _write_subsets(self, venues_group, all_venues):
        """Write subset data to HDF5."""
        subsets_group = venues_group.create_group('subsets')

        # Flatten all subsets from all venues
        all_subsets = []
        for venue in all_venues:
            for subset in venue.subsets.values():
                all_subsets.append(subset)

        if not all_subsets:
            logger.warning("No subsets to serialize")
            return 0

        num_subsets = len(all_subsets)

        # Core attributes
        # IMPORTANT: Use global venue IDs (not type-scoped IDs)
        venue_ids = np.array([self._venue_to_global_id[id(s.venue)] for s in all_subsets], dtype=np.int32)
        subset_indices = np.array([s.subset_index for s in all_subsets], dtype=np.int32)
        subset_names = np.array([s.subset_name for s in all_subsets], dtype=h5py.string_dtype())

        # Member counts (useful for C++)
        member_counts = np.array([len(s.members) for s in all_subsets], dtype=np.int32)

        # Write datasets
        self._create_dataset(subsets_group, 'venue_ids', venue_ids)
        self._create_dataset(subsets_group, 'subset_indices', subset_indices)
        self._create_dataset(subsets_group, 'subset_names', subset_names)
        self._create_dataset(subsets_group, 'member_counts', member_counts)

        # Write member lists (ragged array - need special handling)
        self._write_subset_members(subsets_group, all_subsets)

        return num_subsets

    def _write_subset_members(self, subsets_group, all_subsets):
        """
        Write subset member lists as ragged arrays.

        Uses offset-based encoding:
        - members_flat: Flattened array of all person IDs
        - members_offsets: Start index for each subset
        """
        # Flatten all member lists
        members_flat = []
        members_offsets = [0]  # Start offset

        for subset in all_subsets:
            member_ids = [p.id for p in subset.members]
            members_flat.extend(member_ids)
            members_offsets.append(len(members_flat))

        # Convert to arrays
        members_flat = np.array(members_flat, dtype=np.int32)
        members_offsets = np.array(members_offsets[:-1], dtype=np.int32)  # Drop last offset

        # Write datasets
        self._create_dataset(subsets_group, 'members_flat', members_flat)
        self._create_dataset(subsets_group, 'members_offsets', members_offsets)

        logger.info(f"    Total subset memberships: {len(members_flat):,}")

    def _write_relationships(self, f, world):
        """Write relationship data (activity_map, hierarchies)."""
        rel_group = f.create_group('relationships')

        # Activity map (person → venues via activities)
        if self.config.should_include_activity_map():
            self._write_activity_map(rel_group, world)

    def _write_activity_map(self, rel_group, world):
        """
        Write activity_map data.

        For each person, stores which subsets they belong to for each activity.

        Structure:
        - activity_names: Unique activity names
        - person_activity_flat: Flattened list of (person_id, activity_idx, venue_id, subset_idx)
        - person_activity_offsets: Start index for each person
        """
        activity_map_group = rel_group.create_group('activity_map')

        # Collect all unique activity names
        activity_names_set = set()
        for person in world.population.people:
            activity_names_set.update(person.activities)

        activity_names = sorted(list(activity_names_set))
        activity_to_idx = {name: idx for idx, name in enumerate(activity_names)}

        # Write activity names
        activity_names_array = np.array(activity_names, dtype=h5py.string_dtype())
        self._create_dataset(activity_map_group, 'activity_names', activity_names_array)

        # Flatten activity_map for all people
        # Format: (person_id, activity_idx, venue_id, subset_idx)
        activity_data = []
        activity_offsets = [0]

        for person in world.population.people:
            for activity_name, subsets_or_dict in person.activity_map.items():
                if activity_name not in activity_to_idx:
                    continue  # Skip if activity not in registry

                activity_idx = activity_to_idx[activity_name]

                # Handle two cases:
                # 1. subsets_or_dict is a list of Subsets (e.g., 'residence', 'primary_activity')
                # 2. subsets_or_dict is a dict mapping venue_type → list of Subsets (e.g., 'leisure')

                if isinstance(subsets_or_dict, dict):
                    # Flatten the dict: iterate over all venue types
                    for venue_type, subsets_list in subsets_or_dict.items():
                        if not isinstance(subsets_list, list):
                            logger.warning(f"Person {person.id} activity '{activity_name}' venue_type '{venue_type}': expected list, got {type(subsets_list)}")
                            continue

                        for subset in subsets_list:
                            if not hasattr(subset, 'venue') or not hasattr(subset, 'subset_index'):
                                logger.warning(f"Person {person.id} activity '{activity_name}': invalid subset {type(subset)}")
                                continue

                            # IMPORTANT: Use global venue ID (not type-scoped ID)
                            activity_data.append([
                                person.id,
                                activity_idx,
                                self._venue_to_global_id[id(subset.venue)],
                                subset.subset_index
                            ])

                elif isinstance(subsets_or_dict, list):
                    # Simple list of subsets
                    for subset in subsets_or_dict:
                        if not hasattr(subset, 'venue') or not hasattr(subset, 'subset_index'):
                            logger.warning(f"Person {person.id} activity '{activity_name}': invalid subset {type(subset)}")
                            continue

                        # IMPORTANT: Use global venue ID (not type-scoped ID)
                        activity_data.append([
                            person.id,
                            activity_idx,
                            self._venue_to_global_id[id(subset.venue)],
                            subset.subset_index
                        ])

                else:
                    logger.warning(f"Person {person.id} activity '{activity_name}': unexpected type {type(subsets_or_dict)}")

            activity_offsets.append(len(activity_data))

        # Convert to arrays
        if activity_data:
            activity_data = np.array(activity_data, dtype=np.int32)
        else:
            activity_data = np.zeros((0, 4), dtype=np.int32)

        activity_offsets = np.array(activity_offsets[:-1], dtype=np.int32)

        # Write datasets
        self._create_dataset(activity_map_group, 'activity_data', activity_data)
        self._create_dataset(activity_map_group, 'activity_offsets', activity_offsets)

        logger.info(f"  Activity map: {len(activity_names)} unique activities")
        logger.info(f"    Total activity mappings: {len(activity_data):,}")

    def _write_property_array(self, group, prop_name, objects):
        """
        Write a property array for a list of objects.

        Handles different property types (int, float, str, bool, list, dict).

        Args:
            group: HDF5 group to write to
            prop_name: Property name
            objects: List of objects (Person, Venue, GeographicalUnit)
        """
        # Extract property values
        values = []
        for obj in objects:
            if hasattr(obj, 'properties'):
                val = obj.properties.get(prop_name, None)
            else:
                val = None
            values.append(val)

        # Determine type and convert to array
        if not values or all(v is None for v in values):
            # All None - skip
            logger.debug(f"Skipping property '{prop_name}' (all None)")
            return

        # Infer type from first non-None value
        sample_val = next((v for v in values if v is not None), None)

        if sample_val is None:
            return

        if isinstance(sample_val, bool):
            # Boolean
            arr = np.array([v if v is not None else False for v in values], dtype=np.bool_)
        elif isinstance(sample_val, int):
            # Integer
            arr = np.array([v if v is not None else -1 for v in values], dtype=np.int32)
        elif isinstance(sample_val, float):
            # Float
            arr = np.array([v if v is not None else np.nan for v in values], dtype=np.float32)
        elif isinstance(sample_val, str):
            # String
            arr = np.array([v if v is not None else "" for v in values], dtype=h5py.string_dtype())
        elif isinstance(sample_val, (list, dict)):
            # Complex type - serialize as JSON string
            import json
            arr = np.array([json.dumps(v) if v is not None else "" for v in values],
                          dtype=h5py.string_dtype())
        else:
            # Unknown type - try converting to string
            logger.warning(f"Unknown property type for '{prop_name}': {type(sample_val)}")
            arr = np.array([str(v) if v is not None else "" for v in values],
                          dtype=h5py.string_dtype())

        self._create_dataset(group, prop_name, arr)

    def _create_dataset(self, group, name, data):
        """
        Create HDF5 dataset with compression.

        Args:
            group: HDF5 group
            name: Dataset name
            data: NumPy array
        """
        compression = self.compression_settings['compression']
        compression_level = self.compression_settings['compression_level']

        # Only compress if data is large enough
        if len(data) > 100:
            group.create_dataset(
                name,
                data=data,
                compression=compression,
                compression_opts=compression_level
            )
        else:
            group.create_dataset(name, data=data)
