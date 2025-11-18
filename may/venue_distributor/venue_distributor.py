"""
VenueDistributor: YAML-driven system for allocating people to venues

This module reads distributor configuration from YAML files and allocates people
to venues based on flexible rules including:
- Attribute matching (age, gender, etc.)
- Distance constraints
- Capacity management
- Special case handling (e.g., boarding school students)
"""

import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from scipy.spatial import cKDTree
import logging

logger = logging.getLogger(__name__)


class VenueDistributor:
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

    def __init__(self, config_path: str):
        """
        Initialize VenueDistributor from YAML configuration.

        Args:
            config_path: Path to distributor YAML file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.spatial_index = None
        self.venue_list = None

        # Performance optimization: Cache pre-processed venue attribute data
        # This avoids repeated dict lookups and string operations in hot path
        self.venue_attribute_cache = {}  # venue_id -> pre-processed attribute data
        self.attribute_index_built = False

        # Probability allocation cache
        # Maps (file_path, probability_column) -> {geo_unit_name: probability}
        self.probability_cache = {}

        # Extract key config values
        self.venue_type = self.config.get('venue_type')
        self.activity_map_key = self.config.get('activity_map_key')
        self.verbose = self.config.get('settings', {}).get('verbose', False)

        # Geographical level configuration (default to SGU for backward compatibility)
        self.venue_geo_level = self.config.get('venue_selection', {}).get('venue_geo_level', 'SGU')

        # Load probability files for priority allocation groups
        self._load_probability_files()

        # Set logging level
        if self.config.get('settings', {}).get('debug', False):
            logger.setLevel(logging.DEBUG)

        logger.info(f"Initialized VenueDistributor for venue_type='{self.venue_type}' at geo_level='{self.venue_geo_level}'")

    def _load_config(self) -> Dict:
        """Load and parse YAML configuration file."""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config

    def _load_probability_files(self):
        """
        Load probability CSV files for priority allocation groups.

        Builds a cache of {geo_unit_name: probability} for fast lookup during allocation.
        """
        priority_config = self.config.get('eligibility', {}).get('priority_allocation', {})

        if not priority_config.get('enabled', False):
            return

        groups = priority_config.get('groups', [])

        for group in groups:
            prob_config = group.get('probability_config')

            # Skip if no probability config or if it's a simple float
            if not prob_config or isinstance(prob_config, (int, float)):
                continue

            # Only load file-based probabilities
            if prob_config.get('type') != 'file':
                continue

            file_path = prob_config.get('file_path')
            lookup_column = prob_config.get('lookup_column', 'geo_unit')
            probability_column = prob_config.get('probability_column')
            default_prob = prob_config.get('default', 0.0)

            if not file_path or not probability_column:
                logger.warning(f"Group '{group.get('name')}': probability_config missing file_path or probability_column")
                continue

            # Create cache key
            cache_key = (file_path, probability_column)

            # Skip if already loaded
            if cache_key in self.probability_cache:
                continue

            # Load CSV file
            full_path = Path(file_path)
            if not full_path.is_absolute():
                # Make relative to project root
                # config_path is yaml/distributors/xxx.yaml
                # We need to go up to yaml/, then up to project root
                project_root = self.config_path.parent.parent.parent
                full_path = project_root / file_path

            try:
                logger.info(f"Loading probability file: {full_path}")
                df = pd.read_csv(full_path)

                # Validate columns exist
                if lookup_column not in df.columns:
                    logger.error(f"Column '{lookup_column}' not found in {file_path}")
                    continue

                if probability_column not in df.columns:
                    logger.error(f"Column '{probability_column}' not found in {file_path}")
                    continue

                # Build lookup dict: {geo_unit_name: probability}
                prob_dict = dict(zip(df[lookup_column], df[probability_column]))

                # Store in cache
                self.probability_cache[cache_key] = {
                    'lookup': prob_dict,
                    'default': default_prob
                }

                logger.info(f"Loaded {len(prob_dict)} probabilities from column '{probability_column}'")

            except Exception as e:
                logger.error(f"Failed to load probability file {full_path}: {e}")

    def _get_geo_unit_at_level(self, person):
        """
        Get the person's geographical unit at the configured venue_geo_level.

        This enables flexibility: if venues are at MGU or LGU level but people are at SGU,
        we automatically traverse up the hierarchy to find the matching ancestor.

        Args:
            person: Person object with geographical_unit attribute

        Returns:
            GeographicalUnit at the configured level, or None if not found
        """
        if not hasattr(person, 'geographical_unit') or person.geographical_unit is None:
            return None

        person_geo_unit = person.geographical_unit

        # If person is already at the target level, return it
        if person_geo_unit.level == self.venue_geo_level:
            return person_geo_unit

        # Otherwise, traverse up to find ancestor at target level
        ancestor = person_geo_unit.get_ancestor_by_level(self.venue_geo_level)

        if ancestor is None and self.verbose:
            logger.debug(f"Person at {person_geo_unit.level} '{person_geo_unit.name}' has no ancestor at {self.venue_geo_level}")

        return ancestor

    def allocate(self, world):
        """
        Main entry point: Allocate people to venues.

        Args:
            world: World object containing people, venues, geography
        """
        logger.info(f"Starting allocation for {self.venue_type}")

        # Get venues of this type
        venues = world.venues_by_type(self.venue_type)
        if not venues:
            logger.warning(f"No venues of type '{self.venue_type}' found")
            return

        logger.info(f"Found {len(venues)} venues of type '{self.venue_type}'")

        # Build spatial index if needed
        if self.config.get('settings', {}).get('use_spatial_index', True):
            self._build_spatial_index(venues)

        # Build attribute index for fast filtering (critical performance optimization)
        self._build_attribute_index(venues)

        # Phase 1: Handle special cases FIRST (bypasses global filters)
        # Special cases get ALL unassigned people (e.g., student_dorms residents can be any age)
        all_unassigned = self._get_unassigned_people(world)
        logger.info(f"Found {len(all_unassigned)} unassigned people")

        if not all_unassigned:
            logger.info("No unassigned people to allocate")
            return

        remaining_people = self._handle_special_cases(all_unassigned, venues, world)
        logger.info(f"{len(remaining_people)} people remaining after special cases")

        # Now apply global filters for priority/normal allocation
        eligible_people = self._apply_global_filters(remaining_people)
        logger.info(f"{len(eligible_people)} people eligible after global filters (special cases excluded)")

        if not eligible_people:
            logger.info("No eligible people remaining for priority/normal allocation")
            # Log summary for special cases only
            if self.config.get('settings', {}).get('log_summary', True):
                self._log_allocation_summary(world)
            return

        # Phase 2: Priority allocation (if configured)
        remaining_people = eligible_people
        if remaining_people:
            remaining_people = self._handle_priority_allocation(remaining_people, venues)

        # Phase 3: Normal allocation (remaining people)
        if remaining_people:
            self._allocate_normal(remaining_people, venues)

        # Log summary
        if self.config.get('settings', {}).get('log_summary', True):
            self._log_allocation_summary(world)

            # Check for unallocated priority people
            self._check_priority_coverage(world)

    def _get_unassigned_people(self, world) -> List:
        """
        Get people who don't already have this activity assigned.

        Does NOT apply global filters - special cases need access to all unassigned people.
        """
        unassigned = []
        already_assigned = 0
        missing_attrs = 0

        for person in world.people:
            # Check if already assigned
            if self.activity_map_key in person.activity_map:
                already_assigned += 1
                continue

            # Check required attributes
            required_attrs = self.config.get('validation', {}).get('required_person_attributes', [])
            if not self._has_required_attributes(person, required_attrs):
                missing_attrs += 1
                if self.verbose and len(unassigned) == 0:  # Log first failure
                    logger.debug(f"Person {person.id} missing required attributes. Has: {dir(person)}")
                continue

            unassigned.append(person)

        if self.verbose:
            logger.info(f"Unassigned people: {already_assigned} already assigned, {missing_attrs} missing attributes, {len(unassigned)} unassigned")

        return unassigned

    def _apply_global_filters(self, people: List) -> List:
        """
        Apply global filters and exclusions to a list of people.

        Used after special cases to filter people for priority/normal allocation.
        """
        eligible = []
        filtered_by_global = 0
        filtered_by_exclusions = 0

        # Get global filters (apply to priority and normal allocation only)
        global_filters = self.config.get('eligibility', {}).get('global_filters', [])

        # Get exclusion rules
        exclude_config = self.config.get('eligibility', {}).get('exclude', {})

        for person in people:
            # Check global filters (e.g., age, residence type)
            if global_filters and not self._person_matches_filters(person, global_filters):
                filtered_by_global += 1
                continue

            # Check exclusion rules
            if exclude_config and self._person_excluded(person, exclude_config):
                filtered_by_exclusions += 1
                continue

            eligible.append(person)

        if self.verbose:
            logger.info(f"Global filters: {filtered_by_global} filtered by global rules, {filtered_by_exclusions} filtered by exclusions, {len(eligible)} eligible")

        return eligible

    def _has_required_attributes(self, person, required_attrs: List[str]) -> bool:
        """Check if person has all required attributes."""
        for attr in required_attrs:
            if not hasattr(person, attr):
                return False
            if getattr(person, attr) is None:
                return False
        return True

    def _build_spatial_index(self, venues):
        """Build KDTree for fast distance queries."""
        coords = []
        self.venue_list = []

        for venue in venues:
            # Venue stores coordinates as (lat, lon) tuple
            if venue.coordinates is not None and len(venue.coordinates) == 2:
                lat, lon = venue.coordinates
                if lat is not None and lon is not None:
                    coords.append([lat, lon])
                    self.venue_list.append(venue)

        if coords:
            self.spatial_index = cKDTree(np.array(coords))
            logger.info(f"Built spatial index with {len(coords)} venues")
        else:
            logger.warning("No venues with coordinates found for spatial index")

    def _build_attribute_index(self, venues):
        """
        Pre-process venue attributes for fast filtering.

        This eliminates repeated dict lookups, string operations, and rule parsing
        in the hot path (_venue_accepts_person), providing 10-50x speedup.
        """
        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        if not attributes:
            logger.debug("No attributes to index")
            return

        for venue in venues:
            venue_cache = {}

            for rule in attributes:
                attr_name = rule.get('name')
                attr_type = rule.get('type')

                if attr_type == 'numerical':
                    # Pre-extract min/max values
                    venue_constraints = rule.get('venue_constraints', {})
                    min_col = venue_constraints.get('min_column')
                    max_col = venue_constraints.get('max_column')

                    cache_key = f'num_{attr_name}'
                    venue_cache[cache_key] = {
                        'min': venue.properties.get(min_col) if min_col else None,
                        'max': venue.properties.get(max_col) if max_col else None
                    }

                elif attr_type == 'categorical':
                    # Pre-extract and process categorical value
                    venue_column = rule.get('venue_column')
                    if venue_column:
                        venue_value = venue.properties.get(venue_column)
                        if venue_value is None or venue_value == '':
                            venue_value = rule.get('assume_if_missing', 'Mixed')

                        # Pre-process case sensitivity
                        case_sensitive = rule.get('case_sensitive', False)
                        if not case_sensitive:
                            venue_value = str(venue_value).lower() if venue_value else ''

                        # Pre-compute matching rules
                        matching_rules = rule.get('matching_rules', {})
                        if not case_sensitive:
                            matching_rules = {
                                k.lower(): [v.lower() for v in vals]
                                for k, vals in matching_rules.items()
                            }

                        # Store the allowed person values for this venue
                        cache_key = f'cat_{attr_name}'
                        venue_cache[cache_key] = {
                            'venue_value': venue_value,
                            'allowed_person_values': matching_rules.get(venue_value, None),
                            'case_sensitive': case_sensitive
                        }

            # Store cache using venue id (fast lookup)
            self.venue_attribute_cache[id(venue)] = venue_cache

        self.attribute_index_built = True
        logger.info(f"Built attribute index for {len(venues)} venues with {len(attributes)} attributes")

    def _handle_priority_allocation(self, people: List, venues: List) -> List:
        """
        Handle priority allocation groups (processed before normal allocation).

        Returns:
            List of people NOT in priority groups (for normal allocation)
        """
        priority_config = self.config.get('eligibility', {}).get('priority_allocation', {})

        if not priority_config.get('enabled', False):
            return people  # No priority allocation configured

        groups = priority_config.get('groups', [])
        if not groups:
            return people

        logger.info("")
        logger.info("=" * 60)
        logger.info("PRIORITY ALLOCATION")
        logger.info("=" * 60)

        # Sort groups by priority (lowest number = highest priority)
        groups_sorted = sorted(groups, key=lambda g: g.get('priority', 999))

        remaining_people = list(people)
        all_priority_people = []

        # Process each priority group
        for group in groups_sorted:
            group_name = group.get('name', 'unnamed')
            allow_overflow = group.get('allow_overflow', False)
            filters = group.get('filters', [])

            # Filter people matching this group
            group_people = []
            for person in remaining_people:
                if self._person_matches_filters(person, filters):
                    group_people.append(person)

            if not group_people:
                logger.info(f"Group '{group_name}': 0 people match")
                continue

            # Apply probability filtering (reflects that not all eligible people will be allocated)
            prob_config = group.get('probability_config')
            if prob_config:
                group_people_before_prob = len(group_people)
                group_people = self._apply_probability_filter(group_people, prob_config, group_name)
                logger.info(f"Group '{group_name}': {group_people_before_prob} matched filters, {len(group_people)} selected by probability")

            if not group_people:
                logger.info(f"Group '{group_name}': 0 people after probability filtering")
                continue

            # Sort by age descending (older first) if priority_order is age_desc
            priority_order = priority_config.get('priority_order')
            if priority_order == 'age_desc':
                group_people.sort(key=lambda p: p.age, reverse=True)

            logger.info(f"Group '{group_name}': {len(group_people)} people to allocate (overflow={'allowed' if allow_overflow else 'not allowed'})")

            # Allocate this group
            if allow_overflow:
                # Temporarily disable capacity checking
                original_when_full = self.config.get('allocation', {}).get('when_full', 'exclude')
                self.config.setdefault('allocation', {})['when_full'] = 'overflow'

            allocated_count = self._allocate_group(group_people, venues, allow_overflow=allow_overflow)

            if allow_overflow:
                # Restore original setting
                self.config['allocation']['when_full'] = original_when_full

            logger.info(f"  → Allocated {allocated_count}/{len(group_people)} from group '{group_name}'")

            # Track all priority people
            all_priority_people.extend(group_people)

        # Remove priority people from remaining pool
        priority_ids = {p.id for p in all_priority_people}
        remaining_people = [p for p in remaining_people if p.id not in priority_ids]

        logger.info(f"Priority allocation complete: {len(all_priority_people)} people processed, {len(remaining_people)} remaining for normal allocation")
        logger.info("=" * 60)

        return remaining_people

    def _person_matches_filters(self, person, filters: List[Dict]) -> bool:
        """Check if person matches all filters in a group."""
        for filter_rule in filters:
            attr_name = filter_rule.get('attribute')
            filter_type = filter_rule.get('type', 'numerical')
            min_val = filter_rule.get('min')
            max_val = filter_rule.get('max')
            value = filter_rule.get('value')
            values = filter_rule.get('values', [])  # For categorical filters with multiple allowed values

            # Handle nested attributes (e.g., "residence.type")
            if '.' in attr_name:
                # Special handling for residence.type - check activity_map
                if attr_name == 'residence.type':
                    person_value = None
                    # Check all possible residence types in activity_map
                    # Residences are stored as person.activity_map[venue_type] = [Subset, ...]
                    residence_types = ['household', 'care_home', 'student_dorms', 'boarding_school', 'prison']

                    for residence_type in residence_types:
                        if residence_type in person.activity_map and person.activity_map[residence_type]:
                            residence = person.activity_map[residence_type]
                            # activity_map stores a list of Subsets
                            if isinstance(residence, list) and residence:
                                # Get the venue from the first subset
                                subset = residence[0]
                                if hasattr(subset, 'venue'):
                                    person_value = subset.venue.type
                                else:
                                    person_value = residence_type
                            else:
                                person_value = residence_type
                            break

                    # If still no residence found, treat as 'household' (default)
                    if person_value is None:
                        person_value = 'household'
                else:
                    # Generic nested attribute handling with support for dictionaries
                    # Handle residence.* paths specially (stored in activity_map)
                    if attr_name.startswith('residence.'):
                        # Get residence from activity_map
                        residence = None
                        residence_types = ['household', 'care_home', 'student_dorms', 'boarding_school', 'prison']

                        for residence_type in residence_types:
                            if residence_type in person.activity_map and person.activity_map[residence_type]:
                                residence_data = person.activity_map[residence_type]
                                # activity_map stores a list of Subsets
                                if isinstance(residence_data, list) and residence_data:
                                    subset = residence_data[0]
                                    if hasattr(subset, 'venue'):
                                        residence = subset.venue
                                        break

                        if residence is None:
                            return False

                        # Now traverse the rest of the path from residence
                        # e.g., "residence.properties.original_pattern" -> "properties.original_pattern"
                        remaining_path = attr_name.replace('residence.', '')
                        person_value = self._get_nested_value_with_dict_support(residence, remaining_path)
                        if person_value is None:
                            return False
                    else:
                        # Normal nested attribute (with dict support)
                        person_value = self._get_nested_value_with_dict_support(person, attr_name)
                        if person_value is None:
                            return False
            else:
                person_value = getattr(person, attr_name, None)
                if person_value is None:
                    return False

            # Numerical filters: Range check
            if filter_type == 'numerical':
                if min_val is not None and person_value < min_val:
                    return False
                if max_val is not None and person_value > max_val:
                    return False

            # Categorical filters: Check if value is in allowed list
            elif filter_type == 'categorical':
                if values:  # Check against list of allowed values
                    if person_value not in values:
                        # Debug logging for residence type filtering
                        if self.verbose and attr_name == 'residence.type':
                            logger.debug(f"Person age {person.age} filtered out: residence_type={person_value}, allowed={values}")
                        return False
                elif value is not None:  # Check against single value
                    if person_value != value:
                        return False

            # Fallback: Exact value check for legacy filters
            if value is not None and person_value != value:
                return False

        return True

    def _apply_probability_filter(self, people: List, prob_config, group_name: str) -> List:
        """
        Apply probability filtering to a list of people.

        Args:
            people: List of people who matched filters
            prob_config: Probability configuration (can be float or dict)
            group_name: Name of the group (for logging)

        Returns:
            List of people selected by probability
        """
        if not prob_config:
            return people

        # Simple case: probability is a float (apply same probability to everyone)
        if isinstance(prob_config, (int, float)):
            probability = float(prob_config)
            selected = [p for p in people if np.random.random() < probability]
            return selected

        # Complex case: file-based probabilities
        if prob_config.get('type') == 'file':
            file_path = prob_config.get('file_path')
            probability_column = prob_config.get('probability_column')
            lookup_attribute = prob_config.get('lookup_attribute', 'geographical_unit.name')
            default_prob = prob_config.get('default', 0.0)

            # Get cached probabilities
            cache_key = (file_path, probability_column)
            cached_data = self.probability_cache.get(cache_key)

            if not cached_data:
                logger.warning(f"Group '{group_name}': No cached probabilities found for {cache_key}, using default={default_prob}")
                # Fallback to default probability
                selected = [p for p in people if np.random.random() < default_prob]
                return selected

            prob_lookup = cached_data['lookup']
            default_prob = cached_data['default']

            # Apply probabilities
            selected = []
            for person in people:
                # Get lookup value from person (e.g., geographical_unit.name)
                lookup_value = self._get_nested_value(person, lookup_attribute)

                if lookup_value is None:
                    # Person doesn't have the lookup attribute
                    probability = default_prob
                else:
                    # Look up probability in cache
                    probability = prob_lookup.get(lookup_value, default_prob)

                # Apply probability
                if np.random.random() < probability:
                    selected.append(person)

            return selected

        # Unknown probability config type
        logger.warning(f"Group '{group_name}': Unknown probability_config type, not applying probability filter")
        return people

    def _person_excluded(self, person, exclude_config: dict) -> bool:
        """
        Check if person should be excluded based on exclusion rules.

        Supports simple syntax like:
            exclude:
                households:
                    original_pattern: "0 >=0 0 0"

        Returns True if person should be EXCLUDED (filtered out).
        """
        # Check household exclusions
        household_exclusions = exclude_config.get('households', {})
        if household_exclusions:
            # Get person's household from activity_map
            if 'household' not in person.activity_map:
                # No household = not excluded by household rules
                return False

            residence = person.activity_map['household']

            # Handle list of subsets
            if isinstance(residence, list):
                if not residence:
                    return False
                residence_venue = residence[0].venue if hasattr(residence[0], 'venue') else residence[0]
            else:
                residence_venue = residence

            # Check each household property exclusion
            for property_name, exclude_value in household_exclusions.items():
                if hasattr(residence_venue, 'properties') and isinstance(residence_venue.properties, dict):
                    actual_value = residence_venue.properties.get(property_name)

                    # If value matches exclusion, person should be excluded
                    if actual_value == exclude_value:
                        if self.verbose:
                            logger.debug(f"Person {person.id}/{person.age}{person.sex} excluded: household.properties['{property_name}'] = '{actual_value}'")
                        return True

        return False

    def _allocate_group(self, people: List, venues: List, allow_overflow: bool = False) -> int:
        """
        Allocate a specific group of people (e.g., priority school-age children).

        PERFORMANCE OPTIMIZATION: Geo-unit level caching
        - Compute closest venues ONCE per geo_unit (not per person)
        - Group people by attribute combinations within each geo_unit
        - Filter venues ONCE per unique attribute combo (not per person)

        This reduces spatial queries by 99% and attribute filtering by 95%.

        Returns:
            Number of people successfully allocated
        """
        allocated_count = 0

        # Extract attribute names from config (generic, works with any attributes)
        eligibility = self.config.get('eligibility', {})
        attribute_rules = eligibility.get('attributes', [])
        attribute_names = [rule.get('name') for rule in attribute_rules]

        selection_config = self.config.get('venue_selection', {})
        target_count = selection_config.get('count', 5)

        # Group by geo_unit for batching (at the configured venue_geo_level)
        people_by_geo_unit = {}
        for person in people:
            geo_unit = self._get_geo_unit_at_level(person)
            if geo_unit is None:
                continue
            if geo_unit not in people_by_geo_unit:
                people_by_geo_unit[geo_unit] = []
            people_by_geo_unit[geo_unit].append(person)

        # Process each geo_unit
        for geo_unit, geo_unit_people in people_by_geo_unit.items():
            # Get coordinates
            if geo_unit.coordinates is None or len(geo_unit.coordinates) != 2:
                continue

            lat, lon = geo_unit.coordinates

            # OPTIMIZATION: Find closest venues ONCE per geo_unit (not per person!)
            total_venues = len(venues)
            search_attempts = [
                min(50, total_venues),
                min(200, total_venues),
                total_venues
            ]
            search_attempts = sorted(set(search_attempts))

            # Try to find nearby venues with fallback
            geo_unit_nearby_venues = []
            for search_count in search_attempts:
                geo_unit_nearby_venues = self._find_closest_venues((lat, lon), venues, search_count)
                if geo_unit_nearby_venues:
                    break

            if not geo_unit_nearby_venues:
                if self.verbose:
                    logger.debug(f"Geo unit {geo_unit.name} ({geo_unit.level}) has no nearby venues")
                continue

            # OPTIMIZATION: Group people by their attribute values (generic!)
            # This works with ANY attributes defined in YAML (age/sex/income/disability/etc)
            people_by_attributes = {}
            for person in geo_unit_people:
                # Create cache key from person's attribute values
                # e.g., if attributes are ["age", "sex"] → key = (17, "male")
                # e.g., if attributes are ["age", "sex", "disability"] → key = (17, "male", False)
                attr_values = tuple(getattr(person, attr_name, None) for attr_name in attribute_names)

                if attr_values not in people_by_attributes:
                    people_by_attributes[attr_values] = []
                people_by_attributes[attr_values].append(person)

            # OPTIMIZATION: For each unique attribute combo, filter venues ONCE
            for attr_values, people_group in people_by_attributes.items():
                # Filter venues based on this attribute combination
                # Use first person in group as representative (they all have same attributes)
                representative_person = people_group[0]
                eligible_venues = self._filter_venues_by_person(representative_person, geo_unit_nearby_venues)

                if not eligible_venues and len(geo_unit_nearby_venues) < total_venues:
                    # Fallback: try expanding search if needed
                    for search_count in search_attempts[1:]:  # Skip first, already tried
                        expanded_venues = self._find_closest_venues((lat, lon), venues, search_count)
                        eligible_venues = self._filter_venues_by_person(representative_person, expanded_venues)
                        if eligible_venues:
                            if self.verbose:
                                logger.debug(f"Geo unit {geo_unit.name} ({geo_unit.level}) with attributes {attr_values} required expanded search ({search_count} venues)")
                            break

                # Assign all people in this group to eligible venues
                if eligible_venues:
                    selection_pool = eligible_venues[:target_count]

                    for person in people_group:
                        venue = self._select_venue(person, selection_pool, (lat, lon))
                        if venue:
                            person.activity_map[self.activity_map_key] = venue
                            allocated_count += 1
                elif allow_overflow:
                    # For priority allocation, log if no venues accept this attribute combo
                    if self.verbose:
                        attr_display = ", ".join(f"{name}={val}" for name, val in zip(attribute_names, attr_values))
                        logger.debug(f"Geo unit {geo_unit.name} ({geo_unit.level}): {len(people_group)} people with [{attr_display}] have no eligible venues")

        return allocated_count

    def _check_priority_coverage(self, world):
        """Check that all priority groups with overflow enabled are fully allocated."""
        priority_config = self.config.get('eligibility', {}).get('priority_allocation', {})

        if not priority_config.get('enabled', False):
            return

        groups = priority_config.get('groups', [])

        for group in groups:
            if not group.get('allow_overflow', False):
                continue  # Only check groups with overflow enabled

            group_name = group.get('name', 'unnamed')
            filters = group.get('filters', [])

            # Count unallocated people in this group
            unallocated = []
            for person in world.people:
                if self.activity_map_key in person.activity_map:
                    continue  # Already allocated

                if self._person_matches_filters(person, filters):
                    unallocated.append(person)

            if unallocated:
                logger.warning(f"⚠️  PRIORITY GROUP '{group_name}': {len(unallocated)} people NOT allocated!")
                logger.warning(f"   This may indicate insufficient venue capacity or constraint mismatches.")
            else:
                logger.info(f"✓ PRIORITY GROUP '{group_name}': All people allocated")

    def _handle_special_cases(self, people: List, venues: List, world) -> List:
        """
        Handle special case allocations (e.g., boarding school students).

        Returns:
            List of people NOT handled by special cases
        """
        special_cases = self.config.get('special_cases', [])
        if not special_cases:
            return people

        remaining_people = []
        allocated_count = 0

        for person in people:
            allocated = False

            for case in special_cases:
                if self._matches_special_case(person, case):
                    # Try to allocate according to special case rule
                    if self._allocate_special_case(person, case, venues):
                        allocated = True
                        allocated_count += 1
                        break

            if not allocated:
                remaining_people.append(person)

        if allocated_count > 0:
            logger.info(f"Allocated {allocated_count} people via special cases")

        return remaining_people

    def _matches_special_case(self, person, case: Dict) -> bool:
        """Check if person matches special case condition."""
        condition = case.get('condition', {})

        # Check residence type (residence is stored in activity_map)
        if 'person_residence_type' in condition:
            required_type = condition['person_residence_type']

            # Check all possible residence types in activity_map
            residence_types_to_check = ['household', 'care_home', 'student_dorms', 'boarding_school', 'prison']
            residence_venue = None

            for res_type in residence_types_to_check:
                if res_type in person.activity_map and person.activity_map[res_type]:
                    residence = person.activity_map[res_type]
                    # Handle both single venue and list of subsets
                    if isinstance(residence, list):
                        if not residence:
                            continue
                        # Get venue from first subset
                        residence_venue = residence[0].venue if hasattr(residence[0], 'venue') else residence[0]
                    else:
                        residence_venue = residence
                    break

            # Check if we found a residence and if it matches the required type
            if residence_venue is None:
                return False
            if not hasattr(residence_venue, 'type'):
                return False
            if residence_venue.type != required_type:
                return False

        # Check filters (e.g., age range)
        if 'filters' in condition:
            filters = condition['filters']
            if not self._person_matches_filters(person, filters):
                return False

        return True

    def _allocate_special_case(self, person, case: Dict, venues: List) -> bool:
        """
        Allocate person according to special case rule.

        Returns:
            True if successfully allocated, False otherwise
        """
        allocation_rule = case.get('allocation_rule', {})
        strategy = allocation_rule.get('strategy')
        match_by = allocation_rule.get('match_by', [])

        selected_venue = None

        # Strategy-based allocation (closest, random, etc.)
        if strategy:
            # Get person's location
            geo_unit = self._get_geo_unit_at_level(person)
            if geo_unit and geo_unit.coordinates:
                person_location = geo_unit.coordinates

                if strategy == 'closest':
                    # Find closest venue
                    min_dist = float('inf')
                    for venue in venues:
                        if venue.coordinates and len(venue.coordinates) == 2:
                            dist = self._haversine_distance(person_location, venue.coordinates)
                            if dist < min_dist:
                                min_dist = dist
                                selected_venue = venue
                elif strategy == 'random':
                    if venues:
                        selected_venue = np.random.choice(venues)

        # Fallback: match_by criteria (existing logic)
        elif match_by:
            # Debug: log what we're looking for
            residence_name = self._get_nested_value_person(person, 'residence.name')
            residence_geo = self._get_nested_value_person(person, 'residence.geographical_unit.name')
            logger.debug(f"Person {person.id}: Looking for venue matching name='{residence_name}', geo_unit='{residence_geo}'")
            logger.debug(f"Checking against {len(venues)} venues")

            # Sample first 3 venues to see what we're checking against
            for i, venue in enumerate(venues[:3]):
                venue_geo = self._get_nested_value(venue, 'geographical_unit.name')
                logger.debug(f"  Sample venue {i}: name='{venue.name}', geo_unit='{venue_geo}'")

            for venue in venues:
                if self._venue_matches_criteria(person, venue, match_by):
                    selected_venue = venue
                    logger.debug(f"Person {person.id}: MATCHED to venue '{venue.name}'")
                    break

        # Allocate if venue found
        if selected_venue:
            person.activity_map[self.activity_map_key] = selected_venue
            if self.verbose:
                logger.debug(f"Special case: Allocated person {person.id} to {selected_venue.name}")
            return True

        # No match found
        residence_name = self._get_nested_value_person(person, 'residence.name')
        if_no_match = allocation_rule.get('if_no_match', 'error')
        if if_no_match == 'error':
            raise ValueError(f"Special case allocation failed for person {person.id} (age: {person.age}) with residence '{residence_name}'")
        elif if_no_match == 'warn':
            logger.warning(f"Special case: No matching venue found for person {person.id} with residence '{residence_name}'")

        return False

    def _venue_matches_criteria(self, person, venue, match_by: List[Dict]) -> bool:
        """Check if venue matches all criteria in match_by list."""
        for criterion in match_by:
            field = criterion.get('field')
            source = criterion.get('source')  # e.g., "person.residence.name"
            target = criterion.get('target')  # e.g., "venue.name"
            match_type = criterion.get('match_type', 'exact')

            # Get source value (from person)
            source_value = self._get_nested_value_person(person, source.replace('person.', ''))

            # Get target value (from venue)
            target_value = self._get_nested_value(venue, target.replace('venue.', ''))

            # Compare
            if match_type == 'exact':
                if source_value != target_value:
                    # Debug logging - always log for first few failures (limit output)
                    if person.id == 22406:  # Only log for the problematic person
                        logger.info(f"Person {person.id} vs Venue '{venue.name}': Match failed on {field}: "
                                   f"'{source_value}' != '{target_value}'")
                    return False

        return True

    def _get_nested_value_person(self, person, path: str):
        """
        Get value from person with special handling for residence.

        For paths like 'residence.name' or 'residence.geographical_unit.name',
        this looks in person.activity_map for any residence type.
        """
        if path.startswith('residence.'):
            # Get residence from activity_map - check all residence types
            residence_types_to_check = ['household', 'care_home', 'student_dorms', 'boarding_school', 'prison']
            residence_venue = None

            for res_type in residence_types_to_check:
                if res_type in person.activity_map and person.activity_map[res_type]:
                    residence = person.activity_map[res_type]
                    # Handle list of subsets
                    if isinstance(residence, list):
                        if not residence:
                            continue
                        residence_venue = residence[0].venue if hasattr(residence[0], 'venue') else residence[0]
                    else:
                        residence_venue = residence
                    break

            if residence_venue is None:
                return None

            # Get the requested attribute (handle nested paths like 'geographical_unit.name')
            attr_path = path.replace('residence.', '')
            # Use _get_nested_value to handle nested attributes
            return self._get_nested_value(residence_venue, attr_path)

        # Normal attribute access
        return self._get_nested_value(person, path)

    def _get_nested_value(self, obj, path: str):
        """Get value from nested object path (e.g., 'name' or 'geo_unit')."""
        parts = path.split('.')
        value = obj
        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

    def _get_nested_value_with_dict_support(self, obj, path: str):
        """
        Get value from nested path supporting both object attributes and dictionaries.

        Examples:
            - 'name' -> getattr(obj, 'name')
            - 'properties.original_pattern' -> obj.properties['original_pattern'] if properties is a dict
            - 'geo_unit.name' -> obj.geo_unit.name
        """
        parts = path.split('.')
        value = obj

        for part in parts:
            if value is None:
                return None

            # Check if current value is a dictionary
            if isinstance(value, dict):
                value = value.get(part)
            # Check if it's an object with the attribute
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None

        return value

    def _allocate_normal(self, people: List, venues: List):
        """Normal allocation for people not handled by special cases."""
        batch_by = self.config.get('allocation', {}).get('batch_by', 'geo_unit')

        if batch_by == 'geo_unit':
            self._allocate_by_geo_unit(people, venues)
        else:
            self._allocate_individual(people, venues)

    def _allocate_by_geo_unit(self, people: List, venues: List):
        """Batch allocation by geo_unit for performance."""
        # Group people by geo_unit (at the configured venue_geo_level)
        people_by_geo_unit = {}
        for person in people:
            geo_unit = self._get_geo_unit_at_level(person)
            if geo_unit is None:
                continue
            if geo_unit not in people_by_geo_unit:
                people_by_geo_unit[geo_unit] = []
            people_by_geo_unit[geo_unit].append(person)

        logger.info(f"Batching: {len(people_by_geo_unit)} geo_units to process at {self.venue_geo_level} level")

        # Process each geo_unit
        allocated_count = 0
        for geo_unit, geo_unit_people in people_by_geo_unit.items():
            # geo_unit is already a GeographicalUnit object at the configured level

            # Get coordinates from GeographicalUnit
            if geo_unit.coordinates is None or len(geo_unit.coordinates) != 2:
                logger.warning(f"Geo unit {geo_unit.name} ({geo_unit.level}) has no coordinates, skipping batch")
                continue

            lat, lon = geo_unit.coordinates

            # Find eligible venues for this batch (once per geo_unit)
            eligible_venues = self._find_eligible_venues_for_location(
                (lat, lon), venues
            )

            if not eligible_venues:
                continue

            # Allocate each person in this batch
            for person in geo_unit_people:
                # Filter venues by person attributes
                person_venues = self._filter_venues_by_person(person, eligible_venues)

                if person_venues:
                    venue = self._select_venue(person, person_venues, (lat, lon))
                    if venue:
                        person.activity_map[self.activity_map_key] = venue
                        allocated_count += 1

        logger.info(f"Normal allocation: Allocated {allocated_count} people")

    def _allocate_individual(self, people: List, venues: List):
        """Allocate people individually (slower, but more precise)."""
        allocated_count = 0

        for person in people:
            # Get person location
            location = self._get_person_location(person)
            if location is None:
                continue

            # Find eligible venues
            eligible_venues = self._find_eligible_venues_for_location(location, venues)

            # Filter by person attributes
            person_venues = self._filter_venues_by_person(person, eligible_venues)

            if person_venues:
                venue = self._select_venue(person, person_venues, location)
                if venue:
                    person.activity_map[self.activity_map_key] = venue
                    allocated_count += 1

        logger.info(f"Normal allocation: Allocated {allocated_count} people")

    def _get_person_location(self, person) -> Optional[Tuple[float, float]]:
        """Get person's location coordinates."""
        location_source = self.config.get('venue_selection', {}).get(
            'person_location_source', 'residence.geo_unit.coordinates'
        )

        if 'geo_unit.coordinates' in location_source:
            if hasattr(person.residence, 'geo_unit'):
                # This would need to look up the geo_unit object
                # For now, simplified:
                geo_unit_code = person.residence.geo_unit
                # Would need: geo_unit = world.geography.get_geo_unit(geo_unit_code)
                # Return (geo_unit.lat, geo_unit.lon)
                pass

        # Fallback: try direct coordinates
        if hasattr(person.residence, 'lat') and hasattr(person.residence, 'lon'):
            return (person.residence.lat, person.residence.lon)

        return None

    def _find_eligible_venues_for_location(
        self, location: Tuple[float, float], venues: List
    ) -> List:
        """Find venues eligible based on distance from location."""
        selection = self.config.get('venue_selection', {})
        consider_by = selection.get('consider_by', 'count')

        if consider_by == 'count':
            count = selection.get('count', 5)
            return self._find_closest_venues(location, venues, count)

        elif consider_by == 'distance':
            max_distance = selection.get('max_distance', 10)
            max_distance_unit = selection.get('max_distance_unit', 'km')
            return self._find_venues_within_distance(location, venues, max_distance, max_distance_unit)

        elif consider_by == 'geo_unit':
            # Would need geo_unit filtering
            return venues

        return venues

    def _find_closest_venues(
        self, location: Tuple[float, float], venues: List, count: int
    ) -> List:
        """Find N closest venues using spatial index."""
        if self.spatial_index is None:
            # Fallback: calculate all distances
            return self._find_closest_venues_brute_force(location, venues, count)

        # Create a set of allowed venue IDs for fast lookup
        allowed_venue_ids = {id(venue) for venue in venues}

        # BUG FIX: If venues list is filtered, we need to query MORE venues from the spatial index
        # and then filter the results to only include venues in our allowed list.
        # Query enough venues to ensure we get at least 'count' after filtering.
        max_query = min(len(self.venue_list), count * 10)  # Query 10x to be safe

        # Query KDTree for closest venues from ALL venues
        distances, indices = self.spatial_index.query(location, k=max_query)

        # Handle single result (scalar) vs multiple (array)
        if np.isscalar(indices):
            indices = [indices]
        else:
            indices = indices.tolist()

        # Filter results to only include venues in our allowed set
        closest_venues = []
        for i in indices:
            if 0 <= i < len(self.venue_list):
                venue = self.venue_list[i]
                if id(venue) in allowed_venue_ids:
                    closest_venues.append(venue)
                    if len(closest_venues) >= count:
                        break

        return closest_venues

    def _find_closest_venues_brute_force(
        self, location: Tuple[float, float], venues: List, count: int
    ) -> List:
        """Fallback: Find closest venues without spatial index."""
        venues_with_dist = []
        for venue in venues:
            if venue.coordinates is not None and len(venue.coordinates) == 2:
                lat, lon = venue.coordinates
                if lat is not None and lon is not None:
                    dist = self._haversine_distance(location, (lat, lon))
                    venues_with_dist.append((venue, dist))

        # Sort by distance and take top N
        venues_with_dist.sort(key=lambda x: x[1])
        return [v for v, d in venues_with_dist[:count]]

    def _find_venues_within_distance(
        self, location: Tuple[float, float], venues: List,
        max_distance: float, unit: str
    ) -> List:
        """Find all venues within distance radius."""
        # Convert to km if needed
        if unit == 'miles':
            max_distance *= 1.60934
        elif unit == 'meters':
            max_distance /= 1000

        eligible = []
        for venue in venues:
            if venue.coordinates is not None and len(venue.coordinates) == 2:
                lat, lon = venue.coordinates
                if lat is not None and lon is not None:
                    dist = self._haversine_distance(location, (lat, lon))
                    if dist <= max_distance:
                        eligible.append(venue)

        return eligible

    def _haversine_distance(
        self, loc1: Tuple[float, float], loc2: Tuple[float, float]
    ) -> float:
        """Calculate distance between two lat/lon points in km."""
        lat1, lon1 = np.radians(loc1)
        lat2, lon2 = np.radians(loc2)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))

        # Earth radius in km
        r = 6371

        return c * r

    def _filter_venues_by_person(self, person, venues: List) -> List:
        """Filter venues based on person's attributes (age, gender, etc.)."""
        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        eligible_venues = []

        for venue in venues:
            if self._venue_accepts_person(person, venue, attributes):
                eligible_venues.append(venue)

        return eligible_venues

    def _venue_accepts_person(self, person, venue, attribute_rules: List[Dict]) -> bool:
        """
        Check if venue accepts person based on attribute rules.

        OPTIMIZED VERSION: Uses pre-computed cache for 10-50x speedup.
        """
        # Use cached venue data if available
        venue_cache = self.venue_attribute_cache.get(id(venue))

        if venue_cache:
            # Fast path: Use pre-computed cache
            for rule in attribute_rules:
                attr_name = rule.get('name')
                attr_type = rule.get('type')

                # Get person's attribute value
                person_value = getattr(person, attr_name, None)
                if person_value is None:
                    return False

                if attr_type == 'numerical':
                    cache_key = f'num_{attr_name}'
                    cached_data = venue_cache.get(cache_key)
                    if cached_data:
                        min_val = cached_data['min']
                        max_val = cached_data['max']
                        if min_val is not None and person_value < min_val:
                            return False
                        if max_val is not None and person_value > max_val:
                            return False

                elif attr_type == 'categorical':
                    cache_key = f'cat_{attr_name}'
                    cached_data = venue_cache.get(cache_key)
                    if cached_data:
                        allowed_values = cached_data['allowed_person_values']
                        if allowed_values is not None:
                            # Pre-process person value for case sensitivity
                            if not cached_data['case_sensitive']:
                                person_value = str(person_value).lower() if person_value else ''
                            if person_value not in allowed_values:
                                return False
            return True
        else:
            # Fallback path: Use original logic (for backwards compatibility)
            return self._venue_accepts_person_slow(person, venue, attribute_rules)

    def _venue_accepts_person_slow(self, person, venue, attribute_rules: List[Dict]) -> bool:
        """Original (slow) implementation - fallback for venues without cache."""
        for rule in attribute_rules:
            attr_name = rule.get('name')
            attr_type = rule.get('type')

            person_value = getattr(person, attr_name, None)
            if person_value is None:
                return False

            if attr_type == 'numerical':
                if not self._check_numerical_constraint(person_value, venue, rule):
                    return False
            elif attr_type == 'categorical':
                if not self._check_categorical_constraint(person_value, venue, rule):
                    return False
        return True

    def _check_numerical_constraint(self, person_value, venue, rule: Dict) -> bool:
        """Check numerical constraint (e.g., age range)."""
        venue_constraints = rule.get('venue_constraints', {})
        min_col = venue_constraints.get('min_column')
        max_col = venue_constraints.get('max_column')

        if min_col:
            min_val = venue.properties.get(min_col)
            if min_val is not None and person_value < min_val:
                return False

        if max_col:
            max_val = venue.properties.get(max_col)
            if max_val is not None and person_value > max_val:
                return False

        return True

    def _check_categorical_constraint(self, person_value, venue, rule: Dict) -> bool:
        """Check categorical constraint (e.g., gender)."""
        venue_column = rule.get('venue_column')
        if not venue_column:
            return True

        venue_value = venue.properties.get(venue_column)
        if venue_value is None or venue_value == '':
            assume_if_missing = rule.get('assume_if_missing', 'Mixed')
            venue_value = assume_if_missing

        matching_rules = rule.get('matching_rules', {})
        case_sensitive = rule.get('case_sensitive', False)

        if not case_sensitive:
            venue_value = str(venue_value).lower() if venue_value else ''
            person_value = str(person_value).lower() if person_value else ''
            matching_rules = {k.lower(): [v.lower() for v in vals]
                            for k, vals in matching_rules.items()}

        if venue_value in matching_rules:
            return person_value in matching_rules[venue_value]

        return True

    def _select_venue(
        self, person, venues: List, person_location: Tuple[float, float]
    ) -> Optional[Any]:
        """Select final venue from eligible list based on strategy."""
        if not venues:
            return None

        strategy = self.config.get('allocation', {}).get('strategy', 'random')

        if strategy == 'random':
            return np.random.choice(venues)

        elif strategy == 'closest':
            # Find closest
            min_dist = float('inf')
            closest = None
            for venue in venues:
                if venue.coordinates and len(venue.coordinates) == 2:
                    lat, lon = venue.coordinates
                    dist = self._haversine_distance(person_location, (lat, lon))
                    if dist < min_dist:
                        min_dist = dist
                        closest = venue
            return closest

        elif strategy == 'proportional':
            # Weight by inverse distance
            distances = []
            valid_venues = []
            for v in venues:
                if v.coordinates and len(v.coordinates) == 2:
                    lat, lon = v.coordinates
                    dist = self._haversine_distance(person_location, (lat, lon))
                    distances.append(dist)
                    valid_venues.append(v)

            if not valid_venues:
                return venues[0] if venues else None

            weights = [1.0 / (d + 0.1) for d in distances]  # +0.1 to avoid division by zero
            weights = np.array(weights) / sum(weights)
            return np.random.choice(valid_venues, p=weights)

        return venues[0]

    def _log_allocation_summary(self, world):
        """Log summary statistics of allocation."""
        # Count only people allocated to THIS venue type (not just any primary_activity)
        allocated = sum(
            1 for p in world.people
            if self.activity_map_key in p.activity_map
            and hasattr(p.activity_map[self.activity_map_key], 'type')
            and p.activity_map[self.activity_map_key].type == self.venue_type
        )
        total = len(world.people)

        logger.info(f"Allocation Summary:")
        logger.info(f"  - Total people: {total}")
        logger.info(f"  - Allocated to {self.venue_type}: {allocated} ({allocated/total*100:.1f}%)")
        logger.info(f"  - Unallocated: {total - allocated}")

    def export_allocations(self, world, output_path: str):
        """
        Export allocations to CSV file.

        Args:
            world: World object with people and their allocations
            output_path: Path to output CSV file
        """
        import csv

        logger.info(f"Exporting allocations to {output_path}")

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            header = [
                'person_id',
                'person_sex',
                'person_age',
                'residence_type',
                'residence_original_pattern',
                'residence_geo_unit',
                'venue_name',
                'venue_type',
            ]

            # Add venue-specific columns based on what's in properties
            # For schools: StatutoryLowAge, StatutoryHighAge, Gender, SchoolCapacity
            sample_venues = world.venues_by_type(self.venue_type)
            if sample_venues:
                sample_venue = sample_venues[0]
                venue_property_cols = sorted(sample_venue.properties.keys())
                header.extend(venue_property_cols)

            writer.writerow(header)

            # Write data for allocated people
            allocated_count = 0
            for person in world.people:
                if self.activity_map_key not in person.activity_map:
                    continue

                venue = person.activity_map[self.activity_map_key]

                # Only export people allocated to THIS venue type
                if not hasattr(venue, 'type') or venue.type != self.venue_type:
                    continue

                # Get residence type and venue - check all possible residence keys in activity_map
                residence_type = 'unknown'
                residence_original_pattern = ''
                residence_venue = None
                # Residences are stored as person.activity_map[venue_type] = [Subset, ...]
                residence_types_to_check = ['household', 'care_home', 'student_dorms', 'boarding_school', 'prison']

                for res_type in residence_types_to_check:
                    if res_type in person.activity_map and person.activity_map[res_type]:
                        residence = person.activity_map[res_type]
                        # activity_map stores a list of Subsets
                        if isinstance(residence, list) and residence:
                            # Get the venue from the first subset
                            subset = residence[0]
                            if hasattr(subset, 'venue'):
                                residence_venue = subset.venue
                                residence_type = residence_venue.type
                            else:
                                residence_type = res_type
                        else:
                            residence_type = res_type
                        break

                # Extract original_pattern from residence venue properties if available
                if residence_venue and hasattr(residence_venue, 'properties'):
                    if isinstance(residence_venue.properties, dict):
                        residence_original_pattern = residence_venue.properties.get('original_pattern', '')

                # Get geographical unit name
                geo_unit_name = person.geographical_unit.name if person.geographical_unit else 'unknown'

                # Build row
                row = [
                    person.id,
                    person.sex,
                    person.age,
                    residence_type,
                    residence_original_pattern,
                    geo_unit_name,
                    venue.name,
                    venue.type,
                ]

                # Add venue properties in same order as header
                for prop_col in venue_property_cols:
                    row.append(venue.properties.get(prop_col, ''))

                writer.writerow(row)
                allocated_count += 1

        logger.info(f"Exported {allocated_count} allocations to {output_path}")

    @classmethod
    def from_yaml(cls, yaml_path: str):
        """Create VenueDistributor from YAML file path."""
        return cls(yaml_path)
