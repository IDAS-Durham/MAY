"""
Generic venue allocator with YAML configuration.

Allocates people to venues (care homes, dorms, company housing, etc.)
based on flexible YAML-defined criteria.

Venue allocations are configured in allocation_strategy.yaml as part of
the unified household + venue allocation strategy.
"""

import os
import logging
import yaml
import random
from typing import List, Optional, Dict

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

    # Allocate people to venues
    allocated_people = []

    for venue in venue_list:
        capacity = int(venue.properties.get(capacity_property, 0))
        if capacity == 0:
            continue

        # Filter eligible people to only those from this venue's geographical unit
        venue_geo_unit = venue.geographical_unit
        venue_eligible = [p for p in eligible_people if p.geographical_unit == venue_geo_unit]

        # Allocate people to this venue
        venue_residents = []
        for _ in range(capacity):
            if not venue_eligible:
                break

            person = venue_eligible.pop(0)
            # Remove from global pool as well
            eligible_people.remove(person)

            venue_residents.append(person)
            allocated_people.append(person)

        # Store residents in venue properties
        if venue_residents:
            if 'residents' not in venue.properties:
                venue.properties['residents'] = []
            venue.properties['residents'].extend(venue_residents)

            # Set venue reference on each person (optional)
            for person in venue_residents:
                setattr(person, f'{venue_type}_venue', venue)

        if idx >= people_to_allocate:
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


def _get_eligible_people(population, household_distributor, eligibility: Dict) -> List:
    """
    Get list of people who meet eligibility criteria.

    Args:
        population: PopulationManager
        household_distributor: HouseholdDistributor
        eligibility: Dict with criteria (min_age, max_age, sex, etc.)

    Returns:
        list: List of eligible Person objects
    """
    min_age = eligibility.get('min_age', 0)
    max_age = eligibility.get('max_age')
    required_sex = eligibility.get('sex')

    eligible = []

    for person in population.get_all_people():
        # Skip if already allocated
        if person.id in household_distributor.allocated_people:
            continue

        # Check age
        if person.age < min_age:
            continue
        if max_age is not None and person.age > max_age:
            continue

        # Check sex
        if required_sex is not None and person.sex != required_sex:
            continue

        # Add other criteria here as needed
        # (activities, location, etc.)

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
        random.shuffle(people)
    elif strategy == "oldest_first":
        people.sort(key=lambda p: p.age, reverse=True)
    elif strategy == "youngest_first":
        people.sort(key=lambda p: p.age)
    else:
        logger.warning(f"Unknown strategy '{strategy}', using random")
        random.shuffle(people)

    return people


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

    # Calculate total capacity across all attribute slots
    total_capacity = 0
    for venue in venue_list:
        for column_name in column_mappings.keys():
            cap = venue.properties.get(column_name, 0)
            if cap:
                total_capacity += int(cap)

    logger.info(f"  Total attribute-based capacity: {total_capacity}")

    # Get general eligibility criteria (pre-filter)
    eligibility = allocation_config.get('eligibility', {})
    min_age_filter = eligibility.get('min_age', 0)
    max_age_filter = eligibility.get('max_age')
    sex_filter = eligibility.get('sex')

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

    # Allocate people to venues by attribute slots
    allocated_people = []
    allocation_stats = {}  # Track allocations per attribute slot

    for venue in venue_list:
        # For each attribute slot in this venue
        for column_name, criteria in column_mappings.items():
            # Get capacity for this slot
            capacity = venue.properties.get(column_name, 0)
            if not capacity or capacity == 0:
                continue

            capacity = int(capacity)

            # Get people for this attribute slot FROM THIS VENUE'S GEO UNIT
            available_people = people_by_attributes.get(column_name, [])
            if not available_people:
                continue

            # Filter people to only those from this venue's geographical unit
            venue_geo_unit = venue.geographical_unit
            geo_filtered_people = [p for p in available_people if p.geographical_unit == venue_geo_unit]

            # Allocate people to this slot
            venue_residents = []
            allocated_count = 0

            for _ in range(capacity):
                if not geo_filtered_people:
                    break

                person = geo_filtered_people.pop(0)  # Take from front (already sorted by strategy)
                # Remove from global pool as well
                available_people.remove(person)

                venue_residents.append(person)
                allocated_people.append(person)
                allocated_count += 1

            # Track stats
            if column_name not in allocation_stats:
                allocation_stats[column_name] = 0
            allocation_stats[column_name] += allocated_count

            # Store residents in venue (by attribute slot)
            if venue_residents:
                if 'residents' not in venue.properties:
                    venue.properties['residents'] = []
                venue.properties['residents'].extend(venue_residents)

                # Also track by slot
                slot_key = f'residents_{column_name}'
                if slot_key not in venue.properties:
                    venue.properties[slot_key] = []
                venue.properties[slot_key].extend(venue_residents)

                # Set venue reference on each person
                for person in venue_residents:
                    setattr(person, f'{venue_type}_venue', venue)

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
