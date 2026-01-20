"""
Data models for household allocation.

This module contains the core dataclasses used throughout the household
allocation system.

Note: Households are now represented as Venue objects with type="household".
The Household class has been removed in favor of the generic Venue system.
"""

from typing import Optional, List, Any
from dataclasses import dataclass


@dataclass
class Category:
    """
    Generic category for classifying entities based on any attribute.

    Supports:
    - Numerical attributes (e.g., age, income) with min/max ranges
    - Categorical attributes (future: education level, gender) with allowed values

    Examples:
        # Age category
        Category(name="Kids", symbol="K", attribute="age", type="numerical",
                min_value=0, max_value=17)

        # Income category
        Category(name="Low Income", symbol="LI", attribute="income", type="numerical",
                min_value=0, max_value=30000)
    """
    name: str
    symbol: str
    attribute: str                      # e.g., "age", "income", "education"
    type: str                           # "numerical" or "categorical"
    min_value: Optional[float] = None   # For numerical types
    max_value: Optional[float] = None   # For numerical types
    allowed_values: Optional[List[str]] = None  # For categorical types (future)

    def matches(self, entity: Any) -> bool:
        """
        Check if an entity matches this category.

        Args:
            entity: Object with the attribute to check (e.g., Person with .age)

        Returns:
            True if entity's attribute value falls within this category
        """
        # Get the attribute value from the entity
        attr_value = getattr(entity, self.attribute)

        if self.type == "numerical":
            if self.max_value is None:
                return attr_value >= self.min_value
            return self.min_value <= attr_value <= self.max_value
        elif self.type == "categorical":
            if self.allowed_values is None:
                raise ValueError(f"Category {self.name} is categorical but has no allowed_values")
            return attr_value in self.allowed_values
        else:
            raise ValueError(f"Unknown category type: {self.type}")

    def __repr__(self):
        if self.type == "numerical":
            max_str = f"{self.max_value}" if self.max_value is not None else "∞"
            return f"{self.name}({self.attribute}:{self.min_value}-{max_str})"
        else:
            return f"{self.name}({self.attribute}:{self.allowed_values})"


# Backwards compatibility alias (deprecated)
AgeCategory = Category
