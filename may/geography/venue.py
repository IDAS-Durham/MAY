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
        'parent',      # Parent venue (e.g., School for a Classroom)
        'children',    # List of child venues (e.g., Classrooms for a School)
    ]

    def __init__(self,
                 name: str,
                 venue_type,
                 geographical_unit,
                 coordinates=None,
                 properties: dict=None,
                 subsets: dict[str, Subset] = None,
                 parent=None,
                 children=None,
                 ):
        self.id = id(self)              # Unique numeric ID (generated)
        self.name = name                # Name of the venue (e.g., "St Mary's Hospital")
        self.type = venue_type          # Type of venue (e.g., "hospital", "school")
        self.geographical_unit = geographical_unit  # Reference to GeographicalUnit
        self.coordinates = coordinates  # Optional (latitude, longitude) tuple
        self.properties = properties if properties is not None else {}
        self.subsets = subsets if subsets is not None else {} # dict(subset_name, Subset object)
        self.parent = parent            # Parent venue reference
        self.children = children if children is not None else []  # List of child venues

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

    def add_to_subset(self, person, subset_key=None, activity_name=None, activity_type=None):
        """
        Add a person to a subset of this venue and register the activity.

        Args:
            person: Person object to add
            subset_key: Key for the subset (if None, uses first subset or creates default)
            activity_name: Activity name to register (if None, uses 'residence' for residence types, venue type otherwise)
            activity_type: Type for nesting in activity_map dict (if None, uses self.type)
                          This allows multiple venue types under the same activity_name
                          Example: activity_name='primary_activity', activity_type='own_land'
        """
        from may.population import Subset

        # Use 'residence' for all residence types, venue type otherwise
        if activity_name is None:
            # Check if this venue is a residence type
            is_residence = self.properties.get('is_residence', False)
            activity_name = 'residence' if is_residence else self.type

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

        # UNIFIED STRUCTURE: Use nested dict for all activities
        # Structure: person.activity_map[activity_name][venue_type] = [subsets]

        # Initialize nested dict if needed
        if not isinstance(person.activity_map[activity_name], dict):
            person.activity_map[activity_name] = {}

        # Determine the venue type key for nesting (use override or default to self.type)
        venue_type_key = activity_type if activity_type is not None else self.type

        # Initialize list for this venue type if needed
        if venue_type_key not in person.activity_map[activity_name]:
            person.activity_map[activity_name][venue_type_key] = []

        # Add subset to person's activity_map (check by venue ID to avoid duplicates)
        subset_already_added = any(
            s.venue.id == self.id
            for s in person.activity_map[activity_name][venue_type_key]
        )
        if not subset_already_added:
            person.activity_map[activity_name][venue_type_key].append(subset)

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

    def has_category(self, category_name: str) -> bool:
        """
        Check if this venue has a subset with the given category name.

        Args:
            category_name: Name of the category to check for (e.g., "Adults", "Kids")

        Returns:
            bool: True if a subset with this name exists and has members
        """
        for subset in self.subsets.values():
            if subset.subset_name == category_name and len(subset.members) > 0:
                return True
        return False

    def get_composition(self, categories=None):
        """
        Get composition by category (useful for household-type venues).

        Args:
            categories: List of Category objects

        Returns:
            dict: Composition counts by category name
        """
        # Get categories from properties if not provided
        if categories is None:
            categories = self.properties.get('_age_categories', [])

        if not categories:
            return {}

        composition = {cat.name: 0 for cat in categories}
        for person in self.get_all_members():
            for cat in categories:
                if cat.matches(person):
                    composition[cat.name] += 1
                    break
        return composition

    def add_child_venue(self, child):
        """
        Add a child venue and set this venue as its parent.
        Child venue inherits geographical_unit from parent if not already set.

        Args:
            child: Child Venue object to add

        Example:
            >>> school = venue_manager.create_venue("school", geo_unit)
            >>> classroom = venue_manager.create_venue("classroom", geo_unit)
            >>> school.add_child_venue(classroom)
        """
        # Inherit geographical_unit from parent if child doesn't have one
        if child.geographical_unit is None:
            child.geographical_unit = self.geographical_unit

        # Add to children list and set parent reference
        self.children.append(child)
        child.parent = self

    def get_all_children(self):
        """
        Get all direct child venues.

        Returns:
            List of child Venue objects
        """
        return self.children

    def get_all_descendants(self):
        """
        Get all descendant venues (children, grandchildren, etc.).

        Returns:
            List of all descendant Venue objects
        """
        descendants = []
        for child in self.children:
            descendants.append(child)
            descendants.extend(child.get_all_descendants())
        return descendants

    def get_root_venue(self):
        """
        Get the top-level parent venue in the hierarchy.

        Returns:
            Root Venue object (or self if this is the root)
        """
        current = self
        while current.parent is not None:
            current = current.parent
        return current

    def is_root(self):
        """
        Check if this venue is a root (has no parent).

        Returns:
            bool: True if this is a root venue
        """
        return self.parent is None

    def is_leaf(self):
        """
        Check if this venue is a leaf (has no children).

        Returns:
            bool: True if this venue has no children
        """
        return len(self.children) == 0

    def get_depth(self):
        """
        Get the depth of this venue in the hierarchy (0 for root).

        Returns:
            int: Depth level (0 = root, 1 = child of root, etc.)
        """
        depth = 0
        current = self.parent
        while current is not None:
            depth += 1
            current = current.parent
        return depth

    def get_total_members_recursive(self):
        """
        Get total number of members including all child venues.

        Returns:
            int: Total members across this venue and all descendants
        """
        total = self.num_members
        for child in self.children:
            total += child.get_total_members_recursive()
        return total
