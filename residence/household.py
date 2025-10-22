"""
Household module for distributing people into households.

This module handles:
- Loading household composition data from CSV
- Parsing household composition patterns (e.g., ">=2 >=0 2 0")
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
from dataclasses import dataclass, field

from geography.geography import GeographicalUnit, Geography
from population.person import Person
from population.population import PopulationManager
from residence.relationship_rules import RelationshipRulesValidator

logger = logging.getLogger("household")


@dataclass
class AgeCategory:
    """Represents an age category for household composition."""
    name: str
    symbol: str
    min_age: int
    max_age: Optional[int]

    def matches(self, age: int) -> bool:
        """Check if an age falls within this category."""
        if self.max_age is None:
            return age >= self.min_age
        return self.min_age <= age <= self.max_age

    def __repr__(self):
        max_str = f"{self.max_age}" if self.max_age is not None else "∞"
        return f"{self.name}({self.min_age}-{max_str})"


@dataclass
class CompositionPattern:
    """
    Represents a household composition pattern.

    Example: ">=2 >=0 2 0" means:
    - 2 or more people in category 0 (Kids)
    - 0 or more people in category 1 (Young Adults)
    - exactly 2 people in category 2 (Adults)
    - exactly 0 people in category 3 (Old Adults)
    """
    original_pattern: str
    requirements: List[Tuple[str, int]]  # List of (operator, count) for each category
    # operator can be "exact" or "gte" (greater than or equal)

    @classmethod
    def from_string(cls, pattern: str) -> 'CompositionPattern':
        """
        Parse a composition pattern string.

        Args:
            pattern: Pattern string like ">=2 >=0 2 0"

        Returns:
            CompositionPattern object
        """
        parts = pattern.strip().split()
        requirements = []

        for part in parts:
            if part.startswith(">="):
                # Greater-than-or-equal requirement
                count = int(part[2:])
                requirements.append(("gte", count))
            else:
                # Exact requirement
                count = int(part)
                requirements.append(("exact", count))

        return cls(original_pattern=pattern, requirements=requirements)

    def get_min_count(self, category_idx: int) -> int:
        """Get minimum required count for a category."""
        if category_idx >= len(self.requirements):
            return 0
        operator, count = self.requirements[category_idx]
        return count

    def get_max_count(self, category_idx: int) -> Optional[int]:
        """Get maximum allowed count for a category (None if unlimited)."""
        if category_idx >= len(self.requirements):
            return None
        operator, count = self.requirements[category_idx]
        if operator == "exact":
            return count
        else:  # gte
            return None  # No upper limit

    def is_flexible(self, category_idx: int) -> bool:
        """Check if a category has flexible (>=) requirement."""
        if category_idx >= len(self.requirements):
            return True
        operator, _ = self.requirements[category_idx]
        return operator == "gte"

    def min_household_size(self) -> int:
        """Calculate minimum household size required."""
        return sum(self.get_min_count(i) for i in range(len(self.requirements)))

    def validate_against_rules(self, validation_rules: List[Dict],
                              category_name_to_idx: Dict[str, int]) -> bool:
        """
        Validate this pattern against a list of validation rules.

        Args:
            validation_rules: List of rule dicts from config
            category_name_to_idx: Mapping from category name to index

        Returns:
            bool: True if pattern passes all rules, False otherwise
        """
        for rule in validation_rules:
            # Extract rule components
            condition = rule.get('condition', {})
            requirement = rule.get('requirement', {})
            rule_name = rule.get('name', 'Unnamed rule')

            # Get category indices
            cond_category = condition.get('category')
            req_category = requirement.get('category')

            if cond_category not in category_name_to_idx:
                logger.warning(f"Rule '{rule_name}': Unknown category '{cond_category}'")
                continue
            if req_category not in category_name_to_idx:
                logger.warning(f"Rule '{rule_name}': Unknown category '{req_category}'")
                continue

            cond_cat_idx = category_name_to_idx[cond_category]
            req_cat_idx = category_name_to_idx[req_category]

            # Get counts for this pattern
            cond_count = self.get_min_count(cond_cat_idx)
            req_count = self.get_min_count(req_cat_idx)

            # Evaluate condition
            cond_operator = condition.get('operator')
            cond_value = condition.get('value')
            condition_met = self._evaluate_operator(cond_count, cond_operator, cond_value)

            # If condition is met, check requirement
            if condition_met:
                req_operator = requirement.get('operator')
                req_value = requirement.get('value')
                requirement_met = self._evaluate_operator(req_count, req_operator, req_value)

                if not requirement_met:
                    logger.debug(f"  Pattern violates rule '{rule_name}': "
                               f"{cond_category} {cond_operator} {cond_value} implies "
                               f"{req_category} {req_operator} {req_value}, "
                               f"but {req_category}={req_count}")
                    return False

        return True

    def _evaluate_operator(self, actual: int, operator: str, expected: int) -> bool:
        """
        Evaluate a comparison operator.

        Args:
            actual: Actual value
            operator: Comparison operator (>=, >, ==, <=, <)
            expected: Expected value

        Returns:
            bool: True if comparison holds, False otherwise
        """
        if operator == ">=":
            return actual >= expected
        elif operator == ">":
            return actual > expected
        elif operator == "==":
            return actual == expected
        elif operator == "<=":
            return actual <= expected
        elif operator == "<":
            return actual < expected
        else:
            logger.warning(f"Unknown operator '{operator}', assuming False")
            return False

    def demote_once(self, priority_order: List[int]) -> Optional['CompositionPattern']:
        """
        Attempt to demote this pattern by reducing requirements.

        Args:
            priority_order: List of category indices in order of demotion priority

        Returns:
            New CompositionPattern with reduced requirements, or None if can't demote
        """
        new_requirements = list(self.requirements)

        # Try to demote in priority order
        for cat_idx in priority_order:
            if cat_idx >= len(new_requirements):
                continue

            operator, count = new_requirements[cat_idx]

            # Try to reduce the count
            if operator == "gte" and count > 0:
                # Reduce >=N to >=(N-1)
                new_requirements[cat_idx] = ("gte", count - 1)
                new_pattern = self._requirements_to_string(new_requirements)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )
            elif operator == "exact" and count > 0:
                # Reduce exact N to (N-1)
                new_requirements[cat_idx] = ("exact", count - 1)
                new_pattern = self._requirements_to_string(new_requirements)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )

        # Couldn't demote further
        return None

    def promote_once(self, priority_order: List[int]) -> Optional['CompositionPattern']:
        """
        Attempt to promote this pattern by relaxing requirements to allow more people.

        Promotion converts:
          - "0" (exact) -> ">=0" (flexible, allow any)
          - "N" (exact) -> ">=N" (flexible, allow N or more)

        Args:
            priority_order: List of category indices in order of promotion priority

        Returns:
            New CompositionPattern with relaxed requirements, or None if can't promote
        """
        new_requirements = list(self.requirements)

        # Try to promote in priority order
        for cat_idx in priority_order:
            if cat_idx >= len(new_requirements):
                continue

            operator, count = new_requirements[cat_idx]

            # Only promote exact counts (not already flexible)
            if operator == "exact":
                # Convert exact count to >=count
                new_requirements[cat_idx] = ("gte", count)
                new_pattern = self._requirements_to_string(new_requirements)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )

        # Couldn't promote further (all categories already flexible)
        return None

    def _requirements_to_string(self, requirements: List[Tuple[str, int]]) -> str:
        """Convert requirements back to pattern string."""
        parts = []
        for operator, count in requirements:
            if operator == "gte":
                parts.append(f">={count}")
            else:
                parts.append(str(count))
        return " ".join(parts)

    def __repr__(self):
        return f"Pattern({self._requirements_to_string(self.requirements)})"

    def to_string(self) -> str:
        """Get current pattern as string."""
        return self._requirements_to_string(self.requirements)


@dataclass
class Household:
    """Represents a household with residents."""
    id: int
    geographical_unit: GeographicalUnit
    residents: List['Person'] = field(default_factory=list)
    properties: Dict = field(default_factory=dict)

    def add_resident(self, person: 'Person'):
        """Add a person to this household."""
        self.residents.append(person)
        person.residence = self

    def size(self) -> int:
        """Get household size."""
        return len(self.residents)

    def get_composition(self) -> Dict[str, int]:
        """Get household composition by age category."""
        if not hasattr(self, '_age_categories'):
            return {}

        composition = {cat.name: 0 for cat in self._age_categories}
        for person in self.residents:
            for cat in self._age_categories:
                if cat.matches(person.age):
                    composition[cat.name] += 1
                    break
        return composition

    def __repr__(self):
        return f"Household(id={self.id}, unit={self.geographical_unit.name}, size={self.size()})"


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
                                       target_size: Optional[int] = None) -> Tuple[Optional[Household], Optional[int]]:
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

        Returns:
            Tuple of (Household object if successful or None, failed_category_idx or None)
        """
        # Check if relationship rules apply to this pattern
        rule = self.relationship_rules.get_rule_for_pattern(pattern.original_pattern)

        if not rule:
            # No rules for this pattern, use default allocation
            return self._allocate_household(area_code, pattern, max_size, allocate_flexible, target_size)

        # Log first time we apply rules for this pattern
        if not hasattr(self, '_logged_rules'):
            self._logged_rules = set()
        if pattern.original_pattern not in self._logged_rules:
            logger.info(f"✓ Applying relationship rules for pattern: '{pattern.original_pattern}'")
            self._logged_rules.add(pattern.original_pattern)

        if area_code not in self.person_pool_by_area:
            return (None, None)

        pools = self.person_pool_by_area[area_code]

        # Detailed logging for ALL households in one specific geo unit
        if not hasattr(self, '_detailed_log_area'):
            self._detailed_log_area = area_code
            self._detailed_log_household_count = 0
            logger.info("")
            logger.info("=" * 80)
            logger.info(f"DETAILED ALLOCATION FOR GEO UNIT: {area_code}")
            logger.info("=" * 80)
            logger.info("")

        if area_code == self._detailed_log_area:
            self._detailed_log_household_count += 1
            logger.info("=" * 80)
            logger.info(f"HOUSEHOLD #{self._detailed_log_household_count} - Pattern '{pattern.original_pattern}'")
            logger.info("=" * 80)
            logger.info(f"Rule: {rule.name}")
            logger.info(f"Selection order: {' → '.join(rule.selection_order)}")
            logger.info("")
            self._show_detailed_logs = True
        else:
            self._show_detailed_logs = False

        # Track selected people by role
        selected_by_role: Dict[str, List[Person]] = {role_name: [] for role_name in rule.roles.keys()}

        # Select people for each role in order
        for role_name in rule.selection_order:
            role_config = rule.roles[role_name]
            category_names = role_config['categories']
            role_count = role_config['count']

            if self._show_detailed_logs:
                logger.info(f"Step: Selecting role '{role_name}'")
                logger.info(f"  Categories: {category_names}")
                logger.info(f"  Count needed: {role_count}")

            # Map category names to indices
            category_indices = []
            for cat_name in category_names:
                if cat_name in self.relationship_rules.category_name_to_idx:
                    category_indices.append(self.relationship_rules.category_name_to_idx[cat_name])

            # Get candidates from these categories
            candidates = []
            for cat_idx in category_indices:
                candidates.extend(pools[cat_idx])

            if self._show_detailed_logs:
                logger.info(f"  Available candidates: {len(candidates)} people")

            if not candidates:
                # No people available for this role
                if self._show_detailed_logs:
                    logger.info(f"  ✗ FAILED: No candidates available")
                return (None, category_indices[0] if category_indices else None)

            # Check for pair_matching constraint for this role
            pair_constraint = None
            for constraint in rule.constraints:
                if constraint['type'] == 'pair_matching' and constraint.get('role') == role_name:
                    # Check if require_exact_count is specified
                    required_count = constraint.get('require_exact_count')
                    if required_count is None or role_count == required_count:
                        pair_constraint = constraint
                        break

            if pair_constraint and role_count == 2:
                # Select a compatible pair
                # IMPORTANT: Pass existing people (e.g., children) so pair can be validated against them
                if self._show_detailed_logs:
                    logger.info(f"  Mode: Selecting a compatible pair")
                    if selected_by_role:
                        already_selected = sum(len(people) for people in selected_by_role.values())
                        logger.info(f"  Constraints: Must validate against {already_selected} already-selected people")

                pair = self.relationship_rules.select_pair(
                    candidates,
                    pair_constraint,
                    existing_people_by_role=selected_by_role,
                    constraints=rule.constraints,
                    current_role=role_name,
                    show_detailed_logs=self._show_detailed_logs
                )
                if not pair:
                    # Couldn't find valid pair
                    if self._show_detailed_logs:
                        logger.info(f"  ✗ FAILED: Could not find valid pair")
                    return (None, category_indices[0] if category_indices else None)

                selected_by_role[role_name] = list(pair)
                if self._show_detailed_logs:
                    logger.info(f"  ✓ Selected: {pair[0]} and {pair[1]}")
                    logger.info("")

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
                        current_role=role_name
                    )

                    if not person:
                        return (None, category_indices[0] if category_indices else None)

                    selected_by_role[role_name].append(person)
                    # Remove from candidates
                    candidates = [p for p in candidates if p.id != person.id]

            else:
                # Select specific number of people
                if self._show_detailed_logs:
                    logger.info(f"  Mode: Selecting {role_count} person(s) individually")

                for i in range(role_count):
                    person = self.relationship_rules.select_person_with_constraint(
                        candidates=candidates,
                        existing_people_by_role=selected_by_role,
                        constraints=rule.constraints,
                        current_role=role_name
                    )

                    if not person:
                        if self._show_detailed_logs:
                            logger.info(f"  ✗ FAILED: Could not find valid person {i+1}/{role_count}")
                        return (None, category_indices[0] if category_indices else None)

                    selected_by_role[role_name].append(person)
                    if self._show_detailed_logs:
                        logger.info(f"  ✓ Selected person {i+1}/{role_count}: {person}")
                    # Remove from candidates
                    candidates = [p for p in candidates if p.id != person.id]

                if self._show_detailed_logs:
                    logger.info("")

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
            logger.info("FINAL HOUSEHOLD COMPOSITION:")
            logger.info(f"  Household ID: {household.id}")
            logger.info(f"  Geo Unit: {area_code}")
            logger.info(f"  Pattern: {pattern.original_pattern}")
            logger.info(f"  Total members: {len(all_selected)}")
            logger.info("")
            for role_name, people in selected_by_role.items():
                if people:
                    logger.info(f"  {role_name}:")
                    for person in people:
                        logger.info(f"    - {person}")
            logger.info("=" * 80)
            logger.info("")

        return (household, None)

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
        selections = []  # Store planned selections: (cat_idx, count)

        # BALANCED DISTRIBUTION: Use proportional allocation when target_size is specified
        if allocate_flexible and target_size is not None:
            # First pass: allocate exact counts for fixed categories
            fixed_total = 0
            flexible_categories = []

            for cat_idx in range(len(self.age_categories)):
                min_count = pattern.get_min_count(cat_idx)
                max_count = pattern.get_max_count(cat_idx)
                available = len(pools[cat_idx])

                # Check minimum availability
                if available < min_count:
                    return (None, cat_idx)

                if max_count is not None:
                    # Fixed category - allocate exactly
                    selections.append((cat_idx, max_count))
                    fixed_total += max_count
                else:
                    # Flexible category - defer allocation
                    flexible_categories.append((cat_idx, min_count, available))

            # Second pass: distribute remaining capacity proportionally across flexible categories
            remaining_capacity = target_size - fixed_total

            if remaining_capacity < 0:
                # Can't meet target - fixed categories already exceed it
                return (None, None)

            # Calculate proportional allocation based on availability
            total_available = sum(avail for _, _, avail in flexible_categories)

            for cat_idx, min_count, available in flexible_categories:
                if total_available > 0:
                    # Proportional share of remaining capacity
                    proportion = available / total_available
                    allocated = int(remaining_capacity * proportion)
                    # Ensure we meet minimum and don't exceed available
                    allocated = max(min_count, min(allocated, available))
                else:
                    allocated = min_count

                selections.append((cat_idx, allocated))

            # Sort selections by category index to maintain order
            selections.sort(key=lambda x: x[0])

            total_selected = sum(count for _, count in selections)

        else:
            # ORIGINAL LOGIC: Sequential allocation
            # PHASE 1: Check if ALL categories can be fulfilled (don't modify pools yet!)
            total_selected = 0
            for cat_idx in range(len(self.age_categories)):
                min_count = pattern.get_min_count(cat_idx)
                max_count = pattern.get_max_count(cat_idx)

                available = len(pools[cat_idx])

                # Check if we have enough people
                if available < min_count:
                    # Can't fulfill - return failure with the category that caused it
                    return (None, cat_idx)

                # Decide how many to take
                if max_count is not None:
                    # Exact count specified
                    count = max_count
                else:
                    # Flexible (>=) category
                    if allocate_flexible and available > min_count:
                        # RANDOM ALLOCATION: Randomly allocate between min and available
                        # But respect max_size if specified
                        max_allocatable = available
                        if max_size is not None:
                            remaining_capacity = max_size - total_selected
                            max_allocatable = min(max_allocatable, remaining_capacity)

                        # Random count between min and max_allocatable
                        if max_allocatable > min_count:
                            count = random.randint(min_count, max_allocatable)
                        else:
                            count = min_count
                    else:
                        # Take minimum required
                        count = min_count

                # Apply max_size constraint if specified
                if max_size is not None:
                    remaining_capacity = max_size - total_selected
                    count = min(count, remaining_capacity)

                    # If this brings us below minimum, we can't fulfill the pattern
                    if count < min_count:
                        return (None, cat_idx)

                total_selected += count
                selections.append((cat_idx, count))

        # PHASE 2: All checks passed! Now actually take people from pools
        selected_people = []
        for cat_idx, count in selections:
            if count > 0:
                selected = pools[cat_idx][:count]
                selected_people.extend(selected)
                pools[cat_idx] = pools[cat_idx][count:]

        if not selected_people:
            return (None, None)

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

        return (household, None)

    def _attempt_with_demotion(self, area_code: str, pattern: CompositionPattern,
                               max_attempts: int, max_size: Optional[int] = None,
                               allocate_flexible: bool = False,
                               target_size: Optional[int] = None) -> Optional[Household]:
        """
        Attempt to allocate a household, using intelligent demotion if necessary.

        Demotion strategy:
        - Tries to demote the category that actually caused the failure
        - Falls back to configured priority order if failure category can't be demoted

        Args:
            area_code: SGU code
            pattern: Initial composition pattern
            max_attempts: Maximum demotion attempts
            max_size: Maximum household size (optional)
            allocate_flexible: If True, allocate people to flexible (>=) categories randomly

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
            # Try to allocate with current pattern
            # First try with relationship rules if available
            household, failed_category_idx = self._allocate_household_with_rules(
                area_code, current_pattern, max_size, allocate_flexible, target_size
            )

            # If rules-based allocation returned None and called the fallback,
            # the fallback already tried regular allocation, so we're done
            if household:
                if attempt > 0:
                    logger.debug(f"    Succeeded after {attempt} demotion(s): {current_pattern.to_string()}")
                return household

            # Store which category failed
            last_failed_category = failed_category_idx

            # Check minimum size
            min_size = self.config['demotion']['min_household_size']
            if current_pattern.min_household_size() < min_size:
                logger.debug(f"    Pattern too small after demotion: {current_pattern.to_string()}")
                return None

            # Try to demote
            if attempt < max_attempts:
                # INTELLIGENT DEMOTION: Try to demote the category that failed
                new_pattern = None

                if failed_category_idx is not None:
                    # Try demoting the failed category first
                    cat_name = self.age_categories[failed_category_idx].name
                    logger.debug(f"    Attempting intelligent demotion: {cat_name} (category {failed_category_idx}) caused failure")
                    new_pattern = current_pattern.demote_once([failed_category_idx])

                # If intelligent demotion didn't work, try fallback priority order
                if new_pattern is None:
                    logger.debug(f"    Intelligent demotion failed, trying fallback priority order")
                    new_pattern = current_pattern.demote_once(fallback_priority)

                if new_pattern is None:
                    logger.debug(f"    Cannot demote further: {current_pattern.to_string()}")
                    return None

                # Validate the new pattern against demotion rules
                validation_rules = self.config.get('demotion', {}).get('validation_rules', [])
                if validation_rules and not new_pattern.validate_against_rules(
                    validation_rules, self.category_name_to_idx
                ):
                    logger.debug(f"    Demoted pattern violates validation rules: {new_pattern.to_string()}")
                    return None

                current_pattern = new_pattern
            else:
                logger.debug(f"    Max demotion attempts reached: {current_pattern.to_string()}")
                return None

        return None

    def distribute_households(self):
        """
        Main method to distribute people into households.

        This method:
        1. Prepares person pools by area
        2. Iterates through household composition data
        3. Attempts to create households with given patterns
        4. Uses demotion when needed to handle census obfuscation
        """
        logger.info("Starting household distribution...")

        # Prepare pools
        self._prepare_person_pools()

        # Get config
        demotion_enabled = self.config['demotion']['enabled']
        max_attempts = self.config['demotion']['max_attempts']

        total_requested = 0
        total_created = 0
        total_demoted = 0

        # Iterate through each area
        for area_code, compositions in self.household_counts_by_area.items():
            logger.debug(f"Processing area {area_code}...")

            # Iterate through each composition type in this area
            for pattern_str, count in compositions.items():
                total_requested += count
                pattern = CompositionPattern.from_string(pattern_str)

                # Try to create 'count' households of this type
                for i in range(count):
                    if demotion_enabled:
                        household = self._attempt_with_demotion(area_code, pattern, max_attempts)
                    else:
                        household, _ = self._allocate_household(area_code, pattern)

                    if household:
                        self.households.append(household)
                        total_created += 1

                        # Check if we used demotion
                        if household.properties.get('original_pattern') != pattern.to_string():
                            total_demoted += 1
                    else:
                        logger.debug(f"  Failed to allocate household {i+1}/{count} of type '{pattern_str}' in {area_code}")

        # Log summary
        logger.info("=" * 60)
        logger.info("Household distribution complete!")
        logger.info(f"  Requested households: {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
        logger.info(f"  Households using demotion: {total_demoted:,} ({100*total_demoted/max(total_created,1):.1f}%)")
        logger.info(f"  People allocated: {len(self.allocated_people):,}")
        logger.info(f"  People unallocated: {len(self.population.get_all_people()) - len(self.allocated_people):,}")
        logger.info("=" * 60)

        # Print relationship rules statistics
        self.relationship_rules.print_statistics()

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

        # Count total available people in ALL categories (not just flexible)
        total_available = 0
        for cat_idx in range(len(self.age_categories)):
            total_available += len(pools[cat_idx])

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
                                   round_name: Optional[str] = None):
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

        Returns:
            dict: Statistics about this round's allocation
        """
        self.current_round += 1
        round_label = round_name or f"Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting household allocation: {round_label}")
        logger.info("=" * 60)

        # Prepare or refresh pools
        self._prepare_person_pools(refresh=refresh_pools)

        # Get config
        demotion_enabled = self.config['demotion']['enabled']
        max_attempts = self.config['demotion']['max_attempts']

        # Track round statistics
        round_start_households = len(self.households)
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

                pattern = CompositionPattern.from_string(actual_pattern_str)

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
                        household = self._attempt_with_demotion(area_code, pattern, max_attempts, max_household_size, allocate_flexible, target_size)
                    else:
                        household, _ = self._allocate_household(area_code, pattern, max_household_size, allocate_flexible, target_size)

                    if household:
                        # Get the actual pattern that was used (may have been demoted)
                        actual_pattern_used = household.properties.get('actual_pattern')

                        # DEBUG: Log what we're comparing

                        # Check if we used demotion
                        # Compare the actual pattern used vs the initial pattern requested (assumption)
                        if actual_pattern_used != actual_pattern_str:
                            total_demoted += 1
                            print(f"DEBUG -> DEMOTION DETECTED: {actual_pattern_used} != {actual_pattern_str}")

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

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Requested households (filtered): {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
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

    def distribute_households_from_yaml(self, rounds_config_file: str = "allocation_rounds.yaml"):
        """
        Execute multi-round allocation from a YAML configuration file.

        The YAML file should define rounds with patterns, limits, and options.
        See allocation_rounds.yaml for examples.

        Args:
            rounds_config_file: Path to YAML file (relative to data_dir or absolute)

        Returns:
            list: List of statistics dicts, one per round
        """
        # Load rounds configuration
        if not os.path.isabs(rounds_config_file):
            rounds_config_path = os.path.join(self.data_dir, rounds_config_file)
        else:
            rounds_config_path = rounds_config_file

        logger.info(f"Loading allocation rounds configuration from {rounds_config_path}")

        with open(rounds_config_path, 'r') as f:
            rounds_config = yaml.safe_load(f)

        # Check if multi-round is enabled
        if not rounds_config.get('enabled', True):
            logger.info("Multi-round allocation is disabled in config, using single-pass allocation")
            self.distribute_households()
            return []

        # Get rounds
        rounds = rounds_config.get('rounds', [])
        if not rounds:
            logger.warning("No rounds defined in config, using single-pass allocation")
            self.distribute_households()
            return []

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Starting multi-round allocation with {len(rounds)} rounds")
        logger.info("=" * 60)

        # Execute each round
        all_stats = []
        for i, round_config in enumerate(rounds):
            round_name = round_config.get('name', f"Round {i+1}")
            description = round_config.get('description')

            if description:
                logger.info("")
                logger.info(f"Round {i+1}: {round_name}")
                logger.info(f"  Description: {description}")

            # Get round parameters
            patterns = round_config.get('patterns')
            max_households = round_config.get('max_households')
            refresh_pools = round_config.get('refresh_pools', False)
            enable_demotion = round_config.get('enable_demotion')

            # Temporarily override demotion setting if specified
            original_demotion = None
            if enable_demotion is not None:
                original_demotion = self.config['demotion']['enabled']
                self.config['demotion']['enabled'] = enable_demotion

            # Execute round
            try:
                stats = self.distribute_households_round(
                    pattern_filter=patterns,
                    max_households=max_households,
                    refresh_pools=refresh_pools,
                    round_name=round_name
                )
                all_stats.append(stats)
            finally:
                # Restore original demotion setting
                if original_demotion is not None:
                    self.config['demotion']['enabled'] = original_demotion

        # Print overall summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("MULTI-ROUND ALLOCATION SUMMARY")
        logger.info("=" * 60)

        for stats in all_stats:
            logger.info("")
            logger.info(f"{stats['round_name']}:")
            logger.info(f"  Households created: {stats['households_created']:,}")
            logger.info(f"  People allocated: {stats['people_allocated_this_round']:,}")
            if stats['households_with_demotion'] > 0:
                logger.info(f"  Households with demotion: {stats['households_with_demotion']:,}")

        logger.info("")
        logger.info("Overall Totals:")
        logger.info(f"  Total households: {len(self.households):,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  Total people remaining: {self.get_available_people_count():,}")
        logger.info("=" * 60)

        return all_stats

    def allocate_excess_to_households(self,
                                      target_patterns: List[str],
                                      add_category: str,
                                      constraints: Optional[List[Dict]] = None,
                                      max_per_household: Optional[int] = None,
                                      add_distribution: Optional[Dict] = None,
                                      refresh_pools: bool = False,
                                      round_name: Optional[str] = None):
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

        Returns:
            dict: Statistics about this excess allocation
        """
        self.current_round += 1
        round_label = round_name or f"Excess Allocation Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting excess allocation: {round_label}")
        logger.info("=" * 60)
        logger.info(f"Target patterns: {target_patterns}")
        logger.info(f"Adding category: {add_category}")
        logger.info(f"Constraints: {constraints}")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self._prepare_person_pools(refresh=True)

        # Find category index for the category to add
        add_cat_idx = self.category_name_to_idx.get(add_category)
        if add_cat_idx is None:
            logger.error(f"Unknown category '{add_category}'")
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0,
                'error': f"Unknown category '{add_category}'"
            }

        # Filter households by target patterns
        target_households = []
        for household in self.households:
            original_pattern = household.properties.get('original_pattern', '')
            if original_pattern in target_patterns:
                target_households.append(household)

        logger.info(f"Found {len(target_households)} households matching target patterns")

        if not target_households:
            logger.warning("No households found matching target patterns")
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0
            }

        # Shuffle households for fairness
        random.shuffle(target_households)

        # Track statistics
        people_added = 0
        households_modified = 0

        # Iterate through target households and try to add people
        for household in target_households:
            area_code = household.geographical_unit.name

            # Get person pool for this area
            if area_code not in self.person_pool_by_area:
                continue

            pools = self.person_pool_by_area[area_code]
            available_people = pools[add_cat_idx]

            if not available_people:
                continue

            # Determine target number to add for this household
            if add_distribution:
                target_to_add = self._sample_from_distribution(add_distribution)
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
                    if constraints and not self._check_constraints_if_added(
                        household, add_category, constraints
                    ):
                        # Can't add more to this household due to constraints
                        break

                    # Add the person
                    person = available_people[0]  # Always take first (already shuffled)
                    household.add_resident(person)
                    self.allocated_people.add(person.id)
                    pools[add_cat_idx].pop(0)  # Remove from pool

                    added_to_this_household += 1
                    people_added += 1
            else:
                # Finite target - add up to target_to_add people
                for _ in range(int(target_to_add)):
                    # Check if we have people available
                    if not available_people:
                        break

                    # Check if adding this person would violate constraints
                    if constraints and not self._check_constraints_if_added(
                        household, add_category, constraints
                    ):
                        # Can't add more to this household due to constraints
                        break

                    # Add the person
                    person = available_people[0]  # Always take first (already shuffled)
                    household.add_resident(person)
                    self.allocated_people.add(person.id)
                    pools[add_cat_idx].pop(0)  # Remove from pool

                    added_to_this_household += 1
                    people_added += 1

            if added_to_this_household > 0:
                households_modified += 1
                logger.debug(f"Added {added_to_this_household} {add_category} to household {household.id}")

        # Statistics
        stats = {
            'round_name': round_label,
            'round_number': self.current_round,
            'people_added': people_added,
            'households_modified': households_modified,
            'target_households_count': len(target_households),
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Target households: {len(target_households):,}")
        logger.info(f"  Households modified: {households_modified:,}")
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
        self.current_round += 1
        round_label = round_name or f"Overflow Allocation Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting overflow allocation: {round_label}")
        logger.info("=" * 60)
        logger.info(f"Target patterns: {target_patterns}")
        logger.info(f"Adding category: {add_category}")
        logger.info(f"Pattern bias: {pattern_bias}")
        logger.info("WARNING: This step IGNORES max household size constraints!")
        logger.info("")

        # Refresh pools if requested
        if refresh_pools:
            self._prepare_person_pools(refresh=True)

        # Find category index
        add_cat_idx = self.category_name_to_idx.get(add_category)
        if add_cat_idx is None:
            logger.error(f"Unknown category '{add_category}'")
            return {
                'round_name': round_label,
                'people_added': 0,
                'households_modified': 0,
                'error': f"Unknown category '{add_category}'"
            }

        # Group households by area and pattern
        households_by_area_pattern = {}
        for household in self.households:
            original_pattern = household.properties.get('original_pattern', '')
            if original_pattern in target_patterns:
                area_code = household.geographical_unit.name
                key = (area_code, original_pattern)
                if key not in households_by_area_pattern:
                    households_by_area_pattern[key] = []
                households_by_area_pattern[key].append(household)

        logger.info(f"Found {sum(len(hhs) for hhs in households_by_area_pattern.values())} eligible households across {len(households_by_area_pattern)} area-pattern combinations")

        # Track statistics
        people_added = 0
        households_modified = 0

        # Process each area
        for area_code in set(k[0] for k in households_by_area_pattern.keys()):
            if area_code not in self.person_pool_by_area:
                continue

            pools = self.person_pool_by_area[area_code]
            available_people = pools[add_cat_idx]

            if not available_people:
                continue

            logger.debug(f"Area {area_code}: {len(available_people)} {add_category} available")

            # Get all households in this area across all patterns
            area_households_by_pattern = {}
            for (ac, pattern), hhs in households_by_area_pattern.items():
                if ac == area_code:
                    area_households_by_pattern[pattern] = hhs

            # Calculate distribution with bias
            total_to_allocate = len(available_people)

            # Apply bias weights
            pattern_weights = {}
            for pattern in area_households_by_pattern.keys():
                weight = pattern_bias.get(pattern, 1.0) if pattern_bias else 1.0
                num_households = len(area_households_by_pattern[pattern])
                pattern_weights[pattern] = weight * num_households

            total_weight = sum(pattern_weights.values())

            if total_weight == 0:
                continue

            # Allocate to each pattern proportionally
            pattern_allocations = {}
            allocated_so_far = 0

            for pattern in area_households_by_pattern.keys():
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

                pattern_households = area_households_by_pattern[pattern]
                num_hh = len(pattern_households)

                # Distribute balancedly
                base_per_household = num_to_add // num_hh
                remainder_hh = num_to_add % num_hh

                # Shuffle for fairness
                import random
                shuffled_hh = pattern_households.copy()
                random.shuffle(shuffled_hh)

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
                        self.allocated_people.add(person.id)
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
            'round_number': self.current_round,
            'people_added': people_added,
            'households_modified': households_modified,
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Get remaining people by category
        remaining_by_category = self.get_available_people_by_category()

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Households modified: {households_modified:,}")
        logger.info(f"  People added (overflow): {people_added:,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {stats['total_people_remaining']:,}")
        logger.info("")
        logger.info("  Remaining by category:")
        for cat_name in [cat.name for cat in self.age_categories]:
            count = remaining_by_category.get(cat_name, 0)
            logger.info(f"    {cat_name}: {count:,}")
        logger.info("=" * 60)

        return stats

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
        self.current_round += 1
        round_label = round_name or f"Promotion Allocation Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting promotion allocation: {round_label}")
        logger.info("=" * 60)
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
            cat_idx = self.category_name_to_idx.get(category_name)
            if cat_idx is None:
                logger.warning(f"Unknown category '{category_name}', skipping")
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
        self.current_round += 1
        round_label = round_name or f"Rule-Based Promotion Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting rule-based promotion: {round_label}")
        logger.info("=" * 60)
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
                    cat_idx = self.category_name_to_idx.get(category_name)
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
