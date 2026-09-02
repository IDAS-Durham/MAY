"""
MultiVenueDistributor: Generic distributor for assigning multiple venue options

This is a distributor that works with any set of venue types.

Structure:
    person.activity_map[activity_map_key] = {
        venue_type_1: [subset1, subset2, subset3],
        venue_type_2: [subset1, subset2],
        venue_type_3: [subset1, subset2, subset3, subset4],
    }

Example use cases:
    - Leisure activities: cinema, gym, pub, grocery
    - Social venues: cafe, park, community_center
    - Service locations: bank, post_office, library
    - Any other scenario requiring multiple venue options
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from may.utils.attribute_access import get_attribute
from may.utils.age_bands import parse_age_band

from .base_distributor import BaseDistributor
from may.population import Subset
from may.utils import path_resolver as pr

logger = logging.getLogger(__name__)

def _parse_numerical_band(label):
    """Parse a numerical band such as "1.5-3.0". None if unparseable."""
    try:
        parts = label.split("-")
        if len(parts) != 2:
            return None
        return float(parts[0]), float(parts[1])
    except (ValueError, AttributeError):
        return None


class MultiVenueDistributor(BaseDistributor):
    """
    Distributor for assigning multiple venue options to people.

    Features:
    - Handles any number of venue types
    - Assigns N closest venues per type to each person
    - Stores in nested dict: activity_map[key][venue_type] = [subsets]
    - Configurable age filtering
    - Distance-based venue selection with spatial indexing
    """

    def __init__(self, config_path: str = None, config_dict: dict = None):
        """
        Initialize MultiVenueDistributor from YAML configuration.

        Args:
            config_path: Path to distributor YAML file
            config_dict: Dictionary config (alternative to file)
        """
        super().__init__(config_file=config_path, config_dict=config_dict)

        # Extract configuration
        self.activity_map_key = self.config.get("activity_map_key")
        self.subset_key = self.config.get("subset_key", "default")
        self.venue_types = self.config.get("venue_types", [])

        # Validation
        if not self.activity_map_key:
            raise ValueError("activity_map_key must be specified in configuration")
        if not self.venue_types:
            raise ValueError("venue_types must be specified in configuration")

        # Venue selection config
        venue_selection = self.config.get("venue_selection", {})
        self.default_venue_count = venue_selection.get("count", 5)

        # How the candidate pool is defined:
        #   'count'    — the N venues nearest the geo unit's coordinates. Every
        #                person in the unit is at those coordinates, so all of
        #                them receive the same N.
        #   'geo_unit' — every venue of that type in the unit, from which each
        #                person draws their own set of `count`.
        self.consider_by = venue_selection.get("consider_by", "count")
        if self.consider_by not in ("count", "geo_unit"):
            raise ValueError(
                "MultiVenueDistributor: "
                f"venue_selection.consider_by must be 'count' or 'geo_unit', "
                f"got {self.consider_by!r}."
            )

        self.selection_strategy = self.config.get("allocation", {}).get("strategy")
        if self.consider_by == "geo_unit":
            if self.selection_strategy not in ("random", "closest_balanced"):
                raise ValueError(
                    "MultiVenueDistributor: "
                    f"venue_selection.consider_by 'geo_unit' requires "
                    f"allocation.strategy 'random' (uniform over the unit's venues) "
                    f"or 'closest_balanced' (weighted by inverse distance from the "
                    f"unit's coordinates); got {self.selection_strategy!r}."
                )
        elif self.selection_strategy is not None:
            raise ValueError(
                "MultiVenueDistributor: "
                f"allocation.strategy applies only when venue_selection.consider_by "
                f"is 'geo_unit'; got strategy {self.selection_strategy!r} with "
                f"consider_by {self.consider_by!r}."
            )

        # Per-venue-type configuration
        self.venue_type_config = self.config.get("venue_type_config", {})

        # Load participation data for venue types that have it
        self.participation_data = (
            {}
        )  # venue_type -> {data, row_filters, probability_column}
        for venue_type, type_config in self.venue_type_config.items():
            if "participation_filter" in type_config:
                self._load_participation_data(
                    venue_type, type_config["participation_filter"]
                )

        # Eligibility config
        eligibility = self.config.get("eligibility", {})
        self.min_age = None
        self.max_age = None
        # Extract age filters from global filters
        global_filters = eligibility.get("global_filters", [])
        for filter_rule in global_filters:
            if (
                filter_rule.get("attribute") == "age"
                and filter_rule.get("type") == "numerical"
            ):
                self.min_age = filter_rule.get("min")
                self.max_age = filter_rule.get("max")
                break

        logger.info("Initialized MultiVenueDistributor")
        logger.info(f"  activity_map_key: '{self.activity_map_key}'")
        logger.info(f"  venue_types: {self.venue_types}")
        logger.info(f"  subset_key: '{self.subset_key}'")
        logger.info(f"  default_venue_count: {self.default_venue_count}")
        logger.info(
            f"  consider_by: '{self.consider_by}'"
            + (
                f", strategy: '{self.selection_strategy}'"
                if self.selection_strategy
                else ""
            )
        )

        # Log per-venue-type overrides
        for venue_type in self.venue_types:
            count = self._get_venue_count_for_type(venue_type)
            if count != self.default_venue_count:
                logger.info(f"    {venue_type}: {count} venues (override)")
            if venue_type in self.participation_data:
                logger.info(f"    {venue_type}: has participation filtering")

        if self.min_age is not None or self.max_age is not None:
            logger.info(f"  age_filter: [{self.min_age}, {self.max_age}]")

    def _get_venue_count_for_type(self, venue_type: str) -> int:
        """Get the number of venues to assign for a specific type, including overrides."""
        return self.venue_type_config.get(venue_type, {}).get(
            "count", self.default_venue_count
        )

    def _load_participation_data(self, venue_type: str, filter_config: Dict):
        """
        Load participation data for a venue type and build lookup index.

        Args:
            venue_type: Type of venue
            filter_config: Participation filter configuration from YAML
        """
        data_file = pr.resolve(filter_config.get("data_file", "")) or None
        if not data_file:
            logger.warning(
                f"No data_file specified for {venue_type} participation filter"
            )
            return

        try:
            # Load CSV
            df = pd.read_csv(data_file)
            logger.info(
                f"Loaded participation data for '{venue_type}': {len(df)} rows from {data_file}"
            )

            row_filters = filter_config.get("row_filters", [])
            prob_config = filter_config.get("probability_column", {})

            # Build lookup index
            # Index structure: {(filter_val1, filter_val2, ...): {sex: prob}}
            lookup_index = {}

            for _, row in df.iterrows():
                # Extract filter keys from this row
                filter_keys = []
                for filter_cfg in row_filters:
                    csv_column = filter_cfg.get("csv_column")
                    value = row.get(csv_column)
                    filter_keys.append(str(value))

                # Build probability dict for this row
                # If using column_template, we need all possible values
                if "column_template" in prob_config:
                    # Extract all probability columns (e.g., pct_male, pct_female)
                    prob_dict = {}
                    template = prob_config["column_template"]
                    # Try to infer possible values from columns
                    # For "pct_{value}", extract all columns matching pattern
                    prefix = template.split("{")[0]  # e.g., "pct_"
                    for col in row.index:
                        if col.startswith(prefix):
                            # Extract the value part: "pct_male" -> "male"
                            attr_value = col[len(prefix) :]
                            prob_dict[attr_value] = float(row[col])

                    lookup_index[tuple(filter_keys)] = prob_dict

                elif "column_name" in prob_config:
                    # Fixed column - single probability value
                    column_name = prob_config["column_name"]
                    lookup_index[tuple(filter_keys)] = float(row[column_name])

            logger.info(
                f"Built participation lookup index for '{venue_type}': {len(lookup_index)} entries"
            )

            # Store the lookup index and configuration
            self.participation_data[venue_type] = {
                "lookup_index": lookup_index,
                "row_filters": row_filters,
                "probability_column": prob_config,
                "ranges": self._build_participation_ranges(lookup_index, row_filters),
            }

        except Exception as e:
            logger.error(f"Failed to load participation data for '{venue_type}': {e}")
            # Mark as failed so _should_allocate_venue_type returns False (fail-closed)
            self.participation_data[venue_type] = {
                "lookup_index": {},
                "row_filters": filter_config.get("row_filters", []),
                "probability_column": filter_config.get("probability_column", {}),
                "ranges": {},
            }

    def _build_participation_ranges(
        self, lookup_index: Dict, row_filters: List[Dict]
    ) -> Dict:
        """
        Pre-parse the bands each range filter can match, keyed by filter position.

        The bands are fixed once the CSV is loaded, so parsing them per person
        would repeat the same string work on every allocation decision. Bands
        stay in lookup-index order because the first match wins.
        """
        ranges = {}

        for filter_idx, filter_cfg in enumerate(row_filters):
            match_type = filter_cfg.get("match_type", "exact")
            if match_type == "age_range":
                parse = parse_age_band
            elif match_type == "numerical_range":
                parse = _parse_numerical_band
            else:
                continue

            bands = []
            seen = set()
            for key_tuple in lookup_index:
                if filter_idx >= len(key_tuple):
                    continue
                label = key_tuple[filter_idx]
                if label in seen:
                    continue
                seen.add(label)
                bounds = parse(label)
                if bounds is not None:
                    bands.append((bounds[0], bounds[1], label))

            ranges[filter_idx] = bands

        return ranges

    def _should_allocate_venue_type(self, person, venue_type: str) -> bool:
        """
        Check if a person should be allocated to a specific venue type.

        Uses participation data if configured, otherwise returns True.

        Args:
            person: Person object
            venue_type: Type of venue

        Returns:
            True if person should be allocated, False otherwise
        """
        # No participation filter = allocate to everyone
        if venue_type not in self.participation_data:
            return True

        participation_config = self.participation_data[venue_type]
        lookup_index = participation_config["lookup_index"]
        row_filters = participation_config["row_filters"]
        prob_config = participation_config["probability_column"]
        ranges = participation_config["ranges"]

        # Build lookup key from person attributes
        lookup_keys = []
        for filter_idx, filter_cfg in enumerate(row_filters):
            person_attr = filter_cfg.get("person_attribute")
            match_type = filter_cfg.get("match_type", "exact")

            # Get person attribute value
            person_value = get_attribute(person, person_attr)
            if person_value is None:
                return False

            # Find matching CSV value based on match_type
            csv_value = None

            if match_type == "exact":
                csv_value = str(person_value)
            else:
                for low, high, label in ranges.get(filter_idx, ()):
                    if low <= person_value <= high:
                        csv_value = label
                        break

            if csv_value is None:
                return False

            lookup_keys.append(csv_value)

        # Look up probability in index
        lookup_tuple = tuple(lookup_keys)
        if lookup_tuple not in lookup_index:
            return False

        prob_value = lookup_index[lookup_tuple]

        # Get probability based on configuration
        probability = None

        if isinstance(prob_value, dict):
            # Template-based: select probability by person attribute
            person_attr = prob_config.get("person_attribute")
            attr_value = get_attribute(person, person_attr)
            if attr_value is not None:
                probability = prob_value.get(str(attr_value).lower())
        else:
            # Fixed column: probability is a single value
            probability = prob_value

        if probability is None:
            return False

        # Probabilistic allocation
        return np.random.random() < probability

    def allocate(self, world):
        """
        Main entry point: Allocate venues to people.

        Args:
            world: World object containing people, venues, geography
        """
        logger.info("Starting MultiVenueDistributor allocation")
        logger.info(f"Processing venue types: {self.venue_types}")

        # Build spatial indices for each venue type using base class method
        self._build_spatial_indices(
            {vt: world.venues_by_type(vt) for vt in self.venue_types}
        )

        # Get eligible people
        eligible_people = self._get_eligible_people(world)
        logger.info(f"Found {len(eligible_people)} eligible people")

        if not eligible_people:
            logger.info("No eligible people for allocation")
            return

        # Allocate venues to each person
        self._allocate_venues(eligible_people, world)

        # Always log the allocation summary; all valid MAY worlds use this diagnostic.
        self._log_summary(world)

    def _get_eligible_people(self, world) -> List:
        """
        Get people eligible for allocation based on configured criteria.

        Args:
            world: World object

        Returns:
            List of eligible people
        """
        eligible = []

        for person in world.people:
            # Check age filters
            if self.min_age is not None and person.age < self.min_age:
                continue
            if self.max_age is not None and person.age > self.max_age:
                continue

            # Check geographical unit
            if person.geographical_unit is None:
                continue

            eligible.append(person)

        return eligible

    def _build_geo_unit_pools(self, world, venue_type: str) -> Dict[str, List]:
        """Group every venue of one type by the unit it sits in.

        Keyed by unit name at ``venue_geo_level``, so a venue recorded at a
        finer level is counted against its ancestor there.
        """
        level = self._require_venue_geo_level()
        pools = {}
        for venue in world.venues_by_type(venue_type):
            unit = venue.geographical_unit
            if unit is None:
                continue
            if unit.level != level:
                unit = unit.get_ancestor_by_level(level)
            if unit is None:
                continue
            pools.setdefault(unit.name, []).append(venue)
        return pools

    def _pool_weights(self, coords, pool: List) -> Optional[np.ndarray]:
        """Draw weights for one unit's pool, or None for a uniform draw.

        ``closest_balanced`` weights by inverse distance from the unit's own
        coordinates. Every person in the unit sits at those coordinates, so the
        weights are shared; what differs between people is the draw, not the
        distribution it is drawn from.
        """
        if self.selection_strategy != "closest_balanced":
            return None
        dists = np.array(
            [
                self._haversine_distance(coords, self._get_venue_location(v))
                for v in pool
            ]
        )
        return 1.0 / (dists + 0.1)

    def _sample_option_sets(self, pool_size: int, weights, n_people: int, count: int):
        """Draw ``count`` distinct venue indices for each person, independently.

        Returns ``(picked, valid)``, where ``picked`` is (n_people, count)
        indices into the pool and ``valid`` masks the positions actually filled;
        or None when the pool is no larger than count and everyone should simply
        get all of it.

        Cost is O(count) per person rather than O(pool_size). The distribution
        is shared across the unit, so it is turned into a CDF once and sampled
        by binary search. Walking the pool per person would be 4e9 pairs for a
        unit of a million people against a pool of four thousand.
        """
        if pool_size <= count:
            return None

        if weights is None:
            cdf = np.arange(1, pool_size + 1, dtype=np.float64) / pool_size
        else:
            cdf = np.cumsum(weights, dtype=np.float64)
            cdf /= cdf[-1]
        cdf[-1] = 1.0

        # Over-draw, then keep the distinct values. Duplicates are what the
        # margin is for: drawing exactly `count` would leave most people short.
        draws = max(3 * count, count + 8)
        idx = np.searchsorted(cdf, np.random.random((n_people, draws)))
        np.clip(idx, 0, pool_size - 1, out=idx)

        # Keep the first occurrence of each value in the order it was drawn.
        # Deduplicating on a sorted row instead would keep whichever duplicates
        # sort lowest, which is a bias toward low pool indices, not a sample:
        # over 133k people against 450 venues it gave the first venues ~4,400
        # people each and the last ones 1.
        order = np.argsort(idx, axis=1, kind="stable")
        by_value = np.take_along_axis(idx, order, axis=1)
        first_sorted = np.ones(idx.shape, dtype=bool)
        first_sorted[:, 1:] = by_value[:, 1:] != by_value[:, :-1]
        is_first = np.zeros(idx.shape, dtype=bool)
        np.put_along_axis(is_first, order, first_sorted, axis=1)

        # A stable argsort on the negated mask brings each row's distinct
        # entries to the front, still in draw order.
        rank = np.argsort(~is_first, axis=1, kind="stable")
        picked = np.take_along_axis(idx, rank[:, :count], axis=1)
        n_unique = is_first.sum(axis=1)
        valid = np.arange(count)[None, :] < n_unique[:, None]
        return picked, valid

    def _allocate_venues_by_geo_unit(self, people: List, world):
        """Give each person their own draw from their unit's venues.

        The alternative, ``consider_by: count``, hands every person in a unit
        the same N venues, because a person carries no position finer than their
        unit and so every one of them resolves to the same nearest N.
        """
        level = self._require_venue_geo_level()
        people_by_unit = {}
        for person in people:
            unit = self._get_geo_unit_at_level(person, world, target_level=level)
            if unit is None:
                continue
            people_by_unit.setdefault(unit, []).append(person)

        logger.info(
            f"Batching {len(people)} people into {len(people_by_unit)} "
            f"unique {level} units (per-person draws)"
        )

        pools_by_type = {
            vt: self._build_geo_unit_pools(world, vt) for vt in self.venue_types
        }

        venue_dicts = {}
        for unit, unit_people in people_by_unit.items():
            coords = (
                unit.coordinates
                if (unit.coordinates and len(unit.coordinates) == 2)
                else None
            )

            for venue_type in self.venue_types:
                pool = pools_by_type[venue_type].get(unit.name, [])
                if not pool:
                    continue

                takers = [
                    p
                    for p in unit_people
                    if self._should_allocate_venue_type(p, venue_type)
                ]
                if not takers:
                    continue

                count = self._get_venue_count_for_type(venue_type)
                weights = self._pool_weights(coords, pool) if coords else None
                sampled = self._sample_option_sets(
                    len(pool), weights, len(takers), count
                )

                subset_cache = {}

                def subset_for(j, _pool=pool, _cache=subset_cache):
                    hit = _cache.get(j)
                    if hit is None:
                        hit = self._get_or_create_subset(_pool[j])
                        _cache[j] = hit
                    return hit

                if sampled is None:
                    shared = [subset_for(j) for j in range(len(pool))]
                    for person in takers:
                        for subset in shared:
                            subset.add_member(person)
                        venue_dicts.setdefault(person, {})[venue_type] = list(shared)
                    continue

                picked, valid = sampled
                for row, person in enumerate(takers):
                    subsets = []
                    for slot in range(count):
                        if not valid[row, slot]:
                            break
                        subset = subset_for(int(picked[row, slot]))
                        subset.add_member(person)
                        subsets.append(subset)
                    if subsets:
                        venue_dicts.setdefault(person, {})[venue_type] = subsets

        for person, venue_dict in venue_dicts.items():
            person.activity_map[self.activity_map_key] = venue_dict
            if self.activity_map_key not in person.activities:
                person.add_activity(self.activity_map_key)

        logger.info(f"Allocated venues to {len(venue_dicts)} people")

    def _allocate_venues(self, people: List, world):
        """
        Allocate venues to each person using geo_unit batching for performance.

        Groups people by their geographical_unit coordinates.

        Args:
            people: List of eligible people
            world: World object
        """
        if self.consider_by == "geo_unit":
            self._allocate_venues_by_geo_unit(people, world)
            return

        # Step 1: Group people by geographical_unit
        people_by_geo_unit = {}
        for person in people:
            geo_unit = person.geographical_unit
            if geo_unit is None:
                continue
            if geo_unit not in people_by_geo_unit:
                people_by_geo_unit[geo_unit] = []
            people_by_geo_unit[geo_unit].append(person)

        logger.info(
            f"Batching {len(people)} people into {len(people_by_geo_unit)} unique geo_units"
        )

        # Step 2: For each unique geo_unit, query spatial index once per venue_type
        geo_unit_venue_cache = {}  # (geo_unit, venue_type) -> [venues]

        for geo_unit in people_by_geo_unit.keys():
            # Get geo_unit coordinates
            if geo_unit.coordinates is None or len(geo_unit.coordinates) != 2:
                logger.warning(
                    f"Geo unit {geo_unit.name} has invalid coordinates ({getattr(geo_unit, 'coordinates', None)}), "
                    f"skipping {len(people_by_geo_unit[geo_unit])} people"
                )
                continue

            coords = list(geo_unit.coordinates)

            # Query once per venue type for this geo_unit
            for venue_type in self.venue_types:
                cache_key = (geo_unit, venue_type)
                geo_unit_venue_cache[cache_key] = self._find_closest_venues(
                    coords, venue_type, self._get_venue_count_for_type(venue_type)
                )

        # Step 3: Assign cached venue results to all people in each geo_unit
        allocated_count = 0

        # Progress tracking
        total_people = len(people)
        people_processed = 0
        progress_interval = max(1, total_people // 10)  # Update every 10%

        for geo_unit, geo_unit_people in people_by_geo_unit.items():
            for person in geo_unit_people:
                venue_dict = {}

                # Get cached venues for each venue type
                for venue_type in self.venue_types:
                    # Check if person should get this venue type (participation filtering)
                    if not self._should_allocate_venue_type(person, venue_type):
                        continue

                    cache_key = (geo_unit, venue_type)
                    venues = geo_unit_venue_cache.get(cache_key, [])

                    if venues:
                        # Create subsets and add person to each
                        subsets = []
                        for venue in venues:
                            subset = self._get_or_create_subset(venue)
                            subset.add_member(person)
                            subsets.append(subset)

                        venue_dict[venue_type] = subsets

                # Store in activity_map if we found any venues
                if venue_dict:
                    person.activity_map[self.activity_map_key] = venue_dict

                    # Add activity to person's activities list
                    if self.activity_map_key not in person.activities:
                        person.add_activity(self.activity_map_key)

                    allocated_count += 1

                # Update progress tracking
                people_processed += 1
                if (
                    people_processed % progress_interval == 0
                    or people_processed == total_people
                ):
                    percent_complete = (people_processed / total_people) * 100
                    logger.info(
                        f"  Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated"
                    )

        logger.info(f"Allocated venues to {allocated_count} people")

    def _get_or_create_subset(self, venue):
        """
        Get or create a subset with the configured subset_key.

        Args:
            venue: Venue object

        Returns:
            Subset object
        """
        # Check if subset already exists
        if self.subset_key in venue.subsets:
            return venue.subsets[self.subset_key]

        # Create new subset — use max existing index + 1 to avoid collisions after deletions
        subset_index = (
            (max(s.subset_index for s in venue.subsets.values()) + 1)
            if venue.subsets
            else 0
        )
        subset = Subset(
            venue=venue, subset_index=subset_index, subset_name=self.subset_key
        )
        venue.subsets[self.subset_key] = subset

        return subset

    def _log_summary(self, world):
        """Log summary statistics of allocation."""
        total_allocated = 0
        type_counts = {vtype: 0 for vtype in self.venue_types}
        venue_count_stats = {vtype: [] for vtype in self.venue_types}

        for person in world.people:
            if self.activity_map_key in person.activity_map:
                total_allocated += 1

                venue_dict = person.activity_map[self.activity_map_key]
                for vtype in self.venue_types:
                    if vtype in venue_dict and venue_dict[vtype]:
                        type_counts[vtype] += 1
                        venue_count_stats[vtype].append(len(venue_dict[vtype]))

        logger.info("=== MultiVenueDistributor Summary ===")
        logger.info(f"Total people allocated: {total_allocated}")
        logger.info(f"Breakdown by venue type:")
        for vtype, count in type_counts.items():
            if venue_count_stats[vtype]:
                avg_venues = sum(venue_count_stats[vtype]) / len(
                    venue_count_stats[vtype]
                )
                logger.info(
                    f"  - {vtype}: {count} people (avg {avg_venues:.1f} venues/person)"
                )
            else:
                logger.info(f"  - {vtype}: {count} people")

    @property
    def venue_type(self):
        """Return the activity map key as this distributor's venue type."""
        return self.activity_map_key
