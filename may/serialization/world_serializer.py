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

            # Write activity mappings
            logger.info("Serializing activity mappings...")
            self._write_activity_mappings(f, world)

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

        logger.info(f"  Serializing {num_people:,} people...")

        # ============================================================
        # SORT BY GEO_UNIT_ID FOR EFFICIENT PARTITIONED LOADING
        # ============================================================
        logger.info(f"    Sorting people by geo_unit_id for partitioning...")

        # Sort people by their geographical unit ID
        people_sorted = sorted(people, key=lambda p: p.geographical_unit.id if p.geographical_unit else -1)

        # Store sorted people for activity mapping serialization
        self._people_sorted = people_sorted

        logger.info(f"    ✓ Sorted {num_people:,} people by geo_unit_id")

        # Core attributes (always included)
        ids = np.array([p.id for p in people_sorted], dtype=np.int32)
        ages = np.array([p.age for p in people_sorted], dtype=np.float32)
        sexes = np.array([p.sex for p in people_sorted], dtype=h5py.string_dtype())

        # Geographical unit IDs (where person lives - SGU level)
        geo_unit_ids = np.array(
            [p.geographical_unit.id if p.geographical_unit else -1 for p in people_sorted],
            dtype=np.int32
        )

        logger.info(f"    ✓ Built core attribute arrays")

        # ============================================================
        # CREATE PARTITION INDEX
        # ============================================================
        logger.info(f"    Building partition index...")
        self._write_partition_index(pop_group, geo_unit_ids)
        logger.info(f"    ✓ Wrote partition index")

        # Write core datasets
        self._create_dataset(pop_group, 'ids', ids)
        self._create_dataset(pop_group, 'ages', ages)
        self._create_dataset(pop_group, 'sexes', sexes)
        self._create_dataset(pop_group, 'geo_unit_ids', geo_unit_ids)

        logger.info(f"    ✓ Wrote core datasets to HDF5")

        # Properties (configured in YAML)
        properties_to_include = self.config.get_person_properties()
        if properties_to_include:
            props_group = pop_group.create_group('properties')

            for prop_idx, prop_name in enumerate(properties_to_include, 1):
                logger.info(f"    Writing property {prop_idx}/{len(properties_to_include)}: {prop_name}...")
                self._write_property_array(props_group, prop_name, people_sorted)

        logger.info(f"  Wrote {num_people:,} people")
        if properties_to_include:
            logger.info(f"    Including properties: {properties_to_include}")

    def _write_partition_index(self, pop_group, geo_unit_ids):
        """
        Write partition index for efficient geo_unit-based loading.

        Creates index structure that maps geo_unit_id -> (start_index, count)
        allowing efficient range-based reads for partitioned loading.

        Args:
            pop_group: HDF5 population group
            geo_unit_ids: Sorted array of geo_unit_ids for all people

        Structure created:
            /population/partition_index/
                geo_unit_ids: [1, 2, 3, ...] - unique geo_unit IDs
                start_indices: [0, 100000, 250000, ...] - start row for each geo_unit
                counts: [100000, 150000, 50000, ...] - number of people per geo_unit
        """
        index_group = pop_group.create_group('partition_index')

        # Find unique geo_unit_ids and their boundaries
        unique_geo_units = []
        start_indices = []
        counts = []

        if len(geo_unit_ids) == 0:
            # Empty population
            logger.warning("Empty population - no partition index to create")
            return

        current_geo_unit = geo_unit_ids[0]
        current_start = 0
        current_count = 0

        for i, geo_unit_id in enumerate(geo_unit_ids):
            if geo_unit_id != current_geo_unit:
                # Save previous geo_unit
                unique_geo_units.append(current_geo_unit)
                start_indices.append(current_start)
                counts.append(current_count)

                # Start new geo_unit
                current_geo_unit = geo_unit_id
                current_start = i
                current_count = 1
            else:
                current_count += 1

        # Save last geo_unit
        unique_geo_units.append(current_geo_unit)
        start_indices.append(current_start)
        counts.append(current_count)

        # Convert to numpy arrays
        unique_geo_units = np.array(unique_geo_units, dtype=np.int32)
        start_indices = np.array(start_indices, dtype=np.int32)
        counts = np.array(counts, dtype=np.int32)

        # Write datasets
        self._create_dataset(index_group, 'geo_unit_ids', unique_geo_units)
        self._create_dataset(index_group, 'start_indices', start_indices)
        self._create_dataset(index_group, 'counts', counts)

        logger.info(f"      Created partition index for {len(unique_geo_units)} geo_units")
        logger.info(f"      Min people per geo_unit: {counts.min()}")
        logger.info(f"      Max people per geo_unit: {counts.max()}")
        logger.info(f"      Avg people per geo_unit: {counts.mean():.1f}")

    def _write_activity_mapping_partition_index(self, activity_map_group, people_sorted, activity_offsets, total_activity_mappings):
        """
        Write partition index for efficient geo_unit-based activity mapping loading.

        Creates index structure that maps geo_unit_id -> (start_row, count)
        for the activity_data array, allowing efficient range-based reads.

        Args:
            activity_map_group: HDF5 activity_map group
            people_sorted: People list sorted by geo_unit_id
            activity_offsets: Array of start indices for each person's activity mappings
            total_activity_mappings: Total number of rows in activity_data

        Structure created:
            /activity_mappings/activity_map/partition_index/
                geo_unit_ids: [1, 2, 3, ...] - unique geo_unit IDs
                start_indices: [0, 500000, 1250000, ...] - start row in activity_data
                counts: [500000, 750000, 300000, ...] - number of mapping rows per geo_unit
        """
        index_group = activity_map_group.create_group('partition_index')

        if len(people_sorted) == 0:
            logger.warning("Empty population - no activity mapping partition index to create")
            return

        # Group people by geo_unit and track activity mapping row ranges
        unique_geo_units = []
        start_indices = []
        counts = []

        current_geo_unit = people_sorted[0].geographical_unit.id if people_sorted[0].geographical_unit else -1
        current_start_row = 0  # Start row in activity_data for this geo_unit

        for person_idx, person in enumerate(people_sorted):
            geo_unit_id = person.geographical_unit.id if person.geographical_unit else -1

            if geo_unit_id != current_geo_unit:
                # Save previous geo_unit's activity mapping range
                # End row is the start of current person's activity mappings
                end_row = activity_offsets[person_idx] if person_idx < len(activity_offsets) else total_activity_mappings
                activity_mappings_count = end_row - current_start_row

                unique_geo_units.append(current_geo_unit)
                start_indices.append(current_start_row)
                counts.append(activity_mappings_count)

                # Start new geo_unit
                current_geo_unit = geo_unit_id
                current_start_row = end_row

        # Save last geo_unit (activity mappings extend to end of activity_data)
        activity_mappings_count = total_activity_mappings - current_start_row
        unique_geo_units.append(current_geo_unit)
        start_indices.append(current_start_row)
        counts.append(activity_mappings_count)

        # Convert to numpy arrays
        unique_geo_units = np.array(unique_geo_units, dtype=np.int32)
        start_indices = np.array(start_indices, dtype=np.int32)
        counts = np.array(counts, dtype=np.int32)

        # Write datasets
        self._create_dataset(index_group, 'geo_unit_ids', unique_geo_units)
        self._create_dataset(index_group, 'start_indices', start_indices)
        self._create_dataset(index_group, 'counts', counts)

        logger.info(f"      Created activity mapping partition index for {len(unique_geo_units)} geo_units")
        if len(counts) > 0:
            logger.info(f"      Min mappings per geo_unit: {counts.min()}")
            logger.info(f"      Max mappings per geo_unit: {counts.max()}")
            logger.info(f"      Avg mappings per geo_unit: {counts.mean():.1f}")

    def _write_subset_metadata_partition_index(self, subsets_group, all_subsets_sorted):
        """
        Write partition index for efficient geo_unit-based subset metadata loading.

        Creates index structure that maps geo_unit_id -> (start_index, count)
        for the subset metadata arrays (venue_ids, subset_indices, etc.),
        allowing efficient range-based reads without scanning all 35M venue_ids.

        Args:
            subsets_group: HDF5 subsets group
            all_subsets_sorted: Subsets list sorted by venue's geo_unit_id

        Structure created:
            /venues/subsets/partition_index/
                geo_unit_ids: [1, 2, 3, ...] - unique geo_unit IDs
                start_indices: [0, 1000, 3500, ...] - start row in subset arrays
                counts: [1000, 2500, 750, ...] - number of subsets per geo_unit
        """
        index_group = subsets_group.create_group('partition_index')

        if len(all_subsets_sorted) == 0:
            logger.warning("Empty subsets - no metadata partition index to create")
            return

        # Find unique geo_unit_ids and their boundaries
        unique_geo_units = []
        start_indices = []
        counts = []

        current_geo_unit = all_subsets_sorted[0].venue.geographical_unit.id if all_subsets_sorted[0].venue.geographical_unit else -1
        current_start = 0
        current_count = 0

        for i, subset in enumerate(all_subsets_sorted):
            geo_unit_id = subset.venue.geographical_unit.id if subset.venue.geographical_unit else -1

            if geo_unit_id != current_geo_unit:
                # Save previous geo_unit
                unique_geo_units.append(current_geo_unit)
                start_indices.append(current_start)
                counts.append(current_count)

                # Start new geo_unit
                current_geo_unit = geo_unit_id
                current_start = i
                current_count = 1
            else:
                current_count += 1

        # Save last geo_unit
        unique_geo_units.append(current_geo_unit)
        start_indices.append(current_start)
        counts.append(current_count)

        # Convert to numpy arrays
        unique_geo_units = np.array(unique_geo_units, dtype=np.int32)
        start_indices = np.array(start_indices, dtype=np.int32)
        counts = np.array(counts, dtype=np.int32)

        # Write datasets
        self._create_dataset(index_group, 'geo_unit_ids', unique_geo_units)
        self._create_dataset(index_group, 'start_indices', start_indices)
        self._create_dataset(index_group, 'counts', counts)

        logger.info(f"      Created subset metadata partition index for {len(unique_geo_units)} geo_units")
        if len(counts) > 0:
            logger.info(f"      Min subsets per geo_unit: {counts.min()}")
            logger.info(f"      Max subsets per geo_unit: {counts.max()}")
            logger.info(f"      Avg subsets per geo_unit: {counts.mean():.1f}")

    def _write_subset_members_partition_index(self, subsets_group, all_subsets_sorted, members_offsets, total_members):
        """
        Write partition index for efficient geo_unit-based subset membership loading.

        Creates index structure that maps geo_unit_id -> (start_row, count)
        for the members_flat array, allowing efficient range-based reads.

        Args:
            subsets_group: HDF5 subsets group
            all_subsets_sorted: Subsets list sorted by venue's geo_unit_id
            members_offsets: Array of start indices for each subset's members in members_flat
            total_members: Total number of entries in members_flat

        Structure created:
            /venues/subsets/members_partition_index/
                geo_unit_ids: [1, 2, 3, ...] - unique geo_unit IDs
                start_indices: [0, 50000, 125000, ...] - start row in members_flat
                counts: [50000, 75000, 30000, ...] - number of members per geo_unit
        """
        index_group = subsets_group.create_group('members_partition_index')

        if len(all_subsets_sorted) == 0:
            logger.warning("Empty subsets - no partition index to create")
            return

        # Group subsets by geo_unit and track membership row ranges
        unique_geo_units = []
        start_indices = []
        counts = []

        current_geo_unit = all_subsets_sorted[0].venue.geographical_unit.id if all_subsets_sorted[0].venue.geographical_unit else -1
        current_start_row = 0  # Start row in members_flat for this geo_unit

        for subset_idx, subset in enumerate(all_subsets_sorted):
            geo_unit_id = subset.venue.geographical_unit.id if subset.venue.geographical_unit else -1

            if geo_unit_id != current_geo_unit:
                # Save previous geo_unit's membership range
                # End row is the start of current subset's members
                end_row = members_offsets[subset_idx] if subset_idx < len(members_offsets) else total_members
                member_count = end_row - current_start_row

                unique_geo_units.append(current_geo_unit)
                start_indices.append(current_start_row)
                counts.append(member_count)

                # Start new geo_unit
                current_geo_unit = geo_unit_id
                current_start_row = end_row

        # Save last geo_unit (members extend to end of members_flat)
        member_count = total_members - current_start_row
        unique_geo_units.append(current_geo_unit)
        start_indices.append(current_start_row)
        counts.append(member_count)

        # Convert to numpy arrays
        unique_geo_units = np.array(unique_geo_units, dtype=np.int32)
        start_indices = np.array(start_indices, dtype=np.int32)
        counts = np.array(counts, dtype=np.int32)

        # Write datasets
        self._create_dataset(index_group, 'geo_unit_ids', unique_geo_units)
        self._create_dataset(index_group, 'start_indices', start_indices)
        self._create_dataset(index_group, 'counts', counts)

        logger.info(f"      Created subset partition index for {len(unique_geo_units)} geo_units")
        if len(counts) > 0:
            logger.info(f"      Min members per geo_unit: {counts.min()}")
            logger.info(f"      Max members per geo_unit: {counts.max()}")
            logger.info(f"      Avg members per geo_unit: {counts.mean():.1f}")

    def _write_venue_partition_index(self, venues_group, all_venues_sorted):
        """
        Write partition index for efficient geo_unit-based venue loading.

        Creates index structure that maps geo_unit_id -> (start_index, count)
        for the venue arrays, allowing efficient range-based reads.

        Args:
            venues_group: HDF5 venues group
            all_venues_sorted: Venues list sorted by geo_unit_id

        Structure created:
            /venues/partition_index/
                geo_unit_ids: [1, 2, 3, ...] - unique geo_unit IDs
                start_indices: [0, 100, 350, ...] - start row in venue arrays
                counts: [100, 250, 75, ...] - number of venues per geo_unit
        """
        index_group = venues_group.create_group('partition_index')

        if len(all_venues_sorted) == 0:
            logger.warning("Empty venues - no partition index to create")
            return

        # Find unique geo_unit_ids and their boundaries
        unique_geo_units = []
        start_indices = []
        counts = []

        current_geo_unit = all_venues_sorted[0].geographical_unit.id if all_venues_sorted[0].geographical_unit else -1
        current_start = 0
        current_count = 0

        for i, venue in enumerate(all_venues_sorted):
            geo_unit_id = venue.geographical_unit.id if venue.geographical_unit else -1

            if geo_unit_id != current_geo_unit:
                # Save previous geo_unit
                unique_geo_units.append(current_geo_unit)
                start_indices.append(current_start)
                counts.append(current_count)

                # Start new geo_unit
                current_geo_unit = geo_unit_id
                current_start = i
                current_count = 1
            else:
                current_count += 1

        # Save last geo_unit
        unique_geo_units.append(current_geo_unit)
        start_indices.append(current_start)
        counts.append(current_count)

        # Convert to numpy arrays
        unique_geo_units = np.array(unique_geo_units, dtype=np.int32)
        start_indices = np.array(start_indices, dtype=np.int32)
        counts = np.array(counts, dtype=np.int32)

        # Write datasets
        self._create_dataset(index_group, 'geo_unit_ids', unique_geo_units)
        self._create_dataset(index_group, 'start_indices', start_indices)
        self._create_dataset(index_group, 'counts', counts)

        logger.info(f"      Created venue partition index for {len(unique_geo_units)} geo_units")
        logger.info(f"      Min venues per geo_unit: {counts.min()}")
        logger.info(f"      Max venues per geo_unit: {counts.max()}")
        logger.info(f"      Avg venues per geo_unit: {counts.mean():.1f}")

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

        # ============================================================
        # SORT BY GEO_UNIT_ID FOR EFFICIENT PARTITIONED LOADING
        # ============================================================
        logger.info(f"    Sorting {num_venues:,} venues by geo_unit_id for partitioning...")

        # Sort venues by their geographical unit ID
        all_venues_sorted = sorted(
            all_venues,
            key=lambda v: v.geographical_unit.id if v.geographical_unit else -1
        )

        logger.info(f"    ✓ Sorted {num_venues:,} venues by geo_unit_id")

        # CRITICAL: Venue IDs in Python are TYPE-SCOPED (each type has its own ID counter starting at 0)
        # This causes collisions: hospital_0, school_0, office_0 all have id=0
        # For C++, we need GLOBAL unique IDs. Assign sequential global IDs here.

        # Assign global IDs (0, 1, 2, ..., N-1) to SORTED venues
        global_ids = np.arange(num_venues, dtype=np.int32)

        # Create mapping for faster lookup during activity map export
        self._venue_to_global_id = {}
        for v, global_id in zip(all_venues_sorted, global_ids):
            self._venue_to_global_id[id(v)] = global_id

        # Also store type-scoped IDs for debugging/reference
        type_scoped_ids = np.array([v.id for v in all_venues_sorted], dtype=np.int32)

        # Core attributes (always included)
        ids = global_ids  # Use GLOBAL IDs for C++
        names = np.array([v.name for v in all_venues_sorted], dtype=h5py.string_dtype())
        types = np.array([v.type for v in all_venues_sorted], dtype=h5py.string_dtype())

        # Geographical unit IDs (where venue is located)
        geo_unit_ids = np.array(
            [v.geographical_unit.id if v.geographical_unit else -1 for v in all_venues_sorted],
            dtype=np.int32
        )

        # Parent venue IDs (-1 for root venues)
        # IMPORTANT: Use global IDs for parents too!
        parent_ids = np.array(
            [self._venue_to_global_id.get(id(v.parent), -1) if v.parent else -1 for v in all_venues_sorted],
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
                [v.coordinates[0] if v.coordinates else np.nan for v in all_venues_sorted],
                dtype=np.float32
            )
            longitudes = np.array(
                [v.coordinates[1] if v.coordinates else np.nan for v in all_venues_sorted],
                dtype=np.float32
            )

            self._create_dataset(venues_group, 'latitudes', latitudes)
            self._create_dataset(venues_group, 'longitudes', longitudes)

        # is_residence flag (optional)
        if venue_global_settings.get('include_is_residence', True):
            is_residence = np.array(
                [v.properties.get('is_residence', False) for v in all_venues_sorted],
                dtype=np.bool_
            )
            self._create_dataset(venues_group, 'is_residence', is_residence)

        # ============================================================
        # CREATE PARTITION INDEX FOR VENUES
        # ============================================================
        logger.info(f"    Building venue partition index...")
        self._write_venue_partition_index(venues_group, all_venues_sorted)
        logger.info(f"    ✓ Wrote venue partition index")

        # Properties (per-type configuration)
        self._write_venue_properties(venues_group, all_venues_sorted)

        # Write subsets
        num_subsets = self._write_subsets(venues_group, all_venues_sorted)

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

        # ============================================================
        # SORT BY VENUE'S GEO_UNIT_ID FOR EFFICIENT PARTITIONED LOADING
        # ============================================================
        logger.info(f"    Sorting {num_subsets:,} subsets by venue's geo_unit_id for partitioning...")

        # Sort subsets by their venue's geographical unit ID
        all_subsets_sorted = sorted(
            all_subsets,
            key=lambda s: s.venue.geographical_unit.id if s.venue.geographical_unit else -1
        )

        logger.info(f"    ✓ Sorted {num_subsets:,} subsets by venue's geo_unit_id")

        # Core attributes
        # IMPORTANT: Use global venue IDs (not type-scoped IDs)
        venue_ids = np.array([self._venue_to_global_id[id(s.venue)] for s in all_subsets_sorted], dtype=np.int32)
        subset_indices = np.array([s.subset_index for s in all_subsets_sorted], dtype=np.int32)
        subset_names = np.array([s.subset_name for s in all_subsets_sorted], dtype=h5py.string_dtype())

        # Member counts (useful for C++)
        member_counts = np.array([len(s.members) for s in all_subsets_sorted], dtype=np.int32)

        # ============================================================
        # CREATE PARTITION INDEX FOR SUBSET METADATA
        # ============================================================
        logger.info(f"    Building subset metadata partition index...")
        self._write_subset_metadata_partition_index(subsets_group, all_subsets_sorted)
        logger.info(f"    ✓ Wrote subset metadata partition index")

        # Write datasets
        self._create_dataset(subsets_group, 'venue_ids', venue_ids)
        self._create_dataset(subsets_group, 'subset_indices', subset_indices)
        self._create_dataset(subsets_group, 'subset_names', subset_names)
        self._create_dataset(subsets_group, 'member_counts', member_counts)

        # Write member lists (ragged array - need special handling)
        self._write_subset_members(subsets_group, all_subsets_sorted)

        return num_subsets

    def _write_subset_members(self, subsets_group, all_subsets):
        """
        Write subset member lists as ragged arrays with partition indexing.

        Uses offset-based encoding:
        - members_flat: Flattened array of all person IDs (sorted by venue's geo_unit_id)
        - members_offsets: Start index for each subset
        - partition_index: geo_unit-based index for efficient partitioned loading
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

        # ============================================================
        # CREATE PARTITION INDEX FOR SUBSET MEMBERSHIPS
        # ============================================================
        logger.info(f"    Building subset members partition index...")
        total_members = len(members_flat)
        self._write_subset_members_partition_index(subsets_group, all_subsets, members_offsets, total_members)
        logger.info(f"    ✓ Wrote subset members partition index")

        # Write datasets
        self._create_dataset(subsets_group, 'members_flat', members_flat)
        self._create_dataset(subsets_group, 'members_offsets', members_offsets)

        logger.info(f"    Total subset memberships: {len(members_flat):,}")

    def _write_activity_mappings(self, f, world):
        """Write activity mapping data (activity_map, hierarchies)."""
        rel_group = f.create_group('activity_mappings')

        # Activity map (person → venues via activities)
        if self.config.should_include_activity_map():
            # Use sorted people order (same as population)
            people_sorted = getattr(self, '_people_sorted', world.population.people)
            self._write_activity_map(rel_group, world, people_sorted)

    def _write_activity_map(self, rel_group, world, people_sorted):
        """
        Write activity_map data.

        For each person, stores which subsets they belong to for each activity.

        Structure:
        - activity_names: Unique activity names
        - person_activity_flat: Flattened list of (person_id, activity_idx, venue_id, subset_idx)
        - person_activity_offsets: Start index for each person
        - partition_index: geo_unit-based index for efficient partitioned loading

        Args:
            rel_group: HDF5 activity mapping group
            world: World object
            people_sorted: People list sorted by geo_unit_id
        """
        activity_map_group = rel_group.create_group('activity_map')

        # Collect all unique activity names
        activity_names_set = set()
        for person in people_sorted:
            activity_names_set.update(person.activities)

        activity_names = sorted(list(activity_names_set))
        activity_to_idx = {name: idx for idx, name in enumerate(activity_names)}

        # Write activity names
        activity_names_array = np.array(activity_names, dtype=h5py.string_dtype())
        self._create_dataset(activity_map_group, 'activity_names', activity_names_array)

        # Flatten activity_map for all people
        # Format: (person_id, activity_idx, venue_id, subset_idx)
        # Use separate lists for integer values to avoid list-of-lists overhead
        p_ids = []
        a_idxs = []
        v_ids_list = []
        s_idxs = []
        activity_offsets = [0]

        # Progress tracking
        num_people = len(people_sorted)
        progress_interval = max(1, num_people // 10)  # Update every 10%

        # Cache activity indices to avoid dict lookup in inner loop
        activity_indices = {name: activity_to_idx[name] for name in activity_names}
        venue_to_id = self._venue_to_global_id

        for person_idx, person in enumerate(people_sorted, 1):
            person_id = person.id
            activity_map = person.activity_map
            
            # Accessing activities directly to avoid repeated .items() calls if possible
            # However, we need both name and types, so items() is generally okay if
            # the dict is small. The real bottleneck is the intermediate list.
            for name, types in activity_map.items():
                if name in activity_to_idx:
                    act_idx = activity_to_idx[name]
                    for subsets_list in types.values():
                        for subset in subsets_list:
                            v_id = id(subset.venue)
                            if v_id in venue_to_id:
                                p_ids.append(person_id)
                                a_idxs.append(act_idx)
                                v_ids_list.append(venue_to_id[v_id])
                                s_idxs.append(subset.subset_index)

            activity_offsets.append(len(p_ids))

            # Log progress
            if person_idx % progress_interval == 0 or person_idx == num_people:
                progress = (person_idx / num_people) * 100
                logger.info(f"    Progress: {person_idx:,}/{num_people:,} people processed ({progress:.1f}%) - {len(p_ids):,} mappings")

        # Convert to a single 2D array
        if p_ids:
            activity_data = np.empty((len(p_ids), 4), dtype=np.int32)
            activity_data[:, 0] = p_ids
            activity_data[:, 1] = a_idxs
            activity_data[:, 2] = v_ids_list
            activity_data[:, 3] = s_idxs
        else:
            activity_data = np.zeros((0, 4), dtype=np.int32)

        activity_offsets = np.array(activity_offsets[:-1], dtype=np.int32)

        # ============================================================
        # CREATE PARTITION INDEX FOR ACTIVITY MAPS
        # ============================================================
        logger.info(f"  Building activity mapping partition index...")
        total_activity_mappings = len(activity_data)
        self._write_activity_mapping_partition_index(activity_map_group, people_sorted, activity_offsets, total_activity_mappings)
        logger.info(f"    ✓ Wrote activity mapping partition index")

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
        # Extract property values (Optimized list comprehension)
        # Assuming all objects are of the same class or have 'properties'
        values = [obj.properties.get(prop_name) for obj in objects]

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
            # Pre-allocate for performance if string length is predictable, but h5py.string_dtype is flexible
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
