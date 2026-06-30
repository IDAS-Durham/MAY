"""
Handler for promoting households and allocating remaining people.

This module contains logic for:
- Promoting households to accept more people
- Applying relationship rules during promotion
"""

import logging
import numpy as np
from typing import List, Optional, Dict
from itertools import islice
from may.residence.composition_pattern import CompositionPattern

logger = logging.getLogger("household")


class HouseholdPromoter:
    """Handles household promotion and final people allocation."""

    def __init__(self, household_distributor):
        """
        Initialize the promoter.

        Args:
            household_distributor: Reference to parent HouseholdDistributor
        """
        self.distributor = household_distributor
        self._households_by_geo_unit = None
        self._households_by_pattern = None

    def _adding_person_satisfies_rules(self, household, category_name: str,
                                       validation_rules: List[Dict]) -> bool:
        """
        Check whether adding one person of `category_name` to `household` would
        violate any validation rule.

        Unlike validate_against_rules (which works on pattern *minimums*), this
        evaluates rules against the **actual current composition** of the household
        *after* the hypothetical addition.  That catches cases like adding a Kid to
        an elderly-only household where Adults == 0 in reality even though the
        promoted pattern says '>=0' for Adults.

        Args:
            household: The household venue being considered.
            category_name: The category of the person about to be added.
            validation_rules: List of rule dicts from the promotion config.

        Returns:
            True if adding the person is safe, False if it would violate a rule.
        """
        if not validation_rules:
            return True

        age_categories = household.properties.get('_age_categories', self.distributor.categories)
        composition = household.get_composition(age_categories)

        # Simulate adding one person of this category
        simulated = dict(composition)
        simulated[category_name] = simulated.get(category_name, 0) + 1

        cat_map = self.distributor.category_name_to_idx

        for rule in validation_rules:
            condition = rule.get('condition', {})
            requirement = rule.get('requirement', {})
            rule_name = rule.get('name', 'Unnamed rule')

            cond_category = condition.get('category')
            if cond_category not in cat_map:
                continue

            cond_count = simulated.get(cond_category, 0)
            cond_operator = condition.get('operator')
            cond_value = condition.get('value')

            # Use the existing operator evaluator from CompositionPattern
            from may.residence.composition_pattern import CompositionPattern
            cp = CompositionPattern.from_string("0")  # dummy — just for _evaluate_operator
            if not cp._evaluate_operator(cond_count, cond_operator, cond_value):
                continue  # condition not triggered

            # Condition is met — check requirement(s)
            req_list = requirement if isinstance(requirement, list) else [requirement]
            any_req_met = False
            for req in req_list:
                req_category = req.get('category')
                if req_category not in cat_map:
                    continue
                req_count = simulated.get(req_category, 0)
                req_operator = req.get('operator')
                req_value = req.get('value')
                if cp._evaluate_operator(req_count, req_operator, req_value):
                    any_req_met = True
                    break

            if not any_req_met:
                logger.debug(
                    f"    Skipping add: adding {category_name} to household "
                    f"{household.id} would violate rule '{rule_name}'. "
                    f"Simulated composition: {simulated}"
                )
                return False

        return True

    def _get_households_by_geo_unit(self) -> Dict[str, List]:
        """Index households by geo_unit if not already done."""
        if self._households_by_geo_unit is None:
            self._households_by_geo_unit = {}
            all_households = self.distributor.venue_manager.get_venues_by_type("household")
            for hh in all_households:
                geo_code = hh.geographical_unit.name
                if geo_code not in self._households_by_geo_unit:
                    self._households_by_geo_unit[geo_code] = []
                self._households_by_geo_unit[geo_code].append(hh)
        return self._households_by_geo_unit

    def _get_households_by_pattern(self) -> Dict[str, List]:
        """Index households by actual_pattern if not already done."""
        if self._households_by_pattern is None:
            self._households_by_pattern = {}
            all_households = self.distributor.venue_manager.get_venues_by_type("household")
            for hh in all_households:
                pattern = hh.properties.get('allocation_pattern', '')
                if pattern not in self._households_by_pattern:
                    self._households_by_pattern[pattern] = []
                self._households_by_pattern[pattern].append(hh)
        return self._households_by_pattern

    def reset_indexes(self):
        """Reset the cached indexes."""
        self._households_by_geo_unit = None
        self._households_by_pattern = None

    def promote_and_allocate(self,
                            target_categories: List[str],
                            refresh_pools: bool = False,
                            round_name: Optional[str] = None):
        """
        Promote existing households to accommodate remaining people.

        This method:
        1. Identifies geo_units with remaining people in target categories
        2. Promotes household patterns in those geo_units (0 -> >=0, 1 -> >=1, etc.)
        3. Allocates ALL remaining people to the promoted households

        Args:
            target_categories: List of category names to allocate (e.g., ["Young Adults", "Adults"])
            refresh_pools: If True, refresh person pools
            round_name: Optional name for this round (for logging)

        Returns:
            dict: Statistics about this promotion allocation
        """
        round_label = self.distributor._log_round_start(round_name, "Promotion Allocation Round")
        logger.info(f"Target categories: {target_categories}")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self.distributor._prepare_person_pools(refresh=True)

        # The presence of a household_promotion step is the switch — promotion
        # runs where the strategy invokes it (no separate global enable flag).
        promotion_config = self.distributor.config.get('promotion', {})

        # Get priority order
        priority_config = promotion_config.get('priority', {})
        promotion_priority = []
        for cat_idx, cat in enumerate(self.distributor.categories):
            priority = priority_config.get(cat.name, 999)
            promotion_priority.append((priority, cat_idx))
        promotion_priority.sort()  # Sort by priority
        priority_order = [idx for _, idx in promotion_priority]

        # Get validation rules
        validation_rules = promotion_config.get('validation_rules', [])
        max_attempts = promotion_config.get('max_attempts', 4)

        # Track statistics
        people_added = 0
        households_promoted_count = 0
        promoted_households = set()

        # Process each target category
        for category_name in target_categories:
            cat_idx = self.distributor._validate_category_index(category_name, log_level="warning")
            if cat_idx is None:
                logger.info("Skipping category")
                continue

            logger.info(f"Processing category: {category_name}")

            # Find geo_units with people in this category
            for geo_unit_code, pools in self.distributor.person_pool_by_geo_unit.items():
                available_people = pools[cat_idx]

                if not available_people:
                    continue

                logger.debug(f"  geo_unit {geo_unit_code}: {len(available_people)} {category_name} available")

                # Find households in this geo_unit using index
                geo_unit_households = self._get_households_by_geo_unit().get(geo_unit_code, [])

                if not geo_unit_households:
                    logger.debug(f"    No households in geo_unit {geo_unit_code}")
                    continue

                # Try to promote and allocate to each household
                np.random.shuffle(geo_unit_households)  # For fairness

                for household in geo_unit_households:
                    if not available_people:
                        break

                    # Check if this household can accommodate this category
                    pattern_str = household.properties.get('allocation_pattern', '')
                    pattern = CompositionPattern.from_string(pattern_str)

                    # Try promotion if needed
                    current_pattern = pattern
                    promoted = False

                    for attempt in range(max_attempts + 1):
                        # Can we add someone from this category?
                        min_count = current_pattern.get_min_count(cat_idx)
                        age_categories = household.properties.get('_age_categories', self.distributor.categories)
                        current_count = household.get_composition(age_categories).get(category_name, 0)

                        if current_count >= min_count:
                            # Already meets minimum, check if flexible
                            max_count = current_pattern.get_max_count(cat_idx)
                            if max_count is None:  # Flexible (>=)
                                # Can add!
                                break
                            elif current_count < max_count:  # Still room
                                break

                        # Need to promote
                        if attempt < max_attempts:
                            new_pattern = current_pattern.promote_once(priority_order)
                            if new_pattern is None:
                                # Can't promote further
                                break

                            # Validate
                            if validation_rules and not new_pattern.validate_against_rules(
                                validation_rules, self.distributor.category_name_to_idx
                            ):
                                # Promoted pattern violates rules
                                break

                            current_pattern = new_pattern
                            promoted = True
                        else:
                            # Max attempts reached
                            break

                    # Update household pattern if promoted
                    if promoted and household.id not in promoted_households:
                        household.properties['allocation_pattern'] = current_pattern.to_string()
                        households_promoted_count += 1
                        promoted_households.add(household.id)
                        logger.debug(f"    Promoted household {household.id}: {pattern_str} -> {current_pattern.to_string()}")

                    # Now try to add people
                    max_count = current_pattern.get_max_count(cat_idx)
                    age_categories = household.properties.get('_age_categories', self.distributor.categories)
                    current_count = household.get_composition(age_categories).get(category_name, 0)

                    if not available_people:
                        continue

                    # Create a temporary list of IDs from the pool (we use current state of dict)
                    # We can't use deque for complex dictionary removals, so we just take from the front
                    added_to_this = 0
                    
                    # Determine how many we can add
                    if max_count is None:  # Flexible
                        # Add as many as possible (greedy)
                        can_add = len(available_people)
                    else:  # Fixed
                        can_add = max(0, max_count - current_count)

                    if can_add > 0:
                        # Guard: check that adding this category to this household
                        # does not violate any validation rule against the *actual*
                        # composition (not just the promoted pattern).
                        if not self._adding_person_satisfies_rules(
                            household, category_name, validation_rules
                        ):
                            continue

                        # Extract IDs to remove from the front of the dictionary
                        ids_to_take = list(islice(available_people.keys(), can_add))
                        
                        for pid in ids_to_take:
                            person = available_people.pop(pid)
                            # Key by the person's actual age category; the keyless
                            # fallback would dump them into the household's first
                            # subset and mislabel them (see add_to_subset).
                            household.add_to_subset(
                                person,
                                subset_key=self.distributor._get_person_category_name(person),
                            )
                            self.distributor.allocated_people.add(person.id)
                            added_to_this += 1
                            people_added += 1

                    if added_to_this > 0:
                        logger.debug(f"    Added {added_to_this} {category_name} to household {household.id}")

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'people_added': people_added,
            'households_promoted': households_promoted_count,
            'total_people_allocated': len(self.distributor.allocated_people),
            'total_people_remaining': len(self.distributor.population.get_all_people()) - len(self.distributor.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.distributor.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households promoted: {households_promoted_count:,}")
        logger.info(f"  People added: {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.distributor.categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats

    def promote_with_rules(self,
                          promotion_rules: List[Dict],
                          refresh_pools: bool = False,
                          round_name: Optional[str] = None):
        """
        Promote households according to specific rules.

        Each rule specifies:
          - source_pattern: Original pattern to match (e.g., "0 0 2 0")
          - target_pattern: Promoted pattern (e.g., "0 >=0 2 0")
          - accept_categories: Which categories can be added
          - max_to_add: Maximum people to add to this household

        Args:
            promotion_rules: List of promotion rule dicts
            refresh_pools: If True, refresh person pools
            round_name: Optional name for this round

        Returns:
            dict: Statistics about this promotion allocation
        """
        round_label = self.distributor._log_round_start(round_name, "Rule-Based Promotion Round")
        logger.info(f"Number of promotion rules: {len(promotion_rules)}")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self.distributor._prepare_person_pools(refresh=True)

        # Track statistics
        people_added = 0
        households_promoted_count = 0
        promoted_households = set()

        # Progress tracking
        total_rules = len(promotion_rules)

        # Process each rule
        for rule_idx, rule in enumerate(promotion_rules, 1):
            source_pattern = rule.get('source_pattern')
            target_pattern_str = rule.get('target_pattern')
            accept_categories = rule.get('accept_categories', [])
            max_to_add = rule.get('max_to_add')

            if not source_pattern or not target_pattern_str:
                logger.warning(f"Rule {rule_idx}: Missing source_pattern or target_pattern, skipping")
                continue

            # Parse target pattern to understand constraints
            target_pattern = CompositionPattern.from_string(target_pattern_str)

            logger.info(f"Rule {rule_idx}: {source_pattern} → {target_pattern_str} (categories: {accept_categories})")

            # Find households matching source pattern using index
            all_households_in_pattern = self._get_households_by_pattern().get(source_pattern, [])

            # Track progress for this rule
            rule_start_promoted = households_promoted_count
            rule_start_people_added = people_added
            households_processed = 0
            total_households = len(all_households_in_pattern)
            progress_interval = max(1, total_households // 10)  # Update every 10%

            for household in all_households_in_pattern:

                geo_unit_code = household.geographical_unit.name

                if geo_unit_code not in self.distributor.person_pool_by_geo_unit:
                    continue

                pools = self.distributor.person_pool_by_geo_unit[geo_unit_code]

                # Try to add people from each accepted category
                added_to_this_household = 0

                for category_name in accept_categories:
                    cat_idx = self.distributor._validate_category_index(category_name, log_level=None)
                    if cat_idx is None:
                        continue

                    available_people = pools[cat_idx]
                    if not available_people:
                        continue

                    # Get current count in this category
                    age_categories = household.properties.get('_age_categories', self.distributor.categories)
                    current_composition = household.get_composition(age_categories)
                    current_count = current_composition.get(category_name, 0)

                    # Get max allowed from target pattern
                    max_allowed = target_pattern.get_max_count(cat_idx)

                    # Determine how many we can add to this category
                    if max_allowed is not None:
                        # Exact or fixed requirement - can only add up to max_allowed
                        category_can_add = max(0, max_allowed - current_count)
                    else:
                        # Flexible (>=) requirement - no upper limit for this category
                        category_can_add = len(available_people)

                    # Also respect max_to_add limit
                    if max_to_add is not None:
                        category_can_add = min(category_can_add, max_to_add - added_to_this_household)

                    # Also respect available people
                    category_can_add = min(category_can_add, len(available_people))

                    if category_can_add <= 0:
                        continue

                    # Promote household if this is the first person we're adding
                    if added_to_this_household == 0 and household.id not in promoted_households:
                        household.properties['allocation_pattern'] = target_pattern_str
                        households_promoted_count += 1
                        promoted_households.add(household.id)
                        logger.debug(f"  Promoted household {household.id}: {source_pattern} → {target_pattern_str}")

                    if category_can_add > 0:
                        # Extract IDs to remove from the front of the dictionary
                        # Dict preserves order, so this acts like a queue
                        ids_to_take = list(islice(available_people.keys(), category_can_add))
                        
                        for pid in ids_to_take:
                            if max_to_add is not None and added_to_this_household >= max_to_add:
                                break
                            
                            person = available_people.pop(pid)
                            # Key by the person's actual age category; the keyless
                            # fallback would dump them into the household's first
                            # subset and mislabel them (see add_to_subset).
                            household.add_to_subset(
                                person,
                                subset_key=self.distributor._get_person_category_name(person),
                            )
                            self.distributor.allocated_people.add(person.id)
                            added_to_this_household += 1
                            people_added += 1

                if added_to_this_household > 0:
                    logger.debug(f"  Added {added_to_this_household} people to household {household.id}")

                # Log progress at intervals
                if households_processed % progress_interval == 0 or households_processed == total_households:
                    percent_complete = (households_processed / total_households) * 100
                    rule_households_promoted = households_promoted_count - rule_start_promoted
                    rule_people_added = people_added - rule_start_people_added
                    logger.info(f"  Rule {rule_idx} progress: {households_processed}/{total_households} households checked ({percent_complete:.1f}%) - {rule_households_promoted} promoted, {rule_people_added} people added")

                households_processed += 1

            # Log rule completion summary
            rule_households_promoted = households_promoted_count - rule_start_promoted
            rule_people_added = people_added - rule_start_people_added
            if rule_households_promoted > 0 or rule_people_added > 0:
                logger.info(f"  Rule {rule_idx} complete: {rule_households_promoted} households promoted, {rule_people_added} people added")
            
            # Reset pattern index so the next rule sees updated patterns
            if rule_households_promoted > 0:
                self._households_by_pattern = None

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'people_added': people_added,
            'households_promoted': households_promoted_count,
            'total_people_allocated': len(self.distributor.allocated_people),
            'total_people_remaining': len(self.distributor.population.get_all_people()) - len(self.distributor.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.distributor.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households promoted: {households_promoted_count:,}")
        logger.info(f"  People added: {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.distributor.categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats
