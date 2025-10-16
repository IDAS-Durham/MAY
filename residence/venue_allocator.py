"""
Generic venue allocator with YAML configuration.

Allocates people to venues (care homes, dorms, company housing, etc.)
based on flexible YAML-defined criteria.
"""

import os
import logging
import yaml
import random
from typing import List, Optional, Dict

logger = logging.getLogger("venue_allocator")


def allocate_people_to_venues(geography, population, venues, household_distributor,
                               config_file: str = "data/venues/venue_allocation.yaml"):
    """
    Allocate people to venues based on YAML configuration.

    This is a completely generic function that works with any venue type.
    Configuration is defined in venue_allocation.yaml.

    Args:
        geography: Geography object
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor (to mark people as allocated)
        config_file: Path to YAML configuration file

    Returns:
        dict: Statistics about allocation for each venue type
    """
    logger.info("=" * 60)
    logger.info("Starting venue allocation from YAML configuration")
    logger.info("=" * 60)

    # Load configuration
    logger.info(f"Loading venue allocation config from {config_file}")
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    venue_allocations = config.get('venue_allocations', [])
    if not venue_allocations:
        logger.warning("No venue allocations defined in config")
        return {}

    # Track overall statistics
    all_stats = {}

    # Process each venue type
    for allocation_config in venue_allocations:
        venue_type = allocation_config.get('venue_type')
        enabled = allocation_config.get('enabled', True)

        if not enabled:
            logger.info(f"Skipping {venue_type} (disabled in config)")
            continue

        logger.info("")
        logger.info(f"Processing {venue_type}...")

        stats = _allocate_to_venue_type(
            venue_type=venue_type,
            allocation_config=allocation_config,
            population=population,
            venues=venues,
            household_distributor=household_distributor
        )

        all_stats[venue_type] = stats

    # Print overall summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("VENUE ALLOCATION SUMMARY")
    logger.info("=" * 60)

    total_allocated = 0
    for venue_type, stats in all_stats.items():
        logger.info(f"{venue_type}:")
        logger.info(f"  Venues: {stats['venues']}")
        logger.info(f"  Allocated: {stats['allocated']} people")
        logger.info(f"  Capacity used: {stats['capacity_used']}/{stats['total_capacity']} ({stats.get('capacity_pct', 0):.1f}%)")
        total_allocated += stats['allocated']

    logger.info("")
    logger.info(f"Total people allocated to venues: {total_allocated}")
    logger.info("=" * 60)

    return all_stats


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
    idx = 0

    for venue in venue_list:
        capacity = int(venue.properties.get(capacity_property, 0))
        if capacity == 0:
            continue

        # Allocate people to this venue
        venue_residents = []
        for _ in range(capacity):
            if idx >= people_to_allocate:
                break

            person = eligible_people[idx]
            venue_residents.append(person)
            allocated_people.append(person)
            idx += 1

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
