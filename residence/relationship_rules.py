"""
Relationship rules for household composition.

This module handles generic demographic and attribute-based constraints for households:
- Numerical attribute differences between roles (e.g., age, income, education level)
- Couple matching with configurable categorical and numerical attributes
- Smart person selection with best-candidate fallback

The system is fully generic and works with:
- Any age categories defined in households_config.yaml
- Any numerical attributes (age, income, education years, etc.)
- Any categorical attributes (sex, religion, occupation, etc.)

No hardcoded assumptions about specific attributes - everything is configurable and pattern-based.
"""

import os
import logging
import yaml
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from population.person import Person

logger = logging.getLogger("relationship_rules")


@dataclass
class RelationshipRule:
    """A relationship rule for a specific household pattern."""
    name: str
    patterns: List[str]
    roles: Dict[str, Dict]  # role_name -> {categories: [...], count: ...}
    selection_order: List[str]
    constraints: List[Dict]


class RelationshipRulesValidator:
    """
    Validates and enforces relationship rules during household allocation.

    This class implements smart person selection that:
    1. Selects people according to role selection order
    2. Validates age difference constraints between roles
    3. Applies couple matching for romantic partners
    4. Falls back to "best candidate" if no perfect match exists
    """

    def __init__(self,
                 age_categories: List,
                 config_file: str = "data/households/relationship_rules.yaml"):
        """
        Initialize relationship rules validator.

        Args:
            age_categories: List of AgeCategory objects from household config
            config_file: Path to relationship rules YAML configuration
        """
        self.age_categories = age_categories
        self.category_name_to_idx = {cat.name: idx for idx, cat in enumerate(age_categories)}

        # Load configuration
        self.enabled = False
        self.rules = []
        self.selection_strategy = {}
        self.track_statistics = False

        if os.path.exists(config_file):
            self._load_config(config_file)
        else:
            logger.warning(f"Relationship rules config not found: {config_file}")
            logger.warning("Relationship rules disabled")

        # Statistics tracking
        self.stats = {
            'best_candidate_selections': 0,
            'same_category_pairs': 0,
            'different_category_pairs': 0,
            'numerical_attribute_differences': [],
            'violations': {
                'numerical_attribute_difference': 0,
                'pair_numerical_attribute_diff': 0
            }
        }

    def _load_config(self, config_file: str):
        """Load configuration from YAML file."""
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        self.enabled = config.get('enabled', False)
        self.selection_strategy = config.get('selection_strategy', {})
        self.track_statistics = config.get('track_statistics', False)

        # Parse rules
        for rule_config in config.get('rules', []):
            rule = RelationshipRule(
                name=rule_config.get('name', 'Unnamed rule'),
                patterns=rule_config.get('patterns', []),
                roles=rule_config.get('roles', {}),
                selection_order=rule_config.get('selection_order', []),
                constraints=rule_config.get('constraints', [])
            )
            self.rules.append(rule)

        logger.info(f"Loaded {len(self.rules)} relationship rules")

    def get_rule_for_pattern(self, pattern_str: str) -> Optional[RelationshipRule]:
        """
        Get relationship rule for a household pattern.

        Args:
            pattern_str: Household composition pattern (e.g., ">=2 >=0 2 0")

        Returns:
            RelationshipRule or None if pattern not found
        """
        if not self.enabled:
            return None

        for rule in self.rules:
            if pattern_str in rule.patterns:
                return rule

        return None

    def get_rule_by_name(self, rule_name: str) -> Optional[RelationshipRule]:
        """
        Get relationship rule by name.

        Args:
            rule_name: Name of the rule (e.g., "Two-adult family with kids")

        Returns:
            RelationshipRule or None if rule not found
        """
        if not self.enabled:
            return None

        for rule in self.rules:
            if rule.name == rule_name:
                return rule

        return None

    def validate_numerical_attribute_difference_constraint(self,
                                          person1: Person,
                                          people2: List[Person],
                                          constraint: Dict,
                                          log_rejection: bool = False) -> Tuple[bool, float]:
        """
        Validate numerical attribute difference constraint between person1 and people in people2.

        Constraint format:
          - attribute: name of numerical attribute to compare (e.g., "age", "income")
          - role_1: person1's role
          - role_2: people2's role
          - min_difference: min(person1[attribute] - person2[attribute])
          - max_difference: max(person1[attribute] - person2[attribute])
          - max_difference_by_categorical_attribute: {attribute: name, values: {val: max_diff}}

        When validating:
        - Check against MINIMUM attribute value in people2 for min_difference
        - Check against MAXIMUM attribute value in people2 for max_difference

        Args:
            person1: Person from role_1
            people2: List of people from role_2
            constraint: Constraint dict
            log_rejection: If True, log when validation fails (for debugging)

        Returns:
            Tuple of (is_valid, penalty_score)
        """
        if not people2:
            return (True, 0.0)

        attribute = constraint.get('attribute', 'age')  # Default to 'age' for backward compatibility
        min_diff = constraint.get('min_difference', 0)
        max_diff = constraint.get('max_difference', 100)

        # Override max based on categorical attribute if specified
        max_diff_by_cat = constraint.get('max_difference_by_categorical_attribute', {})
        if max_diff_by_cat:
            cat_attr_name = max_diff_by_cat.get('attribute')
            cat_values = max_diff_by_cat.get('values', {})
            person1_cat_value = getattr(person1, cat_attr_name, None)
            if person1_cat_value and person1_cat_value in cat_values:
                max_diff = cat_values[person1_cat_value]

        # Get attribute values
        person1_value = getattr(person1, attribute)

        # Check against person with MAX attribute value in people2 for min constraint
        max_person = max(people2, key=lambda p: getattr(p, attribute))
        max_value = getattr(max_person, attribute)
        diff_max = person1_value - max_value

        if diff_max < min_diff:
            penalty = min_diff - diff_max
            if log_rejection:
                logger.info(f"      ✗ Rejected: {person1} - too young (diff={diff_max} < min={min_diff})")
            return (False, penalty)

        # Check against person with MIN attribute value in people2 for max constraint
        min_person = min(people2, key=lambda p: getattr(p, attribute))
        min_value = getattr(min_person, attribute)
        diff_min = person1_value - min_value

        if diff_min > max_diff:
            penalty = diff_min - max_diff
            if log_rejection:
                logger.info(f"      ✗ Rejected: {person1} - too old (diff={diff_min} > max={max_diff}, penalty={penalty})")
            return (False, penalty)

        return (True, 0.0)

    def validate_couple_numerical_attribute_difference(self,
                                      person1: Person,
                                      person2: Person,
                                      constraint: Dict) -> Tuple[bool, float]:
        """
        Validate numerical attribute difference between couple members.

        Args:
            person1: First person
            person2: Second person
            constraint: Constraint dict with numerical_attribute parameters

        Returns:
            Tuple of (is_valid, penalty_score)
        """
        num_attr_config = constraint.get('numerical_attribute', {})
        if not num_attr_config:
            return (True, 0.0)

        attribute = num_attr_config.get('attribute', 'age')
        max_absolute = num_attr_config.get('max_absolute_difference', 100)

        value1 = getattr(person1, attribute)
        value2 = getattr(person2, attribute)
        diff = abs(value1 - value2)

        if diff > max_absolute:
            penalty = diff - max_absolute
            return (False, penalty)

        return (True, 0.0)

    def calculate_couple_numerical_attribute_penalty(self,
                                    person1: Person,
                                    person2: Person,
                                    constraint: Dict) -> float:
        """
        Calculate penalty score for couple numerical attribute difference.

        Lower score = better match based on expected mean/std.

        Args:
            person1: First person
            person2: Second person
            constraint: Constraint dict

        Returns:
            Penalty score (0.0 = perfect match)
        """
        num_attr_config = constraint.get('numerical_attribute', {})
        if not num_attr_config:
            return 0.0

        attribute = num_attr_config.get('attribute', 'age')
        mean = num_attr_config.get('mean_difference', 3.0)
        std = num_attr_config.get('std_difference', 5.0)

        value1 = getattr(person1, attribute)
        value2 = getattr(person2, attribute)
        diff = abs(value1 - value2)

        # Z-score: how many standard deviations from mean
        z_score = abs(diff - mean) / max(std, 1.0)

        # Apply penalty mode
        penalty_mode = self.selection_strategy.get('penalty_mode', 'squared')
        if penalty_mode == 'squared':
            return z_score ** 2
        else:
            return z_score

    def select_person_with_constraint(self,
                                     candidates: List[Person],
                                     existing_people_by_role: Dict[str, List[Person]],
                                     constraints: List[Dict],
                                     current_role: str,
                                     required_sex: Optional[str] = None,
                                     show_detailed_logs: bool = False) -> Optional[Person]:
        """
        Select a person from candidates that satisfies all constraints.

        Implements smart selection:
        1. Try random selection up to max_attempts
        2. If no valid person found, use best candidate (lowest penalty)

        Args:
            candidates: List of candidate persons
            existing_people_by_role: Dict of role_name -> list of already selected people
            constraints: List of constraint dicts to validate
            current_role: Name of role being filled
            required_sex: Required sex (None = any)
            show_detailed_logs: If True, log detailed selection process

        Returns:
            Selected person or None
        """
        if not candidates:
            return None

        # Filter by sex if specified
        if required_sex:
            candidates = [p for p in candidates if p.sex == required_sex]
            if not candidates:
                return None

        max_attempts = self.selection_strategy.get('max_attempts', 50)
        use_best = self.selection_strategy.get('use_best_candidate', True)

        # Filter constraints relevant to current_role
        relevant_constraints = [
            c for c in constraints
            if c.get('type') == 'numerical_attribute_difference' and c.get('role_1') == current_role
        ]

        # Try random selection up to max_attempts
        candidates_tested = 0
        candidates_rejected = 0

        for attempt in range(min(max_attempts, len(candidates))):
            candidate = random.choice(candidates)
            candidates_tested += 1

            # Validate all relevant constraints
            all_valid = True
            for constraint in relevant_constraints:
                role_2 = constraint.get('role_2')
                people_2 = existing_people_by_role.get(role_2, [])

                is_valid, penalty = self.validate_numerical_attribute_difference_constraint(
                    candidate, people_2, constraint, log_rejection=show_detailed_logs
                )

                if not is_valid:
                    all_valid = False
                    candidates_rejected += 1
                    break

            if all_valid:
                if show_detailed_logs:
                    if candidates_rejected > 0:
                        logger.info(f"  ✓ Selected (tested {candidates_tested} candidates, rejected {candidates_rejected}): {candidate}")
                    else:
                        logger.info(f"  ✓ Selected on first try: {candidate}")
                return candidate

        # No valid candidate found, use best candidate if enabled
        if self.selection_strategy.get('log_violations', False):
            logger.warning(f"No valid candidate found for {current_role} after {max_attempts} attempts. use_best_candidate={use_best}")

        if use_best:
            best_candidate = None
            best_penalty = float('inf')

            for candidate in candidates:
                total_penalty = 0.0

                for constraint in relevant_constraints:
                    role_2 = constraint.get('role_2')
                    people_2 = existing_people_by_role.get(role_2, [])

                    is_valid, penalty = self.validate_numerical_attribute_difference_constraint(
                        candidate, people_2, constraint
                    )
                    total_penalty += penalty

                if total_penalty < best_penalty:
                    best_penalty = total_penalty
                    best_candidate = candidate

            if best_candidate:
                self.stats['best_candidate_selections'] += 1
                self.stats['violations']['numerical_attribute_difference'] += 1

                logger.error(f"⚠️  USING BEST CANDIDATE (VIOLATES CONSTRAINTS) for {current_role}: "
                           f"age={best_candidate.age}, sex={best_candidate.sex}, "
                           f"penalty={best_penalty:.2f}")

                return best_candidate

        if self.selection_strategy.get('log_violations', False):
            logger.warning(f"Returning None for {current_role} - no valid candidates and use_best_candidate=False")

        return None

    def select_pair(self,
                     candidates: List[Person],
                     constraint: Dict,
                     existing_people_by_role: Optional[Dict[str, List[Person]]] = None,
                     constraints: Optional[List[Dict]] = None,
                     current_role: Optional[str] = None,
                     show_detailed_logs: bool = False) -> Optional[Tuple[Person, Person]]:
        """
        Select 2 people from candidates to form a compatible pair.

        Can be used for: romantic partners, roommates, business partners, siblings, etc.

        Selection process:
        1. Decide same/different category based on same_category_probability
        2. Select first person randomly (validating against existing people if provided)
        3. Select second person with attribute compatibility and validation

        Args:
            candidates: List of candidate persons
            constraint: Pair matching constraint
            existing_people_by_role: Dict of already selected people by role (optional)
            constraints: List of all constraints to validate against (optional)
            current_role: Name of current role being filled (optional)
            show_detailed_logs: If True, log detailed selection process

        Returns:
            Tuple of (person1, person2) or None
        """
        if existing_people_by_role is None:
            existing_people_by_role = {}
        if constraints is None:
            constraints = []
        if len(candidates) < 2:
            return None

        # Extract categorical attribute config
        cat_attr_config = constraint.get('categorical_attribute', {})
        cat_attribute = cat_attr_config.get('attribute', 'sex')
        same_category_prob = cat_attr_config.get('same_category_probability', 0.05)

        is_same_category = random.random() < same_category_prob

        if show_detailed_logs:
            pair_type = f"same-{cat_attribute}" if is_same_category else f"different-{cat_attribute}"
            logger.info(f"    Pair type: {pair_type} (prob={same_category_prob*100:.0f}%)")

        # Get relevant numerical_attribute_difference constraints for this role
        relevant_constraints = [
            c for c in constraints
            if c.get('type') == 'numerical_attribute_difference' and c.get('role_1') == current_role
        ] if current_role else []

        if show_detailed_logs and relevant_constraints:
            for rc in relevant_constraints:
                role_2 = rc.get('role_2')
                people_2 = existing_people_by_role.get(role_2, [])
                if people_2:
                    attribute = rc.get('attribute', 'age')
                    values = [getattr(p, attribute) for p in people_2]
                    logger.info(f"    {attribute.capitalize()} constraints: Both partners must be {rc.get('min_difference')}-{rc.get('max_difference')} {attribute} units older than {role_2} ({attribute}s: {values})")

        max_attempts = self.selection_strategy.get('max_attempts', 50)
        use_best = self.selection_strategy.get('use_best_candidate', True)

        # Try to find a valid couple
        attempts_made = 0
        candidates_tested = 0
        candidates_rejected = 0

        for attempt in range(min(max_attempts, len(candidates))):
            # Select first person randomly
            first_person = random.choice(candidates)
            candidates_tested += 1

            # Validate first person against existing people (e.g., children)
            first_valid = True
            for rel_constraint in relevant_constraints:
                role_2 = rel_constraint.get('role_2')
                people_2 = existing_people_by_role.get(role_2, [])
                if people_2:
                    # Only log rejections if detailed logging is enabled
                    is_valid, _ = self.validate_numerical_attribute_difference_constraint(
                        first_person, people_2, rel_constraint, log_rejection=show_detailed_logs
                    )
                    if not is_valid:
                        first_valid = False
                        candidates_rejected += 1
                        break

            if not first_valid:
                continue

            # Filter remaining candidates
            remaining = [p for p in candidates if p.id != first_person.id]

            # Determine required categorical attribute value for second person
            first_cat_value = getattr(first_person, cat_attribute)
            if is_same_category:
                required_cat_value = first_cat_value
            else:
                # For binary attributes like sex, swap the value
                # This is a simple heuristic - for more complex categories, you'd need a mapping
                if cat_attribute == 'sex':
                    required_cat_value = 'male' if first_cat_value == 'female' else 'female'
                else:
                    # For non-binary categorical attributes, we can't easily determine "opposite"
                    # So we just select a different value
                    all_cat_values = list(set([getattr(p, cat_attribute) for p in candidates]))
                    other_values = [v for v in all_cat_values if v != first_cat_value]
                    required_cat_value = random.choice(other_values) if other_values else first_cat_value

            # Filter by categorical attribute
            remaining = [p for p in remaining if getattr(p, cat_attribute) == required_cat_value]
            if not remaining:
                continue

            # Try to find valid partner
            for partner_attempt in range(min(max_attempts, len(remaining))):
                candidate = random.choice(remaining)
                candidates_tested += 1

                # Validate partner against first person (couple numerical attribute difference)
                is_valid, penalty = self.validate_couple_numerical_attribute_difference(
                    first_person, candidate, constraint
                )
                if not is_valid:
                    candidates_rejected += 1
                    if show_detailed_logs:
                        logger.info(f"      ✗ Rejected: Partner pair has age difference too large")
                    continue

                # Validate partner against existing people (e.g., children)
                partner_valid = True
                for rel_constraint in relevant_constraints:
                    role_2 = rel_constraint.get('role_2')
                    people_2 = existing_people_by_role.get(role_2, [])
                    if people_2:
                        is_valid, _ = self.validate_numerical_attribute_difference_constraint(
                            candidate, people_2, rel_constraint, log_rejection=show_detailed_logs
                        )
                        if not is_valid:
                            partner_valid = False
                            candidates_rejected += 1
                            break

                if partner_valid:
                    # Found a valid pair!
                    if show_detailed_logs:
                        num_attr_config = constraint.get('numerical_attribute', {})
                        if num_attr_config:
                            num_attr = num_attr_config.get('attribute', 'age')
                            val1 = getattr(first_person, num_attr)
                            val2 = getattr(candidate, num_attr)
                            diff = abs(val1 - val2)
                            if candidates_rejected > 0:
                                logger.info(f"    ✓ Found valid pair (tested {candidates_tested} candidates, rejected {candidates_rejected})")
                            else:
                                logger.info(f"    ✓ Found valid pair on first try")
                            logger.info(f"      Partner 1: {first_person} ({num_attr} {val1})")
                            logger.info(f"      Partner 2: {candidate} ({num_attr} {val2})")
                            logger.info(f"      {num_attr.capitalize()} difference: {diff}")
                        else:
                            if candidates_rejected > 0:
                                logger.info(f"    ✓ Found valid pair (tested {candidates_tested} candidates, rejected {candidates_rejected})")
                            else:
                                logger.info(f"    ✓ Found valid pair on first try")
                            logger.info(f"      Partner 1: {first_person}")
                            logger.info(f"      Partner 2: {candidate}")

                    if self.track_statistics:
                        # Track numerical attribute differences
                        num_attr_config = constraint.get('numerical_attribute', {})
                        if num_attr_config:
                            num_attr = num_attr_config.get('attribute')
                            if num_attr and hasattr(first_person, num_attr) and hasattr(candidate, num_attr):
                                diff = abs(getattr(first_person, num_attr) - getattr(candidate, num_attr))
                                self.stats['numerical_attribute_differences'].append(diff)

                        # Track categorical attribute statistics
                        if is_same_category:
                            self.stats['same_category_pairs'] += 1
                        else:
                            self.stats['different_category_pairs'] += 1

                    return (first_person, candidate)

            attempts_made += 1

        # No valid pair found, use best candidate
        if use_best:
            best_partner = None
            best_penalty = float('inf')

            for candidate in remaining:
                is_valid, val_penalty = self.validate_couple_numerical_attribute_difference(
                    first_person, candidate, constraint
                )
                attr_penalty = self.calculate_couple_numerical_attribute_penalty(
                    first_person, candidate, constraint
                )
                total_penalty = val_penalty + attr_penalty

                if total_penalty < best_penalty:
                    best_penalty = total_penalty
                    best_partner = candidate

            if best_partner:
                self.stats['best_candidate_selections'] += 1
                self.stats['violations']['pair_numerical_attribute_diff'] += 1

                if self.track_statistics:
                    # Track numerical attribute differences
                    num_attr_config = constraint.get('numerical_attribute', {})
                    if num_attr_config:
                        num_attr = num_attr_config.get('attribute')
                        if num_attr and hasattr(first_person, num_attr) and hasattr(best_partner, num_attr):
                            diff = abs(getattr(first_person, num_attr) - getattr(best_partner, num_attr))
                            self.stats['numerical_attribute_differences'].append(diff)

                    # Track categorical attribute statistics
                    if is_same_category:
                        self.stats['same_category_pairs'] += 1
                    else:
                        self.stats['different_category_pairs'] += 1

                return (first_person, best_partner)

        return None

    def print_statistics(self):
        """Print statistics about relationship rule application."""
        if not self.track_statistics:
            return

        logger.info("=" * 60)
        logger.info("RELATIONSHIP RULES STATISTICS")
        logger.info("=" * 60)

        # Best candidate selections
        if self.stats['best_candidate_selections'] > 0:
            logger.info(f"Best candidate selections: {self.stats['best_candidate_selections']:,}")

        # Pair types
        total_pairs = self.stats['same_category_pairs'] + self.stats['different_category_pairs']
        if total_pairs > 0:
            logger.info(f"Pairs created: {total_pairs:,}")
            logger.info(f"  Same-category: {self.stats['same_category_pairs']:,} "
                       f"({100*self.stats['same_category_pairs']/total_pairs:.1f}%)")
            logger.info(f"  Different-category: {self.stats['different_category_pairs']:,} "
                       f"({100*self.stats['different_category_pairs']/total_pairs:.1f}%)")

        # Numerical attribute differences
        if self.stats['numerical_attribute_differences']:
            import statistics as stats_module
            logger.info(f"Partner numerical attribute differences:")
            logger.info(f"  Mean: {stats_module.mean(self.stats['numerical_attribute_differences']):.1f}")
            logger.info(f"  Median: {stats_module.median(self.stats['numerical_attribute_differences']):.1f}")
            logger.info(f"  Range: {min(self.stats['numerical_attribute_differences'])}-"
                       f"{max(self.stats['numerical_attribute_differences'])}")

        # Violations
        total_violations = sum(self.stats['violations'].values())
        if total_violations > 0:
            logger.info(f"Rule violations (resolved with best candidate):")
            for violation_type, count in self.stats['violations'].items():
                if count > 0:
                    logger.info(f"  {violation_type}: {count:,}")

        logger.info("=" * 60)
