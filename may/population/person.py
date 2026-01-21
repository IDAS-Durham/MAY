"""
Person class for June Zero.

Represents an individual agent with age, sex, geographical unit, and activities.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from may.geography.geography import GeographicalUnit
    from may.world import Subset


class Person:
    """
    Represents an individual person in the simulation.

    Attributes:
        id (int): Unique numeric identifier
        age (int): Age in years
        sex (str): Sex category (e.g., "male", "female")
        geographical_unit (GeographicalUnit): SGU where person lives
        activities (list): List of activity names this person can do
        properties (dict): Extensible dictionary for additional attributes
        activity_map (defaultdict):
    """

    _id_counter = 0
 
    __slots__ = [
        'id',
        'age',
        'sex',
        'geographical_unit',
        'activities',
        'properties',
        'activity_map',
    ]


    def __init__(
        self,
        age: float,
        sex: str,
        geographical_unit: Optional["GeographicalUnit"] = None,
        activities: Optional[list[str]] = None,
        properties: Optional[dict[str, Any]] = None,
        activity_map: Optional[dict[str, dict[str, list["Subset"]]]] = None
    ) -> None:
        """
        Initialize a Person.

        Args:
            age (int): Age in years
            sex (str): Sex category
            geographical_unit (GeographicalUnit, optional): SGU where person lives
            activities (list[str], optional): List of activity names
            properties (dict, optional): Additional attributes
            activity_map (dict[str, dict[str, list[Subset]]], optional):
              UNIFIED STRUCTURE: Nested dictionary mapping:
                activity_name -> venue_type -> [subsets]
              Examples:
                - activity_map['residence']['household'] = [subset]
                - activity_map['primary_activity']['own_land'] = [subset]
                - activity_map['primary_activity']['lords_demesne'] = [subset]
                - activity_map['leisure']['cinema'] = [subset1, subset2, subset3]
              Default = {}.

        """
        self.id = Person._id_counter
        Person._id_counter += 1
        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit
        self.activities = activities if activities is not None else set()
        self.properties = properties if properties is not None else {}
        # UNIFIED STRUCTURE: activity_map[activity_name][venue_type] = [subsets]
        if activity_map is None:
            self.activity_map = {}
       
    @classmethod
    def reset_counter(cls) -> None:
        """Reset the ID counter (useful for testing)."""
        cls._id_counter = 0

    def add_activity(self, activity: str) -> None:
        """
        Add an activity to this person's activity list.

        Args:
            activity (str): Name of the activity to add
        """
        #if activity not in self.activities:
        self.activities.add(activity)

        # Initialize activity_map with empty dict for unified structure
        # Structure: activity_map[activity_name][venue_type] = [subsets]
        if activity not in self.activity_map:
            self.activity_map[activity] = {}

    def remove_activity(self, activity: str) -> None:
        """
        Remove an activity from this person's activity list.

        Args:
            activity (str): Name of the activity to remove
        """
        #if activity in self.activities:
        self.activities.remove(activity)

    def add_activities(self, activities):
        self.activities.update(activities)

    def has_activity(self, activity: str) -> bool:
        """
        Check if person has a specific activity.

        Args:
            activity (str): Name of the activity to check

        Returns:
            bool: True if person has this activity
        """
        return activity in self.activities

    @classmethod
    def register_residence_types(cls, residence_types: list[str]) -> None:
        """
        Register residence types from VenueManager configuration.

        This should be called once during world setup to enable the
        residence property to work with custom residence types.

        Args:
            residence_types: List of venue types that are residences
                           (e.g., ['household', 'care_home', 'student_dorms'])

        Example:
            >>> Person.register_residence_types(['household', 'care_home', 'farm'])
        """
        cls._residence_types_registry = residence_types

    @property
    def residence(self):
        """
        Get the venue where this person resides.

        This property automatically finds the person's residence by checking
        for the 'residence' activity in their activity_map. All residence types
        (household, care_home, boarding_school, student_dorms, etc.) are
        registered under the 'residence' activity.

        Returns:
            Venue object where person lives, or None if no residence assigned

        Examples:
            >>> person.residence
            <Venue #123: household_E00004320 (household) in E00004320>

            >>> person.residence.type
            'household'

            >>> person.residence.geographical_unit.name
            'E00004320'

            >>> # Works with any residence type
            >>> person.residence.type
            'care_home'
        """
        # Check for 'residence' activity in activity_map
        # UNIFIED STRUCTURE: activity_map['residence'][venue_type] = [subsets]
        if 'residence' in self.activity_map and self.activity_map['residence']:
            # Iterate through venue types (household, care_home, etc.) and return first found
            for venue_type, subsets in self.activity_map['residence'].items():
                if subsets:  # Check if list is not empty
                    return subsets[0].venue

        return None

    @property
    def residence_type(self):
        """
        Get the type of residence this person lives in.

        Returns:
            String indicating residence type (e.g., 'household', 'care_home',
            'farm', 'bench'), or None if no residence assigned

        Examples:
            >>> person.residence_type
            'household'

            >>> person.residence_type
            'care_home'

            >>> person.residence_type
            'farm'
        """
        residence = self.residence
        return residence.type if residence else None

    def has_residence(self) -> bool:
        """
        Check if person has been assigned a residence.

        Returns:
            True if person has a residence, False otherwise

        Example:
            >>> person.has_residence()
            True
        """
        return self.residence is not None

    def get_residence_property(self, property_name: str, default=None):
        """
        Get a property from the person's residence venue.

        Args:
            property_name: Name of the property to retrieve
            default: Default value if property not found or no residence

        Returns:
            Property value or default

        Examples:
            >>> person.get_residence_property('original_pattern')
            '0 0 2 0'

            >>> person.get_residence_property('capacity', default=0)
            4

            >>> person.get_residence_property('nonexistent', default='N/A')
            'N/A'
        """
        if self.residence:
            return self.residence.properties.get(property_name, default)
        return default

    def __repr__(self) -> str:
        """String representation of the Person."""
        geo_unit_name = self.geographical_unit.name if self.geographical_unit else "None"
        return (f"Person(id={self.id}, age={self.age}, sex={self.sex}, "
                f"geographical_unit={geo_unit_name}, activities={self.activities})")

    def __eq__(self, other) -> bool:
        """ Method to determine if two Person objects are basically equal.

        Doesn't check they have the same IDs as if ID assignment is different with all
        other attributes being equal, I'd still like this to return True / Gavin 21/Jan/26.
        """
        if float(self.age) != float(other.age):
            return False
        if self.geographical_unit != other.geographical_unit:
            return False
        for attr in ['sex',
                     'activities',
                     'properties',
                     'activity_map',
                     ]:
            if getattr(self, attr) != getattr(other, attr):
                return False
        return True

    def __hash__(self) -> int:
        """Hash based on unique ID for use in sets/dicts."""
        return hash(self.id)


