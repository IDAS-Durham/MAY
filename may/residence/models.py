"""
Data models for household allocation.

This module contains the core dataclasses used throughout the household
allocation system.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

from may.geography.geography import GeographicalUnit
from may.population.person import Person


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
class Household:
    """Represents a household with residents."""
    id: int
    geographical_unit: GeographicalUnit  # Forward reference
    residents: List[Person] = field(default_factory=list)  # Forward reference
    properties: Dict = field(default_factory=dict)

    def add_resident(self, person: Person):
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
