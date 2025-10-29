"""
Household distributor for allocating people into households.

This module handles:
- Loading household composition data from CSV
- Distributing people into households based on composition patterns
- Matching people to households based on age categories
- Handling census data obfuscation through composition demotion
"""

import os
import logging
import yaml
import random
import math
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Set

from geography.geography import Geography
from population.person import Person
from population.population import PopulationManager
from residence.relationship_rules import RelationshipRulesValidator
from residence.models import AgeCategory, Household
from residence.composition_pattern import CompositionPattern
from residence.household_excess_handler import HouseholdExcessHandler

logger = logging.getLogger("household")


# Removed: AgeCategory class - now in residence.models
# Removed: CompositionPattern class - now in residence.composition_pattern
# Removed: Household class - now in residence.models


class HouseholdDistributor:
    """
    Manages household distribution and people allocation.

    This class:
    - Loads household composition data from CSV
    - Loads configuration from YAML
    - Distributes people into households based on composition patterns
    - Handles census obfuscation through pattern demotion
    """

    def __init__(self, geography: Geography, population: PopulationManager,
                 data_dir: str = "data/households", config_file: str = "households_config.yaml"):
        """
        Initialize the household distributor.

        Args:
            geography: Geography object with loaded geographical units
            population: PopulationManager with generated population
            data_dir: Directory containing household data files
            config_file: Path to YAML configuration file (relative to data_dir)
        """
        self.geography = geography
        self.population = population
        self.data_dir = data_dir

        # Load configuration
        config_path = os.path.join(data_dir, config_file)
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Parse age categories from config
        self.age_categories = self._parse_age_categories()

        # Create mapping from category name to index for validation rules
        self.category_name_to_idx = {cat.name: idx for idx, cat in enumerate(self.age_categories)}

        # Household data
        self.households: List[Household] = []
        self.household_counts_by_area: Dict[str, Dict[str, int]] = {}
        self.allocated_people: Set[int] = set()  # Person IDs that have been allocated

        # Pool of available people by area and category
        self.person_pool_by_area: Dict[str, List[List['Person']]] = {}

        # Round tracking
        self.current_round: int = 0
        self.pools_prepared: bool = False

        # Initialize relationship rules validator
        rules_config_path = os.path.join(data_dir, "relationship_rules.yaml")
        self.relationship_rules = RelationshipRulesValidator(
            age_categories=self.age_categories,
            config_file=rules_config_path
        )

        # Initialize excess handler
        self.excess_handler = HouseholdExcessHandler(self)

        logger.info(f"Initialized HouseholdDistributor with {len(self.age_categories)} age categories")
        for cat in self.age_categories:
            logger.info(f"  - {cat}")

    def _parse_age_categories(self) -> List[AgeCategory]:
        """Parse age categories from config."""
        categories = []
        for cat_config in self.config['age_categories']:
            cat = AgeCategory(
                name=cat_config['name'],
                symbol=cat_config['symbol'],
                min_age=cat_config['min_age'],
                max_age=cat_config['max_age']
            )
            categories.append(cat)
        return categories

    def load_household_data(self, filename: str = "households.csv"):
        """
        Load household composition data from CSV.

        Args:
            filename: Name of CSV file in data_dir
        """
        filepath = os.path.join(self.data_dir, filename)
        logger.info(f"Loading household data from {filepath}")

        df = pd.read_csv(filepath)

        # First column is the area code, rest are household compositions
        area_col = df.columns[0]
        composition_cols = df.columns[1:]

        logger.info(f"Found {len(df)} areas with {len(composition_cols)} household types")

        # Store household counts by area
        for _, row in df.iterrows():
            area_code = row[area_col]

            # Only include areas that are in our loaded geography
            if area_code not in self.geography.units:
                continue

            counts = {}
            for col in composition_cols:
                count = int(row[col])
                if count > 0:
                    counts[col] = count

            if counts:
                self.household_counts_by_area[area_code] = counts

        logger.info(f"Loaded household data for {len(self.household_counts_by_area)} geographical units")

    def _categorize_person(self, person: Person) -> int:
        """Get the category index for a person based on their age."""
        for idx, cat in enumerate(self.age_categories):
            if cat.matches(person.age):
                return idx
        # Shouldn't happen, but default to last category
        return len(self.age_categories) - 1

    def _prepare_person_pools(self, refresh: bool = False):
        """
        Prepare pools of available people by area and age category.

        Args:
            refresh: If True, refresh pools with currently unallocated people.
                    If False and pools already exist, skip preparation.
        """
        if self.pools_prepared and not refresh:
            logger.debug("Person pools already prepared, skipping...")
            return

        logger.info("Preparing person pools by area and age category...")

        if refresh:
            # Clear existing pools for refresh
            self.person_pool_by_area = {}

        # Get all SGU units
        sgu_units = self.geography.get_units_by_level("SGU")

        for area_code, unit in sgu_units.items():
            # Get all people in this area
            people = self.population.get_people_by_area(area_code)

            if not people:
                continue

            # Initialize category pools
            category_pools = [[] for _ in self.age_categories]

            # Categorize each person (only if not already allocated)
            for person in people:
                if person.id not in self.allocated_people:
                    cat_idx = self._categorize_person(person)
                    category_pools[cat_idx].append(person)

            # Shuffle each pool for randomness
            for pool in category_pools:
                random.shuffle(pool)

            self.person_pool_by_area[area_code] = category_pools

            # Log pool sizes
            pool_sizes = [len(pool) for pool in category_pools]
            logger.debug(f"  {area_code}: {pool_sizes}")

        total_people = sum(sum(len(pool) for pool in pools)
                          for pools in self.person_pool_by_area.values())
        logger.info(f"Prepared person pools for {len(self.person_pool_by_area)} areas ({total_people} total people)")
        self.pools_prepared = True

    def _allocate_household_with_rules(self, area_code: str, pattern: CompositionPattern,
                                       max_size: Optional[int] = None,
                                       allocate_flexible: bool = False,
                                       target_size: Optional[int] = None,
                                       rule_name: Optional[str] = None) -> Tuple[Optional[Household], Optional[int]]:
        """
        Allocate a household using relationship rules.

        This method follows the role-based selection order defined in relationship_rules.yaml:
        1. Select people for each role in order (e.g., kids first, then adults)
        2. Apply age difference constraints between roles
        3. Apply couple matching constraints within roles

        Args:
            area_code: SGU code
            pattern: Composition pattern to match
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories
            target_size: Target household size for balanced distribution (optional)
            rule_name: Optional rule name to use (overrides auto-matching)

        Returns:
            Tuple of (Household object if successful or None, failed_category_idx or None)
        """
        # If no rule is specified, use simple allocation (no rules)
        if not rule_name:
            return self._allocate_household(area_code, pattern, max_size, allocate_flexible, target_size)

        # Get pattern to match (for logging)
        pattern_to_match = getattr(pattern, 'census_pattern', pattern.original_pattern)

        # Use explicitly specified rule
        rule = self.relationship_rules.get_rule_by_name(rule_name)
        if not rule:
            logger.warning(f"Rule '{rule_name}' not found, falling back to simple allocation")
            return self._allocate_household(area_code, pattern, max_size, allocate_flexible, target_size)

        # Log first time we apply rules for this pattern
        if not hasattr(self, '_logged_rules'):
            self._logged_rules = set()

        # Create a unique key for logging (pattern + rule_name if specified)
        log_key = f"{pattern_to_match}_{rule_name}" if rule_name else pattern_to_match

        if log_key not in self._logged_rules:
            if rule_name:
                logger.debug(f"✓ Applying explicit rule '{rule_name}' to pattern: '{pattern.original_pattern}'")
            elif hasattr(pattern, 'census_pattern'):
                logger.debug(f"✓ Applying relationship rules for pattern: '{pattern.census_pattern}' (using assumption: '{pattern.original_pattern}')")
            else:
                logger.debug(f"✓ Applying relationship rules for pattern: '{pattern.original_pattern}'")
            self._logged_rules.add(log_key)

        if area_code not in self.person_pool_by_area:
            return (None, None)

        pools = self.person_pool_by_area[area_code]

        # Detailed logging for ALL households in ALL geo units
        household_num = self._setup_allocation_logging(area_code)
        logger.debug("=" * 80)
        logger.debug(f"GEO UNIT: {area_code} - HOUSEHOLD #{household_num}")
        if hasattr(pattern, 'census_pattern'):
            logger.debug(f"Census Pattern: '{pattern.census_pattern}'")
            logger.debug(f"Assumption: '{pattern.original_pattern}'")
        else:
            logger.debug(f"Pattern: '{pattern.to_string()}'")
        logger.debug("=" * 80)
        logger.debug(f"Rule: {rule.name}")
        logger.debug(f"Selection order: {' → '.join(rule.selection_order)}")
        logger.debug("")
        self._show_detailed_logs = True

        # Get backtracking config
        backtrack_config = self.relationship_rules.selection_strategy.get('backtracking', {})

        # Use backtracking algorithm to select people for all roles
        selected_by_role, failed_cat_idx = self._select_roles_with_backtracking(
            rule, pattern, pools, backtrack_config, self._show_detailed_logs
        )

        # Check if role selection failed
        if selected_by_role is None:
            return (None, failed_cat_idx)

        # Collect all selected people
        all_selected = []
        for people_list in selected_by_role.values():
            all_selected.extend(people_list)

        if not all_selected:
            return (None, None)

        # Remove selected people from pools
        selected_ids = {p.id for p in all_selected}
        for cat_idx in range(len(self.age_categories)):
            pools[cat_idx] = [p for p in pools[cat_idx] if p.id not in selected_ids]

        # Create household
        unit = self.geography.get_unit(area_code)
        household = Household(
            id=len(self.households),
            geographical_unit=unit,
            properties={
                'original_pattern': pattern.original_pattern,
                'actual_pattern': pattern.to_string()
            }
        )
        household._age_categories = self.age_categories

        # Add residents
        for person in all_selected:
            household.add_resident(person)
            self.allocated_people.add(person.id)

        if self._show_detailed_logs:
            logger.debug("FINAL HOUSEHOLD COMPOSITION:")
            logger.debug(f"  Household ID: {household.id}")
            logger.debug(f"  Geo Unit: {area_code}")
            logger.debug(f"  Pattern: {pattern.original_pattern}")
            logger.debug(f"  Total members: {len(all_selected)}")
            logger.debug("")
            for role_name, people in selected_by_role.items():
                if people:
                    logger.debug(f"  {role_name}:")
                    for person in people:
                        logger.debug(f"    - {person}")
            logger.debug("=" * 80)
            logger.debug("")

        return (household, None)

    def _adjust_role_count_for_pattern(self, role_count, role_name: str, category_names: List[str],
                                       category_indices: List[int], pattern: CompositionPattern,
                                       show_detailed_logs: bool) -> Tuple[int, bool]:
        """
        Adjust role count based on pattern requirements.

        When a pattern has been demoted, the pattern's count takes precedence over the rule's count.
        This ensures that demoted patterns (e.g., "2C" demoted to "1C") are allocated correctly.

        Args:
            role_count: Original count from the rule (can be int or "any")
            role_name: Name of the role being processed
            category_names: List of category names for this role
            category_indices: List of category indices for this role
            pattern: Composition pattern being allocated
            show_detailed_logs: Whether to show detailed debug logs

        Returns:
            Tuple of (adjusted_role_count, should_skip_role):
            - adjusted_role_count: The count to use (may be modified from original)
            - should_skip_role: True if the role should be skipped (pattern requires 0 people)
        """
        # Calculate total count needed from pattern for these categories
        pattern_count = sum(pattern.get_min_count(cat_idx) for cat_idx in category_indices)

        # If role_count is numeric and pattern_count is different, use pattern_count
        if isinstance(role_count, int) and pattern_count != role_count:
            if show_detailed_logs:
                logger.debug(f"Step: Selecting role '{role_name}'")
                logger.debug(f"  Categories: {category_names}")
                logger.debug(f"  Count needed (from rule): {role_count}")
                logger.debug(f"  Count needed (from pattern): {pattern_count} (using pattern count)")
            role_count = pattern_count

            # If pattern requires 0 people for this role, skip it
            if role_count == 0:
                if show_detailed_logs:
                    logger.debug(f"  → Pattern requires 0 people for this role, skipping")
                    logger.debug("")
                return (role_count, True)  # Signal to skip this role
        else:
            if show_detailed_logs:
                logger.debug(f"Step: Selecting role '{role_name}'")
                logger.debug(f"  Categories: {category_names}")
                logger.debug(f"  Count needed: {role_count}")

        return (role_count, False)  # Don't skip

    def _prepare_role_candidates(self, pools: List[List[Person]], category_indices: List[int],
                                 role_index: int, backtrack_attempt: int,
                                 tried_first_role_ids: Set[int], avoid_duplicates: bool,
                                 show_detailed_logs: bool, log_backtracks: bool) -> List[Person]:
        """
        Prepare candidate pool for role selection with backtracking support.

        Gets candidates from specified categories and filters out already-tried candidates
        when backtracking to avoid duplicate attempts.

        Args:
            pools: Available people by category
            category_indices: Category indices to draw candidates from
            role_index: Index of current role in selection order (0 = first role)
            backtrack_attempt: Current backtracking attempt number
            tried_first_role_ids: Set of person IDs already tried for first role
            avoid_duplicates: Whether to avoid duplicate attempts during backtracking
            show_detailed_logs: Whether to show detailed debug logs
            log_backtracks: Whether to log backtracking information

        Returns:
            List of candidate people for this role
        """
        # Get candidates from these categories
        candidates = []
        for cat_idx in category_indices:
            candidates.extend(pools[cat_idx])

        # If this is the first role and we're backtracking, exclude already-tried people
        if role_index == 0 and backtrack_attempt > 0 and avoid_duplicates and tried_first_role_ids:
            original_count = len(candidates)
            candidates = [p for p in candidates if p.id not in tried_first_role_ids]
            if show_detailed_logs and log_backtracks:
                logger.debug(f"  Backtracking: Excluded {original_count - len(candidates)} already-tried candidates")

        if show_detailed_logs:
            logger.debug(f"  Available candidates: {len(candidates)} people")

        return candidates

    def _can_skip_role_with_no_candidates(self, role_count, category_indices: List[int],
                                          pattern: CompositionPattern,
                                          show_detailed_logs: bool) -> bool:
        """
        Check if a role with no candidates can be skipped.

        When no candidates are available, some roles can be skipped if the pattern
        allows 0 people for that role (e.g., for "any" count roles with min=0).

        Args:
            role_count: Original count from the rule (can be int or "any")
            category_indices: Category indices for this role
            pattern: Composition pattern being allocated
            show_detailed_logs: Whether to show detailed debug logs

        Returns:
            True if role can be skipped (continue to next role),
            False if allocation should fail (break)
        """
        # Check if this role allows 0 people (e.g., role_count == "any" with min=0)
        if role_count == "any":
            # Calculate minimum needed from pattern
            total_needed = 0
            for cat_idx in category_indices:
                min_count = pattern.get_min_count(cat_idx)
                total_needed += min_count

            if total_needed == 0:
                # Pattern allows 0 people for this role - can skip it
                if show_detailed_logs:
                    logger.debug(f"  → Pattern allows 0 people for this role, skipping")
                    logger.debug("")
                return True  # Can skip

        # If we get here, the role requires people but none are available
        if show_detailed_logs:
            logger.debug(f"  ✗ FAILED: No candidates available")
        return False  # Cannot skip - allocation fails

    def _find_pair_constraint_for_role(self, rule, role_name: str, role_count) -> Optional[Dict]:
        """
        Find a pair_matching constraint that applies to the given role.

        Searches through rule constraints for a pair_matching constraint that:
        1. Applies to this specific role
        2. Has a matching require_exact_count (if specified)

        Args:
            rule: The relationship rule containing constraints
            role_name: Name of the role to check
            role_count: Expected count for this role (int or "any")

        Returns:
            The matching pair_matching constraint dict, or None if not found
        """
        for constraint in rule.constraints:
            if constraint['type'] == 'pair_matching' and constraint.get('role') == role_name:
                # Check if require_exact_count is specified
                required_count = constraint.get('require_exact_count')
                if required_count is None or role_count == required_count:
                    return constraint
        return None

    def _handle_role_selection_failure(self, failed_at_role_index: int, rule,
                                       selected_by_role: Dict[str, List[Person]],
                                       backtrack_enabled: bool, backtrack_attempt: int,
                                       max_backtracks: int, avoid_duplicates: bool,
                                       log_backtracks: bool) -> Tuple[str, Optional[int], List[int]]:
        """
        Handle role selection failure and determine backtracking action.

        When role selection fails, this method decides whether to:
        1. Cannot backtrack (failed at first role) → return failure
        2. Do backtrack (retry with different first role) → continue
        3. Exhausted backtracks (tried too many times) → return failure

        Args:
            failed_at_role_index: Index of the role that failed
            rule: The relationship rule
            selected_by_role: Currently selected people by role
            backtrack_enabled: Whether backtracking is enabled
            backtrack_attempt: Current backtracking attempt number
            max_backtracks: Maximum number of backtracks allowed
            avoid_duplicates: Whether to avoid duplicate attempts
            log_backtracks: Whether to log backtracking information

        Returns:
            Tuple of (action, failed_category_idx, tried_person_ids):
            - action: 'cannot_backtrack', 'do_backtrack', or 'exhausted'
            - failed_category_idx: Category index that caused failure (or None)
            - tried_person_ids: List of person IDs to add to tried set (empty if not do_backtrack)
        """
        first_role_name = rule.selection_order[0]
        failed_role_name = rule.selection_order[failed_at_role_index]

        # Check if we can backtrack
        if failed_at_role_index == 0:
            # Failed at first role - cannot backtrack
            if log_backtracks:
                logger.debug(f"  ✗ Cannot backtrack: Failed at first role '{failed_role_name}'")
            # Get category index for failure reporting
            role_config = rule.roles[failed_role_name]
            category_names = role_config['categories']
            category_indices = [self.relationship_rules.category_name_to_idx[cat]
                               for cat in category_names
                               if cat in self.relationship_rules.category_name_to_idx]
            return ('cannot_backtrack', category_indices[0] if category_indices else None, [])

        elif backtrack_enabled and backtrack_attempt < max_backtracks:
            # Can backtrack - get IDs to track for avoiding duplicates
            tried_ids = []
            if avoid_duplicates and selected_by_role.get(first_role_name):
                tried_ids = [person.id for person in selected_by_role[first_role_name]]

            if log_backtracks:
                logger.debug(f"  ⟲ BACKTRACK #{backtrack_attempt + 1}: '{failed_role_name}' failed, "
                           f"retrying with different '{first_role_name}'")
                logger.debug("")
            return ('do_backtrack', None, tried_ids)

        else:
            # Exhausted backtracks
            if log_backtracks:
                logger.debug(f"  ✗ Exhausted {max_backtracks} backtrack attempts")
            # Get category index for failure reporting
            role_config = rule.roles[failed_role_name]
            category_names = role_config['categories']
            category_indices = [self.relationship_rules.category_name_to_idx[cat]
                               for cat in category_names
                               if cat in self.relationship_rules.category_name_to_idx]
            return ('exhausted', category_indices[0] if category_indices else None, [])

    def _select_roles_with_backtracking(self, rule, pattern: CompositionPattern,
                                       pools: Dict[int, List[Person]],
                                       backtrack_config: Dict,
                                       show_detailed_logs: bool) -> Tuple[Optional[Dict[str, List[Person]]], Optional[int]]:
        """
        Select people for household roles using backtracking algorithm.

        This method implements the core backtracking logic for role-based household allocation:
        1. Iterate through roles in selection order
        2. For each role, select people matching constraints
        3. If a role fails, backtrack and try different people for earlier roles
        4. Track tried combinations to avoid duplicates

        Args:
            rule: The relationship rule containing role definitions and constraints
            pattern: Composition pattern to match
            pools: Available people by category
            backtrack_config: Configuration dict with 'enabled', 'max_backtracks', etc.
            show_detailed_logs: Whether to show detailed debug logs

        Returns:
            Tuple of (selected_by_role, failed_category_idx):
            - selected_by_role: Dict mapping role names to selected people if successful
            - failed_category_idx: Category index that caused failure, or None if successful
        """
        backtrack_enabled = backtrack_config.get('enabled', False)
        max_backtracks = backtrack_config.get('max_backtracks', 3)
        log_backtracks = backtrack_config.get('log_backtracks', True)
        avoid_duplicates = backtrack_config.get('avoid_duplicates', True)

        # Backtracking loop
        backtrack_attempt = 0
        tried_first_role_ids = set()  # Track tried first-role person IDs to avoid duplicates

        while backtrack_attempt <= max_backtracks:
            # Track selected people by role
            selected_by_role: Dict[str, List[Person]] = {role_name: [] for role_name in rule.roles.keys()}
            failed_at_role_index = None

            # Select people for each role in order
            for role_index, role_name in enumerate(rule.selection_order):
                role_config = rule.roles[role_name]
                category_names = role_config['categories']
                role_count = role_config['count']

                # Map category names to indices
                category_indices = []
                for cat_name in category_names:
                    if cat_name in self.relationship_rules.category_name_to_idx:
                        category_indices.append(self.relationship_rules.category_name_to_idx[cat_name])

                # Adjust role count based on pattern requirements (e.g., after demotion)
                role_count, should_skip = self._adjust_role_count_for_pattern(
                    role_count, role_name, category_names, category_indices, pattern, show_detailed_logs
                )

                if should_skip:
                    continue

                # Prepare candidates for this role (with backtracking support)
                candidates = self._prepare_role_candidates(
                    pools, category_indices, role_index, backtrack_attempt,
                    tried_first_role_ids, avoid_duplicates, show_detailed_logs, log_backtracks
                )

                if not candidates:
                    # Check if role with no candidates can be skipped
                    if self._can_skip_role_with_no_candidates(
                        role_count, category_indices, pattern, show_detailed_logs
                    ):
                        continue  # Skip this role
                    else:
                        # Allocation fails
                        failed_at_role_index = role_index
                        break

                # Check for pair_matching constraint for this role
                pair_constraint = self._find_pair_constraint_for_role(rule, role_name, role_count)

                if pair_constraint and role_count == 2:
                    # Select a compatible pair
                    # IMPORTANT: Pass existing people (e.g., children) so pair can be validated against them
                    if show_detailed_logs:
                        logger.debug(f"  Mode: Selecting a compatible pair")
                        if selected_by_role:
                            already_selected = sum(len(people) for people in selected_by_role.values())
                            logger.debug(f"  Constraints: Must validate against {already_selected} already-selected people")

                    pair = self.relationship_rules.select_pair(
                        candidates,
                        pair_constraint,
                        existing_people_by_role=selected_by_role,
                        constraints=rule.constraints,
                        current_role=role_name,
                        show_detailed_logs=show_detailed_logs
                    )
                    if not pair:
                        # Couldn't find valid pair
                        if show_detailed_logs:
                            logger.debug(f"  ✗ FAILED: Could not find valid pair")
                        failed_at_role_index = role_index
                        break

                    selected_by_role[role_name] = list(pair)
                    if show_detailed_logs:
                        logger.debug(f"  ✓ Selected: {pair[0]} and {pair[1]}")
                        logger.debug("")

                elif role_count == "any":
                    # Determine count from pattern
                    # For "any", use minimum required from pattern
                    total_needed = 0
                    for cat_idx in category_indices:
                        min_count = pattern.get_min_count(cat_idx)
                        total_needed += min_count

                    # Select people one by one with constraints
                    for i in range(total_needed):
                        person = self.relationship_rules.select_person_with_constraint(
                            candidates=candidates,
                            existing_people_by_role=selected_by_role,
                            constraints=rule.constraints,
                            current_role=role_name,
                            show_detailed_logs=show_detailed_logs
                        )

                        if not person:
                            failed_at_role_index = role_index
                            break

                        selected_by_role[role_name].append(person)
                        # Remove from candidates
                        candidates = [p for p in candidates if p.id != person.id]

                else:
                    # Select specific number of people
                    if show_detailed_logs:
                        logger.debug(f"  Mode: Selecting {role_count} person(s) individually")

                    for i in range(role_count):
                        person = self.relationship_rules.select_person_with_constraint(
                            candidates=candidates,
                            existing_people_by_role=selected_by_role,
                            constraints=rule.constraints,
                            current_role=role_name,
                            show_detailed_logs=show_detailed_logs
                        )

                        if not person:
                            if show_detailed_logs:
                                logger.debug(f"  ✗ FAILED: Could not find valid person {i+1}/{role_count}")
                            failed_at_role_index = role_index
                            break

                        selected_by_role[role_name].append(person)
                        if show_detailed_logs:
                            logger.debug(f"  ✓ Selected person {i+1}/{role_count}: {person}")
                        # Remove from candidates
                        candidates = [p for p in candidates if p.id != person.id]

                    if show_detailed_logs:
                        logger.debug("")

            # Check if role selection succeeded or failed
            if failed_at_role_index is not None:
                # Handle the failure and determine what action to take
                action, failed_cat_idx, tried_ids = self._handle_role_selection_failure(
                    failed_at_role_index, rule, selected_by_role,
                    backtrack_enabled, backtrack_attempt, max_backtracks,
                    avoid_duplicates, log_backtracks
                )

                if action == 'do_backtrack':
                    # Track tried IDs and retry with different first role
                    for person_id in tried_ids:
                        tried_first_role_ids.add(person_id)
                    backtrack_attempt += 1
                    continue  # Continue while loop - retry
                else:
                    # Cannot backtrack or exhausted - return failure
                    return (None, failed_cat_idx)

            # Role selection succeeded! Create household
            if backtrack_attempt > 0 and log_backtracks:
                logger.debug(f"  ✓ SUCCESS after {backtrack_attempt} backtrack(s)")

            break  # Exit backtracking while loop

        return (selected_by_role, None)

    def _allocate_sequential(self, pattern: CompositionPattern,
                            pools: Dict[int, List[Person]],
                            max_size: Optional[int],
                            allocate_flexible: bool) -> Tuple[List[Tuple[int, int]], Optional[int]]:
        """
        Perform sequential allocation through age categories.

        This is the original allocation strategy that processes categories sequentially,
        taking the minimum required (or exact count if specified) from each category.
        For flexible (>=) categories, can optionally allocate random amounts above minimum.

        Args:
            pattern: Composition pattern to match
            pools: Available people by category
            max_size: Maximum household size constraint (optional)
            allocate_flexible: If True, randomly allocate to flexible categories

        Returns:
            Tuple of (selections, failed_category_idx):
            - selections: List of (category_idx, count) tuples if successful
            - failed_category_idx: Category index that caused failure, or None if successful
        """
        selections = []
        logger.debug(f"\n=== ORIGINAL SEQUENTIAL ALLOCATION MODE ===")
        if max_size:
            logger.debug(f"Max size constraint: {max_size}")
        else:
            logger.debug("No max size constraint")

        # PHASE 1: Check if ALL categories can be fulfilled (don't modify pools yet!)
        total_selected = 0
        logger.debug(f"\n--- SEQUENTIAL ALLOCATION PHASE ---")

        for cat_idx in range(len(self.age_categories)):
            min_count = pattern.get_min_count(cat_idx)
            max_count = pattern.get_max_count(cat_idx)
            available = len(pools[cat_idx])

            cat_name = self.age_categories[cat_idx].name
            logger.debug(f"\nCategory {cat_idx} ({cat_name}):")
            logger.debug(f"  min: {min_count}, max: {max_count}, available: {available}")
            logger.debug(f"  total_selected so far: {total_selected}")

            # Check if we have enough people
            if available < min_count:
                # Can't fulfill - return failure with the category that caused it
                logger.debug(f"  ✗ INSUFFICIENT: Need {min_count}, only {available} available")
                return ([], cat_idx)

            # Decide how many to take
            if max_count is not None:
                # Exact count specified
                count = max_count
                logger.debug(f"  → EXACT count specified: {count}")
            else:
                # Flexible (>=) category
                logger.debug(f"  → FLEXIBLE category (min: {min_count})")
                if allocate_flexible and available > min_count:
                    # RANDOM ALLOCATION: Randomly allocate between min and available
                    # But respect max_size if specified
                    max_allocatable = available
                    logger.debug(f"    allocate_flexible=True, available > min_count")
                    logger.debug(f"    initial max_allocatable: {max_allocatable}")

                    if max_size is not None:
                        remaining_capacity = max_size - total_selected
                        max_allocatable = min(max_allocatable, remaining_capacity)
                        logger.debug(f"    remaining_capacity: {remaining_capacity}")
                        logger.debug(f"    adjusted max_allocatable: {max_allocatable}")

                    # Random count between min and max_allocatable
                    if max_allocatable > min_count:
                        count = random.randint(min_count, max_allocatable)
                        logger.debug(f"    random allocation: {count} (range: {min_count}-{max_allocatable})")
                    else:
                        count = min_count
                        logger.debug(f"    max_allocatable <= min_count, using min: {count}")
                else:
                    # Take minimum required
                    count = min_count
                    logger.debug(f"    taking minimum: {count}")

            # Apply max_size constraint if specified
            if max_size is not None:
                remaining_capacity = max_size - total_selected
                original_count = count
                count = min(count, remaining_capacity)
                if count != original_count:
                    logger.debug(f"  max_size constraint applied: {original_count} → {count}")

                # If this brings us below minimum, we can't fulfill the pattern
                if count < min_count:
                    logger.debug(f"  ✗ CONSTRAINT VIOLATION: count ({count}) < min_count ({min_count})")
                    return ([], cat_idx)

            total_selected += count
            selections.append((cat_idx, count))
            logger.debug(f"  ✓ Allocated: {count}")
            logger.debug(f"  new total_selected: {total_selected}")

        logger.debug(f"\n--- SEQUENTIAL ALLOCATION COMPLETE ---")
        logger.debug(f"Total selected: {total_selected}")
        logger.debug(f"Selections: {selections}")

        return (selections, None)

    def _allocate_household(self, area_code: str, pattern: CompositionPattern,
                            max_size: Optional[int] = None,
                            allocate_flexible: bool = False,
                            target_size: Optional[int] = None) -> Tuple[Optional[Household], Optional[int]]:
        """
        Attempt to allocate a household in an area with the given pattern.

        Args:
            area_code: SGU code
            pattern: Composition pattern to match
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories randomly

        Returns:
            Tuple of (Household object if successful or None, failed_category_idx or None)
            - If successful: (household, None)
            - If failed: (None, category_idx that caused failure)
        """
        if area_code not in self.person_pool_by_area:
            return (None, None)

        pools = self.person_pool_by_area[area_code]

        # Detailed logging for ALL households in ALL geo units (NO RULES version)
        household_num = self._setup_allocation_logging(area_code)
        logger.debug("=" * 80)
        logger.debug(f"GEO UNIT: {area_code} - HOUSEHOLD #{household_num}")
        logger.debug(f"Pattern: '{pattern.to_string()}'")
        logger.debug("=" * 80)
        logger.debug(f"Allocation mode: Simple (no constraints)")
        if max_size:
            logger.debug(f"Max household size: {max_size}")
        if target_size:
            logger.debug(f"Target household size: {target_size}")
        logger.debug(f"Allocate flexible: {allocate_flexible}")
        logger.debug("")

        # Determine allocation strategy
        if allocate_flexible and target_size is not None:
            # Use balanced distribution mode
            selections, failed_cat = self._allocate_balanced_distribution(pattern, pools, target_size)
            if failed_cat is not None:
                return (None, failed_cat)
        else:
            # Use sequential allocation mode
            selections, failed_cat = self._allocate_sequential(pattern, pools, max_size, allocate_flexible)
            if failed_cat is not None:
                return (None, failed_cat)

        # PHASE 2: All checks passed! Now actually take people from pools
        selected_people = []
        logger.debug("ALLOCATION DECISIONS:")
        for cat_idx, count in selections:
            cat = self.age_categories[cat_idx]
            logger.debug(f"  {cat.name} (age {cat.min_age}-{cat.max_age if cat.max_age else '∞'}): {count} people")
            if count > 0:
                selected = pools[cat_idx][:count]
                selected_people.extend(selected)
                pools[cat_idx] = pools[cat_idx][count:]
                for person in selected:
                    logger.debug(f"    - {person}")

        if not selected_people:
            logger.debug("  ✗ FAILED: No people selected")
            logger.debug("")
            return (None, None)

        logger.debug("")
        logger.debug("FINAL HOUSEHOLD COMPOSITION:")
        logger.debug(f"  Total members: {len(selected_people)}")
        logger.debug(f"  Pattern: {pattern.original_pattern}")

        # Create household
        unit = self.geography.get_unit(area_code)
        household = Household(
            id=len(self.households),
            geographical_unit=unit,
            properties={
                'original_pattern': pattern.original_pattern,  # The original requested pattern
                'actual_pattern': pattern.to_string()  # The actual pattern used (may be demoted)
            }
        )
        household._age_categories = self.age_categories

        # Add residents
        for person in selected_people:
            household.add_resident(person)
            self.allocated_people.add(person.id)

        logger.debug(f"  ✓ Household {household.id} created successfully")
        logger.debug("=" * 80)
        logger.debug("")

        return (household, None)

    def _attempt_with_demotion(self, area_code: str, pattern: CompositionPattern,
                               max_attempts: int, max_size: Optional[int] = None,
                               allocate_flexible: bool = False,
                               target_size: Optional[int] = None,
                               rule_name: Optional[str] = None,
                               demotion_rules: Optional[Dict[str, str]] = None) -> Optional[Household]:
        """
        Attempt to allocate a household, using intelligent demotion if necessary.

        Demotion strategy:
        - Tries to demote the category that actually caused the failure
        - Falls back to configured priority order if failure category can't be demoted
        - Can switch to a different rule when pattern matches a demotion_rules mapping

        Args:
            area_code: SGU code
            pattern: Initial composition pattern
            max_attempts: Maximum demotion attempts
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories randomly
            rule_name: Optional relationship rule name to apply (overrides auto-matching)
            demotion_rules: Optional dict mapping pattern strings to rule names for demoted patterns

        Returns:
            Household object if successful, None otherwise
        """
        # Get demotion priority from config (used as fallback)
        priority_config = self.config['demotion']['priority']
        priority_order = []
        for cat_idx, cat in enumerate(self.age_categories):
            priority = priority_config.get(cat.name, 999)
            priority_order.append((priority, cat_idx))
        priority_order.sort()  # Sort by priority (lower = demote first)
        fallback_priority = [idx for _, idx in priority_order]

        current_pattern = pattern
        last_failed_category = None

        for attempt in range(max_attempts + 1):
            if attempt > 0:
                logger.debug(f"  ⚠️  DEMOTION ATTEMPT #{attempt}: Trying pattern '{current_pattern.to_string()}'")

            # Try to allocate with current pattern
            # First try with relationship rules if available
            household, failed_category_idx = self._allocate_household_with_rules(
                area_code, current_pattern, max_size, allocate_flexible, target_size, rule_name
            )

            # If rules-based allocation returned None and called the fallback,
            # the fallback already tried regular allocation, so we're done
            if household:
                if attempt > 0:
                    logger.debug(f"  ✓ Succeeded after {attempt} demotion(s) with pattern: {current_pattern.to_string()}")
                    logger.debug("")
                return household

            # Store which category failed
            last_failed_category = failed_category_idx

            if failed_category_idx is not None:
                cat = self.age_categories[failed_category_idx]
                logger.debug(f"  ✗ ALLOCATION FAILED: Category '{cat.name}' (idx {failed_category_idx}) has insufficient people")
            else:
                logger.debug(f"  ✗ ALLOCATION FAILED: No specific category identified")

            # Check minimum size
            min_size = self.config['demotion']['min_household_size']
            if current_pattern.min_household_size() < min_size:
                logger.debug(f"  ✗ Pattern too small after demotion (min size {min_size}): {current_pattern.to_string()}")
                logger.debug("")
                return None

            # Try to demote
            if attempt < max_attempts:
                # INTELLIGENT DEMOTION: Try to demote the category that failed
                new_pattern = None

                if failed_category_idx is not None:
                    # Check how many people are available in this category to jump directly
                    available_count = 0
                    if area_code in self.person_pool_by_area:
                        pools = self.person_pool_by_area[area_code]
                        if failed_category_idx < len(pools):
                            available_count = len(pools[failed_category_idx])

                    # Try demoting the failed category directly to available count
                    cat_name = self.age_categories[failed_category_idx].name
                    logger.debug(f"  → Attempting intelligent demotion: Reducing '{cat_name}' (category {failed_category_idx})")
                    logger.debug(f"  → Available {cat_name}: {available_count} people")

                    # Demote directly to available count instead of one-by-one
                    new_pattern = current_pattern.demote_to_count(failed_category_idx, available_count)

                    # If demote_to_count doesn't exist, fall back to demote_once
                    if new_pattern is None:
                        new_pattern = current_pattern.demote_once([failed_category_idx])

                # If intelligent demotion didn't work, try fallback priority order
                if new_pattern is None:
                    logger.debug(f"  → Intelligent demotion failed, trying fallback priority order")
                    new_pattern = current_pattern.demote_once(fallback_priority)

                if new_pattern is None:
                    logger.debug(f"  ✗ Cannot demote further: {current_pattern.to_string()}")
                    logger.debug("")
                    return None

                # Check if the demoted pattern would result in an empty household
                min_size = self.config['demotion']['min_household_size']
                if new_pattern.min_household_size() < min_size:
                    logger.debug(f"  ✗ Demoted pattern too small (min size {min_size}): '{new_pattern.to_string()}'")
                    logger.debug(f"  ✗ Skipping allocation attempt - would result in empty household")
                    logger.debug("")
                    return None

                # Validate the new pattern against demotion rules
                validation_rules = self.config.get('demotion', {}).get('validation_rules', [])
                if validation_rules and not new_pattern.validate_against_rules(
                    validation_rules, self.category_name_to_idx
                ):
                    logger.debug(f"  ✗ Demoted pattern violates validation rules: {new_pattern.to_string()}")
                    logger.debug("")
                    return None

                logger.debug(f"  → Demoted pattern: '{current_pattern.to_string()}' → '{new_pattern.to_string()}'")

                # Check if we should switch to a different rule for this demoted pattern
                if demotion_rules and new_pattern.to_string() in demotion_rules:
                    new_rule_name = demotion_rules[new_pattern.to_string()]
                    if new_rule_name != rule_name:
                        logger.debug(f"  → Switching rule: '{rule_name}' → '{new_rule_name}'")
                        rule_name = new_rule_name

                logger.debug("")
                current_pattern = new_pattern
            else:
                logger.debug(f"  ✗ Max demotion attempts ({max_attempts}) reached")
                logger.debug("")
                return None

        return None

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
        if area_code not in self.person_pool_by_area:
            return [pattern.min_household_size()] * num_households

        pools = self.person_pool_by_area[area_code]

        # Count total available people in ELIGIBLE categories only
        # (categories where the pattern allows at least 1 person)
        total_available = 0
        for cat_idx in range(len(self.age_categories)):
            max_count = pattern.get_max_count(cat_idx)
            pool_size = len(pools[cat_idx])
            # Only count if category allows people (max_count is None or > 0)
            if max_count is None or max_count > 0:
                total_available += pool_size
                if pool_size > 0:
                    logger.debug(f"  Category {self.age_categories[cat_idx].name}: {pool_size} available (max_count={max_count})")
            else:
                if pool_size > 0:
                    logger.debug(f"  Category {self.age_categories[cat_idx].name}: {pool_size} available but EXCLUDED by pattern (max_count={max_count})")

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
        round_label = self._log_round_start(round_name, "Round")

        # Prepare or refresh pools
        self._prepare_person_pools(refresh=refresh_pools)

        # Get config
        demotion_enabled = self.config['demotion']['enabled']
        max_attempts = self.config['demotion']['max_attempts']

        # Track round statistics
        round_start_allocated = len(self.allocated_people)
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
        for area_code, compositions in self.household_counts_by_area.items():
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
                        household = self._attempt_with_demotion(area_code, pattern, max_attempts, max_household_size, allocate_flexible, target_size, rule_name, demotion_rules)
                    else:
                        household, _ = self._allocate_household_with_rules(area_code, pattern, max_household_size, allocate_flexible, target_size, rule_name)

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

                        self.households.append(household)
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
            'round_number': self.current_round,
            'households_created': households_created,
            'households_requested': total_requested,
            'households_with_demotion': total_demoted,
            'people_allocated_this_round': len(self.allocated_people) - round_start_allocated,
            'total_households': len(self.households),
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Log summary (with additional round-specific info first)
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Requested households (filtered): {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
        if total_demoted > 0:
            logger.info(f"  Households using demotion: {total_demoted:,}")
        logger.info(f"  People allocated this round: {round_stats['people_allocated_this_round']:,}")
        logger.info(f"  Total households so far: {len(self.households):,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {round_stats['total_people_remaining']:,}")
        logger.info("=" * 60)

        return round_stats

    def get_available_people_count(self) -> int:
        """Get the number of people currently available (not allocated)."""
        return len(self.population.get_all_people()) - len(self.allocated_people)

    def get_available_people_by_category(self) -> Dict[str, int]:
        """Get counts of available people by age category."""
        counts = {cat.name: 0 for cat in self.age_categories}

        for person in self.population.get_all_people():
            if person.id not in self.allocated_people:
                for cat in self.age_categories:
                    if cat.matches(person.age):
                        counts[cat.name] += 1
                        break

        return counts

    def mark_people_as_allocated(self, people: List['Person'], venue_type: str = "external"):
        """
        Mark people as allocated (to venues, care homes, etc.) so they won't
        be allocated to households in subsequent rounds.

        This is useful when you're allocating people to venues between household rounds.

        Args:
            people: List of Person objects to mark as allocated
            venue_type: Type of venue (for logging purposes)

        Returns:
            int: Number of people marked as allocated
        """
        count = 0
        for person in people:
            if person.id not in self.allocated_people:
                self.allocated_people.add(person.id)
                count += 1

        logger.info(f"Marked {count} people as allocated to {venue_type}")
        return count

    def reset_allocation(self):
        """
        Reset all household allocations.

        Warning: This will clear all households and reset person allocations.
        Use with caution!
        """
        logger.warning("Resetting all household allocations...")

        # Clear residence from all allocated people
        for person_id in self.allocated_people:
            person = self.population.get_person(person_id)
            if person and hasattr(person, 'residence'):
                person.residence = None

        # Clear all data
        self.households = []
        self.allocated_people = set()
        self.person_pool_by_area = {}
        self.current_round = 0
        self.pools_prepared = False

        logger.info("Allocation reset complete")

    def _select_person_for_excess_with_rule(self, *args, **kwargs):
        """Delegate to excess handler. See HouseholdExcessHandler._select_person_for_excess_with_rule for documentation."""
        return self.excess_handler._select_person_for_excess_with_rule(*args, **kwargs)

    def _get_person_category_name(self, person: 'Person') -> str:
        """Get the category name for a person based on their age."""
        for cat in self.age_categories:
            if cat.max_age is None:
                if person.age >= cat.min_age:
                    return cat.name
            elif cat.min_age <= person.age < cat.max_age:
                return cat.name
        return "Unknown"

    def _validate_category_index(self, category_name: str, log_level: str = "error") -> Optional[int]:
        """
        Validate and retrieve category index by name.

        Args:
            category_name: Name of the category to validate
            log_level: Logging level for invalid category ("error", "warning", or None)

        Returns:
            Category index if valid, None otherwise
        """
        cat_idx = self.category_name_to_idx.get(category_name)
        if cat_idx is None:
            if log_level == "error":
                logger.error(f"Unknown category '{category_name}'")
            elif log_level == "warning":
                logger.warning(f"Unknown category '{category_name}'")
        return cat_idx

    def _filter_households_by_patterns(self, target_patterns: List[str],
                                       pattern_property: str = 'original_pattern') -> List[Household]:
        """
        Filter households by matching patterns.

        Args:
            target_patterns: List of patterns to match
            pattern_property: Property key to check (default: 'original_pattern')

        Returns:
            List of households matching the target patterns
        """
        filtered = []
        for household in self.households:
            pattern = household.properties.get(pattern_property, '')
            if pattern in target_patterns:
                filtered.append(household)
        return filtered

    def _setup_allocation_logging(self, area_code: str) -> int:
        """
        Initialize and update allocation logging for a geographical unit.

        This tracks how many households have been allocated in each area and logs
        the start of allocation for new areas.

        Args:
            area_code: The geographical unit code

        Returns:
            The household number for this area (1-indexed)
        """
        # Initialize logging dict if needed
        if not hasattr(self, '_household_counts_by_area_log'):
            self._household_counts_by_area_log = {}

        # Log start of allocation for new area
        if area_code not in self._household_counts_by_area_log:
            self._household_counts_by_area_log[area_code] = 0
            logger.debug("")
            logger.debug("=" * 80)
            logger.debug(f"STARTING DETAILED ALLOCATION FOR GEO UNIT: {area_code}")
            logger.debug("=" * 80)
            logger.debug("")

        # Increment and return household count
        self._household_counts_by_area_log[area_code] += 1
        return self._household_counts_by_area_log[area_code]

    def _allocate_balanced_distribution(self, pattern: CompositionPattern,
                                       pools: List[List[Person]],
                                       target_size: int) -> Tuple[Optional[List[Tuple[int, int]]], Optional[int]]:
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
        for cat_idx in range(len(self.age_categories)):
            min_count = pattern.get_min_count(cat_idx)
            max_count = pattern.get_max_count(cat_idx)
            available = len(pools[cat_idx])

            cat_name = self.age_categories[cat_idx].name
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
            cat_name = self.age_categories[cat_idx].name
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
                    cat_name = self.age_categories[cat_idx].name
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

    def _log_round_start(self, round_name: Optional[str], default_prefix: str) -> str:
        """
        Log the start of an allocation round with standardized formatting.

        Args:
            round_name: Custom round name (optional)
            default_prefix: Default prefix if no custom name provided

        Returns:
            The round label used for logging
        """
        self.current_round += 1
        round_label = round_name or f"{default_prefix} {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting {default_prefix.lower()}: {round_label}")
        logger.info("=" * 60)

        return round_label

    def _log_round_summary(self, round_label: str, stats: Dict, show_remaining: bool = True):
        """
        Log summary statistics for an allocation round.

        Args:
            round_label: Name of the round
            stats: Statistics dictionary with round results
            show_remaining: If True, show remaining people by category
        """
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")

        # Log round-specific metrics based on what's in stats
        if 'households_created' in stats:
            logger.info(f"  Households created: {stats['households_created']:,}")
        if 'households_modified' in stats:
            logger.info(f"  Households modified: {stats['households_modified']:,}")
        if 'households_promoted' in stats:
            logger.info(f"  Households promoted: {stats['households_promoted']:,}")
        if 'people_added' in stats:
            logger.info(f"  People added: {stats['people_added']:,}")
        if 'people_allocated_this_round' in stats:
            logger.info(f"  People allocated this round: {stats['people_allocated_this_round']:,}")
        if 'households_with_demotion' in stats and stats['households_with_demotion'] > 0:
            logger.info(f"  Households using demotion: {stats['households_with_demotion']:,}")

        # Always show totals
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")

        # Show remaining by category if requested
        if show_remaining:
            remaining_by_category = self.get_available_people_by_category()
            logger.info("")
            logger.info("  Remaining by category:")
            for cat_name in [cat.name for cat in self.age_categories]:
                count = remaining_by_category.get(cat_name, 0)
                logger.info(f"    {cat_name}: {count:,}")

        logger.info("=" * 60)

    def _allocate_person_to_household(self, household: Household, person: Person,
                                      pool: Optional[List[Person]] = None):
        """
        Add person to household, mark as allocated, and optionally remove from pool.

        Args:
            household: Household to add person to
            person: Person to add
            pool: Optional pool to remove person from (modifies list in-place)
        """
        household.add_resident(person)
        self.allocated_people.add(person.id)

        # Remove from pool if provided
        if pool is not None:
            for i, p in enumerate(pool):
                if p.id == person.id:
                    pool.pop(i)
                    break

    def allocate_excess_to_households(self, *args, **kwargs):
        """Delegate to excess handler. See HouseholdExcessHandler.allocate_excess_to_households for documentation."""
        return self.excess_handler.allocate_excess_to_households(*args, **kwargs)

    def allocate_overflow_to_households(self, *args, **kwargs):
        """Delegate to excess handler. See HouseholdExcessHandler.allocate_overflow_to_households for documentation."""
        return self.excess_handler.allocate_overflow_to_households(*args, **kwargs)

    def promote_and_allocate(self,
                            target_categories: List[str],
                            refresh_pools: bool = False,
                            round_name: Optional[str] = None):
        """
        Promote existing households to accommodate remaining people.

        This method:
        1. Identifies areas with remaining people in target categories
        2. Promotes household patterns in those areas (0 -> >=0, 1 -> >=1, etc.)
        3. Allocates ALL remaining people to the promoted households

        Args:
            target_categories: List of category names to allocate (e.g., ["Young Adults", "Adults"])
            refresh_pools: If True, refresh person pools
            round_name: Optional name for this round (for logging)

        Returns:
            dict: Statistics about this promotion allocation
        """
        round_label = self._log_round_start(round_name, "Promotion Allocation Round")
        logger.info(f"Target categories: {target_categories}")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self._prepare_person_pools(refresh=True)

        # Get promotion config
        promotion_config = self.config.get('promotion', {})
        if not promotion_config.get('enabled', False):
            logger.warning("Promotion is disabled in config")
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_promoted': 0
            }

        # Get priority order
        priority_config = promotion_config.get('priority', {})
        promotion_priority = []
        for cat_idx, cat in enumerate(self.age_categories):
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
            cat_idx = self._validate_category_index(category_name, log_level="warning")
            if cat_idx is None:
                logger.info("Skipping category")
                continue

            logger.info(f"Processing category: {category_name}")

            # Find areas with people in this category
            for area_code, pools in self.person_pool_by_area.items():
                available_people = pools[cat_idx]

                if not available_people:
                    continue

                logger.debug(f"  Area {area_code}: {len(available_people)} {category_name} available")

                # Find households in this area
                area_households = [hh for hh in self.households if hh.geographical_unit.name == area_code]

                if not area_households:
                    logger.debug(f"    No households in area {area_code}")
                    continue

                # Try to promote and allocate to each household
                random.shuffle(area_households)  # For fairness

                for household in area_households:
                    if not available_people:
                        break

                    # Check if this household can accommodate this category
                    pattern_str = household.properties.get('actual_pattern', '')
                    pattern = CompositionPattern.from_string(pattern_str)

                    # Try promotion if needed
                    current_pattern = pattern
                    promoted = False

                    for attempt in range(max_attempts + 1):
                        # Can we add someone from this category?
                        min_count = current_pattern.get_min_count(cat_idx)
                        current_count = household.get_composition().get(category_name, 0)

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
                                validation_rules, self.category_name_to_idx
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
                        household.properties['actual_pattern'] = current_pattern.to_string()
                        households_promoted_count += 1
                        promoted_households.add(household.id)
                        logger.debug(f"    Promoted household {household.id}: {pattern_str} -> {current_pattern.to_string()}")

                    # Now try to add people
                    max_count = current_pattern.get_max_count(cat_idx)
                    current_count = household.get_composition().get(category_name, 0)

                    # Determine how many we can add
                    if max_count is None:  # Flexible
                        # Add as many as available (greedy)
                        can_add = len(available_people)
                    else:  # Fixed
                        can_add = max(0, max_count - current_count)

                    # Add people
                    added_to_this = 0
                    for _ in range(can_add):
                        if not available_people:
                            break

                        person = available_people.pop(0)
                        household.add_resident(person)
                        self.allocated_people.add(person.id)
                        added_to_this += 1
                        people_added += 1

                    if added_to_this > 0:
                        logger.debug(f"    Added {added_to_this} {category_name} to household {household.id}")

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.current_round,
            'people_added': people_added,
            'households_promoted': households_promoted_count,
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households promoted: {households_promoted_count:,}")
        logger.info(f"  People added: {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.age_categories]:
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
        round_label = self._log_round_start(round_name, "Rule-Based Promotion Round")
        logger.info(f"Number of promotion rules: {len(promotion_rules)}")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self._prepare_person_pools(refresh=True)

        # Track statistics
        people_added = 0
        households_promoted_count = 0
        promoted_households = set()

        # Process each rule
        for rule_idx, rule in enumerate(promotion_rules):
            source_pattern = rule.get('source_pattern')
            target_pattern_str = rule.get('target_pattern')
            accept_categories = rule.get('accept_categories', [])
            max_to_add = rule.get('max_to_add')

            if not source_pattern or not target_pattern_str:
                logger.warning(f"Rule {rule_idx}: Missing source_pattern or target_pattern, skipping")
                continue

            # Parse target pattern to understand constraints
            target_pattern = CompositionPattern.from_string(target_pattern_str)

            logger.info(f"Rule {rule_idx + 1}: {source_pattern} → {target_pattern_str} (categories: {accept_categories})")

            # Find households matching source pattern
            for household in self.households:
                actual_pattern = household.properties.get('actual_pattern', '')

                if actual_pattern != source_pattern:
                    continue

                area_code = household.geographical_unit.name

                if area_code not in self.person_pool_by_area:
                    continue

                pools = self.person_pool_by_area[area_code]

                # Try to add people from each accepted category
                added_to_this_household = 0

                for category_name in accept_categories:
                    cat_idx = self._validate_category_index(category_name, log_level=None)
                    if cat_idx is None:
                        continue

                    available_people = pools[cat_idx]
                    if not available_people:
                        continue

                    # Get current count in this category
                    current_composition = household.get_composition()
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
                        household.properties['actual_pattern'] = target_pattern_str
                        households_promoted_count += 1
                        promoted_households.add(household.id)
                        logger.debug(f"  Promoted household {household.id}: {source_pattern} → {target_pattern_str}")

                    # Add people
                    for _ in range(category_can_add):
                        if not available_people:
                            break
                        if max_to_add is not None and added_to_this_household >= max_to_add:
                            break

                        person = available_people.pop(0)
                        household.add_resident(person)
                        self.allocated_people.add(person.id)
                        added_to_this_household += 1
                        people_added += 1

                if added_to_this_household > 0:
                    logger.debug(f"  Added {added_to_this_household} people to household {household.id}")

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.current_round,
            'people_added': people_added,
            'households_promoted': households_promoted_count,
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households promoted: {households_promoted_count:,}")
        logger.info(f"  People added: {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.age_categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats

    def _sample_from_distribution(self, distribution_config: Dict) -> int:
        """
        Sample a number from a configured distribution.

        Args:
            distribution_config: Distribution configuration dict

        Returns:
            int: Number sampled from the distribution
        """
        dist_type = distribution_config.get('type', 'weighted')

        if dist_type == 'weighted':
            # Weighted discrete distribution
            probs = distribution_config.get('probabilities', {})

            # Convert string keys to integers and normalize probabilities
            values = []
            weights = []
            for k, v in probs.items():
                values.append(int(k))
                weights.append(float(v))

            # Normalize weights
            total_weight = sum(weights)
            if total_weight == 0:
                return 0

            normalized_weights = [w / total_weight for w in weights]

            # Sample using random.choices
            return random.choices(values, weights=normalized_weights, k=1)[0]

        elif dist_type == 'poisson':
            # Zero-truncated Poisson distribution, capped at max value
            mean = distribution_config.get('mean', 1.0)
            max_val = distribution_config.get('max', 10)  # Default cap at 10
            min_val = distribution_config.get('min', 0)   # Default min at 0 (allow zero)

            # Calculate probabilities for each value
            values = list(range(min_val, max_val + 1))

            # Poisson PMF: P(X=k) = (λ^k * e^(-λ)) / k!
            λ = mean
            probs = []
            for n in values:
                if n == 0 and min_val == 0:
                    # Include zero
                    p = np.exp(-λ)
                else:
                    p = np.exp(-λ) * (λ ** n) / math.factorial(n)
                probs.append(p)

            # Normalize probabilities
            probs = np.array(probs)
            probs = probs / np.sum(probs)

            # Sample from distribution
            return np.random.choice(values, p=probs)

        elif dist_type == 'normal':
            # Normal (Gaussian) distribution
            mean = distribution_config.get('mean', 1.0)
            std = distribution_config.get('std', 0.5)

            # Sample from normal distribution
            value = random.gauss(mean, std)

            # Ensure non-negative and round
            return max(0, int(round(value)))

        else:
            logger.warning(f"Unknown distribution type '{dist_type}', defaulting to 0")
            return 0

    def _check_constraints_if_added(self, household: Household, add_category: str,
                                     constraints: List[Dict]) -> bool:
        """
        Check if adding one more person of add_category would violate constraints.

        Args:
            household: Household to check
            add_category: Category of person being added
            constraints: List of constraint dicts

        Returns:
            bool: True if adding is allowed, False if it would violate constraints
        """
        # Get current composition
        current_composition = household.get_composition()

        # Simulate adding one more person
        simulated_composition = dict(current_composition)
        simulated_composition[add_category] = simulated_composition.get(add_category, 0) + 1

        # Check each constraint
        for constraint in constraints:
            # Category sum constraint
            if 'category_sum' in constraint:
                categories = constraint['category_sum']
                max_sum = constraint.get('max')

                if max_sum is not None:
                    current_sum = sum(simulated_composition.get(cat, 0) for cat in categories)
                    if current_sum > max_sum:
                        logger.debug(f"  Constraint violated: sum({categories}) = {current_sum} > {max_sum}")
                        return False

            # Single category constraint
            elif 'category' in constraint:
                category = constraint['category']
                max_count = constraint.get('max')

                if max_count is not None:
                    current_count = simulated_composition.get(category, 0)
                    if current_count > max_count:
                        logger.debug(f"  Constraint violated: {category} = {current_count} > {max_count}")
                        return False

            # Household size constraint
            elif 'household_size' in constraint:
                max_size = constraint.get('max')

                if max_size is not None:
                    current_size = sum(simulated_composition.values())
                    if current_size > max_size:
                        logger.debug(f"  Constraint violated: household size = {current_size} > {max_size}")
                        return False

        return True

    def export_households_to_csv(self, output_file: str = "household_allocations.csv"):
        """
        Export all household data to a CSV file.

        Creates a detailed CSV with:
        - Household ID
        - Geographical unit
        - Original pattern (from census data)
        - Actual composition (by age category)
        - Household size
        - List of residents with age and sex

        Args:
            output_file: Path to output CSV file
        """
        logger.info(f"Exporting household data to {output_file}...")

        rows = []
        for household in self.households:
            # Get composition
            composition = household.get_composition()
            composition_str = ", ".join([f"{cat}: {count}" for cat, count in composition.items()])

            # Get original pattern
            original_pattern = household.properties.get('original_pattern', 'unknown')

            # Get resident details
            resident_details = []
            for person in household.residents:
                resident_details.append(f"Person_{person.id}(age={person.age},sex={person.sex})")
            residents_str = "; ".join(resident_details)

            # Create row
            row = {
                'household_id': household.id,
                'geo_unit': household.geographical_unit.name,
                'original_pattern': original_pattern,
                'actual_composition': composition_str,
                'household_size': household.size(),
                'num_kids': composition.get('Kids', 0),
                'num_young_adults': composition.get('Young Adults', 0),
                'num_adults': composition.get('Adults', 0),
                'num_old_adults': composition.get('Old Adults', 0),
                'residents': residents_str
            }
            rows.append(row)

        # Create DataFrame and export
        df = pd.DataFrame(rows)
        output_path = os.path.join(self.data_dir, output_file)
        df.to_csv(output_path, index=False)

        logger.info(f"Exported {len(rows)} households to {output_path}")
        return output_path
