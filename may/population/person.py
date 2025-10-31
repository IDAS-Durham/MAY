"""
Person class for June Zero.

Represents an individual agent with age, sex, geographical unit, and activities.
"""

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
    """

    _id_counter = 0

    def __init__(self, age, sex, geographical_unit=None, activities=None, properties=None):
        """
        Initialize a Person.

        Args:
            age (int): Age in years
            sex (str): Sex category
            geographical_unit (GeographicalUnit, optional): SGU where person lives
            activities (list, optional): List of activity names
            properties (dict, optional): Additional attributes
        """
        self.id = Person._id_counter
        Person._id_counter += 1

        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit
        self.activities = activities if activities is not None else []
        self.properties = properties if properties is not None else {}

    @classmethod
    def reset_counter(cls):
        """Reset the ID counter (useful for testing)."""
        cls._id_counter = 0

    def add_activity(self, activity):
        """
        Add an activity to this person's activity list.

        Args:
            activity (str): Name of the activity to add
        """
        if activity not in self.activities:
            self.activities.append(activity)

    def remove_activity(self, activity):
        """
        Remove an activity from this person's activity list.

        Args:
            activity (str): Name of the activity to remove
        """
        if activity in self.activities:
            self.activities.remove(activity)

    def has_activity(self, activity):
        """
        Check if person has a specific activity.

        Args:
            activity (str): Name of the activity to check

        Returns:
            bool: True if person has this activity
        """
        return activity in self.activities

    def __repr__(self):
        """String representation of the Person."""
        geo_unit_name = self.geographical_unit.name if self.geographical_unit else "None"
        return (f"Person(id={self.id}, age={self.age}, sex={self.sex}, "
                f"geographical_unit={geo_unit_name}, activities={self.activities})")

    def __str__(self):
        """User-friendly string representation."""
        return f"Person {self.id} (age {self.age}, {self.sex})"
