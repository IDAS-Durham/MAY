"""
Unified allocation strategy executor.

Executes both household and venue allocations in a single YAML-defined sequence.
"""

import os
import logging
import yaml
from typing import Dict, List
from venue_allocator import _allocate_to_venue_type

logger = logging.getLogger("allocation_strategy")


def execute_allocation_strategy(geography, population, venues, households,
                                strategy_file: str = "data/allocation_strategy.yaml"):
    """
    Execute a unified allocation strategy from YAML configuration.

    This function orchestrates BOTH household and venue allocations in a single
    sequence defined in the YAML file.

    Args:
        geography: Geography object
        population: PopulationManager
        venues: VenueManager
        households: HouseholdDistributor
        strategy_file: Path to YAML strategy file (relative or absolute)

    Returns:
        dict: Complete statistics for all steps
    """
    logger.info("=" * 60)
    logger.info("Executing Unified Allocation Strategy")
    logger.info("=" * 60)

    # Handle relative paths
    if not os.path.isabs(strategy_file):
        # Try relative to current directory first, then relative to data/
        if not os.path.exists(strategy_file):
            strategy_file = f"data/{strategy_file}"

    # Load strategy configuration
    logger.info(f"Loading allocation strategy from {strategy_file}")
    with open(strategy_file, 'r') as f:
        strategy = yaml.safe_load(f)

    # Check if enabled
    if not strategy.get('enabled', True):
        logger.info("Unified strategy is disabled, skipping")
        return {}

    # Get steps
    steps = strategy.get('steps', [])
    if not steps:
        logger.warning("No allocation steps defined in strategy")
        return {}

    logger.info(f"Found {len(steps)} allocation steps")
    logger.info("")

    # Execute each step
    all_stats = {}
    step_number = 1

    for step_config in steps:
        step_type = step_config.get('type')
        step_name = step_config.get('name', f'Step {step_number}')

        if step_type not in ['household', 'venue']:
            logger.warning(f"Unknown step type '{step_type}' for step '{step_name}', skipping")
            continue

        logger.info("=" * 60)
        logger.info(f"Step {step_number}: {step_name} ({step_type})")
        logger.info("=" * 60)

        description = step_config.get('description')
        if description:
            logger.info(f"Description: {description}")
            logger.info("")

        # Execute based on type
        if step_type == 'household':
            stats = _execute_household_step(step_config, households)
        elif step_type == 'venue':
            stats = _execute_venue_step(step_config, population, venues, households)

        all_stats[step_name] = {
            'type': step_type,
            'step_number': step_number,
            **stats
        }

        step_number += 1
        logger.info("")

    # Print overall summary
    logger.info("=" * 60)
    logger.info("UNIFIED ALLOCATION STRATEGY SUMMARY")
    logger.info("=" * 60)
    logger.info("")

    total_household_alloc = 0
    total_venue_alloc = 0

    for step_name, stats in all_stats.items():
        logger.info(f"{stats['step_number']}. {step_name} ({stats['type']}):")

        if stats['type'] == 'household':
            households_created = stats.get('households_created', 0)
            people_allocated = stats.get('people_allocated_this_round', 0)
            logger.info(f"   Households: {households_created:,}")
            logger.info(f"   People: {people_allocated:,}")
            total_household_alloc += people_allocated

        elif stats['type'] == 'venue':
            allocated = stats.get('allocated', 0)
            venues_count = stats.get('venues', 0)
            logger.info(f"   Venues: {venues_count}")
            logger.info(f"   People: {allocated:,}")
            total_venue_alloc += allocated

        logger.info("")

    logger.info("Overall Totals:")
    logger.info(f"  Total households: {len(households.households):,}")
    logger.info(f"  People in households: {total_household_alloc:,}")
    logger.info(f"  People in venues: {total_venue_alloc:,}")
    logger.info(f"  Total allocated: {len(households.allocated_people):,}")
    logger.info(f"  Remaining unallocated: {households.get_available_people_count():,}")

    total_pop = len(population.get_all_people())
    alloc_pct = (len(households.allocated_people) / total_pop * 100) if total_pop > 0 else 0
    logger.info(f"  Allocation rate: {alloc_pct:.1f}%")
    logger.info("=" * 60)

    return all_stats


def _execute_household_step(step_config: Dict, households) -> Dict:
    """
    Execute a household allocation step.

    Args:
        step_config: Configuration dict for this step
        households: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    patterns = step_config.get('patterns')
    max_households = step_config.get('max_households')
    refresh_pools = step_config.get('refresh_pools', False)
    enable_demotion = step_config.get('enable_demotion')
    round_name = step_config.get('name', 'Household Round')

    # Temporarily override demotion if specified
    original_demotion = None
    if enable_demotion is not None:
        original_demotion = households.config['demotion']['enabled']
        households.config['demotion']['enabled'] = enable_demotion

    try:
        stats = households.distribute_households_round(
            pattern_filter=patterns,
            max_households=max_households,
            refresh_pools=refresh_pools,
            round_name=round_name
        )
        return stats
    finally:
        # Restore original demotion setting
        if original_demotion is not None:
            households.config['demotion']['enabled'] = original_demotion


def _execute_venue_step(step_config: Dict, population, venues, households) -> Dict:
    """
    Execute a venue allocation step.

    Args:
        step_config: Configuration dict for this step
        population: PopulationManager
        venues: VenueManager
        households: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    venue_type = step_config.get('venue_type')

    # Create allocation config for venue allocator
    allocation_config = {
        'venue_type': venue_type,
        'description': step_config.get('description', ''),
        'capacity_property': step_config.get('capacity_property', 'capacity'),
        'eligibility': step_config.get('eligibility', {}),
        'strategy': step_config.get('strategy', 'random'),
        'max_allocations': step_config.get('max_allocations')
    }

    # Use the existing venue allocator function
    stats = _allocate_to_venue_type(
        venue_type=venue_type,
        allocation_config=allocation_config,
        population=population,
        venues=venues,
        household_distributor=households
    )

    return stats
