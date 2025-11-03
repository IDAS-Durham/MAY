"""
Venue management for June Zero.
Venues are places where people live, work, learn, or receive services.
"""

import logging
import pandas as pd
import os
from may.population import Subset

logger = logging.getLogger("venue")

class Venue:
    """
    Represents a place where people live, work, learn, or receive services.
    Generic design that works for any geography, past or present.

    Attributes:
      id (id):
        Unique numeric ID for the venue. Generated using id(),
        so will essentially be the memory location of the Venue instance.
      name (str):
        A string giving the name of the venue, e.g. "St Mary's Hospital".
      type :
        A label for the type of venue. Usually a string e.g. "hospital", "school", "household".
      geographical_unit :
        Reference to the GeographicalUnit in which the Venue is located.
      coordinates (tuple[float, float], optional):
        Latitude, longitude tuple. Default is None.
      properties (dict, optional):
        Extensible dict for venue-specific data. Default is {'subgroups':['default']}, which gives a list of the subgroup names for that specific venue. By default, the Venue object has a single subgroup called 'everyone'
    """

    __slots__ = [
        'id',
        'name',
        'type',
        'geographical_unit',
        'coordinates',
        'properties',
        'subsets',
    ]

    def __init__(self,
                 name: str,
                 venue_type,
                 geographical_unit,
                 coordinates=None,
                 properties: dict=None,
                 subsets: dict[str, Subset] = None,
                 ):
        self.id = id(self)              # Unique numeric ID (generated)
        self.name = name                # Name of the venue (e.g., "St Mary's Hospital")
        self.type = venue_type          # Type of venue (e.g., "hospital", "school")
        self.geographical_unit = geographical_unit  # Reference to GeographicalUnit
        self.coordinates = coordinates  # Optional (latitude, longitude) tuple
        self.properties = properties if properties is not None else {}
        self.subsets = subsets if subsets is not None else {} # dict(subset_name, Subset object)

    def get_capacity_for_attributes(self, capacity_config, **attributes):
        """
        Get capacity for specific attributes (e.g., age and sex).

        This method looks up the appropriate capacity column based on the
        provided attributes and the capacity_config from venues_config.yaml.

        Args:
            capacity_config: Capacity configuration dict from VenueManager
            **attributes: Attribute filters (e.g., age=85, sex="male")

        Returns:
            int: Capacity for this attribute combination, or 0 if not found

        Example:
            venue.get_capacity_for_attributes(config, age=85, sex="male")
            # Returns value from 'age_85_94_male' column
        """
        if not capacity_config:
            return 0

        # Get attribute capacities config
        attr_capacities = capacity_config.get('attribute_capacities', {})
        if not attr_capacities:
            return 0

        column_mappings = attr_capacities.get('column_mappings', {})
        if not column_mappings:
            return 0

        # Find matching column
        for column_name, criteria in column_mappings.items():
            match = True

            # Check each attribute provided by caller
            for attr_name, attr_value in attributes.items():
                # Handle age -> age_band mapping
                if attr_name == 'age' and 'age_band' in criteria:
                    min_val, max_val = criteria['age_band']
                    if not (min_val <= attr_value <= max_val):
                        match = False
                        break

                # Direct attribute match
                elif attr_name in criteria:
                    criterion = criteria[attr_name]

                    # Handle range (list format)
                    if isinstance(criterion, list):
                        min_val, max_val = criterion
                        if not (min_val <= attr_value <= max_val):
                            match = False
                            break

                    # Handle categorical (exact match)
                    else:
                        if criterion != attr_value:
                            match = False
                            break

                # Attribute not relevant for this column, skip
                # (e.g., checking 'age' but column only has 'sex')
                else:
                    continue

            if match:
                # Found matching column, return its value
                capacity = self.properties.get(column_name, 0)
                return int(capacity) if capacity else 0

        return 0

    def __repr__(self):
        geo_name = self.geographical_unit.name if self.geographical_unit else "None"
        return f"<Venue #{self.id}: {self.name} ({self.type}) in {geo_name}>"

    def __eq__(self, other):
        """Tests the equality of two Venue objects. """
        for attribute in ['id', 'name', 'type', 'geographic_unit', 'coordinates']:
            if hasattr(self, attribute) ^ hasattr(other, attribute):
                return False
            elif hasattr(self, attribute) and hasattr(other, attribute):
                if not (getattr(self, attribute) == getattr(other, attribute)):
                    return False
        if not (self.properties == other.properties):
            return False
        return True

    @property
    def num_members(self):
        total=0
        for subset in self.subsets.values():
            total += subset.num_members
        return total

    def add_to_subset(self, person, subset_key=None, activity_name=None):
        """
        Add a person to a subset of this venue and register the activity.

        Args:
            person: Person object to add
            subset_key: Key for the subset (if None, uses first subset or creates default)
            activity_name: Activity name to register (if None, uses venue type)
        """
        from may.population import Subset

        # Use venue type as default activity if not specified
        if activity_name is None:
            activity_name = self.type

        # If no subset_key specified, use the first existing subset or create one
        if subset_key is None:
            if self.subsets:
                subset_key = next(iter(self.subsets.keys()))
            else:
                subset_key = 0  # Use numeric index as default

        # Create subset if it doesn't exist
        if subset_key not in self.subsets:
            subset_index = len(self.subsets)
            self.subsets[subset_key] = Subset(
                venue=self,
                subset_index=subset_index,
                subset_name=str(subset_key)
            )

        subset = self.subsets[subset_key]

        # Add person to subset members
        subset.add_member(person)

        # Register activity in person's activity_map
        if activity_name not in person.activities:
            person.add_activity(activity_name)

        # Add subset to person's activity_map (check by venue ID to avoid equality check issues)
        subset_already_added = any(s.venue.id == self.id for s in person.activity_map[activity_name])
        if not subset_already_added:
            person.activity_map[activity_name].append(subset)

    def get_all_members(self):
        """
        Get all members from all subsets.

        Returns:
            List of Person objects
        """
        members = []
        for subset in self.subsets.values():
            members.extend(list(subset.members))
        return members

    def size(self) -> int:
        """
        Get total number of members across all subsets.

        Returns:
            int: Number of members
        """
        return sum(len(subset.members) for subset in self.subsets.values())

    def get_composition(self, age_categories=None):
        """
        Get composition by age category (useful for household-type venues).

        Args:
            age_categories: List of AgeCategory objects

        Returns:
            dict: Composition counts by category name
        """
        # Get age_categories from properties if not provided
        if age_categories is None:
            age_categories = self.properties.get('_age_categories', [])

        if not age_categories:
            return {}

        composition = {cat.name: 0 for cat in age_categories}
        for person in self.get_all_members():
            for cat in age_categories:
                if cat.matches(person.age):
                    composition[cat.name] += 1
                    break
        return composition
