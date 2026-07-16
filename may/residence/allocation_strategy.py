"""
Unified allocation strategy executor.

Executes both household and venue allocations in a single YAML-defined sequence.
"""

import csv
import os
import logging
import operator
import yaml
from typing import Dict, List, Optional
from .venue_allocator import _allocate_to_venue_type
from .household_distributor import HouseholdError
from .composition_pattern import CompositionPattern
from may.utils import path_resolver as pr

logger = logging.getLogger("allocation_strategy")


def execute_allocation_strategy(population,
                                venues,
                                household_distributor,
                                strategy_file: str = "data/households/allocation_strategy.yaml",
                                export_debug_csv: bool = False):
    """
    Execute a unified allocation strategy from YAML configuration.

    This function orchestrates BOTH household and venue allocations in a single
    sequence defined in the YAML file.

    Args:
        population: PopulationManager
        venues: VenueManager
        household_distributor: HouseholdDistributor
        strategy_file (str, optional): Path to YAML strategy file (relative or absolute). Default is "data/households/allocation_strategy.yaml". 

    Returns:
        dict: Complete statistics for all steps
    
    """
    logger.info("=" * 60)
    logger.info("Executing Unified Allocation Strategy")
    logger.info("=" * 60)

    # Resolve template variables, then fall back to data/ prefix for bare relative paths
    strategy_file = pr.resolve(strategy_file)
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

    _resolve_pattern_selectors(
        steps,
        household_distributor.household_pattern_vocabulary,
        household_distributor.categories,
    )
    _validate_step_patterns(steps, household_distributor.household_pattern_vocabulary)
    _setup_structure_mixture(strategy.get('mixture'), steps, household_distributor)

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

    # Optionally export unallocated people (skipped for large worlds —
    # builds a DataFrame across every unplaced person).
    if export_debug_csv:
        household_distributor.export_unallocated_people_to_csv()

    return all_stats


_SELECTOR_OPS = {'>=': operator.ge, '>': operator.gt, '==': operator.eq,
                 '<=': operator.le, '<': operator.lt}


def _resolve_pattern_selectors(steps: List[Dict], vocabulary: set, categories: List) -> None:
    """Resolve `patterns_where` selectors and enforce build-step disjointness.

    Runs once, before any allocation. A selector is a list of
    {category, operator, value} conditions evaluated against each vocabulary
    pattern's minimum counts; the matches are written back into the step as an
    explicit `patterns:` list, so the executor below needs no changes. Every
    resolved or hand-written build-step pattern is then claimed exactly once —
    a pattern claimed twice would double its census build quota, so overlap is
    an error, and a `patterns: null` step takes whatever remains unclaimed.
    """
    build_steps = [s for s in steps if s.get('type') == 'household']
    if not build_steps or not vocabulary:
        return
    name_to_idx = {cat.name: idx for idx, cat in enumerate(categories)}

    for step in build_steps:
        where = step.get('patterns_where')
        if where is None:
            continue
        step_name = step.get('name', 'household')
        if step.get('patterns') is not None:
            raise HouseholdError(
                f"Step '{step_name}': give either 'patterns' or 'patterns_where', not both."
            )
        conditions = []
        for cond in where:
            cat, op, value = cond.get('category'), cond.get('operator'), cond.get('value')
            if cat not in name_to_idx:
                raise HouseholdError(
                    f"Step '{step_name}': patterns_where category {cat!r} is not one of "
                    f"{sorted(name_to_idx)}."
                )
            if op not in _SELECTOR_OPS:
                raise HouseholdError(
                    f"Step '{step_name}': patterns_where operator {op!r} is not one of "
                    f"{sorted(_SELECTOR_OPS)}."
                )
            conditions.append((name_to_idx[cat], _SELECTOR_OPS[op], value))

        matched = []
        for pattern_str in vocabulary:
            pattern = CompositionPattern.from_string(pattern_str)
            if all(op(pattern.get_min_count(idx), value) for idx, op, value in conditions):
                matched.append(pattern_str)
        if not matched:
            raise HouseholdError(
                f"Step '{step_name}': patterns_where matched no pattern in households.csv."
            )
        step['patterns'] = sorted(matched)
        del step['patterns_where']
        logger.info(f"Step '{step_name}': patterns_where resolved to {len(matched)} patterns")

    # pattern -> {interpretation-or-None: step name}. A step without an
    # `interpretation` claims the pattern's WHOLE census count (key None),
    # which conflicts with any other claim; interpretation steps share a
    # pattern as long as their interpretations differ — each takes its
    # mixture quota of the count.
    claimed: Dict[str, Dict[Optional[str], str]] = {}
    for step in build_steps:
        patterns = step.get('patterns')
        if patterns is None:
            continue
        step_name = step.get('name', 'household')
        interp = step.get('interpretation')
        for p in patterns:
            name = p.get('pattern') if isinstance(p, dict) else p
            holders = claimed.setdefault(name, {})
            conflict = (holders.get(interp) if interp is not None and None not in holders
                        else next(iter(holders.values()), None) if interp is None
                        else holders.get(None) or holders.get(interp))
            if conflict:
                raise HouseholdError(
                    f"Pattern '{name}' is claimed by both '{conflict}' and "
                    f"'{step_name}' — a pattern's census count is a build quota, so "
                    f"steps must claim distinct patterns (or distinct interpretations "
                    f"of one pattern under a mixture)."
                )
            holders[interp] = step_name

    for step in build_steps:
        if step.get('patterns') is not None:
            continue
        step_name = step.get('name', 'household')
        remainder = sorted(vocabulary - set(claimed))
        if not remainder:
            raise HouseholdError(
                f"Step '{step_name}' (patterns: null) has no patterns left — "
                f"earlier build steps already claim the whole vocabulary."
            )
        step['patterns'] = remainder
        for name in remainder:
            claimed[name] = {step.get('interpretation'): step_name}
        logger.info(f"Step '{step_name}': patterns null -> {len(remainder)} remaining patterns")


def _setup_structure_mixture(mixture_cfg: Optional[Dict], steps: List[Dict],
                             household_distributor) -> None:
    """Load the structure-mixture table and validate interpretation claims.

    A census composition pattern is a marginal: different household structures
    (a couple, a parent with an adult child, unrelated people) project onto
    the same pattern. The mixture table gives, per geo unit, the measured
    share of each interpretation, and build steps claim one interpretation
    each — the quota split happens at build time.

    Entirely opt-in: no `mixture:` block means no behavior change, and using
    `interpretation:` on a step without the block is an error.
    """
    interp_steps = [s for s in steps
                    if s.get('type') == 'household' and s.get('interpretation') is not None]
    if mixture_cfg is None:
        if interp_steps:
            names = [s.get('name', 'household') for s in interp_steps]
            raise HouseholdError(
                f"Step(s) {names} use 'interpretation' but the strategy has no "
                f"'mixture:' block declaring the shares file."
            )
        household_distributor.structure_mixture = None
        return

    path = pr.resolve(mixture_cfg.get('file', ''))
    if not path or not os.path.exists(path):
        raise HouseholdError(f"mixture.file not found: {path!r}")
    geo_level = mixture_cfg.get('geo_level')
    if geo_level not in household_distributor.geography.levels:
        raise HouseholdError(
            f"mixture.geo_level {geo_level!r} is not one of the configured "
            f"geography levels {household_distributor.geography.levels}."
        )

    shares: Dict[tuple, Dict[str, float]] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            key = (row['geo_unit'], row['pattern'])
            shares.setdefault(key, {})[row['interpretation']] = float(row['share'])

    interps_by_pattern: Dict[str, set] = {}
    for (geo_unit, pattern), parts in shares.items():
        total = sum(parts.values())
        if abs(total - 1.0) > 0.02:
            raise HouseholdError(
                f"mixture shares for ({geo_unit}, '{pattern}') sum to {total:.4f}, not 1."
            )
        for interp in parts:  # normalise away rounding residue
            parts[interp] /= total
        interps_by_pattern.setdefault(pattern, set()).update(parts)

    # Every interpretation of a claimed pattern must be claimed by exactly one
    # step, or part of its census count would silently never be built.
    claimed_by_pattern: Dict[str, set] = {}
    for step in interp_steps:
        step_name = step.get('name', 'household')
        interp = step['interpretation']
        for p in (step.get('patterns') or []):
            name = p.get('pattern') if isinstance(p, dict) else p
            if name not in interps_by_pattern:
                raise HouseholdError(
                    f"Step '{step_name}' claims interpretation '{interp}' of pattern "
                    f"'{name}', which has no rows in {path}."
                )
            if interp not in interps_by_pattern[name]:
                raise HouseholdError(
                    f"Step '{step_name}': interpretation '{interp}' does not exist for "
                    f"pattern '{name}' in {path} (has {sorted(interps_by_pattern[name])})."
                )
            claimed_by_pattern.setdefault(name, set()).add(interp)
    for pattern, claimed in claimed_by_pattern.items():
        missing = interps_by_pattern[pattern] - claimed
        if missing:
            raise HouseholdError(
                f"Pattern '{pattern}' has unclaimed interpretation(s) {sorted(missing)} — "
                f"that share of its census count would never be built. Add a step "
                f"(rule-free is fine) claiming each interpretation."
            )
    unused = set(interps_by_pattern) - set(claimed_by_pattern)
    if unused:
        logger.warning(
            f"mixture file has rows for pattern(s) never claimed with an "
            f"'interpretation:' step (built whole, mixture ignored): {sorted(unused)}"
        )

    household_distributor.structure_mixture = {'geo_level': geo_level, 'shares': shares}
    logger.info(
        f"Structure mixture loaded: {len(interps_by_pattern)} patterns x "
        f"{len({g for g, _ in shares})} geo units at {geo_level}"
    )


def _validate_step_patterns(steps: List[Dict], vocabulary: set) -> None:
    """Fail loud on a `household` build-step pattern absent from households.csv.

    A build step's matcher iterates the CSV columns, so a pattern that isn't a
    column never appears — it builds nothing with no log at all (the silent
    exact-string foot-gun: typo / stray space / wrong operator). Only build steps
    are checked: `household_excess`/`household_overflow` `target_patterns` are a
    catch-all superset matched against existing households' original_pattern and
    already warn ("matched no households") on a miss, and `household_promotion`
    source_patterns match a runtime allocation_pattern, not the CSV.
    """
    if not vocabulary:
        return  # no data loaded to validate against
    unknown: Dict[str, List[str]] = {}
    for step in steps:
        if step.get('type') != 'household':
            continue
        names = [p.get('pattern') if isinstance(p, dict) else p
                 for p in (step.get('patterns') or [])]
        for name in names:
            if name and name not in vocabulary:
                unknown.setdefault(step.get('name', 'household'), []).append(name)
    if unknown:
        raise HouseholdError(
            f"household build step(s) reference composition patterns absent from "
            f"households.csv: {unknown}. Known patterns: {sorted(vocabulary)}"
        )


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
        stats = household_distributor.round_distributor.distribute_households_round(
            pattern_filter=pattern_list,
            pattern_assumptions=pattern_assumptions,
            max_households=max_households,
            max_household_size=max_household_size,
            allocate_flexible=allocate_flexible,
            refresh_pools=refresh_pools,
            round_name=round_name,
            rule_name=rule_name,
            demotion_rules=demotion_rules,
            interpretation=step_config.get('interpretation')
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
        # Capacity rules owned by this allocation step. The presence of
        # capacity_config.attribute_capacities.column_mappings selects
        # attribute-aware vs. simple allocation downstream.
        'capacity_config': step_config.get('capacity_config', {}),
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
