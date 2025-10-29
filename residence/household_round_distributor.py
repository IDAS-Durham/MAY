"""
Handler for distributing households in allocation rounds.

This module contains the core logic for allocating households
during specific allocation rounds (e.g., initial, demotion, balanced).
"""

import logging
from typing import List, Dict, Optional, Tuple
from residence.composition_pattern import CompositionPattern
from residence.models import Household

logger = logging.getLogger("household")


class HouseholdRoundDistributor:
    """Handles household distribution during allocation rounds."""

    def __init__(self, household_distributor):
        """
        Initialize the round distributor.

        Args:
            household_distributor: Reference to parent HouseholdDistributor
        """
        self.distributor = household_distributor

    def _calculate_balanced_distribution(self, area_code: str, pattern: CompositionPattern,
                                        num_households: int, max_household_size: Optional[int]) -> List[int]:
        """
        Calculate balanced household sizes for flexible patterns.

        This function distributes ALL available people across the specified number of households,
        maximizing allocation while maintaining balance.

        Args:
            area_code: SGU code
            pattern: Composition pattern
            num_households: Number of households to create (from CSV - must be respected!)
            max_household_size: Maximum size per household

        Returns:
            List of target sizes for each household
        """
        if area_code not in self.distributor.person_pool_by_area:
            return [pattern.min_household_size()] * num_households

        pools = self.distributor.person_pool_by_area[area_code]

        # Count total available people in ELIGIBLE categories only
        # (categories where the pattern allows at least 1 person)
        total_available = 0
        for cat_idx in range(len(self.distributor.age_categories)):
            max_count = pattern.get_max_count(cat_idx)
            pool_size = len(pools[cat_idx])
            # Only count if category allows people (max_count is None or > 0)
            if max_count is None or max_count > 0:
                total_available += pool_size
                if pool_size > 0:
                    logger.debug(f"  Category {self.distributor.age_categories[cat_idx].name}: {pool_size} available (max_count={max_count})")
            else:
                if pool_size > 0:
                    logger.debug(f"  Category {self.distributor.age_categories[cat_idx].name}: {pool_size} available but EXCLUDED by pattern (max_count={max_count})")

        # Strategy: Fill households to capacity to allocate as many people as possible
        if max_household_size:
            # Fill households close to max_household_size
            ideal_total = min(total_available, max_household_size * num_households)
        else:
            # No size limit - distribute all available people
            ideal_total = total_available

        # Distribute total people as evenly as possible across num_households
        base_size = ideal_total // num_households
        remainder = ideal_total % num_households

        # Create balanced sizes: some households get base_size, some get base_size+1
        sizes = [base_size] * num_households
        for i in range(remainder):
            sizes[i] += 1

        # Ensure we don't exceed max_household_size and meet minimum requirements
        min_size = pattern.min_household_size()
        if max_household_size:
            sizes = [max(min_size, min(s, max_household_size)) for s in sizes]
        else:
            sizes = [max(min_size, s) for s in sizes]

        logger.debug(f"Balanced distribution for {num_households} households in {area_code}:")
        logger.debug(f"  Total available: {total_available}, Target sizes: {sizes[:10]}{'...' if len(sizes) > 10 else ''}")
        return sizes

    def distribute_households_round(self,
                                   pattern_filter: Optional[List[str]] = None,
                                   pattern_assumptions: Optional[Dict[str, str]] = None,
                                   max_households: Optional[int] = None,
                                   max_household_size: Optional[int] = None,
                                   allocate_flexible: bool = False,
                                   refresh_pools: bool = False,
                                   round_name: Optional[str] = None,
                                   rule_name: Optional[str] = None,
                                   demotion_rules: Optional[Dict[str, str]] = None):
        """
        Distribute households in a single round with optional filtering.

        This method allows for multi-round allocation where you can:
        1. Allocate specific household types in each round
        2. Limit the number of households created
        3. Refresh pools to include only remaining unallocated people
        4. Perform other operations between rounds
        5. Use pattern assumptions to override patterns during allocation

        Args:
            pattern_filter: List of patterns to allocate in this round.
                          If None, allocate all patterns.
                          Example: ["0 0 2 0", "0 0 0 2", ">=2 >=0 2 0"]
            pattern_assumptions: Dict mapping pattern strings to their assumed patterns.
                               When a pattern has an assumption, the assumption is used
                               for allocation instead of the original pattern.
                               Example: {"0 >=0 0 0": "0 2 0 0"}
            max_households: Maximum number of households to create in this round.
                          If None, no limit.
            max_household_size: Maximum size for any household. If None, no limit.
            allocate_flexible: If True, use BALANCED DISTRIBUTION for flexible (>=) categories.
                             Strategy:
                             1. Respects the exact number of households from CSV data
                             2. Distributes ALL available people across those households
                             3. Allocates proportionally across flexible categories (e.g., mix of
                                Young Adults, Adults, Old Adults instead of all one type)
                             4. Fills households close to max_household_size to minimize leftovers
                             If False, take only minimum required for flexible categories.
            refresh_pools: If True, refresh person pools to exclude already allocated people.
                         Use this when coming back after other allocation operations.
            round_name: Optional name for this round (for logging)
            rule_name: Optional relationship rule name to apply (overrides auto-matching).
                      Example: "Two-adult family with kids"
            demotion_rules: Optional dict mapping demoted pattern strings to rule names.
                          When a pattern is demoted to match a key in this dict,
                          switch to the corresponding rule.
                          Example: {"0 >=1 1 0": "Single-adult family with young adults"}

        Returns:
            dict: Statistics about this round's allocation
        """
        round_label = self.distributor._log_round_start(round_name, "Round")

        # Prepare or refresh pools
        self.distributor._prepare_person_pools(refresh=refresh_pools)

        # Get config
        demotion_enabled = self.distributor.config['demotion']['enabled']
        max_attempts = self.distributor.config['demotion']['max_attempts']

        # Track round statistics
        round_start_allocated = len(self.distributor.allocated_people)
        total_requested = 0
        total_created = 0
        total_demoted = 0
        households_created = 0

        # Convert pattern filter to set for fast lookup
        pattern_set = set(pattern_filter) if pattern_filter else None

        # Default to empty dict if not provided
        if pattern_assumptions is None:
            pattern_assumptions = {}
        if demotion_rules is None:
            demotion_rules = {}

        # Iterate through each area
        for area_code, compositions in self.distributor.household_counts_by_area.items():
            # Iterate through each composition type in this area
            for pattern_str, count in compositions.items():
                # Check if this pattern should be allocated in this round
                if pattern_set is not None and pattern_str not in pattern_set:
                    continue

                total_requested += count

                # Check if there's an assumption for this pattern
                actual_pattern_str = pattern_assumptions.get(pattern_str, pattern_str)

                if actual_pattern_str != pattern_str:
                    logger.debug(f"Using assumption for pattern '{pattern_str}': '{actual_pattern_str}'")

                # Create pattern from assumption, but preserve census pattern for rule matching
                pattern = CompositionPattern.from_string(actual_pattern_str)
                # Store the census pattern so rules can match against it
                if actual_pattern_str != pattern_str:
                    pattern.census_pattern = pattern_str

                # Validate max_household_size against pattern minimum
                if max_household_size is not None:
                    pattern_min_size = pattern.min_household_size()
                    if max_household_size < pattern_min_size:
                        logger.error(f"ERROR: max_household_size ({max_household_size}) is less than pattern '{actual_pattern_str}' minimum size ({pattern_min_size})")
                        logger.error(f"  Pattern: {pattern_str}")
                        if actual_pattern_str != pattern_str:
                            logger.error(f"  Assumption: {actual_pattern_str}")
                        raise ValueError(f"max_household_size ({max_household_size}) cannot be less than pattern minimum size ({pattern_min_size}) for pattern '{actual_pattern_str}'")

                # PRE-CALCULATE balanced distribution if allocate_flexible is True
                balanced_sizes = None
                if allocate_flexible:
                    balanced_sizes = self._calculate_balanced_distribution(
                        area_code, pattern, count, max_household_size
                    )

                # Try to create 'count' households of this type
                for i in range(count):
                    # Check if we've hit the household limit
                    if max_households is not None and households_created >= max_households:
                        logger.info(f"Reached maximum household limit ({max_households}) for {round_label}")
                        break

                    # Get balanced size for this household if using balanced distribution
                    target_size = balanced_sizes[i] if balanced_sizes and i < len(balanced_sizes) else None

                    if demotion_enabled:
                        household = self.distributor._attempt_with_demotion(area_code, pattern, max_attempts, max_household_size, allocate_flexible, target_size, rule_name, demotion_rules)
                    else:
                        household, _ = self.distributor._allocate_household_with_rules(area_code, pattern, max_household_size, allocate_flexible, target_size, rule_name)

                    if household:
                        # Get the actual pattern that was used (may have been demoted)
                        actual_pattern_used = household.properties.get('actual_pattern')

                        # DEBUG: Log what we're comparing

                        # Check if we used demotion
                        # Compare the actual pattern used vs the initial pattern requested (assumption)
                        if actual_pattern_used != actual_pattern_str:
                            total_demoted += 1
                            logger.debug(f"DEBUG -> DEMOTION DETECTED: {actual_pattern_used} != {actual_pattern_str}")

                        # Override original_pattern with CSV pattern (not assumption)
                        # This ensures excess allocation can target by CSV pattern
                        if actual_pattern_str != pattern_str:
                            household.properties['original_pattern'] = pattern_str

                        self.distributor.households.append(household)
                        total_created += 1
                        households_created += 1
                    else:
                        logger.debug(f"  Failed to allocate household {i+1}/{count} of type '{pattern_str}' in {area_code}")

                # Break outer loop if limit reached
                if max_households is not None and households_created >= max_households:
                    break

            # Break outer loop if limit reached
            if max_households is not None and households_created >= max_households:
                break

        # Calculate round statistics
        round_stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'households_created': households_created,
            'households_requested': total_requested,
            'households_with_demotion': total_demoted,
            'people_allocated_this_round': len(self.distributor.allocated_people) - round_start_allocated,
            'total_households': len(self.distributor.households),
            'total_people_allocated': len(self.distributor.allocated_people),
            'total_people_remaining': len(self.distributor.population.get_all_people()) - len(self.distributor.allocated_people)
        }

        # Log summary (with additional round-specific info first)
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Requested households (filtered): {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
        if total_demoted > 0:
            logger.info(f"  Households using demotion: {total_demoted:,}")
        logger.info(f"  People allocated this round: {round_stats['people_allocated_this_round']:,}")
        logger.info(f"  Total households so far: {len(self.distributor.households):,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {round_stats['total_people_remaining']:,}")
        logger.info("=" * 60)

        return round_stats
