"""
Communal Establishment class for June Zero.

A communal establishment is just a household with workers.
Care homes, student dorms, boarding schools, etc.
"""

import logging
from typing import List, Optional
from .household import Household

logger = logging.getLogger("communal_establishment")


class CommunalEstablishment(Household):
    """
    A communal establishment: household + workers.

    Inherits from Household but adds:
    - Workers (staff who don't live there)
    - Capacity limits
    - Establishment type (care_home, student_accommodation, etc.)

    Design principles:
    - Simple: Just extends Household
    - Generic: No hardcoded types
    - Realistic: Capacity can be exceeded slightly
    """

    def __init__(
        self,
        geographical_unit,
        name: str,
        establishment_type: str,
        capacity: int,
        age_bracket_config: Optional[List] = None
    ):
        """
        Initialize a communal establishment.

        Args:
            geographical_unit: GeographicalUnit (SGU) where located
            name: Name of establishment
            establishment_type: Type (care_home, student_accommodation, etc.)
            capacity: Maximum resident capacity
            age_bracket_config: Age bracket definitions from config
        """
        # Initialize as a household
        super().__init__(geographical_unit, age_bracket_config)

        # Communal-specific attributes
        self.name = name
        self.establishment_type = establishment_type
        self.capacity = capacity

        # Workers (people who work here but don't live here)
        self.workers: List = []

        # Store additional metadata in properties
        self.properties['is_communal'] = True

        logger.debug(
            f"Created {establishment_type} '{name}' in "
            f"{geographical_unit.name if hasattr(geographical_unit, 'name') else geographical_unit} "
            f"(capacity: {capacity})"
        )

    def add_worker(self, person):
        """
        Add a worker to this establishment.

        Args:
            person: Person object (worker, not resident)
        """
        if person in self.workers:
            logger.warning(f"Person {person.id} already works at {self.name}")
            return

        self.workers.append(person)

        # Set person's workplace
        if hasattr(person, 'workplace'):
            person.workplace = self

        logger.debug(
            f"Added person {person.id} as worker at {self.name} "
            f"({len(self.workers)} workers)"
        )

    def remove_worker(self, person):
        """Remove a worker from this establishment."""
        if person not in self.workers:
            logger.warning(f"Person {person.id} doesn't work at {self.name}")
            return

        self.workers.remove(person)

        if hasattr(person, 'workplace'):
            person.workplace = None

        logger.debug(f"Removed person {person.id} as worker from {self.name}")

    def occupancy_rate(self) -> float:
        """Get occupancy as percentage of capacity."""
        if self.capacity == 0:
            return 0.0
        return (self.size() / self.capacity) * 100

    def is_full(self, allow_overfill: bool = True, overfill_pct: float = 0.10) -> bool:
        """
        Check if establishment is at capacity.

        Args:
            allow_overfill: Allow overcapacity (realistic for institutions)
            overfill_pct: Percentage overfill allowed (default 10%)

        Returns:
            True if full or over capacity
        """
        if allow_overfill:
            max_capacity = int(self.capacity * (1 + overfill_pct))
        else:
            max_capacity = self.capacity

        return self.size() >= max_capacity

    def available_spaces(self, allow_overfill: bool = True, overfill_pct: float = 0.10) -> int:
        """Get number of available spaces."""
        if allow_overfill:
            max_capacity = int(self.capacity * (1 + overfill_pct))
        else:
            max_capacity = self.capacity

        available = max_capacity - self.size()
        return max(0, available)

    def __repr__(self) -> str:
        """String representation."""
        gu_name = (
            self.geographical_unit.name
            if hasattr(self.geographical_unit, 'name')
            else str(self.geographical_unit)
        )
        return (
            f"CommunalEstablishment(id={self.id}, name='{self.name}', "
            f"type={self.establishment_type}, geographical_unit={gu_name}, "
            f"occupancy={self.size()}/{self.capacity})"
        )

    def __str__(self) -> str:
        """Human-readable string."""
        gu_name = (
            self.geographical_unit.name
            if hasattr(self.geographical_unit, 'name')
            else str(self.geographical_unit)
        )
        return (
            f"{self.establishment_type.replace('_', ' ').title()}: {self.name} "
            f"in {gu_name} ({self.size()}/{self.capacity} residents, "
            f"{self.occupancy_rate():.1f}% full, {len(self.workers)} workers)"
        )
