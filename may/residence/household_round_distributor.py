"""
Handler for distributing households in allocation rounds.

This module contains the core logic for allocating households
during specific allocation rounds (e.g., initial, demotion, balanced).
"""

import logging
from typing import List, Dict, Optional
from may.residence.composition_pattern import CompositionPattern

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

    def _calculate_balanced_distribution(self, geo_unit_code: str, pattern: CompositionPattern,
                                        num_households: int, max_household_size: Optional[int]) -> List[int]:
        """
        Calculate balanced household sizes for flexible patterns.

        This function distributes ALL available people across the specified number of households,
        maximizing allocation while maintaining balance.

        Args:
            geo_unit_code: SGU code
            pattern: Composition pattern
            num_households: Number of households to create (from CSV - must be respected!)
            max_household_size: Maximum size per household

        Returns:
            List of target sizes for each household
        """
        if geo_unit_code not in self.distributor.person_pool_by_geo_unit:
            return [pattern.min_household_size()] * num_households

        pools = self.distributor.person_pool_by_geo_unit[geo_unit_code]

        # Count total available people in ELIGIBLE categories only
        # (categories where the pattern allows at least 1 person)
        total_available = 0
        for cat_idx in range(len(self.distributor.categories)):
            max_count = pattern.get_max_count(cat_idx)
            pool_size = len(pools[cat_idx])
            # Only count if category allows people (max_count is None or > 0)
            if max_count is None or max_count > 0:
                total_available += pool_size
                if pool_size > 0:
                    logger.debug(f"  Category {self.distributor.categories[cat_idx].name}: {pool_size} available (max_count={max_count})")
            else:
                if pool_size > 0:
                    logger.debug(f"  Category {self.distributor.categories[cat_idx].name}: {pool_size} available but EXCLUDED by pattern (max_count={max_count})")

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

        logger.debug(f"Balanced distribution for {num_households} households in {geo_unit_code}:")
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

        # Calculate total households to allocate for progress tracking
        total_households_to_allocate = 0
        for geo_unit_code, compositions in self.distributor.household_counts_by_geo_unit.items():
            for pattern_str, count in compositions.items():
                # Only count if pattern matches filter
                if pattern_set is None or pattern_str in pattern_set:
                    total_households_to_allocate += count

        # Progress tracking
        households_processed = 0
        progress_interval = max(1, total_households_to_allocate // 10)  # Update every 10%

        logger.info(f"Allocating {total_households_to_allocate:,} households...")

        # Iterate through each geo_unit
        for geo_unit_code, compositions in self.distributor.household_counts_by_geo_unit.items():
            # Iterate through each composition type in this geo_unit
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

                # Validate max_household_size against pattern minimum (currently only used by flexible households (step 23))
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
                        geo_unit_code, pattern, count, max_household_size
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
                        household = self.distributor._attempt_with_demotion(geo_unit_code, pattern, max_attempts, max_household_size, allocate_flexible, target_size, rule_name, demotion_rules)
                    else:
                        household, _ = self.distributor._allocate_household_with_rules(geo_unit_code, pattern, max_household_size, allocate_flexible, target_size, rule_name)

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

                        # Household is already added to VenueManager via create_venue()
                        total_created += 1
                        households_created += 1
                    else:
                        logger.debug(f"  Failed to allocate household {i+1}/{count} of type '{pattern_str}' in {geo_unit_code}")

                    # Update progress counter and log at intervals
                    households_processed += 1
                    if households_processed % progress_interval == 0 or households_processed == total_households_to_allocate:
                        percent_complete = (households_processed / total_households_to_allocate) * 100
                        logger.info(f"  Progress: {households_processed}/{total_households_to_allocate} households processed ({percent_complete:.1f}%) - {households_created} created")

                # Break outer loop if limit reached
                if max_households is not None and households_created >= max_households:
                    break

            # Break outer loop if limit reached
            if max_households is not None and households_created >= max_households:
                break

        # Calculate round statistics
        # Get household count from VenueManager
        all_households = self.distributor.venue_manager.get_venues_by_type("household")

        round_stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'households_created': households_created,
            'households_requested': total_requested,
            'households_with_demotion': total_demoted,
            'people_allocated_this_round': len(self.distributor.allocated_people) - round_start_allocated,
            'total_households': len(all_households),
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
        logger.info(f"  Total households so far: {round_stats['total_households']:,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {round_stats['total_people_remaining']:,}")
        logger.info("=" * 60)

        return round_stats

    def _allocate_balanced_distribution(self, pattern: CompositionPattern,
                                       pools, target_size: int):
        """
        Calculate balanced allocation using proportional distribution.

        This method distributes people proportionally across flexible categories
        to reach a target household size while respecting min/max constraints.

        Args:
            pattern: Composition pattern to match
            pools: Person pools by category
            target_size: Target household size

        Returns:
            Tuple of (selections list, failed_category_idx):
            - On success: ([(cat_idx, count), ...], None)
            - On failure: (None, category_idx that caused failure)
        """
        logger.debug(f"\n=== BALANCED DISTRIBUTION MODE ===")
        logger.debug(f"Target size: {target_size}")

        selections = []  # Store planned selections: (cat_idx, count)

        # First pass: allocate exact counts for fixed categories
        fixed_total = 0
        flexible_categories = []

        logger.debug(f"\n--- FIRST PASS: Categorizing fixed vs flexible ---")
        for cat_idx in range(len(self.distributor.categories)):
            min_count = pattern.get_min_count(cat_idx)
            max_count = pattern.get_max_count(cat_idx)
            available = len(pools[cat_idx])

            cat_name = self.distributor.categories[cat_idx].name
            logger.debug(f"\nCategory {cat_idx} ({cat_name}):")
            logger.debug(f"  min_count: {min_count}, max_count: {max_count}, available: {available}")

            # Check minimum availability
            if available < min_count:
                logger.debug(f"  ✗ INSUFFICIENT: Need {min_count}, only {available} available")
                return (None, cat_idx)

            if max_count is not None:
                # Fixed category - allocate exactly
                logger.debug(f"  → FIXED category: allocating exactly {max_count}")
                selections.append((cat_idx, max_count))
                fixed_total += max_count
            else:
                # Flexible category - defer allocation
                logger.debug(f"  → FLEXIBLE category: deferring (min: {min_count}, available: {available})")
                flexible_categories.append((cat_idx, min_count, available))

        logger.debug(f"\n--- FIRST PASS COMPLETE ---")
        logger.debug(f"Fixed total: {fixed_total}")
        logger.debug(f"Flexible categories: {len(flexible_categories)}")

        # Second pass: distribute remaining capacity proportionally across flexible categories
        remaining_capacity = target_size - fixed_total
        logger.debug(f"\n--- SECOND PASS: Proportional allocation ---")
        logger.debug(f"Remaining capacity: {remaining_capacity} (target: {target_size} - fixed: {fixed_total})")

        if remaining_capacity < 0:
            # Can't meet target - fixed categories already exceed it
            logger.debug(f"✗ ERROR: Fixed categories ({fixed_total}) exceed target size ({target_size})")
            return (None, None)

        # Calculate proportional allocation based on availability
        total_available = sum(avail for _, _, avail in flexible_categories)
        logger.debug(f"Total available in flexible categories: {total_available}")

        # Track allocations with their proportions for remainder distribution
        flexible_allocations = []

        for cat_idx, min_count, available in flexible_categories:
            cat_name = self.distributor.categories[cat_idx].name
            logger.debug(f"\nCategory {cat_idx} ({cat_name}):")
            logger.debug(f"  min: {min_count}, available: {available}")

            if total_available > 0:
                # Proportional share of remaining capacity
                proportion = available / total_available
                allocated = int(remaining_capacity * proportion)
                logger.debug(f"  proportion: {proportion:.3f} ({available}/{total_available})")
                logger.debug(f"  raw allocation: {allocated} ({remaining_capacity} * {proportion:.3f})")

                # Ensure we meet minimum and don't exceed available
                allocated = max(min_count, min(allocated, available))
                logger.debug(f"  initial allocation: {allocated} (after min/max constraints)")
            else:
                proportion = 0
                allocated = min_count
                logger.debug(f"  total_available=0, using min_count: {allocated}")

            flexible_allocations.append((cat_idx, allocated, available, proportion))

        # Calculate shortfall and distribute remainder
        current_total = sum(alloc for _, alloc, _, _ in flexible_allocations)
        shortfall = remaining_capacity - current_total
        logger.debug(f"\nShortfall check: allocated {current_total}, need {remaining_capacity}, shortfall: {shortfall}")

        if shortfall > 0:
            logger.debug(f"Distributing {shortfall} remaining slots...")
            # Sort by proportion (highest first) to prioritize categories with more availability
            flexible_allocations.sort(key=lambda x: x[3], reverse=True)

            for i, (cat_idx, allocated, available, proportion) in enumerate(flexible_allocations):
                if shortfall == 0:
                    break

                # How many more can this category take?
                can_take = available - allocated
                if can_take > 0:
                    give = min(can_take, shortfall)
                    cat_name = self.distributor.categories[cat_idx].name
                    logger.debug(f"  {cat_name}: giving {give} more (was {allocated}, now {allocated + give})")
                    flexible_allocations[i] = (cat_idx, allocated + give, available, proportion)
                    shortfall -= give

        # Add all flexible allocations to selections
        for cat_idx, allocated, _, _ in flexible_allocations:
            selections.append((cat_idx, allocated))

        # Sort selections by category index to maintain order
        selections.sort(key=lambda x: x[0])

        total_selected = sum(count for _, count in selections)
        logger.debug(f"\n--- SECOND PASS COMPLETE ---")
        logger.debug(f"Total selected: {total_selected}")
        logger.debug(f"Selections: {selections}")

        return (selections, None)
