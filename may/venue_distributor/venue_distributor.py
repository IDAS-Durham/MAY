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

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        """
        Initialize VenueDistributor.

        Args:
            config_file: Path to YAML config file
            config_dict: Dictionary config (alternative to file)
        """
        # Load config
        if config_file:
            self.config = self._load_config(config_file)
            self.config_path = Path(config_file) # Keep for relative path resolution
        elif config_dict:
            self.config = config_dict
            self.config_path = None # No config file path if dict is used
        else:
            raise ValueError("Must provide either config_file or config_dict")

        # Initialize core attributes
        self.venue_type = self.config.get('venue_type', 'unknown')
        self.activity_map_key = self.config.get('activity_map_key', 'unknown')
        self.verbose = self.config.get('settings', {}).get('verbose', False)

        # Attribute lookup cache
        self.person_loc_attr = self.config.get('venue_selection', {}).get('person_location_source', 'geographical_unit.coordinates')
        self.person_location_attribute = self._parse_location_attribute(self.person_loc_attr)

        # Pre-process filters
        self._pre_processed_filters = []
        self._pre_processed_exclude = {}

        # Spatial index
        self.spatial_index = None
        self.venue_list = []

        # Attribute index
        self.venue_attribute_cache = {}
        self.categorical_index = {}
        self.attribute_index_built = False

        # Vectorized population arrays
        self.population_arrays = {}

        # Statistics
        self.stats = {}
        # Probability allocation cache
        # Maps (file_path, probability_column) -> {geo_unit_name: probability}
        self.probability_cache = {}

        # Capacity tracking: Maps venue_id -> current_count
        self.venue_capacity_tracker = {}

        # Extract key config values
        self.subset_key = self.config.get('subset_key', None)
        self.activity_type = self.config.get('activity_type', None)  # Override for activity_map nesting

        # Geographical level configuration (default to SGU for backward compatibility)
        self.venue_geo_level = self.config.get('venue_selection', {}).get('venue_geo_level', 'SGU')

        # Batch geographical level (for grouping people during allocation)
        # Defaults to venue_geo_level if not specified
        self.batch_geo_level = self.config.get('venue_selection', {}).get('batch_geo_level', self.venue_geo_level)

        # Load probability files for priority allocation groups
        self._load_probability_files()

        # Set logging level
        if self.config.get('settings', {}).get('debug', False):
            logger.setLevel(logging.DEBUG)

        if self.batch_geo_level != self.venue_geo_level:
            logger.info(f"Initialized VenueDistributor for venue_type='{self.venue_type}' at venue_geo_level='{self.venue_geo_level}', batch_geo_level='{self.batch_geo_level}', using location='{self.person_location_attribute}'")
        else:
            logger.info(f"Initialized VenueDistributor for venue_type='{self.venue_type}' at geo_level='{self.venue_geo_level}' using location='{self.person_location_attribute}'")

    def _load_config(self, config_path: str) -> Dict:
        """Load and parse YAML configuration file."""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config

    def _parse_location_attribute(self, attr_string: str) -> Dict:
        """
        Parses the person_location_source string into a dictionary for easier lookup.
        Examples:
        - 'geographical_unit' -> {'type': 'direct', 'attribute': 'geographical_unit'}
        - 'geographical_unit.coordinates' -> {'type': 'nested', 'attribute': 'geographical_unit', 'sub_attribute': 'coordinates'}
        - 'properties.workplace_sgu' -> {'type': 'properties', 'attribute': 'workplace_sgu'}
        """
        if '.' in attr_string:
            parts = attr_string.split('.')
            if parts[0] == 'properties':
                return {'type': 'properties', 'attribute': parts[1]}
            else:
                return {'type': 'nested', 'attribute': parts[0], 'sub_attribute': parts[1]}
        else:
            return {'type': 'direct', 'attribute': attr_string}

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
            if not full_path.is_absolute() and self.config_path:
                # Make relative to project root
                # config_path is yaml/distributors/xxx.yaml
                # We need to go up to yaml/, then up to project root
                project_root = self.config_path.parent.parent.parent
                full_path = project_root / file_path
            elif not self.config_path:
                logger.warning(f"Cannot resolve relative path '{file_path}' for probability file without a config_file path. Assuming absolute path.")


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

    def _get_venue_capacity(self, venue) -> int:
        """
        Get the capacity of a venue based on the configured capacity_column or fixed_capacity. (Optimized)
        """
        # Use cached fixed_capacity if available
        if self._fixed_capacity is not None:
            return int(self._fixed_capacity)

        if not self._capacity_column:
            return 0

        # Get capacity from venue properties (Avoid dict.get(..., 0) if common)
        capacity = venue.properties.get(self._capacity_column, 0)

        # Handle missing/zero capacity based on config
        if capacity is None or (isinstance(capacity, (int, float)) and pd.isna(capacity)):
            if_missing = self._capacity_handling.get('if_missing', 'skip')
            return 0 if if_missing == 'skip' else 0 # Defaulting to 0 for now
        
        if capacity == 0:
            if_zero = self._capacity_handling.get('if_zero', 'skip')
            if if_zero == 'skip':
                return 0

        return int(capacity)

    def _get_venue_current_count(self, venue) -> int:
        """
        Get the current number of people allocated to this venue.

        Args:
            venue: Venue object

        Returns:
            Current count
        """
        venue_id = id(venue)
        return self.venue_capacity_tracker.get(venue_id, 0)

    def _venue_has_capacity(self, venue) -> bool:
        """
        Check if a venue has available capacity.

        Args:
            venue: Venue object

        Returns:
            True if venue has space, False otherwise
        """
        capacity = self._get_venue_capacity(venue)
        if capacity == 0:
            # No capacity configured = skip this venue
            return False

        current_count = self._get_venue_current_count(venue)
        return current_count < capacity

    def _increment_venue_count(self, venue):
        """
        Increment the allocation count for a venue.

        Args:
            venue: Venue object
        """
        venue_id = id(venue)
        self.venue_capacity_tracker[venue_id] = self.venue_capacity_tracker.get(venue_id, 0) + 1

    def _filter_venues_by_capacity(self, venues: List) -> List:
        """
        Filter venues to only include those with available capacity.

        Args:
            venues: List of venue objects

        Returns:
            List of venues with available capacity
        """
        allocation_config = self.config.get('allocation', {})

        # Check if capacity tracking is enabled
        track_capacity = allocation_config.get('track_capacity', False)
        if not track_capacity:
            # No capacity tracking - return all venues
            return venues

        # Filter to venues with capacity
        venues_with_capacity = [v for v in venues if self._venue_has_capacity(v)]
        return venues_with_capacity

    def _get_geo_unit_at_level(self, person, world=None, target_level=None):
        """
        Get the person's geographical unit at a specified level.

        This enables flexibility: if venues are at MGU or LGU level but people are at SGU,
        we automatically traverse up the hierarchy to find the matching ancestor.

        Supports custom location attributes (e.g., workplace_location) via person_location_attribute config.

        Args:
            person: Person object with geographical_unit or custom location attribute
            world: World object (required if using custom location attribute)
            target_level: Target geographical level (defaults to self.venue_geo_level)

        Returns:
            GeographicalUnit at the target level, or None if not found
        """
        if target_level is None:
            target_level = self.venue_geo_level

        loc_attr_config = self.person_location_attribute
        person_geo_unit = None

        if loc_attr_config['type'] == 'direct':
            # Default: use residence location
            if not hasattr(person, loc_attr_config['attribute']) or getattr(person, loc_attr_config['attribute']) is None:
                return None
            person_geo_unit = getattr(person, loc_attr_config['attribute'])
        elif loc_attr_config['type'] == 'properties':
            # Custom attribute from person.properties dict
            location_value = person.properties.get(loc_attr_config['attribute']) if hasattr(person, 'properties') else None
            if location_value is None:
                return None
            if world is None or not hasattr(world, 'geography'):
                logger.warning(f"Cannot resolve {self.person_loc_attr}='{location_value}' without world.geography")
                return None
            person_geo_unit = world.geography.get_unit(location_value)
        elif loc_attr_config['type'] == 'nested':
            # Nested attribute (e.g., geographical_unit.coordinates)
            base_attr = getattr(person, loc_attr_config['attribute'], None)
            if base_attr and hasattr(base_attr, loc_attr_config['sub_attribute']):
                # If it's a GeographicalUnit object, use it directly
                if hasattr(base_attr, 'level') and hasattr(base_attr, 'name'):
                    person_geo_unit = base_attr
                else:
                    # It's a string/code, need to look it up via world.geography
                    location_value = getattr(base_attr, loc_attr_config['sub_attribute'], None)
                    if location_value is None:
                        return None
                    if world is None or not hasattr(world, 'geography'):
                        logger.warning(f"Cannot resolve {self.person_loc_attr}='{location_value}' without world.geography")
                        return None
                    person_geo_unit = world.geography.get_unit(location_value)

        if person_geo_unit is None:
            if self.verbose:
                logger.debug(f"Could not find geo_unit for person from {self.person_loc_attr}")
            return None

        # If person is already at the target level, return it
        if person_geo_unit.level == target_level:
            return person_geo_unit

        # Otherwise, traverse up to find ancestor at target level
        ancestor = person_geo_unit.get_ancestor_by_level(target_level)

        if ancestor is None and self.verbose:
            logger.debug(f"Person at {person_geo_unit.level} '{person_geo_unit.name}' has no ancestor at {target_level}")

        return ancestor

    def allocate(self, world):
        """
        Main entry point: Allocate people to venues.

        Args:
            world: World object containing people, venues, geography
        """
        # Store world reference for use in helper methods (needed for custom location attributes)
        self.world = world

        # Track allocations made during this run (for accurate summary statistics)
        self.allocated_this_run = 0

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

        # Pre-process eligibility filters for hot path performance
        self._pre_processed_filters = self._pre_process_filters(
            self.config.get('eligibility', {}).get('global_filters', [])
        )
        self._pre_processed_exclude = self.config.get('eligibility', {}).get('exclude', {})

        # Cache allocation configuration for hot path performance (used in _get_venue_capacity)
        self._allocation_config = self.config.get('allocation', {})
        self._fixed_capacity = self._allocation_config.get('fixed_capacity')
        self._capacity_column = self._allocation_config.get('capacity_column')
        self._capacity_handling = self._allocation_config.get('capacity_handling', {})

        # Phase 1: Handle special cases FIRST (bypasses global filters)
        # Special cases get ALL unassigned people (e.g., student_dorms residents can be any age)
        all_unassigned = self._get_unassigned_people(world)
        logger.info(f"Found {len(all_unassigned)} unassigned people")

        if not all_unassigned:
            logger.info("No unassigned people to allocate")
            return
            
        # Build vectorized arrays for the full population of unassigned people
        self._build_population_arrays(all_unassigned)

        remaining_people = self._handle_special_cases(all_unassigned, venues, world)
        logger.info(f"{len(remaining_people)} people remaining after special cases")

        # Now apply global filters for priority/normal allocation - VECTORIZED
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

    def _build_population_arrays(self, people: List):
        """Extract key attributes into NumPy arrays for vectorized filtering."""
        n = len(people)
        if n == 0:
            return

        # Initialize arrays
        self.population_arrays = {
            'indices': np.arange(n, dtype=np.int32),
            'people': np.array(people, dtype=object),
            'age': np.zeros(n, dtype=np.int16),
            'sex': np.zeros(n, dtype=np.int8),  # 0=F, 1=M
            'residence_type': np.zeros(n, dtype=np.int8)  # 0=Household, 1=Other
        }

        # Bulk extraction
        for i, person in enumerate(people):
            self.population_arrays['age'][i] = person.age
            self.population_arrays['sex'][i] = 1 if person.sex == 'male' else 0
            
            res_type = 0 # Default to household
            if hasattr(person, 'residence_type'):
                rt = person.residence_type
                if rt == 'care_home': res_type = 1
                elif rt == 'student_dorms': res_type = 2
                elif rt == 'prison': res_type = 3
                elif rt == 'boarding_school': res_type = 4
                elif rt == 'university': res_type = 5
            self.population_arrays['residence_type'][i] = res_type

    def _apply_filters_vectorized(self, indices: np.ndarray, filters: List[Dict]) -> np.ndarray:
        """Apply filters using vectorized boolean masks."""
        if len(indices) == 0:
            return indices

        mask = np.ones(len(indices), dtype=bool)
        
        # Access arrays directly using the indices
        # Optimization: Don't slice the big arrays, just index them
        current_ages = self.population_arrays['age'][indices]
        current_sexs = self.population_arrays['sex'][indices]
        current_res_types = self.population_arrays['residence_type'][indices]

        for rule in filters:
            attr = rule.get('attribute')
            
            if attr == 'age':
                min_val = rule.get('min')
                max_val = rule.get('max')
                if min_val is not None:
                    mask &= (current_ages >= min_val)
                if max_val is not None:
                    mask &= (current_ages <= max_val)
                    
            elif attr == 'sex':
                val = rule.get('value')
                target = 1 if val == 'male' else 0
                mask &= (current_sexs == target)
                
            elif attr == 'residence.type':
                vals = rule.get('values', [])
                # Map string values to our int codes
                allowed_codes = []
                for v in vals:
                    if v == 'household': allowed_codes.append(0)
                    elif v == 'care_home': allowed_codes.append(1)
                    elif v == 'student_dorms': allowed_codes.append(2)
                    elif v == 'prison': allowed_codes.append(3)
                    elif v == 'boarding_school': allowed_codes.append(4)
                    elif v == 'university': allowed_codes.append(5)
                
                if allowed_codes:
                    # vectorized "isin"
                    res_mask = np.zeros(len(indices), dtype=bool)
                    for code in allowed_codes:
                        res_mask |= (current_res_types == code)
                    mask &= res_mask

        return indices[mask]


    def _get_unassigned_people(self, world) -> List:
        """
        Get people for allocation based on require_unassigned setting.

        If require_unassigned=True (default): Only consider people without this activity assigned
        If require_unassigned=False: Consider all people, even if already assigned

        Does NOT apply global filters - special cases need access to all unassigned people.
        """
        # Read require_unassigned from eligibility config (default True for backward compatibility)
        require_unassigned = self.config.get('eligibility', {}).get('require_unassigned', True)

        unassigned = []
        already_assigned = 0
        missing_attrs = 0

        for person in world.people:
            # Check if already assigned (only if require_unassigned is True)
            if require_unassigned and self.activity_map_key in person.activity_map:
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
            if require_unassigned:
                logger.info(f"Unassigned people: {already_assigned} already assigned, {missing_attrs} missing attributes, {len(unassigned)} unassigned")
            else:
                logger.info(f"Eligible people (require_unassigned=False): {missing_attrs} missing attributes, {len(unassigned)} eligible")

        return unassigned

    def _apply_global_filters(self, people: List) -> List:
        """
        Apply global filters and exclusions to a list of people.
        Updated to use vectorized filtering where possible.
        """
        # If we have population arrays, use vectorized path
        if self.population_arrays and len(people) > 1000:
            # Re-map people objects to their indices in the arrays
            # This works because 'people' is a subset of 'all_unassigned' which we built arrays from
            # However, mapping back is slow O(N). 
            # Better strategy: keep indices flowing through the system.
            # For now, let's just create a quick lookup map if it's not too expensive,
            # OR just re-extract indices if `people` is exactly `all_unassigned` (common case).
            
            # FAST PATH: If people is exactly the array we built
            if len(people) == len(self.population_arrays['people']) and people[0] is self.population_arrays['people'][0]:
                 indices = self.population_arrays['indices']
                 filtered_indices = self._apply_filters_vectorized(indices, self._pre_processed_filters)
                 return self.population_arrays['people'][filtered_indices].tolist()
        
        # Fallback to original loop for complex cases or small lists
        eligible = []
        filtered_by_global = 0
        filtered_by_exclusions = 0

        # Get global filters (apply to priority and normal allocation only)
        global_filters = self.config.get('eligibility', {}).get('global_filters', [])

        # Get exclusion rules
        exclude_config = self.config.get('eligibility', {}).get('exclude', {})

        for person in people:
            # Check global filters (e.g., age, residence type)
            if self._pre_processed_filters and not self._person_matches_filters(person, self._pre_processed_filters):
                filtered_by_global += 1
                continue
            
            # Check exclusions
            if self._pre_processed_exclude and self._person_excluded(person, self._pre_processed_exclude):
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

        Also builds categorical index to pre-group venues by categorical attributes,
        enabling instant filtering (e.g., 1.27M companies → 67K per sector).
        """
        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        if not attributes:
            logger.debug("No attributes to index")
            return

        # Track which attributes should be indexed categorically
        categorical_attrs_to_index = []

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

                        # Build categorical index ONLY for identity mappings
                        # Identity mapping: venue_value maps to itself (e.g., "A": ["A"])
                        # NOT for rule-based mappings (e.g., "Mixed": ["male", "female"])
                        # This optimization only works when person_value == venue_value
                        allowed_values = matching_rules.get(venue_value, None)
                        is_identity_mapping = (
                            allowed_values is not None and
                            len(allowed_values) == 1 and
                            allowed_values[0] == venue_value
                        )

                        if is_identity_mapping:
                            # Track this attribute for indexing
                            if attr_name not in [a[0] for a in categorical_attrs_to_index]:
                                categorical_attrs_to_index.append((attr_name, venue_column, case_sensitive))

                            # Add this venue to the categorical index
                            # Store venue ID (not object) for fast set operations
                            index_key = (attr_name, venue_value)
                            if index_key not in self.categorical_index:
                                self.categorical_index[index_key] = set()
                            self.categorical_index[index_key].add(id(venue))

            # Store cache using venue id (fast lookup)
            self.venue_attribute_cache[id(venue)] = venue_cache

        self.attribute_index_built = True

        # Log index statistics
        if self.categorical_index:
            total_indexed_venues = sum(len(v) for v in self.categorical_index.values())
            logger.info(f"Built attribute index for {len(venues)} venues with {len(attributes)} attributes")
            logger.info(f"Built categorical index: {len(self.categorical_index)} unique value combinations, {total_indexed_venues} total indexed entries")
        else:
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

            # Pass group-specific search_limits if defined, otherwise use global
            group_search_limits = group.get('search_limits', None)
            allocated_count = self._allocate_group(group_people, venues, allow_overflow=allow_overflow, group_search_limits=group_search_limits)

            if allow_overflow:
                # Restore original setting
                self.config['allocation']['when_full'] = original_when_full

            logger.info(f"  → Allocated {allocated_count}/{len(group_people)} from group '{group_name}'")

            # Track allocations for summary
            self.allocated_this_run += allocated_count

            # Track all priority people
            all_priority_people.extend(group_people)

        # Remove priority people from remaining pool
        priority_ids = {p.id for p in all_priority_people}
        remaining_people = [p for p in remaining_people if p.id not in priority_ids]

        logger.info(f"Priority allocation complete: {len(all_priority_people)} people processed, {len(remaining_people)} remaining for normal allocation")
        logger.info("=" * 60)

        return remaining_people

    def _pre_process_filters(self, filters: List[Dict]) -> List[Dict]:
        """Pre-process filters to avoid repeated path parsing."""
        processed = []
        for f in filters:
            p_filter = f.copy()
            attr_name = f.get('attribute')
            if attr_name and '.' in attr_name:
                p_filter['is_nested'] = True
                p_filter['path_parts'] = attr_name.split('.')
                p_filter['is_residence'] = attr_name.startswith('residence.')
                if p_filter['is_residence']:
                    p_filter['residence_path'] = attr_name.replace('residence.', '')
            else:
                p_filter['is_nested'] = False
            processed.append(p_filter)
        return processed

    def _person_matches_filters(self, person, filters: List[Dict]) -> bool:
        """Check if person matches all filters in a group (Optimized)."""
        # Distinguish between pre-processed and raw filters for safety
        # We assume filters passed from _handle_priority_allocation are pre-processed.
        # For other calls, we use the fallback.
        is_pre_processed = 'is_nested' in filters[0] if filters else False

        if is_pre_processed:
            # Optimized path using pre-processed info
            for filter_rule in filters:
                person_value = None
                if filter_rule.get('is_nested'):
                    if filter_rule.get('is_residence'):
                        if filter_rule['attribute'] == 'residence.type':
                            person_value = person.residence_type or 'household'
                        else:
                            residence = person.residence
                            if residence is None: return False
                            person_value = self._get_nested_value_with_dict_support(residence, filter_rule['residence_path'])
                    else:
                        person_value = self._get_nested_value_with_dict_support(person, filter_rule['attribute'])
                    
                    if person_value is None: return False
                else:
                    # Non-nested: use getattr directly
                    person_value = getattr(person, filter_rule['attribute'], None)
                    if person_value is None: return False

                # Validate value
                filter_type = filter_rule.get('type', 'numerical')
                if filter_type == 'numerical':
                    min_val = filter_rule.get('min')
                    max_val = filter_rule.get('max')
                    if min_val is not None and person_value < min_val: return False
                    if max_val is not None and person_value > max_val: return False
                elif filter_type == 'categorical':
                    val = filter_rule.get('value')
                    vals = filter_rule.get('values')
                    if val is not None and person_value != val: return False
                    if vals is not None and person_value not in vals: return False
            return True
        else:
            # Fallback for ad-hoc filter lists (less frequent)
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
                        # Use the new residence property for clean access
                        person_value = person.residence_type

                        # If still no residence found, treat as 'household' (default)
                        if person_value is None:
                            person_value = 'household'
                    else:
                        # Generic nested attribute handling with support for dictionaries
                        # Handle residence.* paths specially
                        if attr_name.startswith('residence.'):
                            # Get residence using person.residence property
                            # This works for all residence types (now using 'residence' activity)
                            residence = person.residence

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

                if filter_type == 'numerical':
                    if min_val is not None and person_value < min_val:
                        return False
                    if max_val is not None and person_value > max_val:
                        return False
                elif filter_type == 'categorical':
                    if values and person_value not in values:
                        return False
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
            # Get person's residence using person.residence property
            # This works for all residence types (now using 'residence' activity)
            residence_venue = person.residence

            # No residence = not excluded by household rules
            if residence_venue is None:
                return False

            # Only apply household exclusions to people living in household-type residences
            if residence_venue.type != 'household':
                return False

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

    def _allocate_group(self, people: List, venues: List, allow_overflow: bool = False, group_search_limits=None) -> int:
        """
        Allocate a specific group of people (e.g., priority school-age children).

        Geo-unit level caching
        - Compute closest venues ONCE per geo_unit (not per person)
        - Group people by attribute combinations within each geo_unit
        - Filter venues ONCE per unique attribute combo (not per person)

        This reduces spatial queries by 99% and attribute filtering by 95%.

        Args:
            people: List of people to allocate
            venues: List of venues to allocate to
            allow_overflow: Whether to allow exceeding venue capacity
            group_search_limits: Optional group-specific search limits (overrides global config)

        Returns:
            Number of people successfully allocated
        """
        allocated_count = 0

        # Progress tracking
        total_people = len(people)
        people_processed = 0
        progress_interval = max(1, total_people // 10)  # Update every 10%

        # Extract attribute names from config (generic, works with any attributes)
        eligibility = self.config.get('eligibility', {})
        attribute_rules = eligibility.get('attributes', [])
        attribute_names = [rule.get('name') for rule in attribute_rules]

        selection_config = self.config.get('venue_selection', {})
        target_count = selection_config.get('count', 5)

        # CONFIGURABLE SEARCH LIMITS: Control how aggressively we expand the search
        # For young children (nursery), searching 50+ schools is unrealistic
        # Parents typically consider only 5-10 nearby schools
        # Priority: Use group-specific limits if provided, otherwise use global config
        if group_search_limits is not None:
            search_limits = group_search_limits
        else:
            search_limits = selection_config.get('search_limits', [50, 200, None])

        # search_limits examples:
        #   [50, 200, None] = try 50, then 200, then all venues (default, backwards compatible)
        #   [10, 20] = try 10, then 20, then stop (realistic for nurseries)
        #   [8, 10] = try 8, then 10, then stop (very restrictive for early childhood)
        #   [5] = only try 5 closest, no expansion (ultra restrictive)
        #   None or [] = use default [50, 200, None]

        if not search_limits:
            search_limits = [50, 200, None]  # Default fallback

        # Group by geo_unit for batching (at the configured batch_geo_level)
        people_by_geo_unit = {}
        for person in people:
            # Use batch_geo_level for grouping people (may differ from venue_geo_level)
            geo_unit = self._get_geo_unit_at_level(person, self.world, target_level=self.batch_geo_level)
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

            # Find closest venues ONCE per geo_unit (not per person!)
            total_venues = len(venues)

            # Build search attempts from config, replacing None with total_venues
            search_attempts = []
            for limit in search_limits:
                if limit is None:
                    search_attempts.append(total_venues)
                else:
                    search_attempts.append(min(limit, total_venues))
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

            # OPTIMIZATION 2: Skip geo-unit if no venues have capacity (for non-overflow groups)
            # This avoids expensive filtering for 85% of people in early childhood group
            if not allow_overflow:
                venues_with_capacity = self._filter_venues_by_capacity(geo_unit_nearby_venues)
                if not venues_with_capacity:
                    if self.verbose:
                        logger.debug(f"Geo unit {geo_unit.name} ({geo_unit.level}): All {len(geo_unit_nearby_venues)} nearby venues at capacity, skipping {len(geo_unit_people)} people")
                    # Still need to count these people for progress tracking
                    for _ in range(len(geo_unit_people)):
                        people_processed += 1
                        if people_processed % progress_interval == 0 or people_processed == total_people:
                            percent_complete = (people_processed / total_people) * 100
                            logger.info(f"    Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")
                    continue

            # Group people by their attribute values 
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

            # For each unique attribute combo, filter venues ONCE
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

                # OPTIMIZATION 3: Skip attribute-group if no venues have capacity (for non-overflow groups)
                # This saves per-person checks when we know the whole group can't be allocated
                if not allow_overflow and eligible_venues:
                    eligible_with_capacity = self._filter_venues_by_capacity(eligible_venues)
                    if not eligible_with_capacity:
                        if self.verbose:
                            attr_display = ", ".join(f"{name}={val}" for name, val in zip(attribute_names, attr_values))
                            logger.debug(f"Geo unit {geo_unit.name}: Attribute group [{attr_display}] has {len(eligible_venues)} eligible venues but all at capacity, skipping {len(people_group)} people")
                        # Update progress tracking for skipped people (same pattern as regular allocation)
                        for _ in range(len(people_group)):
                            people_processed += 1
                            if people_processed % progress_interval == 0 or people_processed == total_people:
                                percent_complete = (people_processed / total_people) * 100
                                logger.info(f"    Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")
                        continue  # Skip this entire attribute group

                # Assign all people in this group to eligible venues
                if eligible_venues:
                    # TWO-PASS ALLOCATION:
                    # Pass 1: Try to allocate to venues with available capacity
                    # Pass 2: If allow_overflow and no capacity available, allocate anyway

                    for person in people_group:
                        allocated = False

                        # PASS 1: Try venues with capacity first
                        venues_with_capacity = self._filter_venues_by_capacity(eligible_venues[:target_count])
                        if venues_with_capacity:
                            venue = self._select_venue(person, venues_with_capacity, (lat, lon))
                            if venue:
                                venue.add_to_subset(person, subset_key=self.subset_key, activity_name=self.activity_map_key, activity_type=self.activity_type)
                                self._increment_venue_count(venue)
                                allocated_count += 1
                                allocated = True

                        # PASS 2: If not allocated and overflow allowed, use any eligible venue
                        if not allocated and allow_overflow:
                            selection_pool = eligible_venues[:target_count]
                            venue = self._select_venue(person, selection_pool, (lat, lon))
                            if venue:
                                venue.add_to_subset(person, subset_key=self.subset_key, activity_name=self.activity_map_key, activity_type=self.activity_type)
                                self._increment_venue_count(venue)
                                allocated_count += 1
                                if self.verbose:
                                    capacity = self._get_venue_capacity(venue)
                                    current = self._get_venue_current_count(venue)
                                    logger.debug(f"OVERFLOW: Person {person.id} allocated to {venue.name} (capacity: {capacity}, current: {current})")

                        # Update progress tracking
                        people_processed += 1
                        if people_processed % progress_interval == 0 or people_processed == total_people:
                            percent_complete = (people_processed / total_people) * 100
                            logger.info(f"    Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")
                elif allow_overflow:
                    # For priority allocation, log if no venues accept this attribute combo
                    if self.verbose:
                        attr_display = ", ".join(f"{name}={val}" for name, val in zip(attribute_names, attr_values))
                        logger.debug(f"Geo unit {geo_unit.name} ({geo_unit.level}): {len(people_group)} people with [{attr_display}] have no eligible venues")

                    # Still need to track progress for unallocated people
                    for person in people_group:
                        people_processed += 1
                        if people_processed % progress_interval == 0 or people_processed == total_people:
                            percent_complete = (people_processed / total_people) * 100
                            logger.info(f"    Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")

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

                # DIAGNOSTIC INFO: Show details about unallocated people
                logger.warning(f"   Unallocated people breakdown:")

                # Group by age
                ages = {}
                for person in unallocated[:20]:  # Show first 20 to avoid spam
                    age = getattr(person, 'age', 'unknown')
                    ages[age] = ages.get(age, 0) + 1
                logger.warning(f"     Ages: {dict(sorted(ages.items()))}")

                # Group by sex
                sexes = {}
                for person in unallocated[:20]:
                    sex = getattr(person, 'sex', 'unknown')
                    sexes[sex] = sexes.get(sex, 0) + 1
                logger.warning(f"     Genders: {sexes}")

                # Group by geo_unit (show top 5)
                geo_units = {}
                for person in unallocated[:20]:
                    geo_unit = getattr(person, 'geographical_unit', None)
                    geo_name = geo_unit.name if geo_unit else 'unknown'
                    geo_units[geo_name] = geo_units.get(geo_name, 0) + 1
                top_geos = sorted(geo_units.items(), key=lambda x: x[1], reverse=True)[:5]
                logger.warning(f"     Top geo-units: {dict(top_geos)}")

                # Check for common issues
                no_coords = sum(1 for p in unallocated if getattr(p, 'geographical_unit', None) and
                               (not p.geographical_unit.coordinates or len(p.geographical_unit.coordinates) != 2))
                if no_coords > 0:
                    logger.warning(f"     ⚠ {no_coords} people have geo-units without valid coordinates!")

                # Sample a few people for detailed inspection
                if len(unallocated) <= 5:
                    logger.warning(f"   Sample unallocated people (all {len(unallocated)}):")
                    for person in unallocated:
                        geo_name = person.geographical_unit.name if hasattr(person, 'geographical_unit') and person.geographical_unit else 'none'
                        logger.warning(f"     - Person {person.id}: age={person.age}, sex={person.sex}, geo_unit={geo_name}")
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

        # OPTIMIZATION: Build venue index for fast lookup by (name, geo_unit)
        # This avoids O(N_people * N_venues) search, reducing 58 min -> seconds for special cases
        venue_index = {}
        for venue in venues:
            if hasattr(venue, 'name') and hasattr(venue, 'geographical_unit') and venue.geographical_unit:
                key = (venue.name, venue.geographical_unit.name)
                venue_index[key] = venue

        if venue_index and self.verbose:
            logger.debug(f"Built special case venue index with {len(venue_index)} entries")

        remaining_people = []
        allocated_count = 0

        for person in people:
            allocated = False

            for case in special_cases:
                if self._matches_special_case(person, case):
                    # Try to allocate according to special case rule
                    if self._allocate_special_case(person, case, venues, venue_index):
                        allocated = True
                        allocated_count += 1
                        break

            if not allocated:
                remaining_people.append(person)

        if allocated_count > 0:
            logger.info(f"Allocated {allocated_count} people via special cases")
            self.allocated_this_run += allocated_count

        return remaining_people

    def _matches_special_case(self, person, case: Dict) -> bool:
        """Check if person matches special case condition."""
        condition = case.get('condition', {})

        # Check residence type (use person.residence property)
        if 'person_residence_type' in condition:
            required_type = condition['person_residence_type']

            # Get residence using person.residence property
            # This works for all residence types (now using 'residence' activity)
            residence_venue = person.residence

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

    def _allocate_special_case(self, person, case: Dict, venues: List, venue_index: Dict = None) -> bool:
        """
        Allocate person according to special case rule.

        Args:
            person: Person to allocate
            case: Special case configuration
            venues: List of all venues (fallback if index not available)
            venue_index: Optional dict mapping (name, geo_unit) -> venue for O(1) lookup

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
            geo_unit = self._get_geo_unit_at_level(person, self.world)
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

        # OPTIMIZED: Use index for match_by criteria
        elif match_by and venue_index:
            # Extract lookup key from match_by criteria
            # For boarding schools: match by (name, geo_unit)
            lookup_key = self._extract_special_case_lookup_key(person, match_by)

            if lookup_key:
                selected_venue = venue_index.get(lookup_key)
                if selected_venue and self.verbose:
                    logger.debug(f"Person {person.id}: Fast lookup found venue '{selected_venue.name}'")

            # Fallback to full search if key extraction failed
            if not selected_venue:
                selected_venue = self._special_case_fallback_search(person, venues, match_by)

        # Fallback: match_by without index (original slow logic)
        elif match_by:
            selected_venue = self._special_case_fallback_search(person, venues, match_by)

        # Allocate if venue found
        if selected_venue:
            selected_venue.add_to_subset(person, subset_key=self.subset_key, activity_name=self.activity_map_key, activity_type=self.activity_type)
            self._increment_venue_count(selected_venue)
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

    def _extract_special_case_lookup_key(self, person, match_by: List[Dict]) -> Optional[Tuple]:
        """
        Extract lookup key from match_by criteria for fast index lookup.

        For boarding schools, this extracts (name, geo_unit) from person's residence.

        Returns:
            Tuple key for venue_index lookup, or None if extraction fails
        """
        try:
            key_parts = []
            for criterion in match_by:
                source = criterion.get('source', '')
                if source.startswith('person.'):
                    source_value = self._get_nested_value_person(person, source.replace('person.', ''))
                    if source_value is None:
                        return None
                    key_parts.append(source_value)

            return tuple(key_parts) if key_parts else None
        except Exception:
            return None

    def _special_case_fallback_search(self, person, venues: List, match_by: List[Dict]):
        """
        Fallback: Original O(N) search through all venues.
        Used when index lookup fails or is not available.
        """
        if self.verbose:
            residence_name = self._get_nested_value_person(person, 'residence.name')
            residence_geo = self._get_nested_value_person(person, 'residence.geographical_unit.name')
            logger.debug(f"Person {person.id}: Fallback search for name='{residence_name}', geo_unit='{residence_geo}'")

        for venue in venues:
            if self._venue_matches_criteria(person, venue, match_by):
                if self.verbose:
                    logger.debug(f"Person {person.id}: MATCHED to venue '{venue.name}'")
                return venue

        return None

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
            # Get residence using person.residence property
            # This works for all residence types (now using 'residence' activity)
            residence_venue = person.residence

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
        # Group people by geo_unit (at the configured batch_geo_level)
        people_by_geo_unit = {}
        for person in people:
            # Use batch_geo_level for grouping people (may differ from venue_geo_level)
            geo_unit = self._get_geo_unit_at_level(person, self.world, target_level=self.batch_geo_level)
            if geo_unit is None:
                continue
            if geo_unit not in people_by_geo_unit:
                people_by_geo_unit[geo_unit] = []
            people_by_geo_unit[geo_unit].append(person)

        logger.info(f"Batching: {len(people_by_geo_unit)} geo_units to process at {self.batch_geo_level} level")

        # PRE-GROUP VENUES BY GEO_UNIT FOR MASSIVE SPEEDUP
        # This replaces O(G * V) filtering with O(V) grouping
        venues_by_geo_name = {}
        for v in venues:
            geo_name = v.geographical_unit.name if v.geographical_unit else None
            if geo_name not in venues_by_geo_name:
                venues_by_geo_name[geo_name] = []
            venues_by_geo_name[geo_name].append(v)
        
        logger.info(f"Pre-grouped {len(venues)} venues into {len(venues_by_geo_name)} geo_units")

        # Progress tracking
        total_people = len(people)
        people_processed = 0
        progress_interval = max(1, total_people // 10)  # Update every 10%

        # Process each geo_unit
        allocated_count = 0
        for geo_unit, geo_unit_people in people_by_geo_unit.items():
            # geo_unit is already a GeographicalUnit object at batch_geo_level

            # If venues are at a different level than batch, get the appropriate parent unit
            if self.batch_geo_level != self.venue_geo_level:
                # Find venues in the parent geographical unit at venue_geo_level
                venue_search_unit = geo_unit.get_ancestor_by_level(self.venue_geo_level)
                if venue_search_unit is None:
                    if self.verbose:
                        logger.debug(f"Batch geo_unit {geo_unit.name} ({self.batch_geo_level}) has no parent at {self.venue_geo_level}")
                    continue
            else:
                venue_search_unit = geo_unit

            # Get coordinates from GeographicalUnit (for distance-based selection)
            if geo_unit.coordinates is None or len(geo_unit.coordinates) != 2:
                logger.warning(f"Geo unit {geo_unit.name} ({geo_unit.level}) has no coordinates, skipping batch")
                continue

            lat, lon = geo_unit.coordinates

            # Filter venues to those in the appropriate geographical unit
            # For companies: find all companies in the parent MGU
            if self.config.get('venue_selection', {}).get('consider_by') == 'geo_unit':
                # Filter venues by geographical unit (using pre-grouped cache)
                eligible_venues = venues_by_geo_name.get(venue_search_unit.name, [])
            else:
                # Use distance-based selection
                eligible_venues = self._find_eligible_venues_for_location(
                    (lat, lon), venues
                )

            # Pre-extract person attributes for this batch (MASSIVE speedup for attribute matching)
            # This avoids repeated getattr calls in the inner loop
            eligibility = self.config.get('eligibility', {})
            attributes_to_extract = [rule.get('name') for rule in eligibility.get('attributes', [])]
            # Also include attributes used in categorical index pre-filtering
            for rule in eligibility.get('attributes', []):
                if rule.get('type') == 'categorical' and rule.get('venue_column'):
                    attributes_to_extract.append(rule.get('name'))
            attributes_to_extract = list(set(attributes_to_extract))

            # Allocate each person in this batch
            for person in geo_unit_people:
                if eligible_venues:
                    # Pre-extract attributes for this specific person
                    person_attrs = {}
                    for attr_name in attributes_to_extract:
                        val = getattr(person, attr_name, None)
                        if val is None and hasattr(person, 'properties'):
                            val = person.properties.get(attr_name)
                        person_attrs[attr_name] = val

                    # Filter venues by person attributes
                    person_venues = self._filter_venues_by_person(person, eligible_venues, person_attrs=person_attrs)

                    if person_venues:
                        # Try to allocate to venues with capacity first
                        venues_with_capacity = self._filter_venues_by_capacity(person_venues)
                        if venues_with_capacity:
                            venue = self._select_venue(person, venues_with_capacity, (lat, lon))
                            if venue:
                                venue.add_to_subset(person, subset_key=self.subset_key, activity_name=self.activity_map_key, activity_type=self.activity_type)
                                self._increment_venue_count(venue)
                                allocated_count += 1

                # Update progress tracking (count all people, not just allocated)
                people_processed += 1
                if people_processed % progress_interval == 0 or people_processed == total_people:
                    percent_complete = (people_processed / total_people) * 100
                    logger.info(f"  Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")

        logger.info(f"Normal allocation: Allocated {allocated_count} people")
        self.allocated_this_run += allocated_count

    def _allocate_individual(self, people: List, venues: List):
        """Allocate people individually (slower, but more precise)."""
        allocated_count = 0

        # Progress tracking
        total_people = len(people)
        progress_interval = max(1, total_people // 10)  # Update every 10%

        for i, person in enumerate(people, 1):
            # Get person location
            location = self._get_person_location(person)
            if location is None:
                continue

            # Find eligible venues
            eligible_venues = self._find_eligible_venues_for_location(location, venues)

            # Filter by person attributes
            person_venues = self._filter_venues_by_person(person, eligible_venues)

            if person_venues:
                # Try to allocate to venues with capacity first
                venues_with_capacity = self._filter_venues_by_capacity(person_venues)
                if venues_with_capacity:
                    venue = self._select_venue(person, venues_with_capacity, location)
                    if venue:
                        venue.add_to_subset(person, subset_key=self.subset_key, activity_name=self.activity_map_key, activity_type=self.activity_type)
                        self._increment_venue_count(venue)
                        allocated_count += 1

            # Update progress tracking
            if i % progress_interval == 0 or i == total_people:
                percent_complete = (i / total_people) * 100
                logger.info(f"  Progress: {i}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")

        logger.info(f"Normal allocation: Allocated {allocated_count} people")
        self.allocated_this_run += allocated_count

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

    def _prefilter_venues_by_categorical(self, person, venues: List, person_attrs: Optional[Dict] = None) -> List:
        """
        Pre-filter venues using categorical index for massive speedup.

        For attributes with categorical matching (e.g., work_sector), this uses
        the pre-built index to instantly filter from 1.27M venues down to the
        relevant subset (e.g., ~67K companies in sector 'A').

        Returns:
            Filtered venue list, or original list if no categorical filtering applies
        """
        if not self.categorical_index:
            return venues  # No categorical index built, return all venues

        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        # Find categorical attributes to use for pre-filtering
        categorical_filters = []
        for rule in attributes:
            if rule.get('type') == 'categorical' and rule.get('venue_column'):
                attr_name = rule.get('name')
                case_sensitive = rule.get('case_sensitive', False)

                # Get person's value for this attribute
                if person_attrs and attr_name in person_attrs:
                    person_value = person_attrs[attr_name]
                else:
                    person_value = getattr(person, attr_name, None)
                    if person_value is None and hasattr(person, 'properties') and attr_name in person.properties:
                        person_value = person.properties[attr_name]

                if person_value is not None:
                    # Apply case sensitivity
                    if not case_sensitive:
                        person_value = str(person_value).lower() if person_value else ''

                    categorical_filters.append((attr_name, person_value))

        # If we have categorical filters, use the index
        if categorical_filters:
            # Find venues that match ALL categorical filters
            # Get first filter set
            attr_name, person_value = categorical_filters[0]
            index_key = (attr_name, person_value)
            filtered_venue_ids = self.categorical_index.get(index_key, set())

            # If multiple filters, intersect them (need to copy only if we modify)
            if len(categorical_filters) > 1:
                filtered_venue_ids = filtered_venue_ids.copy()
                for attr_name, person_value in categorical_filters[1:]:
                    index_key = (attr_name, person_value)
                    filter_set = self.categorical_index.get(index_key, set())
                    filtered_venue_ids &= filter_set

            # Only keep venues that are in the original venue list
            # (to respect geographical/distance filtering)
            result = [v for v in venues if id(v) in filtered_venue_ids]

            return result
        else:
            return venues  # No categorical filters, return all venues

    def _filter_venues_by_person(self, person, venues: List, person_attrs: Optional[Dict] = None) -> List:
        """Filter venues based on person's attributes (age, gender, etc.)."""
        # Step 1: Pre-filter using categorical index (instant filtering for large venue sets)
        venues = self._prefilter_venues_by_categorical(person, venues, person_attrs=person_attrs)

        # Step 2: Filter remaining venues by other attributes (age, gender, etc.)
        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        eligible_venues = []

        for venue in venues:
            if self._venue_accepts_person(person, venue, attributes, person_attrs=person_attrs):
                eligible_venues.append(venue)

        return eligible_venues

    def _venue_accepts_person(self, person, venue, attribute_rules: List[Dict], person_attrs: Optional[Dict] = None) -> bool:
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
                if person_attrs and attr_name in person_attrs:
                    person_value = person_attrs[attr_name]
                else:
                    person_value = getattr(person, attr_name, None)
                    if person_value is None and hasattr(person, 'properties') and attr_name in person.properties:
                        person_value = person.properties[attr_name]
                
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

            # Check direct attribute first, then properties dict
            person_value = getattr(person, attr_name, None)
            if person_value is None and hasattr(person, 'properties') and attr_name in person.properties:
                person_value = person.properties[attr_name]
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
        """Log summary statistics of allocation (Optimized)."""
        total_people = len(world.people)
        
        # Cache config values for the loop
        required_attrs = self.config.get('validation', {}).get('required_person_attributes', [])
        global_filters = self._pre_processed_filters
        exclude_config = self._pre_processed_exclude
        
        total_eligible = 0
        total_with_venue_type = 0
        
        # Perform a single pass over the population
        for person in world.people:
            # 1. Count people with this venue type
            if self.activity_map_key in person.activity_map:
                activity_venues = person.activity_map[self.activity_map_key]
                if isinstance(activity_venues, dict) and self.venue_type in activity_venues:
                    if activity_venues[self.venue_type]:
                        total_with_venue_type += 1
            
            # 2. Check eligibility (for the "eligible people" count)
            # This logic must match the allocation entry logic exactly
            if not self._has_required_attributes(person, required_attrs):
                continue
                
            if global_filters and not self._person_matches_filters(person, global_filters):
                continue
                
            if exclude_config and self._person_excluded(person, exclude_config):
                continue
                
            total_eligible += 1

        # Use allocations made during THIS run
        allocated = self.allocated_this_run

        logger.info(f"Allocation Summary:")
        logger.info(f"  - Total people: {total_people}")
        logger.info(f"  - Eligible people: {total_eligible} ({total_eligible/total_people*100:.1f}%)")
        logger.info(f"  - Allocated during this run: {allocated} ({allocated/total_eligible*100:.1f}% of eligible)" if total_eligible > 0 else f"  - Allocated during this run: {allocated}")
        logger.info(f"  - Total with {self.venue_type} assignments: {total_with_venue_type} (includes assignments from other systems)")
        logger.info(f"  - Unallocated eligible: {total_eligible - allocated}")

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

                # UNIFIED STRUCTURE: activity_map[activity_name][venue_type] = [subsets]
                activity_venues = person.activity_map[self.activity_map_key]
                if not activity_venues:
                    continue

                # Get the subsets for this specific venue type
                if self.venue_type not in activity_venues:
                    continue

                subsets = activity_venues[self.venue_type]
                if not subsets:
                    continue

                # Get the venue from the first subset
                venue = subsets[0].venue

                # Get residence type and venue using the new residence property
                residence_type = person.residence_type if person.residence_type else 'unknown'
                residence_original_pattern = person.get_residence_property('original_pattern', '')

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
        """
        Create appropriate distributor from YAML file path.

        This is a factory method that automatically selects the correct distributor type
        based on the 'distributor_type' field in the YAML:
        - "multi_venue" -> MultiVenueDistributor
        - "single_venue" or missing -> VenueDistributor

        Args:
            yaml_path: Path to distributor YAML file

        Returns:
            Instance of VenueDistributor or MultiVenueDistributor
        """
        # Import here to avoid circular dependency
        from . import distributor_from_yaml
        return distributor_from_yaml(yaml_path)
