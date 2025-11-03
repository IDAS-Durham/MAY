"""
Data models for household allocation.

This module contains the core dataclasses used throughout the household
allocation system.

Note: Households are now represented as Venue objects with type="household".
The Household class has been removed in favor of the generic Venue system.
"""

from typing import Optional
from dataclasses import dataclass


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
