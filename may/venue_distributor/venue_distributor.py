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

        # Extract key config values
        self.venue_type = self.config.get('venue_type')
        self.activity_map_key = self.config.get('activity_map_key')
        self.verbose = self.config.get('settings', {}).get('verbose', False)

        # Set logging level
        if self.config.get('settings', {}).get('debug', False):
            logger.setLevel(logging.DEBUG)

        logger.info(f"Initialized VenueDistributor for venue_type='{self.venue_type}'")

    def _load_config(self) -> Dict:
        """Load and parse YAML configuration file."""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config

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

        # Get eligible people (not already assigned this activity)
        eligible_people = self._get_eligible_people(world)
        logger.info(f"Found {len(eligible_people)} eligible people")

        if not eligible_people:
            logger.info("No eligible people to allocate")
            return

        # Phase 1: Handle special cases (e.g., boarding school students)
        remaining_people = self._handle_special_cases(eligible_people, venues, world)
        logger.info(f"{len(remaining_people)} people remaining after special cases")

        # Phase 2: Mandatory allocation (if configured)
        if remaining_people:
            remaining_people = self._handle_mandatory_allocation(remaining_people, venues)

        # Phase 3: Normal allocation (optional groups)
        if remaining_people:
            self._allocate_normal(remaining_people, venues)

        # Log summary
        if self.config.get('settings', {}).get('log_summary', True):
            self._log_allocation_summary(world)

            # Check for unallocated mandatory people
            self._check_mandatory_coverage(world)

    def _get_eligible_people(self, world) -> List:
        """Get people who don't already have this activity assigned."""
        eligible = []
        already_assigned = 0
        missing_attrs = 0
        filtered_by_global = 0
        filtered_by_exclusions = 0

        # Get global filters (apply to ALL allocation phases)
        global_filters = self.config.get('eligibility', {}).get('global_filters', [])

        # Get exclusion rules
        exclude_config = self.config.get('eligibility', {}).get('exclude', {})

        for person in world.people:
            # Check if already assigned
            if self.activity_map_key in person.activity_map:
                already_assigned += 1
                continue

            # Check required attributes
            required_attrs = self.config.get('validation', {}).get('required_person_attributes', [])
            if not self._has_required_attributes(person, required_attrs):
                missing_attrs += 1
                if self.verbose and len(eligible) == 0:  # Log first failure
                    logger.debug(f"Person {person.id} missing required attributes. Has: {dir(person)}")
                continue

            # Check global filters (e.g., residence type)
            if global_filters and not self._person_matches_filters(person, global_filters):
                filtered_by_global += 1
                continue

            # Check exclusion rules
            if exclude_config and self._person_excluded(person, exclude_config):
                filtered_by_exclusions += 1
                continue

            eligible.append(person)

        if self.verbose:
            logger.info(f"Eligibility check: {already_assigned} already assigned, {missing_attrs} missing attributes, {filtered_by_global} filtered by global rules, {filtered_by_exclusions} filtered by exclusions, {len(eligible)} eligible")

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

    def _handle_mandatory_allocation(self, people: List, venues: List) -> List:
        """
        Handle mandatory allocation groups (e.g., school-age children MUST be allocated).

        Returns:
            List of people NOT in mandatory groups (for normal allocation)
        """
        mandatory_config = self.config.get('eligibility', {}).get('mandatory_allocation', {})

        if not mandatory_config.get('enabled', False):
            return people  # No mandatory allocation configured

        groups = mandatory_config.get('groups', [])
        if not groups:
            return people

        logger.info("")
        logger.info("=" * 60)
        logger.info("MANDATORY ALLOCATION")
        logger.info("=" * 60)

        # Sort groups by priority (lowest number = highest priority)
        groups_sorted = sorted(groups, key=lambda g: g.get('priority', 999))

        remaining_people = list(people)
        all_mandatory_people = []

        # Process each mandatory group
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

            # Sort by age descending (older first) if priority_order is age_desc
            priority_order = mandatory_config.get('priority_order')
            if priority_order == 'age_desc':
                group_people.sort(key=lambda p: p.age, reverse=True)

            logger.info(f"Group '{group_name}': {len(group_people)} people (overflow={'allowed' if allow_overflow else 'not allowed'})")

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

            # Track all mandatory people
            all_mandatory_people.extend(group_people)

        # Remove mandatory people from remaining pool
        mandatory_ids = {p.id for p in all_mandatory_people}
        remaining_people = [p for p in remaining_people if p.id not in mandatory_ids]

        logger.info(f"Mandatory allocation complete: {len(all_mandatory_people)} people processed, {len(remaining_people)} remaining for optional allocation")
        logger.info("=" * 60)

        return remaining_people

    def _person_matches_filters(self, person, filters: List[Dict]) -> bool:
        """Check if person matches all filters in a mandatory group."""
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
                    # Generic nested attribute handling
                    parts = attr_name.split('.')
                    person_value = person
                    for part in parts:
                        person_value = getattr(person_value, part, None)
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
        Allocate a specific group of people (e.g., mandatory school-age children).

        Returns:
            Number of people successfully allocated
        """
        allocated_count = 0

        # Group by geo_unit for batching
        people_by_sgu = {}
        for person in people:
            sgu = person.geographical_unit
            if sgu not in people_by_sgu:
                people_by_sgu[sgu] = []
            people_by_sgu[sgu].append(person)

        # Process each geo_unit
        for sgu, sgu_people in people_by_sgu.items():
            # Get coordinates
            if sgu.coordinates is None or len(sgu.coordinates) != 2:
                continue

            lat, lon = sgu.coordinates

            # Allocate each person in this batch
            for person in sgu_people:
                # CRITICAL FIX: Filter by person attributes (age/sex) FIRST, then find closest
                # This ensures we find the 5 closest schools that ACCEPT this child's age/sex,
                # not just the 5 closest schools in general

                # Step 1: Filter ALL venues by person attributes (age/gender)
                person_eligible_venues = self._filter_venues_by_person(person, venues)

                # Step 2: Find closest venues from the filtered list
                if person_eligible_venues:
                    person_venues = self._find_eligible_venues_for_location((lat, lon), person_eligible_venues)
                else:
                    person_venues = []

                if person_venues:
                    venue = self._select_venue(person, person_venues, (lat, lon))
                    if venue:
                        person.activity_map[self.activity_map_key] = venue
                        allocated_count += 1
                elif allow_overflow:
                    # For mandatory allocation, if no venues accept this person,
                    # log a warning but don't force allocation to ineligible venues
                    if self.verbose:
                        logger.debug(f"Mandatory person (age {person.age}, sex {person.sex}) has no eligible venues - cannot allocate (age/sex matched venues: {len(person_eligible_venues)})")

        return allocated_count

    def _check_mandatory_coverage(self, world):
        """Check that all mandatory groups are fully allocated."""
        mandatory_config = self.config.get('eligibility', {}).get('mandatory_allocation', {})

        if not mandatory_config.get('enabled', False):
            return

        groups = mandatory_config.get('groups', [])

        for group in groups:
            if not group.get('allow_overflow', False):
                continue  # Only check mandatory groups

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
                logger.warning(f"⚠️  MANDATORY GROUP '{group_name}': {len(unallocated)} people NOT allocated!")
                logger.warning(f"   This should not happen for mandatory groups. Check venue capacity and constraints.")
            else:
                logger.info(f"✓ MANDATORY GROUP '{group_name}': All people allocated")

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

            # Check if person has a residence in activity_map
            if 'household' not in person.activity_map:
                return False

            # Get residence from activity_map (could be a list of Subsets)
            residence = person.activity_map['household']

            # Handle both single venue and list of subsets
            if isinstance(residence, list):
                if not residence:
                    return False
                # Get venue from first subset
                residence_venue = residence[0].venue if hasattr(residence[0], 'venue') else residence[0]
            else:
                residence_venue = residence

            # Check venue type
            if not hasattr(residence_venue, 'type'):
                return False
            if residence_venue.type != required_type:
                return False

        return True

    def _allocate_special_case(self, person, case: Dict, venues: List) -> bool:
        """
        Allocate person according to special case rule.

        Returns:
            True if successfully allocated, False otherwise
        """
        allocation_rule = case.get('allocation_rule', {})
        match_by = allocation_rule.get('match_by', [])

        # Find matching venue
        for venue in venues:
            if self._venue_matches_criteria(person, venue, match_by):
                # Allocate!
                person.activity_map[self.activity_map_key] = venue

                if self.verbose:
                    logger.debug(f"Special case: Allocated person to {venue.name}")

                return True

        # No match found
        residence_name = self._get_nested_value_person(person, 'residence.name')
        if_no_match = allocation_rule.get('if_no_match', 'error')
        if if_no_match == 'error':
            raise ValueError(f"Special case mandatory allocation failed for person {person.id} with residence '{residence_name}'")
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
                    return False

        return True

    def _get_nested_value_person(self, person, path: str):
        """
        Get value from person with special handling for residence.

        For paths like 'residence.name' or 'residence.geo_unit',
        this looks in person.activity_map['household'].
        """
        if path.startswith('residence.'):
            # Get residence from activity_map
            if 'household' not in person.activity_map:
                return None

            residence = person.activity_map['household']

            # Handle list of subsets
            if isinstance(residence, list):
                if not residence:
                    return None
                residence_venue = residence[0].venue if hasattr(residence[0], 'venue') else residence[0]
            else:
                residence_venue = residence

            # Get the requested attribute
            attr_name = path.replace('residence.', '')
            return getattr(residence_venue, attr_name, None)

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

    def _allocate_normal(self, people: List, venues: List):
        """Normal allocation for people not handled by special cases."""
        batch_by = self.config.get('allocation', {}).get('batch_by', 'geo_unit')

        if batch_by == 'geo_unit':
            self._allocate_by_geo_unit(people, venues)
        else:
            self._allocate_individual(people, venues)

    def _allocate_by_geo_unit(self, people: List, venues: List):
        """Batch allocation by geo_unit for performance."""
        # Group people by geo_unit
        people_by_sgu = {}
        for person in people:
            # Person.geographical_unit is already the GeographicalUnit object
            sgu = person.geographical_unit
            if sgu not in people_by_sgu:
                people_by_sgu[sgu] = []
            people_by_sgu[sgu].append(person)

        logger.info(f"Batching: {len(people_by_sgu)} geo_units to process")

        # Process each geo_unit
        allocated_count = 0
        for sgu, sgu_people in people_by_sgu.items():
            # sgu is already a GeographicalUnit object, no lookup needed

            # Get coordinates from GeographicalUnit
            if sgu.coordinates is None or len(sgu.coordinates) != 2:
                logger.warning(f"Geo unit {sgu.name} has no coordinates, skipping batch")
                continue

            lat, lon = sgu.coordinates

            # Find eligible venues for this batch (once per geo_unit)
            eligible_venues = self._find_eligible_venues_for_location(
                (lat, lon), venues
            )

            if not eligible_venues:
                continue

            # Allocate each person in this batch
            for person in sgu_people:
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
                sgu_code = person.residence.geo_unit
                # Would need: sgu = world.geography.get_geo_unit(sgu_code)
                # Return (sgu.lat, sgu.lon)
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
        """Check if venue accepts person based on attribute rules."""
        for rule in attribute_rules:
            attr_name = rule.get('name')
            attr_type = rule.get('type')

            # Get person's attribute value
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

        # Check min/max columns (stored in venue.properties)
        min_col = venue_constraints.get('min_column')
        max_col = venue_constraints.get('max_column')

        # Check minimum age constraint
        if min_col:
            min_val = venue.properties.get(min_col)
            if min_val is not None and person_value < min_val:
                return False

        # Check maximum age constraint
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

        # Look in venue.properties dict
        venue_value = venue.properties.get(venue_column)
        if venue_value is None or venue_value == '':
            # Use default assumption
            assume_if_missing = rule.get('assume_if_missing', 'Mixed')
            venue_value = assume_if_missing

        # Check matching rules
        matching_rules = rule.get('matching_rules', {})

        # Case sensitivity
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
        allocated = sum(1 for p in world.people if self.activity_map_key in p.activity_map)
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
                'residence_sgu',
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

                # Get residence type - check all possible residence keys in activity_map
                residence_type = 'unknown'
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
                                residence_type = subset.venue.type
                            else:
                                residence_type = res_type
                        else:
                            residence_type = res_type
                        break

                # Get SGU name
                sgu_name = person.geographical_unit.name if person.geographical_unit else 'unknown'

                # Build row
                row = [
                    person.id,
                    person.sex,
                    person.age,
                    residence_type,
                    sgu_name,
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
