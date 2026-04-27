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
import math
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Set, Any
from itertools import islice
from collections import defaultdict

from may.geography.geography import Geography
from may.geography.venue import Venue
from may.geography.venue_manager import VenueManager
from may.population.person import Person
from may.population.population import PopulationManager
from may.residence.relationship_rules import RelationshipRulesValidator
from may.residence.models import Category
from may.residence.composition_pattern import CompositionPattern
from may.residence.household_excess_handler import HouseholdExcessHandler
from may.residence.household_promoter import HouseholdPromoter
from may.residence.household_round_distributor import HouseholdRoundDistributor
from may.utils.attribute_access import get_person_attribute

logger = logging.getLogger("household")


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
                 venue_manager: VenueManager,
                 data_dir, config_file):
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
        self.venue_manager = venue_manager
        self.data_dir = data_dir

        # Load configuration
        # Try relative to current working directory first, then relative to data_dir
        if os.path.isabs(config_file) or os.path.exists(config_file):
            config_path = config_file
        else:
            config_path = os.path.join(data_dir, config_file)

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Parse categories from config
        self.categories = self._parse_categories()

        # Create mapping from category name to index for validation rules
        self.category_name_to_idx = {cat.name: idx for idx, cat in enumerate(self.categories)}

        # Household data - now stored in VenueManager
        self.household_counts_by_geo_unit: Dict[str, Dict[str, int]] = {}
        self.allocated_people: Set[int] = set()  # Person IDs that have been allocated

        # Pool of available people by geo_unit and category
        self.person_pool_by_geo_unit: Dict[str, List[Dict[int, 'Person']]] = {}

        # Round tracking
        self.current_round: int = 0
        self.pools_prepared: bool = False

        # Initialize relationship rules validator
        # Look for relationship_rules.yaml in the same directory as config_file
        config_dir = os.path.dirname(config_path)
        rules_config_path = os.path.join(config_dir, "relationship_rules.yaml")
        if not os.path.exists(rules_config_path):
            # Fallback to data_dir if not found next to config
            rules_config_path = os.path.join(data_dir, "relationship_rules.yaml")

        self.relationship_rules = RelationshipRulesValidator(
            categories=self.categories,
            config_file=rules_config_path,
            geography=self.geography,
        )

        # Initialize excess handler
        self.excess_handler = HouseholdExcessHandler(self)

        # Initialize promoter
        self.promoter = HouseholdPromoter(self)

        self.round_distributor = HouseholdRoundDistributor(self)

        # Pre-calculate demotion fallback priority
        priority_config = self.config.get('demotion', {}).get('priority', {})
        priority_order = []
        for cat_idx, cat in enumerate(self.categories):
            priority = priority_config.get(cat.name, 999)
            priority_order.append((priority, cat_idx))
        priority_order.sort()  # Sort by priority (lower = demote first)
        self.fallback_priority = [idx for _, idx in priority_order]

        logger.info(f"Initialized HouseholdDistributor with {len(self.categories)} categories")
        for cat in self.categories:
            logger.info(f"  - {cat}")

    def _parse_categories(self) -> List[Category]:
        """Parse categories from config."""
        categories = []
        for cat_config in self.config['categories']:
            cat_type = cat_config['type']

            # Extract type-specific parameters from nested structure
            if cat_type == 'numerical':
                numerical_config = cat_config.get('numerical', {})
                min_value = numerical_config.get('min')
                max_value = numerical_config.get('max')
                allowed_values = None
            elif cat_type == 'categorical':
                categorical_config = cat_config.get('categorical', {})
                min_value = None
                max_value = None
                allowed_values = categorical_config.get('allowed_values')
            else:
                raise ValueError(f"Unknown category type: {cat_type}")

            cat = Category(
                name=cat_config['name'],
                symbol=cat_config['symbol'],
                attribute=cat_config['attribute'],
                type=cat_type,
                min_value=min_value,
                max_value=max_value,
                allowed_values=allowed_values
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

        # Get the smallest geographical level from the loaded geography
        # to filter household data to only relevant geo units
        smallest_level = self.geography.levels[0]
        smallest_units_dict = self.geography.get_units_by_level(smallest_level)

        if not smallest_units_dict:
            logger.warning(f"No {smallest_level} units found in geography. Cannot load household data.")
            return

        # Create a set of geo unit names that exist in our geography for fast lookup
        valid_geo_units = set(smallest_units_dict.keys())
        logger.info(f"Filtering household data to {len(valid_geo_units)} {smallest_level}s in loaded geography")

        df = pd.read_csv(filepath)

        # First column is the geo_unit code, rest are household compositions
        geo_unit_col = df.columns[0]
        composition_cols = df.columns[1:]

        # Filter to only geo units in our geography BEFORE processing
        df = df[df[geo_unit_col].isin(valid_geo_units)]

        logger.info(f"Filtered to {len(df)} geo_units with {len(composition_cols)} household types")

        # Store household counts by geo_unit
        for _, row in df.iterrows():
            geo_unit_code = row[geo_unit_col]

            counts = {}
            for col in composition_cols:
                count = int(row[col])
                if count > 0:
                    counts[col] = count

            if counts:
                self.household_counts_by_geo_unit[geo_unit_code] = counts

        logger.info(f"Loaded household data for {len(self.household_counts_by_geo_unit)} geographical units")

    def _categorize_person(self, person: Person) -> int:
        """Get the category index for a person based on their attributes."""
        for idx, cat in enumerate(self.categories):
            attr = cat.attribute
            val = get_person_attribute(person, attr)
            
            if val is None:
                continue

            if cat.type == 'numerical':
                if (cat.min_value is None or val >= cat.min_value) and \
                   (cat.max_value is None or val <= cat.max_value):
                    return idx
            elif cat.type == 'categorical':
                if cat.allowed_values is None or val in cat.allowed_values:
                    return idx
        
    def _get_person_category_idx(self, person: Person) -> int:
        """Helper to get category index for a person."""
        return self._categorize_person(person)

    def _prepare_person_pools(self, refresh: bool = False):
        """
        Prepare pools of available people by geo_unit and age category.

        Args:
            refresh: If True, refresh pools with currently unallocated people.
                    If False and pools already exist, skip preparation.
        """
        if self.pools_prepared and not refresh:
            logger.debug("Person pools already prepared, skipping...")
            return

        logger.info("Preparing person pools by geo_unit and age category...")

        if refresh:
            # Clear existing pools for refresh
            self.person_pool_by_geo_unit = {}

        # Get all units at the smallest geographical level
        smallest_level = self.geography.levels[0]
        sgu_units = self.geography.get_units_by_level(smallest_level)
        total_units = len(sgu_units)

        # Progress indicator configuration
        progress_interval = max(1, total_units // 10)  # Update every 10% or at least every unit

        for idx, (geo_unit_code, unit) in enumerate(sgu_units.items(), 1):
            # Get all people in this geo_unit
            people = self.population.get_people_by_geo_unit(geo_unit_code)

            if not people:
                continue

            # Initialize category pools as dictionaries
            # We shuffle the list of people first to maintain randomness in the dictionary order
            # (which is preserved in Python 3.7+)
            category_pools = [{} for _ in self.categories]

            # Shuffling people ensures random dictionary order
            np.random.shuffle(people)

            # Categorize each person (only if not already allocated)
            for person in people:
                if person.id not in self.allocated_people:
                    cat_idx = self._categorize_person(person)
                    category_pools[cat_idx][person.id] = person

            self.person_pool_by_geo_unit[geo_unit_code] = category_pools

            # Log pool sizes
            pool_sizes = [len(pool) for pool in category_pools]
            logger.debug(f"  {geo_unit_code}: {pool_sizes}")

            # Progress indicator - log every 10% or at key milestones
            if idx % progress_interval == 0 or idx == total_units:
                percent_complete = (idx / total_units) * 100
                logger.info(f"  Progress: {idx}/{total_units} geo_units processed ({percent_complete:.1f}%)")

        total_people = sum(sum(len(pool) for pool in pools)
                          for pools in self.person_pool_by_geo_unit.values())
        logger.info(f"Prepared person pools for {len(self.person_pool_by_geo_unit)} geo_units ({total_people} total people)")
        self.pools_prepared = True

    def _allocate_household_with_rules(self, geo_unit_code: str, pattern: CompositionPattern,
                                       max_size: Optional[int] = None,
                                       allocate_flexible: bool = False,
                                       target_size: Optional[int] = None,
                                       rule_name: Optional[str] = None) -> Tuple[Optional[Venue], Optional[int]]:
        """
        Allocate a household using relationship rules.

        This method follows the role-based selection order defined in relationship_rules.yaml:
        1. Select people for each role in order (e.g., kids first, then adults)
        2. Apply age difference constraints between roles
        3. Apply couple matching constraints within roles

        Args:
            geo_unit_code: SGU code
            pattern: Composition pattern to match
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories
            target_size: Target household size for balanced distribution (optional)
            rule_name: Optional rule name to use (overrides auto-matching)

        Returns:
            Tuple of (Venue object if successful or None, failed_category_idx or None)
        """
        # If no rule is specified, use simple allocation (no rules)
        if not rule_name:
            return self._allocate_household(geo_unit_code, pattern, max_size, allocate_flexible, target_size)

        # Get pattern to match (for logging)
        pattern_to_match = getattr(pattern, 'census_pattern', pattern.original_pattern)

        # Use explicitly specified rule
        rule = self.relationship_rules.get_rule_by_name(rule_name)
        if not rule:
            logger.warning(f"Rule '{rule_name}' not found, falling back to simple allocation")
            return self._allocate_household(geo_unit_code, pattern, max_size, allocate_flexible, target_size)

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

        if geo_unit_code not in self.person_pool_by_geo_unit:
            return (None, None)

        pools = self.person_pool_by_geo_unit[geo_unit_code]

        # Detailed logging for ALL households in ALL geo units
        household_num = self._setup_allocation_logging(geo_unit_code)
        logger.debug("=" * 80)
        logger.debug(f"GEO UNIT: {geo_unit_code} - HOUSEHOLD #{household_num}")
        if hasattr(pattern, 'census_pattern'):
            logger.debug(f"Census Pattern: '{pattern.census_pattern}'")
            logger.debug(f"Assumption: '{pattern.original_pattern}'")
        else:
            logger.debug(f"Pattern: '{pattern.to_string()}'")
        logger.debug("=" * 80)
        logger.debug(f"Rule: {rule.name}")
        logger.debug(f"Selection order: {' → '.join(rule.selection_order)}")
        logger.debug("")
        self._show_detailed_logs = logger.isEnabledFor(logging.DEBUG)

        # Get backtracking config
        backtrack_config = self.relationship_rules.selection_strategy.get('backtracking', {})

        # Use backtracking algorithm to select people for all roles
        selected_by_role, failed_cat_idx = self._select_roles_with_backtracking(
            rule, pattern, pools, backtrack_config, self._show_detailed_logs,
            geo_unit_code=geo_unit_code,
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
        self.allocated_people.update(selected_ids)
        
        for p in all_selected:
            cat_idx = self._get_person_category_idx(p)
            try:
                del pools[cat_idx][p.id]
            except KeyError:
                pass # Already removed or not in pool

        # Create household as Venue (ID auto-generated)
        unit = self.geography.get_unit(geo_unit_code)
        household = self.venue_manager.create_venue(
            venue_type="household",
            geo_unit=unit,
            properties={
                'original_pattern': pattern.original_pattern,
                'actual_pattern': pattern.to_string(),
                '_age_categories': self.categories
            }
        )

        # Add residents to venue subset (with category name as subset_key)
        for person in all_selected:
            category_name = self._get_person_category_name(person)
            household.add_to_subset(person, subset_key=category_name)
            self.allocated_people.add(person.id)

        if self._show_detailed_logs:
            logger.debug("FINAL HOUSEHOLD COMPOSITION:")
            logger.debug(f"  Household ID: {household.id}")
            logger.debug(f"  Geo Unit: {geo_unit_code}")
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
        # Get candidates from these categories (use .values() for dict-based pools)
        candidates = []
        for cat_idx in category_indices:
            candidates.extend(pools[cat_idx].values())

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
                                       show_detailed_logs: bool,
                                       geo_unit_code: Optional[str] = None) -> Tuple[Optional[Dict[str, List[Person]]], Optional[int]]:
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
            couples_to_flag = []  # Defer property assignment until success

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

                    # Pre-group candidates by categorical attribute
                    cat_attr = pair_constraint.get('categorical_attribute', {}).get('attribute', 'sex')
                    cat_getter = self.relationship_rules._get_attribute_getter(cat_attr)
                    candidates_by_cat = defaultdict(list)
                    for p in candidates:
                        candidates_by_cat[cat_getter(p)].append(p)

                    pair = self.relationship_rules.select_pair(
                        candidates,
                        pair_constraint,
                        existing_people_by_role=selected_by_role,
                        constraints=rule.constraints,
                        current_role=role_name,
                        show_detailed_logs=show_detailed_logs,
                        candidates_by_cat=candidates_by_cat,
                        geo_unit_code=geo_unit_code,
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

                    # Check if this pair should be flagged as a romantic couple
                    if pair_constraint.get('creates_romantic_couple', False):
                        couples_to_flag.append(pair)

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

            # Now that success is certain, apply relationship flagging
            for p0, p1 in couples_to_flag:
                p0.properties['cohabiting_couple'] = [p1.id]
                p1.properties['cohabiting_couple'] = [p0.id]

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

        for cat_idx in range(len(self.categories)):
            min_count = pattern.get_min_count(cat_idx)
            max_count = pattern.get_max_count(cat_idx)
            available = len(pools[cat_idx])

            cat_name = self.categories[cat_idx].name
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
                        count = np.random.randint(min_count, max_allocatable + 1)  # numpy's randint is exclusive of upper bound
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

    def _allocate_household(self, geo_unit_code: str, pattern: CompositionPattern,
                            max_size: Optional[int] = None,
                            allocate_flexible: bool = False,
                            target_size: Optional[int] = None) -> Tuple[Optional[Venue], Optional[int]]:
        """
        Attempt to allocate a household in an geo_unit with the given pattern.

        Args:
            geo_unit_code: SGU code
            pattern: Composition pattern to match
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories randomly

        Returns:
            Tuple of (Venue object if successful or None, failed_category_idx or None)
            - If successful: (household, None)
            - If failed: (None, category_idx that caused failure)
        """
        if geo_unit_code not in self.person_pool_by_geo_unit:
            return (None, None)

        pools = self.person_pool_by_geo_unit[geo_unit_code]

        # Detailed logging for ALL households in ALL geo units (NO RULES version)
        household_num = self._setup_allocation_logging(geo_unit_code)
        logger.debug("=" * 80)
        logger.debug(f"GEO UNIT: {geo_unit_code} - HOUSEHOLD #{household_num}")
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
            selections, failed_cat = self.round_distributor._allocate_balanced_distribution(pattern, pools, target_size)
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
            cat = self.categories[cat_idx]
            logger.debug(f"  {cat.name} ({cat.attribute} {cat.min_value}-{cat.max_value if cat.max_value else '∞'}): {count} people")
            if count > 0:
                pool = pools[cat_idx]
                # Take N IDs from the front of the dictionary
                # Dict preserves order in Python 3.7+, so this is equivalent to list slicing
                ids_to_remove = list(islice(pool.keys(), count))
                
                for pid in ids_to_remove:
                    person = pool.pop(pid)
                    selected_people.append(person)
                    logger.debug(f"    - {person}")

        if not selected_people:
            logger.debug("  ✗ FAILED: No people selected")
            logger.debug("")
            return (None, None)

        logger.debug("")
        logger.debug("FINAL HOUSEHOLD COMPOSITION:")
        logger.debug(f"  Total members: {len(selected_people)}")
        logger.debug(f"  Pattern: {pattern.original_pattern}")

        # Create household as Venue (ID auto-generated)
        unit = self.geography.get_unit(geo_unit_code)
        household = self.venue_manager.create_venue(
            venue_type="household",
            geo_unit=unit,
            properties={
                'original_pattern': pattern.original_pattern,  # The original requested pattern
                'actual_pattern': pattern.to_string(),  # The actual pattern used (may be demoted)
                '_age_categories': self.categories
            }
        )

        # Add residents to venue subset (with category name as subset_key)
        for person in selected_people:
            category_name = self._get_person_category_name(person)
            household.add_to_subset(person, subset_key=category_name)
            self.allocated_people.add(person.id)

        logger.debug(f"  ✓ Household {household.id} created successfully")
        logger.debug("=" * 80)
        logger.debug("")

        return (household, None)

    def _attempt_with_demotion(self, geo_unit_code: str, pattern: CompositionPattern,
                               max_attempts: int, max_size: Optional[int] = None,
                               allocate_flexible: bool = False,
                               target_size: Optional[int] = None,
                               rule_name: Optional[str] = None,
                               demotion_rules: Optional[Dict[str, str]] = None) -> Optional[Venue]:
        """
        Attempt to allocate a household, using intelligent demotion if necessary.

        Demotion strategy:
        - Tries to demote the category that actually caused the failure
        - Falls back to configured priority order if failure category can't be demoted
        - Can switch to a different rule when pattern matches a demotion_rules mapping

        Args:
            geo_unit_code: SGU code
            pattern: Initial composition pattern
            max_attempts: Maximum demotion attempts
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories randomly
            rule_name: Optional relationship rule name to apply (overrides auto-matching)
            demotion_rules: Optional dict mapping pattern strings to rule names for demoted patterns

        Returns:
            Venue object if successful, None otherwise
        """
        # Fallback priority is pre-calculated in __init__
        fallback_priority = self.fallback_priority

        current_pattern = pattern

        for attempt in range(max_attempts + 1):
            if attempt > 0:
                logger.debug(f"  ⚠️  DEMOTION ATTEMPT #{attempt}: Trying pattern '{current_pattern.to_string()}'")

            # Try to allocate with current pattern
            # First try with relationship rules if available
            household, failed_category_idx = self._allocate_household_with_rules(
                geo_unit_code, current_pattern, max_size, allocate_flexible, target_size, rule_name
            )

            # If rules-based allocation returned None and called the fallback,
            # the fallback already tried regular allocation, so we're done
            if household:
                if attempt > 0:
                    logger.debug(f"  ✓ Succeeded after {attempt} demotion(s) with pattern: {current_pattern.to_string()}")
                    logger.debug("")
                return household

            if failed_category_idx is not None:
                cat = self.categories[failed_category_idx]
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
                    if geo_unit_code in self.person_pool_by_geo_unit:
                        pools = self.person_pool_by_geo_unit[geo_unit_code]
                        if failed_category_idx < len(pools):
                            available_count = len(pools[failed_category_idx])

                    # Demote directly to available count instead of one-by-one
                    new_pattern = current_pattern.demote_to_count(failed_category_idx, available_count)

                # If intelligent demotion didn't work, try fallback priority order
                if new_pattern is None:
                    logger.debug(f"  → Intelligent demotion failed, trying fallback priority order")
                    new_pattern = current_pattern.demote_once(fallback_priority)

                    if new_pattern is None:
                        logger.debug(f"  ✗ Cannot demote further: {current_pattern.to_string()}")
                        logger.debug("")
                        return None

                # Safety checks apply to ALL demoted patterns (both intelligent and fallback)
                # Check if the demoted pattern would result in a too-small household
                min_size = self.config['demotion']['min_household_size']
                if new_pattern.min_household_size() < min_size:
                    logger.debug(f"  ✗ Demoted pattern too small (min size {min_size}): '{new_pattern.to_string()}'")
                    logger.debug(f"  ✗ Skipping allocation attempt - would result in empty household")
                    logger.debug("")
                    return None

                # Validate the new pattern against demotion validation rules
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


    def get_available_people_count(self) -> int:
        """Get the number of people currently available (not allocated)."""
        return len(self.population.get_all_people()) - len(self.allocated_people)

    def get_available_people_by_category(self) -> Dict[str, int]:
        """Get counts of available people by category."""
        counts = {cat.name: 0 for cat in self.categories}

        for person in self.population.get_all_people():
            if person.id not in self.allocated_people:
                for cat in self.categories:
                    if cat.matches(person):
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


    def _select_person_for_excess_with_rule(self, *args, **kwargs):
        """Delegate to excess handler. See HouseholdExcessHandler._select_person_for_excess_with_rule for documentation."""
        return self.excess_handler._select_person_for_excess_with_rule(*args, **kwargs)

    def _get_person_category_name(self, person: 'Person') -> str:
        """Get the category name for a person based on their attributes."""
        for cat in self.categories:
            if cat.matches(person):
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
                                       pattern_property: str = 'original_pattern') -> List[Venue]:
        """
        Filter households by matching patterns.

        Args:
            target_patterns: List of patterns to match
            pattern_property: Property key to check (default: 'original_pattern')

        Returns:
            List of households matching the target patterns
        """
        # Get all household venues from VenueManager
        all_households = self.venue_manager.get_venues_by_type("household")

        filtered = []
        for household in all_households:
            pattern = household.properties.get(pattern_property, '')
            if pattern in target_patterns:
                filtered.append(household)
        return filtered

    def _setup_allocation_logging(self, geo_unit_code: str) -> int:
        """
        Initialize and update allocation logging for a geographical unit.

        This tracks how many households have been allocated in each geo_unit and logs
        the start of allocation for new geo_units.

        Args:
            geo_unit_code: The geographical unit code

        Returns:
            The household number for this geo_unit (1-indexed)
        """
        # Initialize logging dict if needed
        if not hasattr(self, '_household_counts_by_geo_unit_log'):
            self._household_counts_by_geo_unit_log = {}

        # Log start of allocation for new geo_unit
        if geo_unit_code not in self._household_counts_by_geo_unit_log:
            self._household_counts_by_geo_unit_log[geo_unit_code] = 0
            logger.debug("")
            logger.debug("=" * 80)
            logger.debug(f"STARTING DETAILED ALLOCATION FOR GEO UNIT: {geo_unit_code}")
            logger.debug("=" * 80)
            logger.debug("")

        # Increment and return household count
        self._household_counts_by_geo_unit_log[geo_unit_code] += 1
        return self._household_counts_by_geo_unit_log[geo_unit_code]


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
            for cat_name in [cat.name for cat in self.categories]:
                count = remaining_by_category.get(cat_name, 0)
                logger.info(f"    {cat_name}: {count:,}")

        logger.info("=" * 60)

    def _allocate_person_to_household(self, household: Venue, person: Person,
                                      pool: Optional[List[Person]] = None):
        """
        Add person to household, mark as allocated, and optionally remove from pool.

        Args:
            household: Household venue to add person to
            person: Person to add
            pool: Optional pool to remove person from (modifies list in-place)
        """
        category_name = self._get_person_category_name(person)
        household.add_to_subset(person, subset_key=category_name)
        self.allocated_people.add(person.id)

        # Remove from pool if provided
        if pool is not None:
            if isinstance(pool, dict):
                pool.pop(person.id, None)
            else:
                # Fallback for list-based pools
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

    def promote_and_allocate(self, *args, **kwargs):
        """Delegate to promoter. See HouseholdPromoter.promote_and_allocate for documentation."""
        return self.promoter.promote_and_allocate(*args, **kwargs)

    def promote_with_rules(self, *args, **kwargs):
        """Delegate to promoter. See HouseholdPromoter.promote_with_rules for documentation."""
        return self.promoter.promote_with_rules(*args, **kwargs)

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

            # Sample using numpy choice
            return np.random.choice(values, p=normalized_weights)

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
            value = np.random.normal(mean, std)

            # Ensure non-negative and round
            return max(0, int(round(value)))

        else:
            logger.warning(f"Unknown distribution type '{dist_type}', defaulting to 0")
            return 0

    def _check_constraints_if_added(self, household: Venue, add_category: str,
                                     constraints: List[Dict]) -> bool:
        """
        Check if adding one more person of add_category would violate constraints.

        Args:
            household: Household venue to check
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

        # Use unified validator
        is_valid, error = self.relationship_rules.validate_composition(simulated_composition, constraints)
        
        if not is_valid and error:
            logger.debug(f"  {error}")
            
        return is_valid

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

        # Get all household venues from VenueManager
        all_households = self.venue_manager.get_venues_by_type("household")

        rows = []
        for household in all_households:
            # Get age categories
            age_categories = household.properties.get('_age_categories', self.categories)

            # Get composition
            composition = household.get_composition(age_categories)
            composition_str = ", ".join([f"{cat}: {count}" for cat, count in composition.items()])

            # Get original pattern
            original_pattern = household.properties.get('original_pattern', 'unknown')

            # Get resident details
            resident_details = []
            for person in household.get_all_members():
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

    def export_unallocated_people_to_csv(self, output_file: str = "unallocated_people.csv"):
        """
        Export list of people who were not allocated to a CSV file.

        Args:
            output_file: Path to output CSV file
        """
        logger.info(f"Exporting unallocated people to {output_file}...")

        rows = []
        for person in self.population.get_all_people():
            if person.id not in self.allocated_people:
                row = {
                    'person_id': person.id,
                    'age': person.age,
                    'sex': person.sex,
                    'geo_unit': person.geographical_unit.name if person.geographical_unit else 'None'
                }
                rows.append(row)

        if not rows:
            logger.info("No unallocated people to export.")
            return None

        # Create DataFrame and export
        df = pd.DataFrame(rows)
        output_path = os.path.join(self.data_dir, output_file)
        df.to_csv(output_path, index=False)

        logger.info(f"Exported {len(rows)} unallocated people to {output_path}")
        return output_path
