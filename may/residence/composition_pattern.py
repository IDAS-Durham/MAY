"""
Composition pattern parsing and manipulation for households.

This module handles household composition patterns like ">=2 >=0 2 0" which specify
the required number of people in each age category.
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("composition_pattern")


@lru_cache(maxsize=1024)
def _parse_pattern_cached(pattern: str) -> Tuple[Tuple[str, int], ...]:
    """
    Cached pattern parsing function.

    Returns a tuple of (operator, count) tuples that can be cached.
    """
    parts = pattern.strip().split()
    requirements = []

    for part in parts:
        if part.startswith(">="):
            count = int(part[2:])
            requirements.append(("gte", count))
        elif part.startswith("<="):
            count = int(part[2:])
            requirements.append(("lte", count))
        else:
            count = int(part)
            requirements.append(("exact", count))

    return tuple(requirements)


@dataclass
class CompositionPattern:
    """
    Represents a household composition pattern.

    Example: ">=2 >=0 2 <=2" means:
    - 2 or more people in category 0 (Kids)
    - 0 or more people in category 1 (Young Adults)
    - exactly 2 people in category 2 (Adults)
    - 2 or fewer people in category 3 (Old Adults)
    """
    original_pattern: str
    requirements: List[Tuple[str, int]]  # List of (operator, count) for each category
    # operator can be "exact", "gte" (>=), or "lte" (<=)

    # Object cache for CompositionPattern instances
    _instance_cache = {}

    @classmethod
    def from_string(cls, pattern: str) -> 'CompositionPattern':
        """
        Parse a composition pattern string (with object-level caching).

        Args:
            pattern: Pattern string like ">=2 >=0 2 <=2"

        Returns:
            CompositionPattern object
        """
        pattern = pattern.strip()
        if pattern in cls._instance_cache:
            return cls._instance_cache[pattern]

        # Use cached parsing function for internal requirements
        requirements_tuple = _parse_pattern_cached(pattern)
        instance = cls(original_pattern=pattern, requirements=list(requirements_tuple))
        
        # Cache the instance
        cls._instance_cache[pattern] = instance
        return instance

    def __post_init__(self):
        """Initialize cached properties."""
        self._string_repr = None
        self._min_size = None

    def get_min_count(self, category_idx: int) -> int:
        """Get minimum required count for a category."""
        if category_idx >= len(self.requirements):
            return 0
        operator, count = self.requirements[category_idx]
        if operator == "lte":
            return 0  # <=N means minimum is 0
        return count  # For "exact" and "gte", minimum is the count

    def get_max_count(self, category_idx: int) -> Optional[int]:
        """Get maximum allowed count for a category (None if unlimited)."""
        if category_idx >= len(self.requirements):
            return None
        operator, count = self.requirements[category_idx]
        if operator == "exact":
            return count  # Exact N means max is N
        elif operator == "lte":
            return count  # <=N means max is N
        else:  # gte
            return None  # >=N means no upper limit

    def is_flexible(self, category_idx: int) -> bool:
        """Check if a category has flexible (>= or <=) requirement."""
        if category_idx >= len(self.requirements):
            return True
        operator, _ = self.requirements[category_idx]
        return operator in ("gte", "lte")

    def min_household_size(self) -> int:
        """Calculate minimum household size required (with caching)."""
        if self._min_size is None:
            self._min_size = sum(self.get_min_count(i) for i in range(len(self.requirements)))
        return self._min_size

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
            if cond_category not in category_name_to_idx:
                logger.warning(f"Rule '{rule_name}': Unknown category '{cond_category}'")
                continue
            
            cond_cat_idx = category_name_to_idx[cond_category]
            cond_count = self.get_min_count(cond_cat_idx)
            
            # Evaluate condition
            cond_operator = condition.get('operator')
            cond_value = condition.get('value')
            if not self._evaluate_operator(cond_count, cond_operator, cond_value):
                continue # Condition not met, skip to next rule

            # Condition met, check requirement(s)
            # requirement can be a single dict or a list of dicts (OR condition)
            req_list = requirement if isinstance(requirement, list) else [requirement]
            
            any_req_met = False
            for req in req_list:
                req_category = req.get('category')
                if req_category not in category_name_to_idx:
                    logger.warning(f"Rule '{rule_name}': Unknown category '{req_category}'")
                    continue

                req_cat_idx = category_name_to_idx[req_category]
                req_count = self.get_min_count(req_cat_idx)
                
                req_operator = req.get('operator')
                req_value = req.get('value')
                
                if self._evaluate_operator(req_count, req_operator, req_value):
                    any_req_met = True
                    break

            if not any_req_met:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"  Pattern violates rule '{rule_name}': {self}")
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
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )
            elif operator == "exact" and count > 0:
                # Reduce exact N to (N-1)
                new_requirements[cat_idx] = ("exact", count - 1)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )

        # Couldn't demote further
        return None

    def demote_to_count(self, cat_idx: int, target_count: int) -> Optional['CompositionPattern']:
        """
        Demote a specific category directly to a target count.

        This is more efficient than calling demote_once multiple times,
        as it jumps directly to the available count.

        Args:
            cat_idx: Category index to demote
            target_count: Target count to demote to (usually the available count)

        Returns:
            New CompositionPattern with the category set to >=target_count, or None if can't demote
        """
        if cat_idx >= len(self.requirements):
            return None

        operator, current_count = self.requirements[cat_idx]

        # Only demote if target is less than current
        # For "gte" operator, demote to >=target_count
        # For "exact" operator, demote to target_count (exact)
        if operator == "gte" and target_count < current_count:
            new_requirements = list(self.requirements)
            new_requirements[cat_idx] = ("gte", target_count)
            return CompositionPattern(
                original_pattern=self.original_pattern,
                requirements=new_requirements
            )
        elif operator == "exact" and target_count < current_count:
            new_requirements = list(self.requirements)
            new_requirements[cat_idx] = ("exact", target_count)
            return CompositionPattern(
                original_pattern=self.original_pattern,
                requirements=new_requirements
            )

        # No demotion needed or possible
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
            elif operator == "lte":
                parts.append(f"<={count}")
            else:  # exact
                parts.append(str(count))
        return " ".join(parts)

    def __repr__(self):
        return f"Pattern({self.to_string()})"

    def to_string(self) -> str:
        """Get current pattern as string (with lazy caching)."""
        if self._string_repr is None:
            self._string_repr = self._requirements_to_string(self.requirements)
        return self._string_repr
