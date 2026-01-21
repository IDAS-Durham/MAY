"""
Unified allocation strategy executor.

Executes both household and venue allocations in a single YAML-defined sequence.
"""

import os
import logging
import yaml
from typing import Dict, List
from .venue_allocator import _allocate_to_venue_type

logger = logging.getLogger("allocation_strategy")


def execute_allocation_strategy(population, venues, household_distributor,
                                strategy_file: str = "data/households/allocation_strategy.yaml"):
    """
    Execute a unified allocation strategy from YAML configuration.

    This function orchestrates BOTH household and venue allocations in a single
    sequence defined in the YAML file.

    Args:
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor
        strategy_file: Path to YAML strategy file (relative or absolute)

    Returns:
        dict: Complete statistics for all steps
    """
    logger.info("=" * 60)
    logger.info("Executing Unified Allocation Strategy")
    logger.info("=" * 60)

    # Handle relative paths - try as-is first, then relative to data/ directory
    if not os.path.isabs(strategy_file):
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

        if step_type not in ['household', 'venue', 'household_excess', 'household_overflow', 'household_promotion']:
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
            stats = _execute_household_step(step_config, household_distributor)
        elif step_type == 'venue':
            stats = _execute_venue_step(step_config, population, venues, household_distributor)
        elif step_type == 'household_excess':
            stats = _execute_household_excess_step(step_config, household_distributor)
        elif step_type == 'household_overflow':
            stats = _execute_household_overflow_step(step_config, household_distributor)
        elif step_type == 'household_promotion':
            stats = _execute_household_promotion_step(step_config, household_distributor)

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
    total_excess_alloc = 0
    total_overflow_alloc = 0

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

        elif stats['type'] == 'household_excess':
            people_added = stats.get('people_added', 0)
            households_modified = stats.get('households_modified', 0)
            logger.info(f"   Households modified: {households_modified:,}")
            logger.info(f"   People added: {people_added:,}")
            total_excess_alloc += people_added

        elif stats['type'] == 'household_overflow':
            people_added = stats.get('people_added', 0)
            households_modified = stats.get('households_modified', 0)
            logger.info(f"   Households modified: {households_modified:,}")
            logger.info(f"   People added (overflow): {people_added:,}")
            total_overflow_alloc += people_added

        elif stats['type'] == 'household_promotion':
            people_added = stats.get('people_added', 0)
            households_promoted = stats.get('households_promoted', 0)
            logger.info(f"   Households promoted: {households_promoted:,}")
            logger.info(f"   People added (promotion): {people_added:,}")
            total_overflow_alloc += people_added  # Count with overflow

        logger.info("")

    logger.info("Overall Totals:")
    # Get household count from VenueManager
    all_households = household_distributor.venue_manager.get_venues_by_type("household")
    logger.info(f"  Total households: {len(all_households):,}")
    logger.info(f"  People in households (initial): {total_household_alloc:,}")
    logger.info(f"  People added to households (excess): {total_excess_alloc:,}")
    logger.info(f"  People added to households (overflow): {total_overflow_alloc:,}")
    logger.info(f"  People in venues: {total_venue_alloc:,}")
    logger.info(f"  Total allocated: {len(household_distributor.allocated_people):,}")
    logger.info(f"  Remaining unallocated: {household_distributor.get_available_people_count():,}")

    total_pop = len(population.get_all_people())
    alloc_pct = (len(household_distributor.allocated_people) / total_pop * 100) if total_pop > 0 else 0
    logger.info(f"  Allocation rate: {alloc_pct:.1f}%")
    logger.info("=" * 60)

    # Export unallocated people if any
    household_distributor.export_unallocated_people_to_csv()

    return all_stats


def _execute_household_step(step_config: Dict, household_distributor) -> Dict:
    """
    Execute a household allocation step.

    Args:
        step_config: Configuration dict for this step
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    patterns = step_config.get('patterns')
    max_households = step_config.get('max_households')
    refresh_pools = step_config.get('refresh_pools', False)
    enable_demotion = step_config.get('enable_demotion')
    max_household_size = step_config.get('max_household_size')
    allocate_flexible = step_config.get('allocate_flexible', False)
    round_name = step_config.get('name', 'Household Round')
    rule_name = step_config.get('rule')  # Optional: explicit rule to apply
    demotion_rules = step_config.get('demotion_rules', {})  # Optional: pattern -> rule mapping for demotions

    if rule_name:
        logger.info(f"  Using explicit relationship rule: '{rule_name}'")

    if demotion_rules:
        logger.info(f"  Demotion rules configured: {len(demotion_rules)} pattern(s)")

    # Process patterns to extract assumptions
    # Patterns can be either:
    #   - Simple strings: "0 >=0 0 0"
    #   - Dicts with pattern and assumption: {pattern: "0 >=0 0 0", assumption: "0 2 0 0"}
    pattern_list = None
    pattern_assumptions = {}

    if patterns is not None:
        pattern_list = []
        for p in patterns:
            if isinstance(p, dict):
                # Format with assumption
                pattern_str = p.get('pattern')
                assumption_str = p.get('assumption')

                if pattern_str:
                    pattern_list.append(pattern_str)
                    if assumption_str:
                        pattern_assumptions[pattern_str] = assumption_str
                        logger.info(f"  Pattern '{pattern_str}' has assumption: '{assumption_str}'")
            else:
                # Simple format
                pattern_list.append(p)

    # Temporarily override demotion if specified
    original_demotion = None
    if enable_demotion is not None:
        original_demotion = household_distributor.config['demotion']['enabled']
        household_distributor.config['demotion']['enabled'] = enable_demotion

    try:
        stats = household_distributor.distribute_households_round(
            pattern_filter=pattern_list,
            pattern_assumptions=pattern_assumptions,
            max_households=max_households,
            max_household_size=max_household_size,
            allocate_flexible=allocate_flexible,
            refresh_pools=refresh_pools,
            round_name=round_name,
            rule_name=rule_name,
            demotion_rules=demotion_rules
        )
        return stats
    finally:
        # Restore original demotion setting
        if original_demotion is not None:
            household_distributor.config['demotion']['enabled'] = original_demotion


def _execute_household_excess_step(step_config: Dict, household_distributor) -> Dict:
    """
    Execute a household excess allocation step.

    This step adds people to existing households created in previous steps.

    Args:
        step_config: Configuration dict for this step
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    target_patterns = step_config.get('target_patterns', [])
    add_category = step_config.get('add_category')
    constraints = step_config.get('constraints')
    max_per_household = step_config.get('max_per_household')
    add_distribution = step_config.get('add_distribution')
    refresh_pools = step_config.get('refresh_pools', False)
    round_name = step_config.get('name', 'Household Excess Round')
    rule_name = step_config.get('rule')  # Optional: relationship rule to apply

    if rule_name:
        logger.info(f"  Using explicit relationship rule: '{rule_name}'")

    if not add_category:
        logger.error("No 'add_category' specified for household_excess step")
        return {
            'people_added': 0,
            'households_modified': 0,
            'error': "Missing 'add_category' parameter"
        }

    stats = household_distributor.allocate_excess_to_households(
        target_patterns=target_patterns,
        add_category=add_category,
        constraints=constraints,
        max_per_household=max_per_household,
        add_distribution=add_distribution,
        refresh_pools=refresh_pools,
        round_name=round_name,
        rule_name=rule_name
    )

    return stats


def _execute_household_overflow_step(step_config: Dict, household_distributor) -> Dict:
    """
    Execute a household overflow allocation step.

    This step adds ALL remaining people from a category to existing households,
    IGNORING max household size constraints. People are distributed balancedly
    across eligible households with optional pattern biasing.

    Args:
        step_config: Configuration dict for this step
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    target_patterns = step_config.get('target_patterns', [])
    add_category = step_config.get('add_category')
    pattern_bias = step_config.get('pattern_bias', {})  # e.g., {"0 >=0 0 0": 2.0}
    refresh_pools = step_config.get('refresh_pools', False)
    round_name = step_config.get('name', 'Household Overflow Round')

    if not add_category:
        logger.error("No 'add_category' specified for household_overflow step")
        return {
            'people_added': 0,
            'households_modified': 0,
            'error': "Missing 'add_category' parameter"
        }

    stats = household_distributor.allocate_overflow_to_households(
        target_patterns=target_patterns,
        add_category=add_category,
        pattern_bias=pattern_bias,
        refresh_pools=refresh_pools,
        round_name=round_name
    )

    return stats


def _execute_household_promotion_step(step_config: Dict, household_distributor) -> Dict:
    """
    Execute a household promotion allocation step.

    This step promotes existing households according to specific rules,
    allowing controlled acceptance of remaining people.

    Args:
        step_config: Configuration dict for this step
        household_distributor: HouseholdDistributor

    Returns:
        dict: Statistics for this step
    """
    promotion_rules = step_config.get('promotion_rules', [])
    target_categories = step_config.get('target_categories', [])  # Fallback to simple mode
    refresh_pools = step_config.get('refresh_pools', False)
    round_name = step_config.get('name', 'Household Promotion Round')

    if not promotion_rules and not target_categories:
        logger.error("No 'promotion_rules' or 'target_categories' specified for household_promotion step")
        return {
            'people_added': 0,
            'households_promoted': 0,
            'error': "Missing 'promotion_rules' or 'target_categories' parameter"
        }

    if promotion_rules:
        # Rule-based promotion (controlled)
        stats = household_distributor.promote_with_rules(
            promotion_rules=promotion_rules,
            refresh_pools=refresh_pools,
            round_name=round_name
        )
    else:
        # Simple promotion (all categories)
        stats = household_distributor.promote_and_allocate(
            target_categories=target_categories,
            refresh_pools=refresh_pools,
            round_name=round_name
        )

    return stats


def _execute_venue_step(step_config: Dict, population, venues, household_distributor) -> Dict:
    """
    Execute a venue allocation step.

    Args:
        step_config: Configuration dict for this step
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor

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
        'max_allocations': step_config.get('max_allocations'),
        # Attribute-aware allocation settings
        'allocation_mode': step_config.get('allocation_mode', 'simple'),
        'use_attribute_capacities': step_config.get('use_attribute_capacities', False),
        # Subset configuration
        'subset_key': step_config.get('subset_key')
    }

    # Use the existing venue allocator function
    stats = _allocate_to_venue_type(
        venue_type=venue_type,
        allocation_config=allocation_config,
        population=population,
        venues=venues,
        household_distributor=household_distributor
    )

    return stats
