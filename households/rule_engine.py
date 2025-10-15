"""
Rule-based household creation engine for June Zero.

Provides a fully generic, configurable system for creating households
based on composition patterns and relationship constraints.
"""

import logging
import random
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("rule_engine")


class RoleResolver:
    """
    Resolves generic roles to actual person categories.

    Maps role names (e.g., "caregiver", "priority") to category indices
    based on the person_categories configuration.
    """

    def __init__(self, person_categories: List[Dict]):
        """
        Initialize role resolver.

        Args:
            person_categories: List of category configs with 'roles' field
        """
        self.categories = person_categories
        self.category_names = [c['name'] for c in person_categories]
        self.role_map = self._build_role_map()

        logger.debug(f"RoleResolver initialized with {len(self.categories)} categories")
        logger.debug(f"Role map: {dict(self.role_map)}")

    def _build_role_map(self) -> Dict[str, List[int]]:
        """
        Build mapping: role -> [category_indices].

        Returns:
            Dict mapping role names to lists of category indices
        """
        role_map = defaultdict(list)

        for idx, category in enumerate(self.categories):
            roles = category.get('roles', [])
            for role in roles:
                role_map[role].append(idx)

        return role_map

    def get_categories_by_role(self, role: str) -> List[int]:
        """
        Get all category indices that have this role.

        Args:
            role: Role name (e.g., "caregiver", "priority")

        Returns:
            List of category indices (0-indexed)
        """
        return self.role_map.get(role, [])

    def has_role(self, category_index: int, role: str) -> bool:
        """
        Check if a category has a specific role.

        Args:
            category_index: Index into categories list
            role: Role name

        Returns:
            True if category has this role
        """
        return category_index in self.role_map.get(role, [])

    def get_category_name(self, category_index: int) -> str:
        """Get category name by index."""
        return self.category_names[category_index]

    def get_category_index(self, category_name: str) -> int:
        """Get category index by name."""
        return self.category_names.index(category_name)


class ConstraintValidator:
    """
    Validates relationship constraints between people.

    Checks age gaps, sex preferences, and other biological/social constraints.
    """

    def __init__(self, constraints_config: Dict):
        """
        Initialize constraint validator.

        Args:
            constraints_config: Relationship constraints from YAML
        """
        self.constraints = constraints_config
        logger.debug("ConstraintValidator initialized")

    def validate_age_gap(
        self,
        person_age: int,
        reference_age: int,
        config_key: str
    ) -> Tuple[bool, float]:
        """
        Validate age gap between two people.

        Args:
            person_age: Age of person being checked
            reference_age: Age of reference person
            config_key: Key in constraints config (e.g., "parent_child.primary_parent")

        Returns:
            Tuple of (is_valid, score)
            - is_valid: True if within constraints
            - score: 0-100, higher = better match
        """
        # Parse config key (e.g., "parent_child.primary_parent" -> ['parent_child', 'primary_parent'])
        keys = config_key.split('.')
        constraint = self.constraints

        for key in keys:
            constraint = constraint.get(key, {})

        if not constraint:
            logger.warning(f"Constraint config not found for key: {config_key}")
            return True, 50.0  # No constraint = accept with neutral score

        age_diff = person_age - reference_age
        min_diff = constraint.get('min_age_difference', 0)
        max_diff = constraint.get('max_age_difference', 100)
        preferred_diff = constraint.get('preferred_age_difference', (min_diff + max_diff) / 2)

        # Hard constraint check
        if age_diff < min_diff or age_diff > max_diff:
            return False, 0.0

        # Calculate score based on distance from preferred
        distance_from_preferred = abs(age_diff - preferred_diff)
        max_distance = max(abs(min_diff - preferred_diff), abs(max_diff - preferred_diff))

        # Score: 100 at preferred, decreasing linearly to 50 at boundaries
        if max_distance > 0:
            score = 100 - (distance_from_preferred / max_distance) * 50
        else:
            score = 100

        return True, max(score, 50.0)

    def validate_sex_preference(
        self,
        person_sex: str,
        reference_sex: str,
        config_key: str,
        probability: float = 0.95
    ) -> Tuple[bool, float]:
        """
        Validate sex preference (e.g., opposite sex for couples).

        Args:
            person_sex: Sex of person being checked
            reference_sex: Sex of reference person
            config_key: Key in constraints config
            probability: Probability of preferring opposite sex (0.0-1.0)

        Returns:
            Tuple of (is_valid, score)
        """
        # This is a soft constraint - always valid, just affects score
        is_opposite_sex = (person_sex != reference_sex)

        if is_opposite_sex:
            # Opposite sex: score based on probability
            score = 50 + (probability * 50)  # 50-100 range
        else:
            # Same sex: score based on (1 - probability)
            score = 50 * (1 - probability)  # 0-50 range

        return True, score


class HouseholdCreationRule:
    """
    Represents a single household creation rule.

    Defines pattern matching and allocation sequence for a specific
    type of household (e.g., nuclear family, elderly couple, etc.)
    """

    def __init__(
        self,
        rule_config: Dict,
        role_resolver: RoleResolver,
        constraint_validator: ConstraintValidator
    ):
        """
        Initialize household creation rule.

        Args:
            rule_config: Rule configuration from YAML
            role_resolver: Role resolver instance
            constraint_validator: Constraint validator instance
        """
        self.name = rule_config['name']
        self.description = rule_config.get('description', '')
        self.priority = rule_config.get('priority', 999)
        self.pattern_match = rule_config['pattern_match']
        self.allocation_sequence = rule_config['allocation_sequence']

        self.role_resolver = role_resolver
        self.constraint_validator = constraint_validator

        logger.debug(f"Created rule: {self.name} (priority {self.priority})")

    def matches_pattern(self, parsed_pattern: Dict) -> bool:
        """
        Check if this rule matches the given pattern.

        Args:
            parsed_pattern: Parsed pattern from distributor
                {
                    'requirements': {category_idx: count},
                    'minimums': {category_idx: count},
                    'pattern': original pattern string
                }

        Returns:
            True if rule matches this pattern
        """
        match_type = self.pattern_match['type']

        if match_type == 'always':
            return True

        if match_type == 'role_based':
            return self._matches_role_based(parsed_pattern)

        if match_type == 'category_index':
            return self._matches_category_index(parsed_pattern)

        if match_type == 'category_name':
            return self._matches_category_name(parsed_pattern)

        logger.warning(f"Unknown match type: {match_type}")
        return False

    def _matches_role_based(self, parsed_pattern: Dict) -> bool:
        """Check if pattern matches role-based conditions."""
        conditions = self.pattern_match.get('conditions', [])

        for condition in conditions:
            role = condition['role']
            operator = condition['operator']
            value = condition['value']

            # Get categories with this role
            category_indices = self.role_resolver.get_categories_by_role(role)

            # Sum up counts for all categories with this role
            total_count = 0
            for cat_idx in category_indices:
                total_count += parsed_pattern['requirements'].get(cat_idx, 0)
                total_count += parsed_pattern['minimums'].get(cat_idx, 0)

            # Check operator
            if operator == '>':
                if not (total_count > value):
                    return False
            elif operator == '>=':
                if not (total_count >= value):
                    return False
            elif operator == '==':
                if not (total_count == value):
                    return False
            elif operator == '<':
                if not (total_count < value):
                    return False
            elif operator == '<=':
                if not (total_count <= value):
                    return False
            else:
                logger.warning(f"Unknown operator: {operator}")
                return False

        return True

    def _matches_category_index(self, parsed_pattern: Dict) -> bool:
        """Check if pattern matches category-index-based conditions."""
        conditions = self.pattern_match.get('conditions', [])

        for condition in conditions:
            cat_idx = condition['category_index']
            operator = condition['operator']
            value = condition['value']

            # Get count for this category
            count = parsed_pattern['requirements'].get(cat_idx, 0)
            count += parsed_pattern['minimums'].get(cat_idx, 0)

            # Check operator
            if operator == '>':
                if not (count > value):
                    return False
            elif operator == '>=':
                if not (count >= value):
                    return False
            elif operator == '==':
                if not (count == value):
                    return False
            elif operator == '<':
                if not (count < value):
                    return False
            elif operator == '<=':
                if not (count <= value):
                    return False

        return True

    def _matches_category_name(self, parsed_pattern: Dict) -> bool:
        """Check if pattern matches category-name-based conditions."""
        conditions = self.pattern_match.get('conditions', [])

        for condition in conditions:
            cat_name = condition['category_name']
            operator = condition['operator']
            value = condition['value']

            # Get category index from name
            try:
                cat_idx = self.role_resolver.get_category_index(cat_name)
            except ValueError:
                logger.warning(f"Unknown category name: {cat_name}")
                return False

            # Get count for this category
            count = parsed_pattern['requirements'].get(cat_idx, 0)
            count += parsed_pattern['minimums'].get(cat_idx, 0)

            # Check operator
            if operator == '>':
                if not (count > value):
                    return False
            elif operator == '>=':
                if not (count >= value):
                    return False
            elif operator == '==':
                if not (count == value):
                    return False
            elif operator == '<':
                if not (count < value):
                    return False
            elif operator == '<=':
                if not (count <= value):
                    return False
            else:
                logger.warning(f"Unknown operator: {operator}")
                return False

        return True

    def __repr__(self):
        return f"<Rule: {self.name} (priority {self.priority})>"


class AllocationExecutor:
    """
    Executes allocation sequences from household creation rules.

    Takes a rule and follows its step-by-step allocation sequence,
    applying constraints and selecting compatible people.
    """

    def __init__(
        self,
        role_resolver: RoleResolver,
        constraint_validator: ConstraintValidator,
        distributor  # Reference to HouseholdDistributor for person pools
    ):
        """
        Initialize allocation executor.

        Args:
            role_resolver: Role resolver instance
            constraint_validator: Constraint validator instance
            distributor: HouseholdDistributor instance (for accessing person pools)
        """
        self.role_resolver = role_resolver
        self.constraint_validator = constraint_validator
        self.distributor = distributor

    def execute_rule(
        self,
        rule: HouseholdCreationRule,
        parsed_pattern: Dict,
        area_code: str,
        household
    ) -> bool:
        """
        Execute a rule's allocation sequence to fill a household.

        Args:
            rule: Household creation rule to execute
            parsed_pattern: Parsed composition pattern
            area_code: S.G.U code
            household: Household object to populate

        Returns:
            True if successful, False if allocation failed
        """
        allocated_people = {}  # {step_number: [people]}

        logger.debug(f"Executing rule '{rule.name}' for pattern '{parsed_pattern['pattern']}'")

        try:
            for step_config in rule.allocation_sequence:
                step_num = step_config['step']
                logger.debug(f"  Step {step_num}: {step_config.get('description', 'No description')}")

                # Resolve category for this step
                category_indices = self._resolve_category(step_config)

                # Determine count
                count = self._resolve_count(step_config, parsed_pattern, category_indices)

                if count == 0:
                    logger.debug(f"    Skipping step {step_num} (count = 0)")
                    continue

                # Get candidates from person pool
                candidates = self._get_candidates(area_code, category_indices)

                if not candidates:
                    logger.debug(f"    No candidates available for step {step_num}")
                    return False

                # Apply constraints and select people
                selected = self._select_people(
                    candidates,
                    count,
                    step_config,
                    allocated_people,
                    area_code
                )

                if len(selected) < count:
                    logger.debug(f"    Could not select enough people: {len(selected)}/{count}")
                    return False

                # Add to household
                for person in selected:
                    household.add_resident(person)

                # Track allocated people for this step
                allocated_people[step_num] = selected

                logger.debug(f"    Allocated {len(selected)} people")

            return True

        except Exception as e:
            logger.error(f"Error executing rule: {e}", exc_info=True)
            return False

    def _resolve_category(self, step_config: Dict) -> List[int]:
        """
        Resolve which category indices this step should use.

        Args:
            step_config: Step configuration from rule

        Returns:
            List of category indices
        """
        if 'category_role' in step_config:
            role = step_config['category_role']
            return self.role_resolver.get_categories_by_role(role)
        elif 'category_index' in step_config:
            return [step_config['category_index']]
        elif 'category_name' in step_config:
            cat_name = step_config['category_name']
            try:
                cat_idx = self.role_resolver.get_category_index(cat_name)
                return [cat_idx]
            except ValueError:
                logger.warning(f"Unknown category name: {cat_name}")
                return []
        else:
            logger.warning(f"Step has no category specification: {step_config}")
            return []

    def _resolve_count(
        self,
        step_config: Dict,
        parsed_pattern: Dict,
        category_indices: List[int]
    ) -> int:
        """
        Determine how many people to allocate in this step.

        Args:
            step_config: Step configuration
            parsed_pattern: Parsed pattern
            category_indices: Category indices for this step

        Returns:
            Number of people to allocate
        """
        count_spec = step_config.get('count', 1)

        if isinstance(count_spec, int):
            return count_spec

        if count_spec == 'minimum_required':
            # Sum minimums for all categories with this role
            total = 0
            for cat_idx in category_indices:
                total += parsed_pattern['requirements'].get(cat_idx, 0)
                total += parsed_pattern['minimums'].get(cat_idx, 0)
            return total

        if count_spec == 'remaining_in_role':
            # Calculate remaining count needed for this role
            total_needed = 0
            for cat_idx in category_indices:
                total_needed += parsed_pattern['requirements'].get(cat_idx, 0)
                total_needed += parsed_pattern['minimums'].get(cat_idx, 0)

            # Subtract what's already allocated in previous steps
            # (This is for multi-step allocation of same role)
            # For now, return total_needed - 1 (assuming step 2 already allocated 1)
            # TODO: Make this more robust by tracking allocated counts per role
            return max(0, total_needed - 1)

        logger.warning(f"Unknown count specification: {count_spec}")
        return 0

    def _get_candidates(self, area_code: str, category_indices: List[int]) -> List:
        """
        Get candidate people from the person pool.

        Args:
            area_code: S.G.U code
            category_indices: Category indices to search

        Returns:
            List of candidate Person objects
        """
        candidates = []

        for cat_idx in category_indices:
            category_name = self.role_resolver.get_category_name(cat_idx)

            # Get people from pool for this category
            pool = self.distributor.person_pool_by_area.get(area_code, {})

            # Check all people in this area
            for person in pool:
                # Skip if already allocated
                if person.id in self.distributor.allocated_people:
                    continue

                # Check if person belongs to this category
                person_category = self.distributor.get_person_category(person)
                if person_category == category_name:
                    candidates.append(person)

        return candidates

    def _select_people(
        self,
        candidates: List,
        count: int,
        step_config: Dict,
        allocated_people: Dict,
        area_code: str
    ) -> List:
        """
        Select people from candidates based on constraints and method.

        Args:
            candidates: List of candidate people
            count: Number of people to select
            step_config: Step configuration with constraints
            allocated_people: Already allocated people from previous steps
            area_code: S.G.U code

        Returns:
            List of selected people
        """
        selection_method = step_config.get('selection_method', 'random')
        constraints = step_config.get('constraints', [])

        if not constraints or selection_method == 'random':
            # Simple random selection
            if len(candidates) < count:
                return candidates
            return random.sample(candidates, count)

        # Constraint-based selection (best_match)
        if selection_method == 'best_match':
            return self._select_best_match(
                candidates,
                count,
                constraints,
                allocated_people,
                area_code
            )

        logger.warning(f"Unknown selection method: {selection_method}")
        return random.sample(candidates, min(count, len(candidates)))

    def _select_best_match(
        self,
        candidates: List,
        count: int,
        constraints: List[Dict],
        allocated_people: Dict,
        area_code: str
    ) -> List:
        """
        Select people that best satisfy constraints.

        Args:
            candidates: List of candidate people
            count: Number of people to select
            constraints: List of constraint definitions
            allocated_people: Already allocated people from previous steps
            area_code: S.G.U code

        Returns:
            List of selected people (best matches)
        """
        # Score each candidate
        scored_candidates = []

        for candidate in candidates:
            total_score = 100.0
            is_valid = True

            for constraint in constraints:
                constraint_type = constraint['type']
                required = constraint.get('required', False)

                if constraint_type == 'age_gap':
                    valid, score = self._check_age_gap_constraint(
                        candidate,
                        constraint,
                        allocated_people
                    )

                    if not valid and required:
                        is_valid = False
                        break

                    total_score += (score - 50)  # Adjust score relative to neutral (50)

                elif constraint_type == 'sex_preference':
                    valid, score = self._check_sex_preference_constraint(
                        candidate,
                        constraint,
                        allocated_people
                    )

                    total_score += (score - 50)

            if is_valid:
                scored_candidates.append((candidate, total_score))

        # Sort by score (descending)
        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        # Select top N
        selected = [person for person, score in scored_candidates[:count]]

        logger.debug(f"    Selected {len(selected)}/{count} people via best_match")
        if scored_candidates:
            logger.debug(f"    Score range: {scored_candidates[-1][1]:.1f} - {scored_candidates[0][1]:.1f}")

        return selected

    def _check_age_gap_constraint(
        self,
        candidate,
        constraint: Dict,
        allocated_people: Dict
    ) -> Tuple[bool, float]:
        """
        Check age gap constraint for a candidate.

        Args:
            candidate: Person being evaluated
            constraint: Constraint definition
            allocated_people: Already allocated people

        Returns:
            Tuple of (is_valid, score)
        """
        config_key = constraint['config_key']

        # Determine reference person(s)
        if 'reference_category_role' in constraint:
            # Reference is from a specific category role
            role = constraint['reference_category_role']
            selection = constraint.get('reference_selection', 'oldest')

            # Find people with this role in allocated_people
            reference_people = []
            category_indices = self.role_resolver.get_categories_by_role(role)

            for step_people in allocated_people.values():
                for person in step_people:
                    person_cat = self.distributor.get_person_category(person)
                    person_cat_idx = self.role_resolver.get_category_index(person_cat)

                    if person_cat_idx in category_indices:
                        reference_people.append(person)

            if not reference_people:
                return True, 100.0  # No reference = no constraint

            # Select reference based on selection method
            if selection == 'oldest':
                reference_person = max(reference_people, key=lambda p: p.age)
            elif selection == 'youngest':
                reference_person = min(reference_people, key=lambda p: p.age)
            else:
                reference_person = reference_people[0]

            reference_age = reference_person.age

        elif 'reference_step' in constraint:
            # Reference is from a specific step
            step_num = constraint['reference_step']

            if step_num not in allocated_people:
                return True, 100.0

            # Use first person from that step
            reference_person = allocated_people[step_num][0]
            reference_age = reference_person.age

        else:
            logger.warning(f"Age gap constraint has no reference: {constraint}")
            return True, 100.0

        # Validate age gap
        return self.constraint_validator.validate_age_gap(
            candidate.age,
            reference_age,
            config_key
        )

    def _check_sex_preference_constraint(
        self,
        candidate,
        constraint: Dict,
        allocated_people: Dict
    ) -> Tuple[bool, float]:
        """
        Check sex preference constraint for a candidate.

        Args:
            candidate: Person being evaluated
            constraint: Constraint definition
            allocated_people: Already allocated people

        Returns:
            Tuple of (is_valid, score)
        """
        # Get reference person
        if 'reference_step' in constraint:
            step_num = constraint['reference_step']

            if step_num not in allocated_people:
                return True, 100.0

            reference_person = allocated_people[step_num][0]
            reference_sex = reference_person.sex
        else:
            return True, 100.0

        # Check sex preference
        config_key = constraint['config_key']
        probability = constraint.get('probability', 0.95)

        return self.constraint_validator.validate_sex_preference(
            candidate.sex,
            reference_sex,
            config_key,
            probability
        )


class RuleEngine:
    """
    Manages household creation rules and orchestrates the allocation process.

    Selects appropriate rule for each pattern and executes allocation sequence.
    """

    def __init__(
        self,
        rules_config: List[Dict],
        role_resolver: RoleResolver,
        constraint_validator: ConstraintValidator
    ):
        """
        Initialize rule engine.

        Args:
            rules_config: List of rule configurations from YAML
            role_resolver: Role resolver instance
            constraint_validator: Constraint validator instance
        """
        self.role_resolver = role_resolver
        self.constraint_validator = constraint_validator

        # Create rule objects sorted by priority
        self.rules = [
            HouseholdCreationRule(r, role_resolver, constraint_validator)
            for r in rules_config
        ]
        self.rules.sort(key=lambda r: r.priority)

        logger.info(f"RuleEngine initialized with {len(self.rules)} rules")

    def find_rule(self, parsed_pattern: Dict) -> Optional[HouseholdCreationRule]:
        """
        Find the best matching rule for this pattern.

        Args:
            parsed_pattern: Parsed pattern from distributor

        Returns:
            Best matching rule, or None if no match
        """
        for rule in self.rules:
            if rule.matches_pattern(parsed_pattern):
                logger.debug(f"Pattern '{parsed_pattern['pattern']}' matched rule: {rule.name}")
                return rule

        logger.warning(f"No rule matched pattern: {parsed_pattern['pattern']}")
        return None

    def __repr__(self):
        return f"<RuleEngine: {len(self.rules)} rules>"
