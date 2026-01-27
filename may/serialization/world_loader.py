"""
World loader for importing from HDF5 format.

Loads world state (geography, population, venues) from HDF5 file
created by WorldSerializer.export_to_hdf5().
"""

import logging
import h5py
import numpy as np
from .serialization_config import SerializationConfig
import time

logger = logging.getLogger("world_loader")


def load_world_from_hdf5(input_file, config_file="yaml/serialization_config.yaml"):
    """
    Load a World object from an HDF5 file created by export_to_hdf5.

    This method deserializes the complete world state (geography, population,
    venues, and relationships) from an HDF5 file.

    Args:
        input_file: Path to input HDF5 file
        config_file: Path to serialization YAML config (default: yaml/serialization_config.yaml)

    Returns:
        World: Reconstructed World object with geography, population, venues, and relationships

    Example:
        >>> from may.serialization import load_world_from_hdf5
        >>> world = load_world_from_hdf5("world_state.h5")
        >>> print(world)
        <World: 1000 units, 95,231 people, 36,443 venues (36,443 households, 0 other)>
    """
    from may.world import World

    logger.info("")
    logger.info("=" * 60)
    logger.info("LOADING WORLD FROM HDF5")
    logger.info("=" * 60)
    logger.info(f"Input file: {input_file}")

    config = SerializationConfig(config_file)

    with h5py.File(input_file, 'r') as f:
        # Read metadata
        logger.info("Reading metadata...")
        num_people = f.attrs.get('num_people', 0)
        num_venues = f.attrs.get('num_venues', 0)
        num_geo_units = f.attrs.get('num_geo_units', 0)

        logger.info(f"  Geography units: {num_geo_units:,}")
        logger.info(f"  People: {num_people:,}")
        logger.info(f"  Venues: {num_venues:,}")

        # Load Geography
        geography = None
        if 'geography' in f:
            logger.info("Loading geography...")
            try:
                geography = _load_geography(f['geography'], config)
            except Exception as e:
                logger.error(f"Failed to load geography: {e}")
                raise
        else:
            logger.error("No geography data found in HDF5 file")
            raise OSError
        
        # Load Population
        laptime = time.perf_counter()
        population = None
        if 'population' in f:
            logger.info("Loading population...")
            try:
                population = _load_population(f['population'], geography, config)
            except Exception as e:
                logger.warning(f"Failed to load population: {e}")
                logger.warning("World will be created without population")
        else:
            logger.warning("No population data found in HDF5 file")
            logger.warning("World will be created without population")
        logger.info(f"Population created in {time.perf_counter() - laptime:.2f} seconds")
        # Load Venues
        venue_manager = None
        if 'venues' in f:
            logger.info("Loading venues...")
            try:
                venue_manager = _load_venues(f['venues'], geography, config)
            except Exception as e:
                logger.warning(f"Failed to load venues: {e}")
                logger.warning("World will be created without venues")
        else:
            logger.warning("No venue data found in HDF5 file")
            logger.warning("World will be created without venues")

        # Load Relationships (activity_map)
        if 'relationships' in f and config.should_include_activity_map():
            logger.info("Loading relationships...")
            try:
                if population and venue_manager:
                    _load_relationships(f['relationships'], population, venue_manager)
                else:
                    logger.warning("Cannot load relationships: population or venues missing")
            except Exception as e:
                logger.warning(f"Failed to load relationships: {e}")
                logger.warning("World will be created without relationships")
        elif 'relationships' not in f:
            logger.info("No relationship data found in HDF5 file")

    # Create World object
    world = World(geography=geography, population=population, venues=venue_manager)

    logger.info("")
    logger.info("Load complete")
    logger.info(f"  {world}")
    logger.info("-" * 50)

    return world


def _load_geography(geo_group, config):
    """Reconstruct Geography hierarchy from HDF5."""
    from may.geography import Geography, GeographicalUnit

    # Read core datasets
    ids = geo_group['ids'][:]
    names = geo_group['names'][:].astype(str)
    levels = geo_group['levels'][:].astype(str) # Only unique levels
    unique_levels = list(dict.fromkeys(levels)) # Only unique levels
    parent_ids = geo_group['parent_ids'][:]

    # Read optional coordinates
    latitudes = None
    longitudes = None
    if 'latitudes' in geo_group and 'longitudes' in geo_group:
        latitudes = geo_group['latitudes'][:]
        longitudes = geo_group['longitudes'][:]

    # Read properties if present
    properties_by_unit = {}
    if 'properties' in geo_group:
        props_group = geo_group['properties']
        for prop_name in props_group.keys():
            prop_data = props_group[prop_name][:]
            # if prop_data.dtype.kind == 'S' or prop_data.dtype.kind == 'O':
            #     prop_data = prop_data.astype(str)
            properties_by_unit[prop_name] = prop_data

    # Create Geography object
    geography = Geography(levels=unique_levels)

    # Create all units first (without parent links, as the parent unit might not exist yet)
    # Creates it as a dict object as it's hashable, so quick for setting the parent relationships
    units_by_id = {}
    for i, (unit_id, name, level) in enumerate(zip(ids, names, levels)):
        coordinates = None
        if latitudes is not None and not np.isnan(latitudes[i]):
            coordinates = (latitudes[i], longitudes[i])

        # Collect properties for this unit
        properties = {}
        for prop_name, prop_array in properties_by_unit.items():
            properties[prop_name] = prop_array[i]

        unit = GeographicalUnit(
            unit_id,
            name=name,
            level=level,
            parent=None,  # Will be set in next pass
            coordinates=coordinates,
            properties=properties
        )
        units_by_id[unit_id] = unit

    # Set parent relationships
    for i, (unit_id, parent_id) in enumerate(zip(ids, parent_ids)):
        if parent_id != -1:
            units_by_id[unit_id].parent = units_by_id[parent_id]

    # Add units to Geography
    geography.add_geo_units(units_by_id.values())

    logger.info(f"  Loaded {len(units_by_id)} geographical units")

    return geography


def _load_population(pop_group, geography, config):
    """Reconstruct PopulationManager with Person objects from HDF5."""
    from may.population import PopulationManager, Person

    # Read core datasets
    ids = pop_group['ids'][:]
    ages = pop_group['ages'][:]
    sexes = pop_group['sexes'][:].astype(str)
    geo_unit_ids = pop_group['geo_unit_ids'][:]

    # Read properties if present
    properties_by_person = {}
    if 'properties' in pop_group:
        props_group = pop_group['properties']
        for prop_name in props_group.keys():
            prop_data = props_group[prop_name][:]
            if prop_data.dtype.kind == 'S' or prop_data.dtype.kind == 'O':
                # Check if it's JSON-encoded
                try:
                    import json
                    prop_data = [json.loads(val) if val else None for val in prop_data.astype(str)]
                except:
                    prop_data = prop_data.astype(str)
            properties_by_person[prop_name] = prop_data

    # Create PopulationManager
    population = PopulationManager(geography, 'dummy_data_dir')

    # Get all geo units for lookup (by ID, not name)
    all_units = geography.units_by_id

    # Create Person objects
    num_people = len(ids)
    progress_interval = max(1, num_people // 10)

    for i, (person_id, age, sex, geo_unit_id) in enumerate(zip(ids, ages, sexes, geo_unit_ids)):
        # Find geographical unit
        geo_unit = all_units.get(geo_unit_id)

        # Collect properties for this person
        properties = {}
        for prop_name, prop_array in properties_by_person.items():
            properties[prop_name] = prop_array[i]

        # Create Person
        person = Person(age=age, sex=sex, geographical_unit=geo_unit, properties=properties)
        person.id = person_id  # Restore original ID

        # Add to population
        population.add_person(person)
        # Add to geo_unit
        geo_unit.people.append(person)
        
        # Log progress
        if (i+1) % progress_interval == 0 or (i+1) == num_people:
            progress = ((i+1) / num_people) * 100
            logger.info(f"    Progress: {i:,}/{num_people:,} people loaded ({progress:.1f}%)")

    logger.info(f"  Loaded {len(population.people):,} people")

    return population


def _load_venues(venues_group, geography, config):
    """Reconstruct VenueManager with Venue and Subset objects from HDF5."""
    from may.geography import VenueManager, Venue

    # Read core venue datasets
    ids = venues_group['ids'][:]
    names = venues_group['names'][:].astype(str)
    types = venues_group['types'][:].astype(str)
    geo_unit_ids = venues_group['geo_unit_ids'][:]
    parent_ids = venues_group['parent_ids'][:]

    # Read optional datasets
    latitudes = None
    longitudes = None
    if 'latitudes' in venues_group and 'longitudes' in venues_group:
        latitudes = venues_group['latitudes'][:]
        longitudes = venues_group['longitudes'][:]

    is_residence = None
    if 'is_residence' in venues_group:
        is_residence = venues_group['is_residence'][:]

    # Read properties by type
    properties_by_venue_type = {}
    if 'properties' in venues_group:
        props_group = venues_group['properties']
        for venue_type in props_group.keys():
            type_group = props_group[venue_type]
            properties_by_venue_type[venue_type] = {}
            for prop_name in type_group.keys():
                prop_data = type_group[prop_name][:]
                if prop_data.dtype.kind == 'S' or prop_data.dtype.kind == 'O':
                    try:
                        import json
                        prop_data = [json.loads(val) if val else None for val in prop_data.astype(str)]
                    except:
                        prop_data = prop_data.astype(str)
                properties_by_venue_type[venue_type][prop_name] = prop_data

    # Create VenueManager
    venue_manager = VenueManager(geography, filter_by_geography=False)

    # Get all geo units for lookup (by ID, not name)
    all_units = geography.units_by_id

    # Create Venue objects first (without parent links)
    num_venues = len(ids)
    venues_by_global_id = {}
    venue_type_counters = {}  # Track type-specific indices for properties

    for i, (venue_id, name, venue_type, geo_unit_id) in enumerate(zip(ids, names, types, geo_unit_ids)):
        # Get type-specific index for property lookup
        type_idx = venue_type_counters.get(venue_type, 0)
        venue_type_counters[venue_type] = type_idx + 1

        # Find geographical unit
        geo_unit = all_units.get(geo_unit_id)

        # Coordinates
        coordinates = None
        if latitudes is not None and not np.isnan(latitudes[i]):
            coordinates = (latitudes[i], longitudes[i])

        # Collect properties for this venue
        properties = {}
        if is_residence is not None:
            properties['is_residence'] = bool(is_residence[i])

        if venue_type in properties_by_venue_type:
            for prop_name, prop_array in properties_by_venue_type[venue_type].items():
                properties[prop_name] = prop_array[type_idx]

        # Create Venue
        venue = Venue(
            name=name,
            venue_type=venue_type,
            geographical_unit=geo_unit,
            coordinates=coordinates,
            properties=properties
        )
        # Note: venue.id will be set by VenueManager (type-scoped), but we track global ID
        venue_manager.add_venue(venue)
        venues_by_global_id[venue_id] = venue

    # Set parent relationships
    for venue_id, parent_id in zip(ids, parent_ids):
        if parent_id != -1:
            venues_by_global_id[venue_id].parent = venues_by_global_id[parent_id]

    logger.info(f"  Loaded {num_venues:,} venues")

    # Load subsets
    subsets_by_venue_and_index = {}
    if 'subsets' in venues_group:
        subsets_by_venue_and_index = _load_subsets(venues_group['subsets'], venues_by_global_id)

    # Store mapping for relationship loading
    venue_manager._subsets_by_venue_and_index = subsets_by_venue_and_index
    venue_manager._venues_by_global_id = venues_by_global_id

    return venue_manager


def _load_subsets(subsets_group, venues_by_global_id):
    """Load Subset objects and assign to venues."""
    from may.population.subset import Subset

    # Read subset metadata
    venue_ids = subsets_group['venue_ids'][:]
    subset_indices = subsets_group['subset_indices'][:]
    subset_names = subsets_group['subset_names'][:].astype(str)
    member_counts = subsets_group['member_counts'][:]

    # Read member lists (ragged array)
    members_flat = subsets_group['members_flat'][:]
    members_offsets = subsets_group['members_offsets'][:]

    num_subsets = len(venue_ids)

    # Create Subset objects (members will be added later during relationship loading)
    subsets_by_venue_and_index = {}

    for i, (venue_id, subset_idx, subset_name) in enumerate(zip(venue_ids, subset_indices, subset_names)):
        venue = venues_by_global_id[venue_id]

        # Create Subset
        subset = Subset(venue=venue, subset_index=subset_idx, subset_name=subset_name)

        # Add to venue
        venue.subsets[subset_name] = subset

        # Store for relationship loading
        subsets_by_venue_and_index[(venue_id, subset_idx)] = subset

    logger.info(f"  Loaded {num_subsets:,} subsets")

    return subsets_by_venue_and_index


def _load_relationships(rel_group, population, venue_manager):
    """Load activity_map relationships between people and venues."""
    if 'activity_map' not in rel_group:
        return

    activity_map_group = rel_group['activity_map']

    # Read activity names
    activity_names = activity_map_group['activity_names'][:].astype(str)

    # Read activity data (person_id, activity_idx, venue_id, subset_idx)
    activity_data = activity_map_group['activity_data'][:]
    activity_offsets = activity_map_group['activity_offsets'][:]

    logger.info(f"  Loading {len(activity_data):,} activity mappings...")

    # Get venue and subset mappings from venue_manager
    venues_by_global_id = venue_manager._venues_by_global_id
    subsets_by_venue_and_index = venue_manager._subsets_by_venue_and_index

    # Process activity mappings
    num_people = len(activity_offsets)
    progress_interval = max(1, num_people // 10)

    for person_idx in range(num_people):
        # Get person_id from first row of their activity data
        if person_idx < len(activity_offsets):
            start_idx = activity_offsets[person_idx]
            if start_idx < len(activity_data):
                person_id = activity_data[start_idx, 0]
            else:
                continue
        else:
            continue

        person = population.get_person(person_id)

        if person is None:
            continue

        # Get all activity mappings for this person
        start_idx = activity_offsets[person_idx]
        end_idx = activity_offsets[person_idx + 1] if person_idx + 1 < len(activity_offsets) else len(activity_data)

        for row in activity_data[start_idx:end_idx]:
            _, activity_idx, venue_id, subset_idx = row

            activity_name = activity_names[activity_idx]
            venue = venues_by_global_id.get(venue_id)

            if venue is None:
                continue

            # Find the subset using the mapping
            subset = subsets_by_venue_and_index.get((venue_id, subset_idx))

            if subset is None:
                continue

            # Add to person's activity_map (unified structure)
            if activity_name not in person.activity_map:
                person.activity_map[activity_name] = {}

            venue_type = venue.type
            if venue_type not in person.activity_map[activity_name]:
                person.activity_map[activity_name][venue_type] = []

            person.activity_map[activity_name][venue_type].append(subset)

            # Add person to subset
            if person not in subset.members:
                subset.members.append(person)

            # Add to person's activities list if not present
            if activity_name not in person.activities:
                person.activities.append(activity_name)

        # Log progress
        if (person_idx + 1) % progress_interval == 0 or person_idx + 1 == num_people:
            progress = ((person_idx + 1) / num_people) * 100
            logger.info(f"    Progress: {person_idx + 1:,}/{num_people:,} people processed ({progress:.1f}%)")

    logger.info(f"  Loaded activity relationships")

    # Clean up temporary attributes
    delattr(venue_manager, '_subsets_by_venue_and_index')
    delattr(venue_manager, '_venues_by_global_id')
