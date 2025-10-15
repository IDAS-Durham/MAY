"""
Household class for June Zero.

Generic, simple container for people living together.
No hardcoded age groups - everything driven by config.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger("household")


class Household:
    """
    A household: people living together at a location.

    Design principles:
    - Simple: Just a container for people
    - Generic: No hardcoded age groups or types
    - Config-driven: Age brackets loaded from config
    - Extensible: properties dict for metadata

    Attributes:
        id: Unique household ID (auto-generated)
        geographical_unit: GeographicalUnit where household is located
        residents: List of Person objects
        properties: Dict for any metadata (type, composition, etc.)
    """

    _id_counter = 0

    def __init__(self, geographical_unit, age_bracket_config: Optional[Dict] = None):
        """
        Initialize a household.

        Args:
            geographical_unit: GeographicalUnit (SGU) where located
            age_bracket_config: Age bracket definitions from config
                               (if None, will load from global config)
        """
        # Auto-generate ID
        Household._id_counter += 1
        self.id = Household._id_counter

        # Location
        self.geographical_unit = geographical_unit

        # Residents
        self.residents: List = []

        # Age bracket configuration (dynamic, not hardcoded)
        self._age_brackets = age_bracket_config or self._load_default_age_brackets()

        # Extensible properties
        self.properties: Dict = {}

        logger.debug(
            f"Created household {self.id} in "
            f"{geographical_unit.name if hasattr(geographical_unit, 'name') else geographical_unit}"
        )

    def _load_default_age_brackets(self) -> List[Dict]:
        """
        Load default person categories from config.

        Returns:
            List of category definitions
        """
        # TODO: Load from global config singleton
        # For now, return default 4-category age-based system
        return [
            {'name': 'kid', 'min_age': 0, 'max_age': 17, 'categorization_type': 'age'},
            {'name': 'young_adult', 'min_age': 18, 'max_age': 25, 'categorization_type': 'age'},
            {'name': 'adult', 'min_age': 26, 'max_age': 64, 'categorization_type': 'age'},
            {'name': 'elder', 'min_age': 65, 'max_age': 120, 'categorization_type': 'age'}
        ]

    def add_resident(self, person):
        """
        Add a person to this household.

        Args:
            person: Person object
        """
        if person in self.residents:
            logger.warning(f"Person {person.id} already in household {self.id}")
            return

        self.residents.append(person)

        # Set person's residence
        if hasattr(person, 'residence'):
            person.residence = self

        logger.debug(
            f"Added person {person.id} (age {person.age}) to household {self.id}"
        )

    def remove_resident(self, person):
        """Remove a person from this household."""
        if person not in self.residents:
            logger.warning(f"Person {person.id} not in household {self.id}")
            return

        self.residents.remove(person)

        if hasattr(person, 'residence'):
            person.residence = None

        logger.debug(f"Removed person {person.id} from household {self.id}")

    def get_residents_by_category(self, category_name: str) -> List:
        """
        Get all residents in a specific category.

        Supports both age-based and property-based categories.

        Args:
            category_name: Name of category (e.g., 'kid', 'adult', 'servant')

        Returns:
            List of Person objects in that category
        """
        # Find the category definition
        category = next(
            (c for c in self._age_brackets if c['name'] == category_name),
            None
        )

        if not category:
            logger.warning(f"Unknown category: {category_name}")
            return []

        # Determine categorization type
        cat_type = category.get('categorization_type', 'age')

        if cat_type == 'age':
            # Age-based: filter by age range
            return [
                person for person in self.residents
                if category['min_age'] <= person.age <= category['max_age']
            ]
        elif cat_type == 'property':
            # Property-based: filter by property value
            property_key = category['property_key']
            property_value = category['property_value']
            return [
                person for person in self.residents
                if hasattr(person, 'properties')
                and person.properties.get(property_key) == property_value
            ]
        else:
            logger.warning(f"Unknown categorization type: {cat_type}")
            return []

    def get_composition(self) -> Dict[str, int]:
        """
        Get current composition (count by category).

        Works for both age-based and property-based categories.

        Returns:
            Dict mapping category name to count

        Example (age-based):
            {'kid': 2, 'young_adult': 0, 'adult': 2, 'elder': 0}

        Example (social class-based):
            {'noble': 1, 'freeman': 2, 'servant': 3, 'slave': 0}
        """
        composition = {}
        for category in self._age_brackets:
            count = len(self.get_residents_by_category(category['name']))
            composition[category['name']] = count
        return composition

    def get_composition_string(self) -> str:
        """
        Get composition as space-separated string.

        Returns:
            String like "2 0 2 0" (ordered by categories)

        Example (age-based):
            If categories = [kid, young_adult, adult, elder]
            And composition = {kid: 2, young_adult: 0, adult: 2, elder: 0}
            Returns: "2 0 2 0"

        Example (social class-based):
            If categories = [noble, freeman, servant, slave]
            And composition = {noble: 1, freeman: 2, servant: 3, slave: 0}
            Returns: "1 2 3 0"
        """
        composition = self.get_composition()
        # Order by category definition order
        counts = [str(composition.get(c['name'], 0)) for c in self._age_brackets]
        return ' '.join(counts)

    def size(self) -> int:
        """Get total number of residents."""
        return len(self.residents)

    def is_empty(self) -> bool:
        """Check if household is empty."""
        return len(self.residents) == 0

    def __repr__(self) -> str:
        """String representation."""
        gu_name = (
            self.geographical_unit.name
            if hasattr(self.geographical_unit, 'name')
            else str(self.geographical_unit)
        )
        return (
            f"Household(id={self.id}, geographical_unit={gu_name}, "
            f"size={self.size()})"
        )

    def __str__(self) -> str:
        """Human-readable string."""
        gu_name = (
            self.geographical_unit.name
            if hasattr(self.geographical_unit, 'name')
            else str(self.geographical_unit)
        )
        return (
            f"Household {self.id} in {gu_name}: "
            f"{self.size()} residents, composition: {self.get_composition_string()}"
        )

    @classmethod
    def reset_id_counter(cls):
        """Reset ID counter (for testing)."""
        cls._id_counter = 0
