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


class _CountOnlySet:
    """Lightweight substitute for Subset.members used in slim loading mode.

    Stores only the member count so that ``len(subset.members)`` returns the
    correct value from HDF5 without holding any Person references in memory.
    Allows the world to be visualised (member counts, venue stats) without
    the ~1–2 GB of memory that the full member sets would consume.
    """

    __slots__ = ('_count',)

    def __init__(self, count: int):
        self._count = count

    def __len__(self):
        return self._count

    def __bool__(self):
        return self._count > 0

    def __iter__(self):
        return iter(())

    def __contains__(self, item):
        return False


def _convert_numpy_value(value):
    """Convert a numpy value to its Python native equivalent."""
    if value is None:
        return None
    if isinstance(value, (np.integer, np.int64, np.int32)):
        return int(value)
    if isinstance(value, (np.floating, np.float64, np.float32)):
        return float(value)
    if isinstance(value, np.ndarray):
        return [_convert_numpy_value(v) for v in value]
    if isinstance(value, (np.str_, np.bytes_)):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return value


def load_world_from_hdf5(input_file, config_file="yaml/serialization_config.yaml", slim=False):
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
    logger.info("LOADING WORLD FROM HDF5" + (" (slim mode)" if slim else ""))
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

        # Pre-load names and registries from metadata group (new format)
        geo_names = None
        level_registry = None
        venue_names = None
        type_registry = None
        subset_names_arr = None

        if 'metadata' in f:
            meta = f['metadata']
            if 'names' in meta:
                if 'geography' in meta['names']:
                    geo_names = meta['names']['geography'][:].astype(str)
                if 'venues' in meta['names']:
                    venue_names = meta['names']['venues'][:].astype(str)
                if 'subsets' in meta['names']:
                    subset_names_arr = meta['names']['subsets'][:].astype(str)
            if 'registries' in meta:
                if 'geo_levels' in meta['registries']:
                    level_registry = meta['registries']['geo_levels'][:].astype(str)
                if 'venue_types' in meta['registries']:
                    type_registry = meta['registries']['venue_types'][:].astype(str)

        # Load Geography
        geography = None
        if 'geography' in f:
            logger.info("Loading geography...")
            try:
                geography = _load_geography(f['geography'], config, geo_names, level_registry)
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
                population = _load_population(f['population'], geography, config, slim=slim)
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
                venue_manager = _load_venues(f['venues'], geography, config, venue_names, type_registry, subset_names_arr, slim=slim)
            except Exception as e:
                logger.warning(f"Failed to load venues: {e}")
                logger.warning("World will be created without venues")
        else:
            logger.warning("No venue data found in HDF5 file")
            logger.warning("World will be created without venues")

        # Load Relationships (activity_map)
        # Group was renamed from 'relationships' to 'activity_mappings' in new format
        activity_group_name = 'activity_mappings' if 'activity_mappings' in f else 'relationships'
        # Compute aggregate statistics from HDF5 data before closing the file
        slim_statistics = None
        unit_statistics = None
        if slim:
            logger.info("Computing slim statistics from HDF5...")
            try:
                slim_statistics = _compute_slim_statistics(f)
                logger.info("Slim statistics computed.")
            except Exception as e:
                logger.warning(f"Failed to compute slim statistics: {e}")
            if geography:
                logger.info("Computing per-unit statistics from HDF5...")
                try:
                    unit_statistics = _compute_unit_statistics(f, geography)
                    logger.info(f"Per-unit statistics computed for {len(unit_statistics)} units.")
                except Exception as e:
                    logger.warning(f"Failed to compute unit statistics: {e}")

        if slim:
            logger.info("Slim mode: skipping relationship loading (member counts already injected).")
        elif activity_group_name in f and config.should_include_activity_map():
            logger.info("Loading relationships...")
            try:
                if population and venue_manager:
                    _load_relationships(f[activity_group_name], population, venue_manager)
                else:
                    logger.warning("Cannot load relationships: population or venues missing")
            except Exception as e:
                logger.warning(f"Failed to load relationships: {e}")
                logger.warning("World will be created without relationships")
        elif activity_group_name not in f:
            logger.info("No relationship data found in HDF5 file")

    # Create World object
    world = World(geography=geography, population=population, venues=venue_manager)

    if slim_statistics is not None:
        world._slim_statistics = slim_statistics
    if unit_statistics is not None:
        world._unit_statistics = unit_statistics

    logger.info("")
    logger.info("Load complete")
    logger.info(f"  {world}")
    logger.info("-" * 50)

    return world


# ============================================================================
# Slim statistics helpers
# ============================================================================

def _compute_array_stats(data, max_categories: int = 25) -> dict:
    """Return numeric or categorical summary stats for a single HDF5 dataset array."""
    if data.dtype.kind in ('f', 'u', 'i'):
        arr = data.astype(np.float64).ravel()
        finite = arr[np.isfinite(arr)]
        if len(finite) == 0:
            return {'type': 'numeric', 'count': 0}
        return {
            'type': 'numeric',
            'count': int(len(finite)),
            'mean': round(float(np.mean(finite)), 4),
            'std': round(float(np.std(finite)), 4),
            'min': float(np.min(finite)),
            'max': float(np.max(finite)),
            'p25': float(np.percentile(finite, 25)),
            'median': float(np.median(finite)),
            'p75': float(np.percentile(finite, 75)),
        }

    # String / bytes / object → categorical
    try:
        if data.dtype.kind in ('S', 'O', 'U'):
            values = data.astype(str)
        else:
            values = data.astype(str)
        unique, counts = np.unique(values, return_counts=True)
        total = int(len(values))
        order = np.argsort(-counts)
        top_u = unique[order[:max_categories]]
        top_c = counts[order[:max_categories]]
        return {
            'type': 'categorical',
            'count': total,
            'unique_count': int(len(unique)),
            'top_values': {
                str(k): {'count': int(v), 'pct': round(100.0 * v / total, 2)}
                for k, v in zip(top_u, top_c)
            },
        }
    except Exception as e:
        return {'type': 'unknown', 'error': str(e)}


def _compute_slim_statistics(f) -> dict:
    """Compute aggregate statistics from an open HDF5 file during slim loading.

    Reads person properties, activity map, subset sizes, and venue properties
    to produce summary statistics.  No individual-level records are stored.

    Args:
        f: open h5py.File handle (read mode)

    Returns:
        dict with keys:
          'person_properties'  – stats per person property plus age and sex
          'activity_map'       – activity-name breakdowns and averages
          'subset_sizes'       – distribution of subset member counts
          'venue_properties'   – per venue-type property stats
    """
    stats: dict = {}

    # ---- Person properties --------------------------------------------------
    person_stats: dict = {}
    if 'population' in f:
        pop = f['population']
        if 'ages' in pop:
            person_stats['age'] = _compute_array_stats(pop['ages'][:])
        if 'sexes' in pop:
            sex_raw = pop['sexes'][:]
            if sex_raw.dtype.kind in ('u', 'i'):
                # Vectorised decode: map int codes → string labels
                _labels = np.array(['male', 'female', 'unknown'])
                clipped = np.clip(sex_raw.astype(np.int64), 0, 2)
                sexes = _labels[clipped]
            else:
                sexes = sex_raw.astype(str)
            person_stats['sex'] = _compute_array_stats(sexes)
        if 'properties' in pop:
            for prop_name in pop['properties'].keys():
                try:
                    person_stats[prop_name] = _compute_array_stats(pop['properties'][prop_name][:])
                except Exception as e:
                    person_stats[prop_name] = {'type': 'error', 'error': str(e)}
    stats['person_properties'] = person_stats

    # ---- Subset sizes (proxy for contacts) ----------------------------------
    if 'venues' in f and 'subsets' in f['venues']:
        mc = f['venues']['subsets']['member_counts'][:].astype(np.int64)
        non_empty = mc[mc > 0]
        if len(non_empty):
            stats['subset_sizes'] = {
                'mean': round(float(np.mean(non_empty)), 2),
                'median': float(np.median(non_empty)),
                'min': int(np.min(non_empty)),
                'max': int(np.max(non_empty)),
                'total_subsets': int(len(mc)),
                'non_empty_subsets': int(len(non_empty)),
            }

    # ---- Activity map -------------------------------------------------------
    activity_group_name = (
        'activity_mappings' if 'activity_mappings' in f else 'relationships'
    )
    if activity_group_name in f and 'activity_map' in f[activity_group_name]:
        am = f[activity_group_name]['activity_map']
        activity_names = am['activity_names'][:].astype(str)
        activity_offsets = am['activity_offsets'][:]   # one entry per person
        activity_data = am['activity_data'][:]         # (N_rows, 4): person_id, act_idx, venue_id, subset_idx

        n_people = len(activity_offsets)
        n_rows = len(activity_data)

        # Per-activity unique-person counts using numpy (fast, no Python loop)
        # Deduplicate (person_id, activity_idx) pairs then count per activity
        if n_rows > 0:
            pairs = np.unique(
                activity_data[:, [0, 1]].astype(np.int64), axis=0
            )
            people_per_act = np.zeros(len(activity_names), dtype=np.int64)
            np.add.at(people_per_act, pairs[:, 1], 1)
            unique_people = int(len(np.unique(pairs[:, 0])))
            mean_unique_acts = len(pairs) / unique_people if unique_people else 0.0
        else:
            people_per_act = np.zeros(len(activity_names), dtype=np.int64)
            unique_people = 0
            mean_unique_acts = 0.0

        mean_assignments = n_rows / n_people if n_people else 0.0

        # Estimated mean contacts:
        #   each person-subset assignment contributes (subset_size - 1) contacts.
        #   mean_contacts ≈ mean(subset_size - 1) × mean_assignments_per_person
        if 'venues' in f and 'subsets' in f['venues'] and n_rows > 0:
            mc_arr = f['venues']['subsets']['member_counts'][:].astype(np.float64)
            non_empty_mc = mc_arr[mc_arr > 0]
            if len(non_empty_mc):
                mean_contacts_est = round(
                    float(np.mean(non_empty_mc - 1)) * mean_assignments, 1
                )
            else:
                mean_contacts_est = 0.0
        else:
            mean_contacts_est = 0.0

        stats['activity_map'] = {
            'activity_counts': {
                str(activity_names[i]): int(people_per_act[i])
                for i in range(len(activity_names))
            },
            'total_people_with_activities': unique_people,
            'mean_activity_types_per_person': round(float(mean_unique_acts), 2),
            'mean_venue_assignments_per_person': round(float(mean_assignments), 2),
            'mean_contacts_estimate': mean_contacts_est,
        }

    # ---- Venue properties ---------------------------------------------------
    venue_prop_stats: dict = {}
    if 'venues' in f and 'properties' in f['venues']:
        for venue_type in f['venues']['properties'].keys():
            vt_stats: dict = {}
            for prop_name in f['venues']['properties'][venue_type].keys():
                try:
                    vt_stats[prop_name] = _compute_array_stats(
                        f['venues']['properties'][venue_type][prop_name][:]
                    )
                except Exception as e:
                    vt_stats[prop_name] = {'type': 'error', 'error': str(e)}
            if vt_stats:
                venue_prop_stats[venue_type] = vt_stats
    stats['venue_properties'] = venue_prop_stats

    return stats


def _compute_unit_statistics(f, geography) -> dict:
    """Pre-compute per-geographic-unit statistics from HDF5 data.

    Computes statistics for every unit in the hierarchy (leaf and aggregate)
    so the API can serve unit details in O(1) without iterating Python objects.

    Leaf-unit stats are derived directly from HDF5 arrays (vectorised numpy),
    then summed upward through the parent chain so every level of the hierarchy
    has correct aggregated counts.

    Returns:
        dict[unit_name, dict] with keys:
          population, age_distribution, sex_distribution,
          venue_types, activity_counts
    """
    if 'population' not in f:
        return {}

    pop = f['population']
    person_ids_arr  = pop['ids'][:]
    person_geo_ids  = pop['geo_unit_ids'][:]
    ages            = pop['ages'][:].astype(np.float64)

    # Decode sexes to string labels (vectorised)
    sex_raw = pop['sexes'][:]
    if sex_raw.dtype.kind in ('u', 'i'):
        _sex_labels = np.array(['male', 'female', 'unknown'])
        sexes = _sex_labels[np.clip(sex_raw.astype(np.int64), 0, 2)]
    else:
        sexes = sex_raw.astype(str)

    uid_to_name = {uid: u.name for uid, u in geography.units_by_id.items()}

    AGE_LABELS = ['0-15', '16-24', '25-34', '35-49', '50-64', '65+']
    AGE_BREAKS = [0, 16, 25, 35, 50, 65, np.inf]

    # ---- Person stats per leaf unit (sort-then-group) -----------------------
    sort_idx = np.argsort(person_geo_ids, kind='stable')
    sg = person_geo_ids[sort_idx]
    sa = ages[sort_idx]
    ss = sexes[sort_idx]

    bounds   = np.where(np.diff(sg) != 0)[0] + 1
    g_starts = np.concatenate([[0], bounds])
    g_ends   = np.concatenate([bounds, [len(sg)]])

    leaf_stats: dict = {}
    for i, geo_id in enumerate(sg[g_starts]):
        unit_name = uid_to_name.get(int(geo_id))
        if unit_name is None:
            continue
        s, e = int(g_starts[i]), int(g_ends[i])
        grp_ages  = sa[s:e]
        grp_sexes = ss[s:e]

        age_dist: dict = {}
        for j, label in enumerate(AGE_LABELS):
            lo, hi = AGE_BREAKS[j], AGE_BREAKS[j + 1]
            age_dist[label] = int(np.sum((grp_ages >= lo) & (grp_ages < hi)))

        sex_u, sex_c = np.unique(grp_sexes, return_counts=True)
        leaf_stats[unit_name] = {
            'population':      int(e - s),
            'age_distribution': age_dist,
            'sex_distribution': {str(k): int(v) for k, v in zip(sex_u, sex_c)},
            'venue_types':      {},
            'activity_counts':  {},
        }

    # ---- Venue type counts per leaf unit ------------------------------------
    if 'venues' in f:
        v = f['venues']
        v_geo_ids  = v['geo_unit_ids'][:]
        types_raw  = v['types'][:] if 'types' in v else np.array([], dtype='u1')

        # Decode type registry if present (new format uses uint8 indices)
        type_reg = None
        try:
            type_reg = f['metadata']['registries']['venue_types'][:].astype(str)
        except Exception:
            pass

        if type_reg is not None and types_raw.dtype.kind in ('u', 'i') and len(types_raw):
            v_types = type_reg[types_raw.astype(int)]
        elif len(types_raw):
            v_types = types_raw.astype(str)
        else:
            v_types = np.array([])

        if len(v_types):
            v_sort   = np.argsort(v_geo_ids, kind='stable')
            svg      = v_geo_ids[v_sort]
            svt      = v_types[v_sort]
            vb       = np.where(np.diff(svg) != 0)[0] + 1
            vs_starts = np.concatenate([[0], vb])
            vs_ends   = np.concatenate([vb, [len(svg)]])

            for i, geo_id in enumerate(svg[vs_starts]):
                unit_name = uid_to_name.get(int(geo_id))
                if unit_name and unit_name in leaf_stats:
                    s, e  = int(vs_starts[i]), int(vs_ends[i])
                    t_u, t_c = np.unique(svt[s:e], return_counts=True)
                    leaf_stats[unit_name]['venue_types'] = {
                        str(k): int(v) for k, v in zip(t_u, t_c)
                    }

    # ---- Activity counts per leaf unit from activity_map -------------------
    act_grp = 'activity_mappings' if 'activity_mappings' in f else 'relationships'
    if act_grp in f and 'activity_map' in f[act_grp]:
        am             = f[act_grp]['activity_map']
        activity_names = am['activity_names'][:].astype(str)
        act_data       = am['activity_data'][:]   # (N_rows, 4)

        # Dense lookup: person_id -> geo_unit_id
        max_pid    = int(np.max(person_ids_arr))
        pid_to_geo = np.full(max_pid + 1, -1, dtype=np.int64)
        pid_to_geo[person_ids_arr.astype(np.int64)] = person_geo_ids.astype(np.int64)

        # Unique (person_id, activity_idx) pairs — avoids counting same person
        # multiple times for the same activity (they may have several venues/subsets)
        pa_pairs = np.unique(act_data[:, [0, 1]].astype(np.int64), axis=0)

        # Vectorised geo_id lookup
        pa_pids = pa_pairs[:, 0]
        valid   = pa_pids <= max_pid
        pa_pids, pa_acts = pa_pids[valid], pa_pairs[valid, 1]
        geo_ids  = pid_to_geo[pa_pids]
        valid2   = geo_ids >= 0

        # (geo_id, act_idx): one row per unique person-activity in that unit
        geo_act = np.column_stack([geo_ids[valid2], pa_acts[valid2]])

        if len(geo_act):
            ga_sort = np.lexsort((geo_act[:, 1], geo_act[:, 0]))
            gas     = geo_act[ga_sort]
            ga_b    = np.where(np.any(np.diff(gas, axis=0) != 0, axis=1))[0] + 1
            ga_starts = np.concatenate([[0], ga_b])
            ga_ends   = np.concatenate([ga_b, [len(gas)]])

            for k in range(len(ga_starts)):
                geo_id  = int(gas[ga_starts[k], 0])
                act_idx = int(gas[ga_starts[k], 1])
                count   = int(ga_ends[k] - ga_starts[k])
                unit_name = uid_to_name.get(geo_id)
                if unit_name and unit_name in leaf_stats:
                    leaf_stats[unit_name]['activity_counts'][
                        str(activity_names[act_idx])
                    ] = count

    # ---- Aggregate upward through the geographic hierarchy ------------------
    all_stats = dict(leaf_stats)

    def _add(dst: dict, src: dict) -> None:
        """Add src stats into dst in-place."""
        dst['population'] = dst.get('population', 0) + src.get('population', 0)
        for label in AGE_LABELS:
            dst.setdefault('age_distribution', {})[label] = (
                dst.get('age_distribution', {}).get(label, 0)
                + src.get('age_distribution', {}).get(label, 0)
            )
        for sex, cnt in src.get('sex_distribution', {}).items():
            dst.setdefault('sex_distribution', {})[sex] = (
                dst.get('sex_distribution', {}).get(sex, 0) + cnt
            )
        for vt, cnt in src.get('venue_types', {}).items():
            dst.setdefault('venue_types', {})[vt] = (
                dst.get('venue_types', {}).get(vt, 0) + cnt
            )
        for act, cnt in src.get('activity_counts', {}).items():
            dst.setdefault('activity_counts', {})[act] = (
                dst.get('activity_counts', {}).get(act, 0) + cnt
            )

    def _aggregate(unit) -> dict:
        """Post-order: compute a unit's stats as the sum of its children."""
        if not unit.children:
            return all_stats.get(unit.name, {
                'population': 0,
                'age_distribution': {k: 0 for k in AGE_LABELS},
                'sex_distribution': {},
                'venue_types': {},
                'activity_counts': {},
            })
        agg: dict = {
            'population': 0,
            'age_distribution': {k: 0 for k in AGE_LABELS},
            'sex_distribution': {},
            'venue_types': {},
            'activity_counts': {},
        }
        # Include any people assigned directly to this non-leaf unit
        if unit.name in leaf_stats:
            _add(agg, leaf_stats[unit.name])
        for child in unit.children:
            _add(agg, _aggregate(child))
        all_stats[unit.name] = agg
        return agg

    # Trigger aggregation from every root unit (units with no parent)
    for unit in geography.units_by_id.values():
        if unit.parent is None:
            _aggregate(unit)

    return all_stats


def _load_geography(geo_group, config, geo_names=None, level_registry=None):
    """Reconstruct Geography hierarchy from HDF5."""
    from may.geography import Geography, GeographicalUnit

    # Read core datasets
    ids = geo_group['ids'][:]

    # Names: new format stores in metadata/names/geography; old format stores inline
    if geo_names is not None:
        names = geo_names
    else:
        names = geo_group['names'][:].astype(str)

    # Levels: new format stores as uint8 integers with a registry lookup; old format stores as strings
    if level_registry is not None:
        levels_raw = geo_group['levels'][:]
        levels = np.array([level_registry[int(v)] for v in levels_raw])
    else:
        levels = geo_group['levels'][:].astype(str)

    # Convert numpy strings to Python strings for levels
    unique_levels = list(dict.fromkeys(str(lvl) for lvl in levels))
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
            properties_by_unit[prop_name] = prop_data

    # Create Geography object
    geography = Geography(levels=unique_levels)

    # Create all units first (without parent links, as the parent unit might not exist yet)
    # Creates it as a dict object as it's hashable, so quick for setting the parent relationships
    units_by_id = {}
    for i, (unit_id, name, level) in enumerate(zip(ids, names, levels)):
        # Convert coordinates to Python floats for JSON serialization compatibility
        coordinates = None
        if latitudes is not None and not np.isnan(latitudes[i]):
            coordinates = (float(latitudes[i]), float(longitudes[i]))

        # Collect properties for this unit, converting numpy types to Python natives
        properties = {}
        for prop_name, prop_array in properties_by_unit.items():
            properties[prop_name] = _convert_numpy_value(prop_array[i])

        unit = GeographicalUnit(
            int(unit_id),  # Convert to Python int
            name=str(name),  # Convert to Python str
            level=str(level),  # Convert to Python str
            parent=None,  # Will be set in next pass
            coordinates=coordinates,
            properties=properties
        )
        units_by_id[int(unit_id)] = unit

    # Set parent relationships and add children to parent's children list
    for i, (unit_id, parent_id) in enumerate(zip(ids, parent_ids)):
        if int(parent_id) != -1:
            child_unit = units_by_id[int(unit_id)]
            parent_unit = units_by_id[int(parent_id)]
            child_unit.parent = parent_unit
            parent_unit.children.append(child_unit)

    # Add units to Geography
    geography.add_geo_units(units_by_id.values())

    logger.info(f"  Loaded {len(units_by_id)} geographical units")

    return geography


def _load_population(pop_group, geography, config, slim=False):
    """Reconstruct PopulationManager with Person objects from HDF5."""
    from may.population import PopulationManager, Person

    # Read core datasets
    ids = pop_group['ids'][:]
    ages = pop_group['ages'][:]
    # Sexes: new format stores as uint8 (0=male, 1=female, 2=unknown); old format stores as strings
    _SEX_DECODE = {0: "male", 1: "female", 2: "unknown"}
    sex_raw = pop_group['sexes'][:]
    if sex_raw.dtype.kind in ('u', 'i'):
        sexes = np.array([_SEX_DECODE.get(int(v), "unknown") for v in sex_raw])
    else:
        sexes = sex_raw.astype(str)
    geo_unit_ids = pop_group['geo_unit_ids'][:]

    # Read properties if present (skipped in slim mode — saves ~400 bytes/person)
    properties_by_person = {}
    if not slim and 'properties' in pop_group:
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
        # Find geographical unit (convert numpy int to Python int for lookup)
        geo_unit = all_units.get(int(geo_unit_id))

        # Collect properties for this person, converting numpy types
        properties = {}
        for prop_name, prop_array in properties_by_person.items():
            properties[prop_name] = _convert_numpy_value(prop_array[i])

        # Create Person with Python native types
        person = Person(age=int(age), sex=str(sex), geographical_unit=geo_unit, properties=properties)
        person.id = int(person_id)  # Restore original ID as Python int

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


def _load_venues(venues_group, geography, config, venue_names=None, type_registry=None, subset_names_arr=None, slim=False):
    """Reconstruct VenueManager with Venue and Subset objects from HDF5."""
    from may.geography import VenueManager, Venue

    # Read core venue datasets
    ids = venues_group['ids'][:]

    # Names: new format stores in metadata/names/venues; old format stores inline
    if venue_names is not None:
        names = venue_names
    else:
        names = venues_group['names'][:].astype(str)

    # Types: new format stores as uint8 integers with a registry lookup; old format stores as strings
    if type_registry is not None:
        types_raw = venues_group['types'][:]
        types = np.array([type_registry[int(v)] for v in types_raw])
    else:
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

    # Read properties by type (skipped in slim mode — saves ~300 bytes/venue)
    properties_by_venue_type = {}
    if not slim and 'properties' in venues_group:
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
        # Get type-specific index for property lookup (convert numpy str to Python str)
        venue_type_str = str(venue_type)
        type_idx = venue_type_counters.get(venue_type_str, 0)
        venue_type_counters[venue_type_str] = type_idx + 1

        # Find geographical unit (convert numpy int to Python int for lookup)
        geo_unit = all_units.get(int(geo_unit_id))

        # Coordinates - convert to Python floats
        coordinates = None
        if latitudes is not None and not np.isnan(latitudes[i]):
            coordinates = (float(latitudes[i]), float(longitudes[i]))

        # Collect properties for this venue, converting numpy types
        properties = {}
        if is_residence is not None:
            properties['is_residence'] = bool(is_residence[i])

        if not slim and venue_type_str in properties_by_venue_type:
            for prop_name, prop_array in properties_by_venue_type[venue_type_str].items():
                properties[prop_name] = _convert_numpy_value(prop_array[type_idx])

        # Create Venue with Python native types
        venue = Venue(
            name=str(name),
            venue_type=venue_type_str,
            geographical_unit=geo_unit,
            coordinates=coordinates,
            properties=properties
        )
        # Note: venue.id will be set by VenueManager (type-scoped), but we track global ID
        venue_manager.add_venue(venue)
        venues_by_global_id[int(venue_id)] = venue

    # Set parent relationships
    for venue_id, parent_id in zip(ids, parent_ids):
        if int(parent_id) != -1:
            venues_by_global_id[int(venue_id)].parent = venues_by_global_id[int(parent_id)]

    logger.info(f"  Loaded {num_venues:,} venues")

    # Load subsets
    subsets_by_venue_and_index = {}
    if 'subsets' in venues_group:
        subsets_by_venue_and_index = _load_subsets(venues_group['subsets'], venues_by_global_id, subset_names_arr, slim=slim)

    # Store mapping for relationship loading
    venue_manager._subsets_by_venue_and_index = subsets_by_venue_and_index
    venue_manager._venues_by_global_id = venues_by_global_id

    return venue_manager


def _load_subsets(subsets_group, venues_by_global_id, subset_names_arr=None, slim=False):
    """Load Subset objects and assign to venues."""
    from may.population.subset import Subset

    # Read subset metadata
    venue_ids = subsets_group['venue_ids'][:]
    subset_indices = subsets_group['subset_indices'][:]
    # Names: new format stores in metadata/names/subsets; old format stores inline
    if subset_names_arr is not None:
        subset_names = subset_names_arr
    else:
        subset_names = subsets_group['subset_names'][:].astype(str)
    member_counts = subsets_group['member_counts'][:]

    # Read member lists (ragged array)
    members_flat = subsets_group['members_flat'][:]
    members_offsets = subsets_group['members_offsets'][:]

    num_subsets = len(venue_ids)

    # Create Subset objects (members will be added later during relationship loading)
    subsets_by_venue_and_index = {}

    for i, (venue_id, subset_idx, subset_name) in enumerate(zip(venue_ids, subset_indices, subset_names)):
        # Convert numpy types to Python natives
        venue_id_int = int(venue_id)
        subset_idx_int = int(subset_idx)
        subset_name_str = str(subset_name)

        venue = venues_by_global_id[venue_id_int]

        # Create Subset with Python native types
        subset = Subset(venue=venue, subset_index=subset_idx_int, subset_name=subset_name_str)

        # In slim mode, inject the member count from HDF5 directly so that
        # len(subset.members) / subset.num_members return the correct value
        # without needing to load and store all the Person references.
        if slim:
            subset.members = _CountOnlySet(int(member_counts[i]))

        # Add to venue
        venue.subsets[subset_name_str] = subset

        # Store for relationship loading
        subsets_by_venue_and_index[(venue_id_int, subset_idx_int)] = subset

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
            start_idx = int(activity_offsets[person_idx])
            if start_idx < len(activity_data):
                person_id = int(activity_data[start_idx, 0])
            else:
                continue
        else:
            continue

        person = population.get_person(person_id)

        if person is None:
            continue

        # Get all activity mappings for this person
        start_idx = int(activity_offsets[person_idx])
        end_idx = int(activity_offsets[person_idx + 1]) if person_idx + 1 < len(activity_offsets) else len(activity_data)

        for row in activity_data[start_idx:end_idx]:
            _, activity_idx, venue_id, subset_idx = row
            # Convert numpy types to Python natives
            activity_idx = int(activity_idx)
            venue_id = int(venue_id)
            subset_idx = int(subset_idx)

            activity_name = str(activity_names[activity_idx])
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
