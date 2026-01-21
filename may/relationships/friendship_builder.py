"""
Friendship builder for creating friendship networks between agents.

"""

import logging
import numpy as np
import numba as nb
import yaml
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger("friendships")


# ============================================================================
# NUMBA JIT-COMPILED FUNCTIONS
# ============================================================================

@nb.njit(cache=True)
def _process_group_numba(group_people, group_ages, group_subsets,
                         all_connections, current_counts, target_counts,
                         weight_fraction, age_range, require_same_subset,
                         check_duplicates):
    """
    Process a single group (venue or geo unit) with Numba acceleration.

    Args:
        group_people: Array of person IDs in this group
        group_ages: Array of ages for people in this group
        group_subsets: Array of subset indices for people in this group
        all_connections: Output array (n_people, max_connections)
        current_counts: Current connection count per person
        target_counts: Target connection count per person
        weight_fraction: Fraction of connections from this source
        age_range: Max age difference allowed (-1 for no filter)
        require_same_subset: Whether to require same subset
        check_duplicates: Whether to check for duplicate connections
    """
    n_group = len(group_people)
    if n_group < 2:
        return

    max_conn = all_connections.shape[1]

    for local_idx in range(n_group):
        person_id = group_people[local_idx]
        target = target_counts[person_id]
        current = current_counts[person_id]

        # How many connections needed from this source
        n_needed = int(round(target * weight_fraction))
        if n_needed <= 0 or current >= target:
            continue

        n_to_add = min(n_needed, target - current)

        # Get person's attributes
        person_age = group_ages[local_idx]
        person_subset = group_subsets[local_idx]

        # Build candidate list
        candidates = np.empty(n_group, dtype=np.int32)
        n_candidates = 0

        for j in range(n_group):
            if j == local_idx:
                continue

            cand_id = group_people[j]

            # Age filter
            if age_range >= 0:
                if abs(group_ages[j] - person_age) > age_range:
                    continue

            # Subset filter
            if require_same_subset:
                if group_subsets[j] != person_subset:
                    continue

            # Duplicate check
            if check_duplicates:
                is_dup = False
                for k in range(current):
                    if all_connections[person_id, k] == cand_id:
                        is_dup = True
                        break
                if is_dup:
                    continue

            candidates[n_candidates] = j
            n_candidates += 1

        if n_candidates == 0:
            continue

        # Sample from candidates (simple random sampling)
        n_sample = min(n_to_add, n_candidates)

        # Fisher-Yates shuffle for sampling without replacement
        for i in range(n_sample):
            # Random index from i to n_candidates-1
            rand_idx = i + int(np.random.random() * (n_candidates - i))
            # Swap
            candidates[i], candidates[rand_idx] = candidates[rand_idx], candidates[i]

        # Add sampled connections
        for i in range(n_sample):
            if current_counts[person_id] >= target_counts[person_id]:
                break
            if current_counts[person_id] >= max_conn:
                break

            conn_id = group_people[candidates[i]]
            idx = current_counts[person_id]
            all_connections[person_id, idx] = conn_id
            current_counts[person_id] += 1


@nb.njit(parallel=True, cache=True)
def _process_all_groups_numba(group_starts, group_ends, group_people_flat,
                               ages, subsets, all_connections, current_counts,
                               target_counts, weight_fraction, age_range,
                               require_same_subset, check_duplicates):
    """
    Process all groups in parallel using Numba.

    Args:
        group_starts: Start index of each group in group_people_flat
        group_ends: End index of each group in group_people_flat
        group_people_flat: Flattened array of all person IDs by group
        ages: Ages array for all people
        subsets: Subset indices for all people
        all_connections: Output array
        current_counts: Current counts
        target_counts: Target counts
        weight_fraction: Weight fraction
        age_range: Age range filter
        require_same_subset: Subset filter flag
        check_duplicates: Duplicate check flag
    """
    n_groups = len(group_starts)

    for g in nb.prange(n_groups):
        start = group_starts[g]
        end = group_ends[g]

        if end <= start + 1:
            continue

        # Extract group data
        group_people = group_people_flat[start:end]
        n_group = len(group_people)

        # Get ages and subsets for this group
        group_ages = np.empty(n_group, dtype=np.int16)
        group_subsets = np.empty(n_group, dtype=np.int16)

        for i in range(n_group):
            pid = group_people[i]
            group_ages[i] = ages[pid]
            group_subsets[i] = subsets[pid]

        # Process this group
        _process_group_numba(
            group_people, group_ages, group_subsets,
            all_connections, current_counts, target_counts,
            weight_fraction, age_range, require_same_subset,
            check_duplicates
        )


# ============================================================================
# RELATIONSHIP BUILDER CLASS
# ============================================================================

class FriendshipBuilder:
    """
    Builds configurable relationship networks between people.

    All relationship types, criteria, and sources are defined in YAML.
    Optimized for large populations (60M+) using Numba JIT compilation.
    """

    def __init__(self, world, config: dict | str):
        """
        Initialize the relationship builder.

        Args:
            world: World object with population and geography
            config: Either a config dict or path to YAML file
        """
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']
        self._build_arrays()

    def _load_config(self, config) -> dict:
        """Load configuration from dict or YAML file."""
        if isinstance(config, str):
            with open(config, 'r') as f:
                return yaml.safe_load(f)
        return config

    def _build_arrays(self):
        """Pre-compute all data as numpy arrays for Numba."""
        logger.info(f"Building arrays for relationship: {self.name}")

        n_people = len(self.world.population.people)

        # Core attributes as contiguous arrays
        self._ages = np.array([p.age for p in self.world.population.people], dtype=np.int16)
        self._n_people = n_people

        # Get geographic levels from world.geography
        geo_levels = self.world.geography.levels if self.world.geography else []
        logger.info(f"Geographic levels: {geo_levels}")

        # Build arrays for ALL geographic levels dynamically
        self._geo_level_data = {}  # {level_name: (starts, ends, people_flat)}
        level_counts = {}

        for level_idx, level_name in enumerate(geo_levels):
            level_to_idx = {}
            people_by_level = defaultdict(list)

            for i, person in enumerate(self.world.population.people):
                # Navigate up the hierarchy to find the unit at this level
                unit = person.geographical_unit
                target_unit = self._get_unit_at_level(unit, level_idx)
                unit_name = target_unit.name if target_unit else ""

                if unit_name not in level_to_idx:
                    level_to_idx[unit_name] = len(level_to_idx)
                idx = level_to_idx[unit_name]
                people_by_level[idx].append(i)

            # Convert to flattened arrays for Numba
            self._geo_level_data[level_name] = self._flatten_groups(people_by_level)
            level_counts[level_name] = len(level_to_idx)

        # Venue indices
        venue_to_idx = {}
        people_by_venue = defaultdict(list)

        for i, person in enumerate(self.world.population.people):
            if 'primary_activity' in person.activity_map:
                activity_value = person.activity_map['primary_activity']

                # Get ALL subsets for this activity (supports multiple jobs/venues)
                all_subsets = self._get_all_subsets(activity_value)

                # Add person to ALL their venues (bigger friend pool!)
                for subset in all_subsets:
                    if subset and hasattr(subset, 'venue'):
                        venue_id = subset.venue.id
                        if venue_id not in venue_to_idx:
                            venue_to_idx[venue_id] = len(venue_to_idx)
                        venue_idx = venue_to_idx[venue_id]
                        people_by_venue[venue_idx].append(i)

        # Dummy subset array (subset filtering not supported with multiple venues)
        self._person_subset = np.zeros(n_people, dtype=np.int16)

        # Convert venue data to flattened arrays for Numba
        self._venue_data = self._flatten_groups(people_by_venue)

        # Log summary
        level_summary = ", ".join([f"{len(self._geo_level_data[l][0])} {l}s" for l in geo_levels])
        logger.info(f"Arrays built: {n_people:,} people, {level_summary}, {len(venue_to_idx)} venues")

    def _get_unit_at_level(self, unit, target_level_idx: int):
        """
        Navigate up the hierarchy to find the unit at a specific level.

        Args:
            unit: Starting geographical unit (most granular level)
            target_level_idx: Index into geography.levels (0 = most granular)

        Returns:
            GeographicalUnit at the target level, or None
        """
        if unit is None:
            return None

        # Level 0 is the most granular (person's direct unit)
        current = unit
        current_level = 0

        while current_level < target_level_idx and current is not None:
            current = current.parent
            current_level += 1

        return current

    def _flatten_groups(self, groups_dict):
        """Convert dict of lists to CSR-like format for Numba."""
        # Sort by group index for consistent ordering
        sorted_groups = sorted(groups_dict.items())

        # Calculate total size
        total_size = sum(len(v) for v in groups_dict.values())

        # Create arrays
        starts = np.zeros(len(sorted_groups), dtype=np.int32)
        ends = np.zeros(len(sorted_groups), dtype=np.int32)
        people_flat = np.zeros(total_size, dtype=np.int32)

        offset = 0
        for i, (group_idx, people_list) in enumerate(sorted_groups):
            starts[i] = offset
            for pid in people_list:
                people_flat[offset] = pid
                offset += 1
            ends[i] = offset

        return starts, ends, people_flat

    def _get_first_subset(self, activity_value):
        """Extract first subset from activity value (dict format)."""
        if isinstance(activity_value, dict):
            for venue_type, subset_list in activity_value.items():
                if isinstance(subset_list, list) and subset_list:
                    return subset_list[0]
        return None

    def _get_all_subsets(self, activity_value):
        """
        Extract ALL subsets from activity value (dict format).

        This allows people with multiple venues for the same activity (e.g., 2 jobs)
        to build relationships from all their venues, not just the first one.

        Returns:
            List of all subsets for this activity
        """
        all_subsets = []
        if isinstance(activity_value, dict):
            for venue_type, subset_list in activity_value.items():
                if isinstance(subset_list, list):
                    all_subsets.extend(subset_list)
        return all_subsets

    def _get_connection_counts(self, n_people: int) -> np.ndarray:
        """Generate connection counts for all people at once."""
        conn_config = self.config['connections']
        default_count = conn_config['default']

        counts = np.full(n_people, default_count, dtype=np.int8)

        for variant in conn_config.get('variants', []):
            prob = variant['probability']
            count = variant['count']
            mask = np.random.random(n_people) < prob
            counts[mask] = count

        return counts

    def build_all(self, store: bool = True) -> dict[int, list[int]]:
        """
        Build relationships for all people using Numba-accelerated processing.

        Args:
            store: If True, store in person.properties using config's storage key

        Returns:
            Dict mapping person_id -> list of connected person_ids
        """
        n_people = self._n_people
        logger.info(f"Building '{self.name}' relationships for {n_people:,} people")

        storage_key = self.config.get('storage', {}).get('key', self.name)
        sources = self.config['sources']

        # Get connection counts
        connection_counts = self._get_connection_counts(n_people)
        max_connections = int(connection_counts.max())

        # Pre-allocate result array
        all_connections = np.full((n_people, max_connections), -1, dtype=np.int32)
        current_counts = np.zeros(n_people, dtype=np.int8)

        # Process each source with weight_fraction = 1.0
        # Each source tries to fill up to target, stopping when full
        total_sources = len(sources)
        for source_idx, source in enumerate(sources, 1):
            source_name = source.get('name', 'unnamed')
            pool_type = source['pool']['type']
            filters = source.get('filters', [])

            logger.info(f"  Processing source {source_idx}/{total_sources}: {source_name} (pool={pool_type})")

            # Parse filters
            age_range = np.int16(-1)  # -1 means no filter
            require_same_subset = False

            for f in filters:
                if f['attribute'] == 'age' and f['match'] == 'range':
                    age_range = np.int16(f['range'])
                elif f['attribute'] == 'subset_name' and f['match'] == 'same':
                    require_same_subset = True

            # Use weight_fraction = 1.0 so each source fills remaining slots
            weight_fraction = np.float64(1.0)

            if pool_type == 'activity':
                starts, ends, people_flat = self._venue_data
                _process_all_groups_numba(
                    starts, ends, people_flat,
                    self._ages, self._person_subset,
                    all_connections, current_counts, connection_counts,
                    weight_fraction, age_range, require_same_subset, False
                )
            elif pool_type.startswith('geographic'):
                # Handle all geographic pool types:
                # - "geographic" with level specified
                # - "geographic_county", "geographic_country", etc. with level specified
                level = source['pool'].get('level')

                if level and level in self._geo_level_data:
                    starts, ends, people_flat = self._geo_level_data[level]
                    _process_all_groups_numba(
                        starts, ends, people_flat,
                        self._ages, self._person_subset,
                        all_connections, current_counts, connection_counts,
                        weight_fraction, age_range, False, True
                    )
                else:
                    available_levels = list(self._geo_level_data.keys())
                    logger.warning(f"    Unknown geographic level '{level}'. "
                                   f"Available levels: {available_levels}. Skipping source.")
                    continue

            # Show progress after each source
            connections_so_far = int(current_counts.sum())
            logger.info(f"    ✓ Completed {source_name}: {connections_so_far:,} connections so far")

        # Convert to dict and store
        logger.info("  Storing connections...")
        relationships = {}

        # Progress tracking
        progress_interval = max(1, n_people // 10)  # Update every 10%

        for i, person in enumerate(self.world.population.people):
            n_conn = current_counts[i]
            connections = all_connections[i, :n_conn].tolist()
            relationships[person.id] = connections

            if store:
                person.properties[storage_key] = connections

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == n_people:
                progress = ((i + 1) / n_people) * 100
                logger.info(f"    Progress: {i+1:,}/{n_people:,} people processed ({progress:.1f}%)")

        total_connections = int(current_counts.sum())
        avg_connections = total_connections / n_people if n_people > 0 else 0
        logger.info(f"Built {total_connections:,} total connections "
                   f"(avg {avg_connections:.1f} per person)")

        return relationships
