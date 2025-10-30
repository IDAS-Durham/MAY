"""
Handler for allocating excess and overflow people to households.

This module contains logic for:
- Allocating unassigned people to existing households (excess allocation)
- Handling overflow allocation when excess allocation leaves people unassigned
"""

import logging
import numpy as np
from typing import List, Optional, Dict
from population.person import Person
from residence.models import Household

logger = logging.getLogger("household")


class HouseholdExcessHandler:
    """Handles excess and overflow people allocation to households."""

    def __init__(self, household_distributor):
        """
        Initialize the excess handler.

        Args:
            household_distributor: Reference to parent HouseholdDistributor
        """
        self.distributor = household_distributor

    def allocate_excess_to_households(self,
                                      target_patterns: List[str],
                                      add_category: str,
                                      constraints: Optional[List[Dict]] = None,
                                      max_per_household: Optional[int] = None,
                                      add_distribution: Optional[Dict] = None,
                                      refresh_pools: bool = False,
                                      round_name: Optional[str] = None,
                                      rule_name: Optional[str] = None):
        """
        Allocate excess people to existing households created in previous steps.

        This method allows you to add people to households that were created earlier,
        respecting flexible patterns and configurable constraints.

        Args:
            target_patterns: List of original patterns to target for adding people.
                           Only households created with these patterns will be modified.
                           Example: [">=2 >=0 2 0", "1 >=0 2 0"]
            add_category: Name of age category to add (e.g., "Young Adults", "Kids")
            constraints: List of constraint dicts defining limits.
                        Example: [{"category_sum": ["Kids", "Young Adults"], "max": 4}]
            max_per_household: Maximum number of people to add per household (None = no limit)
            add_distribution: Distribution config for how many to add per household.
                            Example: {"type": "weighted", "probabilities": {0: 0.3, 1: 0.5, 2: 0.2}}
                            Or: {"type": "poisson", "mean": 1.2}
                            Or: {"type": "normal", "mean": 1.5, "std": 0.7}
            refresh_pools: If True, refresh person pools to get latest unallocated people
            round_name: Optional name for this round (for logging)
            rule_name: Optional relationship rule name to validate people against existing household members

        Returns:
            dict: Statistics about this excess allocation
        """
        round_label = self.distributor._log_round_start(round_name, "Excess Allocation Round")
        logger.info(f"Target patterns: {target_patterns}")
        logger.info(f"Adding category: {add_category}")
        logger.info(f"Constraints: {constraints}")
        if rule_name:
            logger.info(f"Using relationship rule: '{rule_name}'")
        logger.info("")

        # Get rule if specified
        rule = None
        if rule_name:
            rule = self.distributor.relationship_rules.get_rule_by_name(rule_name)
            if not rule:
                logger.error(f"Unknown relationship rule '{rule_name}'")
                return {
                    'round_name': round_label,
                    'people_added': 0,
                    'households_modified': 0,
                    'error': f"Unknown relationship rule '{rule_name}'"
                }

        # Refresh pools if requested
        if refresh_pools:
            self.distributor._prepare_person_pools(refresh=True)

        # Find category index for the category to add
        add_cat_idx = self.distributor._validate_category_index(add_category)
        if add_cat_idx is None:
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0,
                'error': f"Unknown category '{add_category}'"
            }

        # Filter households by target patterns
        target_households = self.distributor._filter_households_by_patterns(target_patterns)
        logger.info(f"Found {len(target_households)} households matching target patterns")

        if not target_households:
            logger.warning("No households found matching target patterns")
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0
            }

        # Shuffle households for fairness
        np.random.shuffle(target_households)

        # Track statistics
        people_added = 0
        households_modified = 0

        # Iterate through target households and try to add people
        for household in target_households:
            geo_unit_code = household.geographical_unit.name

            # Get person pool for this geo_unit
            if geo_unit_code not in self.distributor.person_pool_by_geo_unit:
                continue

            pools = self.distributor.person_pool_by_geo_unit[geo_unit_code]
            available_people = pools[add_cat_idx]

            if not available_people:
                continue

            # Determine target number to add for this household
            if add_distribution:
                target_to_add = self.distributor._sample_from_distribution(add_distribution)
            else:
                # Default: fill to max allowed
                target_to_add = max_per_household if max_per_household is not None else float('inf')

            # Apply max_per_household limit
            if max_per_household is not None:
                target_to_add = min(target_to_add, max_per_household)

            # Try to add the target number of people
            added_to_this_household = 0

            # Handle infinity case (fill to max) vs finite target
            if target_to_add == float('inf'):
                # Fill to capacity (until pool empty or constraints violated)
                while available_people:
                    # Check if adding this person would violate constraints
                    if constraints and not self.distributor._check_constraints_if_added(
                        household, add_category, constraints
                    ):
                        # Can't add more to this household due to constraints
                        break

                    # Select person (with or without relationship rule validation)
                    if rule:
                        # Use relationship rules to validate against existing household members
                        person = self._select_person_for_excess_with_rule(
                            household, available_people, add_category, rule
                        )
                        if not person:
                            # No valid person found for this household
                            break
                    else:
                        # No rule - take first available person
                        person = available_people[0]  # Always take first (already shuffled)

                    # Add the person
                    self.distributor._allocate_person_to_household(household, person, available_people)

                    added_to_this_household += 1
                    people_added += 1
            else:
                # Finite target - add up to target_to_add people
                for _ in range(int(target_to_add)):
                    # Check if we have people available
                    if not available_people:
                        break

                    # Check if adding this person would violate constraints
                    if constraints and not self.distributor._check_constraints_if_added(
                        household, add_category, constraints
                    ):
                        # Can't add more to this household due to constraints
                        break

                    # Select person (with or without relationship rule validation)
                    if rule:
                        # Use relationship rules to validate against existing household members
                        person = self._select_person_for_excess_with_rule(
                            household, available_people, add_category, rule
                        )
                        if not person:
                            # No valid person found for this household
                            break
                    else:
                        # No rule - take first available person
                        person = available_people[0]  # Always take first (already shuffled)

                    # Add the person
                    self.distributor._allocate_person_to_household(household, person, available_people)

                    added_to_this_household += 1
                    people_added += 1

            if added_to_this_household > 0:
                households_modified += 1
                logger.debug(f"Added {added_to_this_household} {add_category} to household {household.id}")

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'people_added': people_added,
            'households_modified': households_modified,
            'target_households_count': len(target_households),
            'total_people_allocated': len(self.distributor.allocated_people),
            'total_people_remaining': len(self.distributor.population.get_all_people()) - len(self.distributor.allocated_people)
        }

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Target households: {len(target_households):,}")
        logger.info(f"  Households modified: {households_modified:,}")
        logger.info(f"  People added: {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")

        # Show remaining by category
        remaining_by_category = self.distributor.get_available_people_by_category()
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.distributor.age_categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats

    def allocate_overflow_to_households(self,
                                       target_patterns: List[str],
                                       add_category: str,
                                       pattern_bias: Optional[Dict[str, float]] = None,
                                       refresh_pools: bool = False,
                                       round_name: Optional[str] = None):
        """
        Allocate ALL remaining people from a category to existing households,
        IGNORING max household size constraints (overflow mode).

        This is a "desperation round" that distributes remaining people balancedly
        across eligible households, optionally biasing certain patterns.

        Args:
            target_patterns: List of patterns to target for adding people.
                           Example: ["2 >=0 2 0", "0 >=0 0 0"]
            add_category: Name of age category to add (e.g., "Young Adults")
            pattern_bias: Dict mapping patterns to bias weights.
                         Higher weight = more likely to receive people.
                         Example: {"0 >=0 0 0": 2.0, "2 >=0 2 0": 1.0}
                         Households with pattern "0 >=0 0 0" get 2x allocation
            refresh_pools: If True, refresh person pools
            round_name: Optional name for this round (for logging)

        Returns:
            dict: Statistics about this overflow allocation
        """
        round_label = self.distributor._log_round_start(round_name, "Overflow Allocation Round")
        logger.info(f"Target patterns: {target_patterns}")
        logger.info(f"Adding category: {add_category}")
        logger.info(f"Pattern bias: {pattern_bias}")
        logger.info("WARNING: This step IGNORES max household size constraints!")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self.distributor._prepare_person_pools(refresh=True)

        # Find category index
        add_cat_idx = self.distributor._validate_category_index(add_category)
        if add_cat_idx is None:
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0,
                'error': f"Unknown category '{add_category}'"
            }

        # Group households by geo_unit and pattern
        filtered_households = self.distributor._filter_households_by_patterns(target_patterns)
        households_by_geo_unit_pattern = {}
        for household in filtered_households:
            geo_unit_code = household.geographical_unit.name
            original_pattern = household.properties.get('original_pattern', '')
            key = (geo_unit_code, original_pattern)
            if key not in households_by_geo_unit_pattern:
                households_by_geo_unit_pattern[key] = []
            households_by_geo_unit_pattern[key].append(household)

        logger.info(f"Found {sum(len(hhs) for hhs in households_by_geo_unit_pattern.values())} eligible households across {len(households_by_geo_unit_pattern)} geo_unit-pattern combinations")

        # Track statistics
        people_added = 0
        households_modified = 0

        # Process each geo_unit
        for geo_unit_code in set(k[0] for k in households_by_geo_unit_pattern.keys()):
            if geo_unit_code not in self.distributor.person_pool_by_geo_unit:
                continue

            pools = self.distributor.person_pool_by_geo_unit[geo_unit_code]
            available_people = pools[add_cat_idx]

            if not available_people:
                continue

            logger.debug(f"geo_unit {geo_unit_code}: {len(available_people)} {add_category} available")

            # Get all households in this geo_unit across all patterns
            geo_unit_households_by_pattern = {}
            for (ac, pattern), hhs in households_by_geo_unit_pattern.items():
                if ac == geo_unit_code:
                    geo_unit_households_by_pattern[pattern] = hhs

            # Calculate distribution with bias
            total_to_allocate = len(available_people)

            # Apply bias weights
            pattern_weights = {}
            for pattern in geo_unit_households_by_pattern.keys():
                weight = pattern_bias.get(pattern, 1.0) if pattern_bias else 1.0
                num_households = len(geo_unit_households_by_pattern[pattern])
                pattern_weights[pattern] = weight * num_households

            total_weight = sum(pattern_weights.values())

            if total_weight == 0:
                continue

            # Allocate to each pattern proportionally
            pattern_allocations = {}
            allocated_so_far = 0

            for pattern in geo_unit_households_by_pattern.keys():
                proportion = pattern_weights[pattern] / total_weight
                allocation = int(total_to_allocate * proportion)
                pattern_allocations[pattern] = allocation
                allocated_so_far += allocation

            # Distribute remainder to highest-weight patterns
            remainder = total_to_allocate - allocated_so_far
            if remainder > 0:
                sorted_patterns = sorted(pattern_weights.keys(), key=lambda p: pattern_weights[p], reverse=True)
                for i in range(remainder):
                    pattern = sorted_patterns[i % len(sorted_patterns)]
                    pattern_allocations[pattern] += 1

            # Track global people index across all patterns
            global_people_index = 0

            # Now distribute within each pattern's households
            for pattern, num_to_add in pattern_allocations.items():
                if num_to_add == 0:
                    continue

                pattern_households = geo_unit_households_by_pattern[pattern]
                num_hh = len(pattern_households)

                # Distribute balancedly
                base_per_household = num_to_add // num_hh
                remainder_hh = num_to_add % num_hh

                # Shuffle for fairness
                shuffled_hh = pattern_households.copy()
                np.random.shuffle(shuffled_hh)

                for hh_idx, household in enumerate(shuffled_hh):
                    # Determine how many to add to this household
                    to_add = base_per_household + (1 if hh_idx < remainder_hh else 0)

                    if to_add == 0:
                        continue

                    # Add people to this household
                    added_to_hh = 0
                    for _ in range(to_add):
                        if global_people_index >= len(available_people):
                            break

                        person = available_people[global_people_index]
                        household.add_resident(person)
                        self.distributor.allocated_people.add(person.id)
                        global_people_index += 1
                        added_to_hh += 1
                        people_added += 1

                    if added_to_hh > 0:
                        households_modified += 1
                        logger.debug(f"Added {added_to_hh} {add_category} to household {household.id} (pattern: {pattern}, now size: {len(household.residents)})")

            # Remove allocated people from pool
            pools[add_cat_idx] = pools[add_cat_idx][global_people_index:]

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.distributor.current_round,
            'people_added': people_added,
            'households_modified': households_modified,
            'total_people_allocated': len(self.distributor.allocated_people),
            'total_people_remaining': len(self.distributor.population.get_all_people()) - len(self.distributor.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.distributor.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households modified: {households_modified:,}")
        logger.info(f"  People added (overflow): {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.distributor.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.distributor.age_categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats

    def _select_person_for_excess_with_rule(self, household: 'Household',
                                           candidates: List['Person'],
                                           add_category: str,
                                           rule) -> Optional['Person']:
        """
        Select a person to add to an existing household using relationship rules.

        This validates the candidate against existing household members based on
        the relationship rule constraints (e.g., age differences).

        Args:
            household: The household to add to
            candidates: List of candidate people to choose from
            add_category: Category name being added (e.g., "Young Adults")
            rule: The relationship rule to use for validation

        Returns:
            Selected person if valid candidate found, None otherwise
        """
        # Organize existing household members by their roles based on the rule
        existing_people_by_role = {}

        # Map each rule role to its category names
        for role_name, role_config in rule.roles.items():
            category_names = role_config['categories']
            existing_people_by_role[role_name] = []

            # Find all household members that belong to this role's categories
            for resident in household.residents:
                resident_cat_name = self.distributor._get_person_category_name(resident)
                if resident_cat_name in category_names:
                    existing_people_by_role[role_name].append(resident)

        # Find which role the person being added belongs to
        current_role = None
        for role_name, role_config in rule.roles.items():
            if add_category in role_config['categories']:
                current_role = role_name
                break

        if not current_role:
            # Category not in any role - just return first candidate
            logger.debug(f"Category '{add_category}' not found in rule roles, using first candidate")
            return candidates[0] if candidates else None

        # Use relationship rules to select a valid person
        person = self.distributor.relationship_rules.select_person_with_constraint(
            candidates=candidates,
            existing_people_by_role=existing_people_by_role,
            constraints=rule.constraints,
            current_role=current_role,
            show_detailed_logs=False  # Keep logs minimal for performance
        )

        return person
