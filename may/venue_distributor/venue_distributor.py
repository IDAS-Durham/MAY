"""
VenueDistributor: System for allocating people to venues

This module reads distributor configuration from YAML files and allocates people
to venues based on flexible rules including:
- Attribute matching (age, gender, etc.)
- Distance constraints
- Capacity management
- Special case handling (e.g., boarding school students)
"""

from .base_distributor import BaseDistributor
from ._allocation import VenueAllocation
from .probability import (
    GEO_UNIT_LOOKUP_ATTRIBUTE,
    RETIRED_PROBABILITY_KEYS,
    ProbabilityConfigError,
    probability_cache_key,
)
from may.utils import path_resolver as pr
from may.utils.attribute_access import get_attribute
from may.utils.stacked_input import as_path_list, load_stacked_csv

import logging
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class VenueDistributor(BaseDistributor):
    """
    Main class for distributing people to venues based on YAML configuration.

    Features:
    - YAML-driven configuration
    - Special case handling (boarding schools, etc.)
    - Distance-based venue selection with spatial indexing
    - Attribute filtering (age, gender, etc.)
    - Capacity tracking
    - Batch processing by geo_unit for performance
    """

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        """
        Initialize VenueDistributor.

        Args:
            config_file: Path to YAML config file
            config_dict: Dictionary config (alternative to file)
        """
        super().__init__(config_file, config_dict)

        # Initialize core attributes
        self.venue_type = self.config.get("venue_type", "unknown")
        self.activity_map_key = self.config.get("activity_map_key", "unknown")
        self.subset_key = self.config.get("subset_key", None)
        self.activity_type = self.config.get("activity_type", None)

        # One internal owner keeps the allocation state together.
        self.allocation = VenueAllocation(self)

        self._pre_processed_filters = self._pre_process_filters(
            self.config.get("eligibility", {}).get("global_filters", [])
        )
        self._pre_processed_match_attrs = self._pre_process_filters(
            self.config.get("eligibility", {}).get("attributes", [])
        )
        self._pre_processed_exclude = self.config.get("eligibility", {}).get(
            "exclude", {}
        )

        # State and tracking
        self.probability_cache = {}
        self.venue_capacity_tracker = {}

        # Load probability files
        self._load_probability_files()

        logger.info(f"Initialized VenueDistributor for venue_type='{self.venue_type}'")

    def _load_probability_files(self):
        """
        Load probability CSV files for priority allocation groups.

        Builds a cache of {geo_unit_name: probability} for fast lookup during allocation.
        """
        priority_config = self.config.get("eligibility", {}).get(
            "priority_allocation", {}
        )

        if not priority_config.get("enabled", False):
            return

        groups = priority_config.get("groups", [])

        for group in groups:
            prob_config = group.get("probability_config")

            # Skip if no probability config or if it's a simple float
            if not prob_config or isinstance(prob_config, (int, float)):
                continue

            # Only load file-based probabilities
            if prob_config.get("type") != "file":
                continue

            group_name = group.get("name")
            label = f"group '{group_name}': probability_config"

            retired = [k for k in RETIRED_PROBABILITY_KEYS if k in prob_config]
            if retired:
                raise ProbabilityConfigError(
                    f"{label} has retired key(s) {retired}. Probability files must "
                    f"cover the loaded geography; remove the key(s)."
                )

            file_path = prob_config.get("file_path")
            lookup_column = prob_config.get("lookup_column", "geo_unit")
            probability_column = prob_config.get("probability_column")

            if not file_path or not probability_column:
                raise ProbabilityConfigError(
                    f"{label} needs both 'file_path' and 'probability_column'; got "
                    f"file_path={file_path!r}, probability_column={probability_column!r}."
                )

            cache_key = probability_cache_key(prob_config)
            if cache_key in self.probability_cache:
                continue

            paths = [
                self._resolve_probability_path(p)
                for p in as_path_list(file_path, f"{label}.file_path")
            ]
            df = load_stacked_csv(
                paths, label=label, key_column=lookup_column, column_policy="strict"
            )

            missing_columns = [
                c for c in (lookup_column, probability_column) if c not in df.columns
            ]
            if missing_columns:
                raise ProbabilityConfigError(
                    f"{label}: column(s) {missing_columns} not found in {paths}; "
                    f"the files carry {list(df.columns)}."
                )

            self.probability_cache[cache_key] = {
                "lookup": dict(zip(df[lookup_column], df[probability_column])),
                "lookup_attribute": prob_config.get(
                    "lookup_attribute", GEO_UNIT_LOOKUP_ATTRIBUTE
                ),
                "label": label,
            }
            logger.info(
                f"{label}: loaded {len(df)} probabilities from column "
                f"'{probability_column}' across {len(paths)} file(s)"
            )

    def _resolve_probability_path(self, file_path):
        """
        Resolve portable path tokens (${data_root} etc.), then try the path
        as-given (CWD-relative) before resolving against the project root.
        """
        resolved = pr.resolve(file_path)
        full_path = Path(resolved)
        if not full_path.is_absolute() and not full_path.exists():
            if self.config_path:
                # config_path is configs/<year>/distributors/xxx.yaml
                project_root = self.config_path.parent.parent.parent
                candidate = project_root / resolved
                if candidate.exists():
                    full_path = candidate
            else:
                logger.warning(
                    f"Cannot resolve relative path '{file_path}' for a probability "
                    f"file without a config_file path. Assuming absolute path."
                )
        return str(full_path)

    def _check_probability_coverage(self, world):
        """
        Every loaded SGU must have a row in each geography-keyed probability
        table. A nation added to the geography but forgotten in a probability
        file list would otherwise place none of its students, silently.
        """
        if not self.probability_cache or world.geography is None:
            return

        sgu_level = world.geography.levels[0]
        loaded_sgus = set(world.geography.get_units_by_level(sgu_level))
        if not loaded_sgus:
            return

        for cached in self.probability_cache.values():
            if cached["lookup_attribute"] != GEO_UNIT_LOOKUP_ATTRIBUTE:
                # The lookup key is not the geography, so coverage is not a
                # claim this check can make.
                continue
            missing = loaded_sgus - set(cached["lookup"])
            if missing:
                raise ProbabilityConfigError(
                    f"{cached['label']}: {len(missing)} of {len(loaded_sgus)} loaded "
                    f"{sgu_level}s have no row (e.g. {sorted(missing)[:5]}). Add the "
                    f"missing file(s) to file_path, or scope the world with "
                    f"geography.filter."
                )

    def allocate(self, world):
        """Main entry point: Allocate people to venues."""
        self.world = world
        self.allocated_this_run = 0

        logger.info(f"Starting allocation for {self.venue_type}")

        self._check_probability_coverage(world)

        venues = world.venues_by_type(self.venue_type)
        if not venues:
            logger.warning(f"No venues of type '{self.venue_type}' found")
            return

        # Pre-calculate set of venue IDs for fast membership testing in matcher
        self.venue_ids = {id(v) for v in venues}

        # Prepare spatial and attribute indices
        if self.config.get("settings", {}).get("use_spatial_index", True):
            self._build_spatial_indices({self.venue_type: venues})

        self.allocation.build_attribute_index(venues)

        # Phase 1: Preparation
        all_unassigned = self._get_unassigned_people(world)
        if not all_unassigned:
            logger.info("No unassigned people to allocate")
            return

        # Prepare vectorized arrays
        self._prepare_vectorized_data(all_unassigned)

        # Phase 2: Special and Priority Allocations
        remaining, special_unallocated = self.allocation.handle_special_cases(
            all_unassigned, venues, world
        )
        eligible = self.allocation.apply_global_filters(remaining)

        unallocated_total = special_unallocated
        if not eligible:
            if unallocated_total:
                self.allocation.handle_fallbacks(unallocated_total, venues, world)
            self.allocation.log_allocation_summary(world, eligible_count=len(eligible))
            return

        remaining, priority_unallocated = self._handle_priority_allocation(
            eligible, venues
        )
        unallocated_total.extend(priority_unallocated)

        # Phase 3: Normal Allocation
        if remaining:
            vt = self.venue_type
            deprioritize_flag = self.config.get("allocation", {}).get(
                "deprioritize_flag"
            )
            if deprioritize_flag:
                # Allocate people WITHOUT the flag (e.g. native workers) first
                # so they claim capacity; people WITH it (e.g. redistributed
                # workers bounced back in-boundary) take only the remaining slack.
                # Capacity is tracked on the venues, so the second pass sees what the
                # first consumed. Flagged people left unallocated are an explicit
                # overflow category: kept as-is and counted.
                native = [
                    p for p in remaining if not p.properties.get(deprioritize_flag)
                ]
                flagged = [p for p in remaining if p.properties.get(deprioritize_flag)]
                native_unallocated = (
                    self._allocate_normal(native, venues) if native else []
                )
                flagged_unallocated = (
                    self._allocate_normal(flagged, venues) if flagged else []
                )
                # "Unplaced" = reached this step but found no in-boundary venue of this
                # type, either capacity full or no eligible venue (e.g. no matching sector
                # nearby). For a workplace distributor that is effectively unemployment.
                logger.info(
                    f"  [capacity priority] '{vt}': "
                    f"{len(native) - len(native_unallocated):,}/{len(native):,} non-flagged placed "
                    f"({len(native_unallocated):,} unplaced — no in-boundary {vt}: "
                    f"capacity full or no eligible venue); "
                    f"{len(flagged) - len(flagged_unallocated):,}/{len(flagged):,} '{deprioritize_flag}' placed "
                    f"({len(flagged_unallocated):,} unplaced -> outside, kept attempted destination, no venue)."
                )
                unallocated_total.extend(native_unallocated)
                unallocated_total.extend(flagged_unallocated)
            else:
                # No deprioritisation: single normal pass. The honest eligible-vs-
                # allocated tally (incl. anything placed in the priority phase above)
                # is reported by reporting.log_allocation_summary. Logging the
                # phase-3 remainder here would understate placement for priority-
                # allocation distributors (e.g. university), so the summary handles it.
                normal_unallocated = self._allocate_normal(remaining, venues)
                unallocated_total.extend(normal_unallocated)

        # Phase 4: Fallbacks and Verification
        if unallocated_total:
            self.allocation.handle_fallbacks(unallocated_total, venues, world)

        # Phase 4.5: Enforce no empty venues (optional)
        if self.config.get("allocation", {}).get("enforce_no_empty_venues", False):
            self._enforce_no_empty_venues(venues)

        self.allocation.log_allocation_summary(world, eligible_count=len(eligible))
        # self.allocation.check_priority_coverage(world) # Temporarily disabled for performance (slow 630k scan)

    def _enforce_no_empty_venues(self, venues):
        """Post-allocation: ensure every venue has at least 1 person.

        For each empty venue, steal the nearest person from the venue
        with the most people. This guarantees minimum occupancy while
        minimally disrupting the existing distribution.

        Note: if there are fewer people than venues, it's impossible to
        fill all venues. In that case, we fill as many as possible.
        """
        subset_key = self.subset_key

        # Build lists of empty and populated venues
        empty_venues = []
        populated_venues = []
        total_people = 0
        for v in venues:
            count = self.venue_capacity_tracker.get(id(v), 0)
            total_people += count
            if count == 0:
                empty_venues.append(v)
            else:
                populated_venues.append((v, count))

        if not empty_venues:
            return

        # Check if we have enough people to fill all empty venues
        # We can only steal from venues that have >1 people
        stealable = sum(max(0, c - 1) for _, c in populated_venues)
        fillable = min(len(empty_venues), stealable)

        if fillable == 0:
            logger.warning(
                f"  enforce_no_empty_venues: Cannot fill {len(empty_venues)} empty venues — "
                f"only {total_people} people across {len(venues)} venues "
                f"(no venue has >1 to spare)"
            )
            return

        if fillable < len(empty_venues):
            logger.info(
                f"  enforce_no_empty_venues: Can fill {fillable}/{len(empty_venues)} empty venues "
                f"({total_people} people across {len(venues)} venues)"
            )

        # Sort populated venues by count descending (steal from most overfull first)
        populated_venues.sort(key=lambda x: x[1], reverse=True)

        reassigned = 0
        for empty_venue in empty_venues:
            # Find the most overfull venue that still has >1 people
            donor = None
            for pv, _ in populated_venues:
                current_count = self.venue_capacity_tracker.get(id(pv), 0)
                if current_count > 1:
                    donor = pv
                    break

            if not donor:
                break  # No more donors available

            # Get the donor's subset and pick a person
            donor_subset = donor.subsets.get(subset_key)
            if not donor_subset or len(donor_subset.members) < 2:
                continue

            # Pick person closest to the empty venue
            empty_loc = self._get_venue_location(empty_venue)
            if empty_loc:
                person = min(
                    donor_subset.members,
                    key=lambda p: self._haversine_distance(
                        empty_loc, self._get_person_location(p) or empty_loc
                    ),
                )
            else:
                person = next(iter(donor_subset.members))

            # Remove from donor
            donor_subset.remove_member(person)
            self.venue_capacity_tracker[id(donor)] -= 1

            # Remove from person's activity_map
            activity_type_key = (
                self.activity_type if self.activity_type else self.venue_type
            )
            if self.activity_map_key in person.activity_map:
                activity_dict = person.activity_map[self.activity_map_key]
                if (
                    isinstance(activity_dict, dict)
                    and activity_type_key in activity_dict
                ):
                    activity_dict[activity_type_key] = [
                        s
                        for s in activity_dict[activity_type_key]
                        if s.venue.id != donor.id
                    ]

            # Add to empty venue
            empty_venue.add_to_subset(
                person,
                subset_key=subset_key,
                activity_name=self.activity_map_key,
                activity_type=self.activity_type,
            )
            self._increment_venue_count(empty_venue)
            reassigned += 1

            # Re-sort populated venues (donor count changed)
            populated_venues.sort(
                key=lambda x: self.venue_capacity_tracker.get(id(x[0]), 0), reverse=True
            )

        remaining_empty = len(empty_venues) - reassigned
        logger.info(
            f"  enforce_no_empty_venues: Reassigned {reassigned}/{len(empty_venues)} empty venues"
            + (
                f" ({remaining_empty} unfillable — not enough people)"
                if remaining_empty > 0
                else ""
            )
        )

    def _prepare_vectorized_data(self, people: List):
        """Build population arrays for all attributes used in filters."""
        attrs = set()
        numerical_attrs = set()
        configs = [
            self.config.get("eligibility", {}).get("global_filters", []),
            *[
                g.get("filters", [])
                for g in self.config.get("eligibility", {})
                .get("priority_allocation", {})
                .get("groups", [])
            ],
        ]
        for filter_list in configs:
            for f in filter_list:
                attr = f.get("attribute")
                if attr:
                    attrs.add(attr)
                    if f.get("type") == "numerical":
                        numerical_attrs.add(attr)

        self._build_population_arrays(
            people, attributes=list(attrs), numerical_attributes=list(numerical_attrs)
        )

    def _get_unassigned_people(self, world) -> List:
        """Get people for allocation based on require_unassigned setting."""
        require_unassigned = self.config.get("eligibility", {}).get(
            "require_unassigned", True
        )
        unassigned = []

        required_attrs = self.config.get("validation", {}).get(
            "required_person_attributes", []
        )
        activity_map_key = self.activity_map_key

        for person in world.people:
            if require_unassigned and activity_map_key in person.activity_map:
                continue

            if required_attrs and not self._has_required_attributes(
                person, required_attrs
            ):
                continue

            unassigned.append(person)
        return unassigned

    def _has_required_attributes(self, person, required_attrs: List[str]) -> bool:
        """Check if person has all required attributes."""
        for attr in required_attrs:
            if get_attribute(person, attr) is None:
                return False
        return True

    def _handle_priority_allocation(
        self, eligible_people: List, venues: List
    ) -> Tuple[List, List]:
        """Handle priority allocation groups (processed before normal allocation)."""
        priority_config = self.config.get("eligibility", {}).get(
            "priority_allocation", {}
        )
        if not priority_config or not priority_config.get("enabled", False):
            return eligible_people, []

        groups = priority_config.get("groups", [])
        logger.info("=" * 60)
        logger.info(f"PHASE 2: Priority allocation ({len(groups)} groups)")

        remaining_people = list(eligible_people)
        unallocated_priority_people = []
        all_priority_people = []

        # Sort groups by priority
        groups_sorted = sorted(groups, key=lambda g: g.get("priority", 999))

        for group in groups_sorted:
            group_name = group.get("name", "unnamed")
            filters = self._pre_process_filters(group.get("filters", []))
            allow_overflow = group.get("allow_overflow", False)

            group_people = []

            # Use filtering manager for matching
            if (
                self.population_arrays
                and len(remaining_people) > 1000
                and self._can_vectorize_filters(filters)
            ):
                indices = [
                    self.person_id_to_index[p.id]
                    for p in remaining_people
                    if p.id in self.person_id_to_index
                ]
                if len(indices) == len(remaining_people):
                    indices_arr = np.array(indices, dtype=np.int32)
                    filtered_indices = self._apply_filters_vectorized(
                        indices_arr, filters
                    )
                    group_people = self.population_arrays["people"][
                        filtered_indices
                    ].tolist()

            if not group_people:
                group_people = [
                    p
                    for p in remaining_people
                    if self.allocation.person_matches_filters(p, filters)
                ]

            if not group_people:
                continue

            # Probability filtering
            prob_config = group.get("probability_config")
            if prob_config:
                group_people = self.allocation.apply_probability_filter(
                    group_people, prob_config, group_name
                )

            if not group_people:
                continue

            # Sort and allocate.
            #
            # Population is created sorted by (age, sex) (see Population.generate_population),
            # so within any age the females (lower ids) precede the males. When a group
            # respects capacity (allow_overflow=False), processing in that order lets the
            # earlier sex claim scarce venue spots first and systematically excludes the
            # other, a directional gender bias in capacity-limited cohorts (e.g. sixth
            # form, nurseries). Overflow groups place everyone regardless of order, so they
            # keep the cheap deterministic ordering.
            #
            # Fix: randomise order within each priority tier. A random sort key (folded into
            # the existing sort, so it costs nothing extra) breaks the sex ordering while
            # preserving the age_desc priority via the primary key.
            randomize = not allow_overflow
            if priority_config.get("priority_order") == "age_desc":
                if randomize:
                    group_people.sort(key=lambda p: (-p.age, np.random.random()))
                else:
                    group_people.sort(key=lambda p: p.age, reverse=True)
            elif randomize:
                np.random.shuffle(group_people)

            logger.info(f"Group '{group_name}': {len(group_people)} selected")

            if allow_overflow:
                original_when_full = self.config.get("allocation", {}).get(
                    "when_full", "exclude"
                )
                self.config.setdefault("allocation", {})["when_full"] = "overflow"

            try:
                allocated_count = self.allocation.allocate_group(
                    group_people,
                    venues,
                    allow_overflow=allow_overflow,
                    group_search_limits=group.get("search_limits"),
                )
            finally:
                if allow_overflow:
                    self.config["allocation"]["when_full"] = original_when_full

            # Tracking
            for p in group_people:
                if self.activity_map_key not in p.activity_map:
                    unallocated_priority_people.append(p)

            self.allocated_this_run += allocated_count
            all_priority_people.extend(group_people)

        priority_ids = {p.id for p in all_priority_people}
        remaining_people = [p for p in remaining_people if p.id not in priority_ids]

        return remaining_people, unallocated_priority_people

    def _allocate_normal(self, people: List, venues: List) -> List:
        """Normal allocation for people not handled by special cases."""
        batch_by = self.config.get("allocation", {}).get("batch_by", "geo_unit")
        if batch_by == "geo_unit":
            return self.allocation.allocate_by_geo_unit(people, venues)
        else:
            return self.allocation.allocate_individual(people, venues)
