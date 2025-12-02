"""
Generic venue allocator with YAML configuration.

Allocates people to venues (care homes, dorms, company housing, etc.)
based on flexible YAML-defined criteria.

Venue allocations are configured in allocation_strategy.yaml as part of
the unified household + venue allocation strategy.
"""

import logging
import numpy as np
from collections import deque
from typing import List, Dict

logger = logging.getLogger("venue_allocator")


def _allocate_to_venue_type(venue_type: str, allocation_config: Dict,
                            population, venues, household_distributor) -> Dict:
    """
    Allocate people to a specific venue type.

    Args:
        venue_type: Type of venue (e.g., "care_home", "student_dorms")
        allocation_config: Configuration dict for this venue type
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics about this allocation
    """
    description = allocation_config.get('description', '')
    if description:
        logger.info(f"  {description}")

    # Check allocation mode
    allocation_mode = allocation_config.get('allocation_mode', 'simple')
    use_attribute_capacities = allocation_config.get('use_attribute_capacities', False)

    # If attribute-aware mode, delegate to specialized function
    if allocation_mode == 'attribute_aware' or use_attribute_capacities:
        return _allocate_with_attributes(
            venue_type=venue_type,
            allocation_config=allocation_config,
            population=population,
            venues=venues,
            household_distributor=household_distributor
        )

    # Otherwise, use simple allocation (original behavior)
    # Get all venues of this type
    venue_list = venues.get_venues_by_type(venue_type)
    if not venue_list:
        logger.warning(f"  No venues found for type '{venue_type}'")
        return {
            'venues': 0,
            'allocated': 0,
            'capacity_used': 0,
            'total_capacity': 0,
            'capacity_pct': 0
        }

    logger.info(f"  Found {len(venue_list)} {venue_type} venues")

    # Calculate total capacity
    capacity_property = allocation_config.get('capacity_property', 'capacity')
    total_capacity = 0

    for venue in venue_list:
        cap = venue.properties.get(capacity_property, 0)
        if cap:
            total_capacity += int(cap)

    logger.info(f"  Total capacity: {total_capacity}")

    if total_capacity == 0:
        logger.warning(f"  No capacity found (check '{capacity_property}' property)")
        return {
            'venues': len(venue_list),
            'allocated': 0,
            'capacity_used': 0,
            'total_capacity': 0,
            'capacity_pct': 0
        }

    # Get eligible people
    eligibility = allocation_config.get('eligibility', {})
    eligible_people = _get_eligible_people(
        population=population,
        household_distributor=household_distributor,
        eligibility=eligibility
    )

    logger.info(f"  Found {len(eligible_people)} eligible people")

    if not eligible_people:
        return {
            'venues': len(venue_list),
            'allocated': 0,
            'capacity_used': 0,
            'total_capacity': total_capacity,
            'capacity_pct': 0
        }

    # Apply strategy (sort eligible people)
    strategy = allocation_config.get('strategy', 'random')
    eligible_people = _apply_strategy(eligible_people, strategy)

    # Determine how many to allocate
    max_allocations = allocation_config.get('max_allocations')
    people_to_allocate = min(len(eligible_people), total_capacity)
    if max_allocations is not None:
        people_to_allocate = min(people_to_allocate, max_allocations)

    logger.info(f"  Allocating {people_to_allocate} people...")

    # Pre-group eligible people by geographical unit to avoid O(n) filtering per venue
    people_by_geo_unit = {}
    for person in eligible_people:
        geo_unit = person.geographical_unit
        if geo_unit not in people_by_geo_unit:
            people_by_geo_unit[geo_unit] = deque()
        people_by_geo_unit[geo_unit].append(person)

    # Allocate people to venues
    allocated_people = []
    eligible_people_set = set(eligible_people)

    # Progress tracking setup
    total_venues = len(venue_list)
    venues_processed = 0
    progress_interval = max(1, total_venues // 10)  # Update every 10%

    for venue in venue_list:
        venues_processed += 1
        capacity = int(venue.properties.get(capacity_property, 0))
        if capacity == 0:
            continue

        # Get pre-grouped people for this venue's geographical unit (O(1) lookup)
        venue_geo_unit = venue.geographical_unit
        venue_eligible = people_by_geo_unit.get(venue_geo_unit, deque())

        # Allocate people to this venue
        venue_residents = []
        for _ in range(capacity):
            # Find next eligible person who hasn't been allocated yet
            person = None
            while venue_eligible:
                candidate = venue_eligible.popleft()
                if candidate in eligible_people_set:
                    person = candidate
                    break

            if person is None:
                break

            # Remove from global pool set
            eligible_people_set.discard(person)

            venue_residents.append(person)
            allocated_people.append(person)

        # Store residents in venue properties and add to venue subsets
        if venue_residents:
            if 'residents' not in venue.properties:
                venue.properties['residents'] = []
            venue.properties['residents'].extend(venue_residents)

            # Get subset_key from config (default to None for backwards compatibility)
            subset_key = allocation_config.get('subset_key', None)

            # Add people to venue's subset system so they're counted properly
            for person in venue_residents:
                venue.add_to_subset(person, subset_key=subset_key)
                # Set venue reference on each person (optional)
                setattr(person, f'{venue_type}_venue', venue)

        # Log progress at intervals
        if venues_processed % progress_interval == 0 or venues_processed == total_venues:
            percent_complete = (venues_processed / total_venues) * 100
            logger.info(f"    Progress: {venues_processed}/{total_venues} venues processed ({percent_complete:.1f}%) - {len(allocated_people)} people allocated so far")

        if len(allocated_people) >= people_to_allocate:
            break

    # Mark allocated people
    if allocated_people:
        household_distributor.mark_people_as_allocated(allocated_people, venue_type)

    # Calculate statistics
    capacity_pct = (len(allocated_people) / total_capacity * 100) if total_capacity > 0 else 0

    logger.info(f"  Allocated {len(allocated_people)} people")
    logger.info(f"  Capacity used: {capacity_pct:.1f}%")

    return {
        'venues': len(venue_list),
        'allocated': len(allocated_people),
        'capacity_used': len(allocated_people),
        'total_capacity': total_capacity,
        'capacity_pct': capacity_pct,
        'remaining_eligible': len(eligible_people) - len(allocated_people)
    }


def _get_eligible_people(population, household_distributor, eligibility) -> List:
    """
    Get list of people who meet eligibility criteria.

    Supports flexible attribute-based filtering with explicit attribute names:
    - Range checks: {attribute: "age", min: value, max: value}
    - Exact matches: {attribute: "sex", value: "F"}
    - Categorical variations: {attribute: "income", value_by_attribute: {...}}

    Examples:
        eligibility = [
            {'attribute': 'age', 'min': 18, 'max': 65},
            {'attribute': 'sex', 'value': 'F'},
            {'attribute': 'employed', 'value': True}
        ]

        # Or empty dict/list for no filtering:
        eligibility = {}
        eligibility = []

    Args:
        population: PopulationManager
        household_distributor: HouseholdDistributor
        eligibility: List of criteria dicts or empty dict/list

    Returns:
        list: List of eligible Person objects
    """
    eligible = []

    # Handle empty eligibility (no filtering)
    if not eligibility:
        # Return all unallocated people
        return [p for p in population.get_all_people()
                if p.id not in household_distributor.allocated_people]

    # Support both list format (new) and dict format (legacy)
    criteria_list = eligibility if isinstance(eligibility, list) else []

    for person in population.get_all_people():
        # Skip if already allocated
        if person.id in household_distributor.allocated_people:
            continue

        # Check all eligibility criteria
        meets_criteria = True
        for criterion in criteria_list:
            # Get attribute name
            attr_name = criterion.get('attribute')
            if not attr_name:
                logger.warning(f"Eligibility criterion missing 'attribute' key: {criterion}")
                continue

            # Get the attribute value from person
            person_value = getattr(person, attr_name, None)

            # If person doesn't have this attribute, they don't qualify
            if person_value is None:
                meets_criteria = False
                break

            # Check if this is a range check or exact match
            if 'min' in criterion or 'max' in criterion:
                # Range check
                min_value = criterion.get('min')
                max_value = criterion.get('max')

                if min_value is not None and person_value < min_value:
                    meets_criteria = False
                    break
                if max_value is not None and person_value > max_value:
                    meets_criteria = False
                    break

            elif 'value' in criterion:
                # Exact match
                expected_value = criterion['value']
                if person_value != expected_value:
                    meets_criteria = False
                    break

            elif 'value_by_attribute' in criterion:
                # Categorical variation (e.g., different max by sex)
                variation_attr = criterion['value_by_attribute'].get('attribute')
                variation_values = criterion['value_by_attribute'].get('values', {})

                if variation_attr:
                    variation_value = getattr(person, variation_attr, None)
                    expected_value = variation_values.get(variation_value)

                    if expected_value is not None and person_value != expected_value:
                        meets_criteria = False
                        break
            else:
                logger.warning(f"Eligibility criterion has no recognized constraint: {criterion}")

        if meets_criteria:
            eligible.append(person)

    return eligible


def _apply_strategy(people: List, strategy: str) -> List:
    """
    Apply allocation strategy to sort/select people.

    Args:
        people: List of Person objects
        strategy: Strategy name ("random", "oldest_first", "youngest_first")

    Returns:
        list: Sorted/shuffled list of people
    """
    if strategy == "random":
        np.random.shuffle(people)
    elif strategy == "oldest_first":
        people.sort(key=lambda p: p.age, reverse=True)
    elif strategy == "youngest_first":
        people.sort(key=lambda p: p.age)
    else:
        logger.warning(f"Unknown strategy '{strategy}', using random")
        np.random.shuffle(people)

    return people


def _check_attribute_constraints(person, venue, attribute_constraints: Dict) -> bool:
    """
    Check if a person meets venue-specific attribute constraints.

    Args:
        person: Person object to check
        venue: Venue object with constraint values in properties
        attribute_constraints: Dict mapping attribute names to constraint config
                              Format: {attribute_name: {min_column: "col", max_column: "col"}}

    Returns:
        bool: True if person meets all constraints, False otherwise
    """
    if not attribute_constraints:
        return True

    for attr_name, constraint_config in attribute_constraints.items():
        # Get the attribute value from the person
        person_value = getattr(person, attr_name, None)
        if person_value is None:
            logger.debug(f"Person {person.id} has no attribute '{attr_name}', skipping constraint check")
            continue

        # Get min constraint from venue
        min_column = constraint_config.get('min_column')
        if min_column:
            min_value = venue.properties.get(min_column)
            if min_value is not None:
                # Handle NaN values
                if isinstance(min_value, float) and np.isnan(min_value):
                    min_value = None
                elif min_value is not None:
                    min_value = float(min_value)
                    if person_value < min_value:
                        return False

        # Get max constraint from venue
        max_column = constraint_config.get('max_column')
        if max_column:
            max_value = venue.properties.get(max_column)
            if max_value is not None:
                # Handle NaN values
                if isinstance(max_value, float) and np.isnan(max_value):
                    max_value = None
                elif max_value is not None:
                    max_value = float(max_value)
                    if person_value > max_value:
                        return False

    return True


def _allocate_with_attributes(venue_type: str, allocation_config: Dict,
                               population, venues, household_distributor) -> Dict:
    """
    Allocate people to venues using attribute-aware capacity matching.

    This function uses the capacity_config from venues_config.yaml to allocate
    people to specific demographic slots (e.g., age_85_94_male).

    Args:
        venue_type: Type of venue (e.g., "care_home")
        allocation_config: Configuration dict for this venue type
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics about this allocation
    """
    logger.info(f"  Using attribute-aware allocation for {venue_type}")

    # Get capacity config from VenueManager
    capacity_config = venues.get_capacity_config(venue_type)
    if not capacity_config:
        logger.warning(f"  No capacity_config found for {venue_type}, falling back to simple allocation")
        # Fall back to simple mode
        allocation_config['allocation_mode'] = 'simple'
        allocation_config['use_attribute_capacities'] = False
        return _allocate_to_venue_type(venue_type, allocation_config, population, venues, household_distributor)

    # Get all venues of this type
    venue_list = venues.get_venues_by_type(venue_type)
    if not venue_list:
        logger.warning(f"  No venues found for type '{venue_type}'")
        return {
            'venues': 0,
            'allocated': 0,
            'capacity_used': 0,
            'total_capacity': 0,
            'capacity_pct': 0
        }

    logger.info(f"  Found {len(venue_list)} {venue_type} venues")

    # Get column mappings from capacity config
    attr_capacities = capacity_config.get('attribute_capacities', {})
    column_mappings = attr_capacities.get('column_mappings', {})

    if not column_mappings:
        logger.warning(f"  No column_mappings in capacity_config, falling back to simple allocation")
        allocation_config['allocation_mode'] = 'simple'
        allocation_config['use_attribute_capacities'] = False
        return _allocate_to_venue_type(venue_type, allocation_config, population, venues, household_distributor)

    # Get attribute constraints (if any)
    attribute_constraints = capacity_config.get('attribute_constraints', {})
    if attribute_constraints:
        logger.info(f"  Attribute constraints configured:")
        for attr_name, constraint_config in attribute_constraints.items():
            min_col = constraint_config.get('min_column', 'N/A')
            max_col = constraint_config.get('max_column', 'N/A')
            logger.info(f"    {attr_name}: min_column={min_col}, max_column={max_col}")

    # Calculate total capacity across all attribute slots
    total_capacity = 0
    for venue in venue_list:
        for column_name in column_mappings.keys():
            cap = venue.properties.get(column_name, 0)
            if cap:
                total_capacity += int(cap)

    logger.info(f"  Total attribute-based capacity: {total_capacity}")

    # Get general eligibility criteria
    eligibility = allocation_config.get('eligibility', {})

    # Get eligible people (broad filter)
    eligible_people = _get_eligible_people(
        population=population,
        household_distributor=household_distributor,
        eligibility=eligibility
    )

    logger.info(f"  Found {len(eligible_people)} eligible people (pre-filtered)")

    if not eligible_people:
        return {
            'venues': len(venue_list),
            'allocated': 0,
            'capacity_used': 0,
            'total_capacity': total_capacity,
            'capacity_pct': 0
        }

    # Group people by attributes (age_band, sex)
    people_by_attributes = {}
    for person in eligible_people:
        # Find which age band this person belongs to
        for column_name, criteria in column_mappings.items():
            match = True

            # Check age_band
            if 'age_band' in criteria:
                min_age, max_age = criteria['age_band']
                if not (min_age <= person.age <= max_age):
                    match = False

            # Check sex
            if 'sex' in criteria:
                if criteria['sex'] != person.sex:
                    match = False

            if match:
                if column_name not in people_by_attributes:
                    people_by_attributes[column_name] = []
                people_by_attributes[column_name].append(person)
                break  # Person matched to this slot, don't check others

    # Log attribute breakdown
    logger.info(f"  People grouped by attributes:")
    for attr_slot, people in people_by_attributes.items():
        logger.info(f"    {attr_slot}: {len(people)} people")

    # Apply strategy to each attribute group
    strategy = allocation_config.get('strategy', 'random')
    for attr_slot in people_by_attributes:
        people_by_attributes[attr_slot] = _apply_strategy(people_by_attributes[attr_slot], strategy)

    # Pre-group people by geographical unit AND attribute slot to avoid O(n) filtering per venue
    # Structure: {(column_name, geo_unit): deque([person, ...])}
    people_by_attr_and_geo = {}
    for column_name, people_list in people_by_attributes.items():
        for person in people_list:
            key = (column_name, person.geographical_unit)
            if key not in people_by_attr_and_geo:
                people_by_attr_and_geo[key] = deque()
            people_by_attr_and_geo[key].append(person)

    # Allocate people to venues by attribute slots
    allocated_people = []
    allocation_stats = {}  # Track allocations per attribute slot

    # Use a set to track allocated person IDs for O(1) lookup instead of O(n) list.remove()
    allocated_person_ids = set()

    # Progress tracking setup
    total_venues = len(venue_list)
    venues_processed = 0
    progress_interval = max(1, total_venues // 10)  # Update every 10%

    logger.info(f"  Allocating people to {total_venues} venues...")

    for venue in venue_list:
        venues_processed += 1
        # For each attribute slot in this venue
        for column_name, criteria in column_mappings.items():
            # Get capacity for this slot
            capacity = venue.properties.get(column_name, 0)
            if not capacity or capacity == 0:
                continue

            capacity = int(capacity)

            # Get pre-grouped people for this attribute slot and geo unit (O(1) lookup)
            venue_geo_unit = venue.geographical_unit
            key = (column_name, venue_geo_unit)
            geo_filtered_people = people_by_attr_and_geo.get(key, deque())

            # Allocate people to this slot
            venue_residents = []
            allocated_count = 0

            for _ in range(capacity):
                # Find next eligible person who hasn't been allocated yet
                person = None
                while geo_filtered_people:
                    candidate = geo_filtered_people.popleft()

                    # Skip if already allocated
                    if candidate.id in allocated_person_ids:
                        continue

                    # Check if person meets venue-specific attribute constraints
                    if not _check_attribute_constraints(candidate, venue, attribute_constraints):
                        # Person doesn't meet constraints, skip them
                        continue

                    # Found a valid person
                    person = candidate
                    break

                if person is None:
                    break

                # Add to allocated set (O(1) instead of O(n) list.remove())
                allocated_person_ids.add(person.id)

                venue_residents.append(person)
                allocated_people.append(person)
                allocated_count += 1

            # Track stats
            if column_name not in allocation_stats:
                allocation_stats[column_name] = 0
            allocation_stats[column_name] += allocated_count

            # Store residents in venue (by attribute slot) and add to venue subsets
            if venue_residents:
                if 'residents' not in venue.properties:
                    venue.properties['residents'] = []
                venue.properties['residents'].extend(venue_residents)

                # Also track by slot
                slot_key = f'residents_{column_name}'
                if slot_key not in venue.properties:
                    venue.properties[slot_key] = []
                venue.properties[slot_key].extend(venue_residents)

                # Get subset_key from config (default to None for backwards compatibility)
                subset_key = allocation_config.get('subset_key', None)

                # Add people to venue's subset system so they're counted properly
                for person in venue_residents:
                    venue.add_to_subset(person, subset_key=subset_key)
                    # Set venue reference on each person
                    # setattr(person, f'{venue_type}_venue', venue)

        # Log progress at intervals
        if venues_processed % progress_interval == 0 or venues_processed == total_venues:
            percent_complete = (venues_processed / total_venues) * 100
            logger.info(f"    Progress: {venues_processed}/{total_venues} venues processed ({percent_complete:.1f}%) - {len(allocated_people)} people allocated so far")

    # Mark allocated people
    if allocated_people:
        household_distributor.mark_people_as_allocated(allocated_people, venue_type)

    # Log allocation stats
    logger.info(f"  Allocation by attribute slot:")
    for attr_slot, count in allocation_stats.items():
        logger.info(f"    {attr_slot}: {count} allocated")

    # Calculate statistics
    capacity_pct = (len(allocated_people) / total_capacity * 100) if total_capacity > 0 else 0

    logger.info(f"  Total allocated: {len(allocated_people)} people")
    logger.info(f"  Capacity used: {capacity_pct:.1f}%")

    # Report remaining unallocated by attribute
    logger.info(f"  Remaining unallocated by attribute:")
    for attr_slot, people in people_by_attributes.items():
        if people:
            logger.info(f"    {attr_slot}: {len(people)} remaining")

    return {
        'venues': len(venue_list),
        'allocated': len(allocated_people),
        'capacity_used': len(allocated_people),
        'total_capacity': total_capacity,
        'capacity_pct': capacity_pct,
        'allocation_by_attribute': allocation_stats
    }
