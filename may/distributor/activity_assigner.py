"""
Activity assignment framework for Person objects.

This module provides a simple, modular system for assigning activities where:
1. Activities can be added independently based on conditions
2. Activities can be chosen probabilistically from mutually exclusive options

Example:
  create simple assigner:
    assigner = ActivityAssigner()

    # Everyone gets home
    assigner.add_independent_rule('home', lambda p: True, 1.0, "Universal home")

    # Children in education
    assigner.add_independent_rule('education', lambda p: 5 <= p.age <= 18, 1.0,
                                 "School age children")

    # Working age - employment choice
    assigner.add_choice_rule(
        choice_name='employment_status',
        condition=lambda p: 19 <= p.age <= 64,
        options=[
            ('employed', 0.80),
            ('not employed', 0.20)
        ],
        description="Employment status for working age"
    )

Example:
  create modern day assigner:
    assigner = ActivityAssigner()

    # HOME - everyone
    assigner.add_independent_rule('home', lambda p: True, 1.0)

    # CHILDCARE - young children
    assigner.add_independent_rule('childcare', lambda p: 2 <= p.age <= 4, 0.64, description="Childcare centre for a young child, e.g. nursery")

    # EDUCATION - school age
    assigner.add_independent_rule('school', lambda p: 5 <= p.age <= 18, 0.95)

    # HIGHER EDUCATION - young adults
    assigner.add_independent_rule('higher_education', lambda p: 18 <= p.age <= 24, 0.49)

    # EMPLOYMENT - working age (mutually exclusive choice)
    assigner.add_choice_rule(
        choice_name='main activity',
        condition=lambda p: 19 <= p.age <= 64,
        options=[
            ('employed', 0.75), # employed
            ('unemployed', 0.05), # actively seeking employment
            ('inactivity', 0.20) # includes students            
        ]
    )

    # LEISURE - adults
    assigner.add_independent_rule('leisure', lambda p: p.age >= 18, 1.0)


"""

from dataclasses import dataclass, field
from typing import Callable, List, Dict, Optional, Any
import time
import random
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class ActivityRule:
    """
    Rule for assigning an activity independently.

    The activity is added if condition is met and probability check passes.
    Multiple rules can apply to the same person.
    """
    activity_name: str
    condition: Callable[['Person'], bool]
    probability: float = 1.0
    description: str = ""

    def should_assign(self, person: 'Person') -> bool:
        """Check if this activity should be assigned to the person."""
        return self.condition(person) and random.random() < self.probability


@dataclass
class ActivityOption:
    """A single option in an ActivityChoice."""
    activity_name: str
    weight: float  # Relative probability weight


@dataclass
class ActivityChoice:
    """
    Choose ONE activity from multiple options based on weighted probabilities.

    This is for mutually exclusive activities, e.g.:
    - Employment status: employed (60%), unemployed (30%), student (10%)
    - Education level: primary (40%), secondary (35%), higher_ed (25%)

    Only ONE option will be selected per person (or none if condition fails).
    """
    choice_name: str
    condition: Callable[['Person'], bool]
    options: List[ActivityOption]
    description: str = ""

    def select_activity(self, person: 'Person') -> Optional[str]:
        """
        Select ONE activity from options based on weighted probabilities.

        Returns:
            Selected activity name, or None if condition doesn't apply
        """
        if not self.condition(person):
            return None

        if not self.options:
            return None

        # Calculate total weight
        total_weight = sum(opt.weight for opt in self.options)
        if total_weight <= 0:
            return None

        # Select based on weighted random choice
        rand_val = random.random() * total_weight
        cumulative = 0.0

        for option in self.options:
            cumulative += option.weight
            if rand_val <= cumulative:
                return option.activity_name

        # Fallback (should rarely reach here due to floating point)
        return self.options[-1].activity_name


class ActivityAssigner:
    """
    Simple activity assigner with two types of rules:
    1. Independent rules: Activities added independently based on conditions
    2. Choice rules: Pick ONE activity from multiple options
    """

    def __init__(self):
        """Initialize empty assigner."""
        self.independent_rules: List[ActivityRule] = []
        self.choice_rules: List[ActivityChoice] = []
        self.geo_classifications: Dict[str, List[str]] = {}

    def add_independent_rule(self, activity_name: str, condition: Callable,
                            probability: float = 1.0, description: str = ""):
        """
        Add a rule that independently assigns an activity.

        Args:
            activity_name: Name of activity to assign
            condition: Function taking Person, returning bool
            probability: Probability of assignment when condition is True
            description: Optional description of this rule
        """
        rule = ActivityRule(
            activity_name=activity_name,
            condition=condition,
            probability=probability,
            description=description
        )
        self.independent_rules.append(rule)

    def add_choice_rule(self, choice_name: str, condition: Callable,
                       options: List[tuple], description: str = ""):
        """
        Add a rule that chooses ONE activity from multiple options.

        Args:
            choice_name: Name for this choice group
            condition: Function taking Person, returning bool
            options: List of (activity_name, weight) tuples
            description: Optional description

        Example:
            assigner.add_choice_rule(
                choice_name='employment_status',
                condition=lambda p: 18 <= p.age <= 64,
                options=[
                    ('employed', 0.75),
                    ('unemployed', 0.20),
                    ('student', 0.05)
                ]
            )
        """
        activity_options = [
            ActivityOption(activity_name=name, weight=weight)
            for name, weight in options
        ]

        choice = ActivityChoice(
            choice_name=choice_name,
            condition=condition,
            options=activity_options,
            description=description
        )
        self.choice_rules.append(choice)

    def assign_activities(self, person: 'Person') -> set[str]:
        """
        Assign activities to a person.

        Process:
        1. Apply all independent rules (can get multiple activities)
        2. Apply all choice rules (each picks at most one activity)

        Args:
            person: Person to assign activities to

        Returns:
            List of assigned activity names
        """
        activities = set()

        # Apply independent rules
        for rule in self.independent_rules:
            if rule.should_assign(person):
                activities.add(rule.activity_name)

        # Apply choice rules (each picks at most one)
        for choice in self.choice_rules:
            selected = choice.select_activity(person)
            if selected:
                activities.add(selected)

        return activities

    def assign_activities_to_population(self, people: list["Person"]):
        """
        Assign activities to all people in the population using the activity assigner.

        This is called AFTER population.generate_population() to assign activities
        based on person attributes (age, sex, geographical_unit, etc.)

        Args:
            people (list[Person]): List of the people for whom to assign activities.
            activity_assigner (ActivityAssigner): Configured activity assigner.
        """
        start_time = time.perf_counter()

        total_people = len(people)

        # Track statistics
        activity_counts = {'Total people' : total_people}

        # Assign activities to each person
        for i, person in enumerate(people):
            # Get activities for this person
            activities = self.assign_activities(person)
            
            # Add activities to person
            person.add_activities(activities)

            # Log activity counts
            for activity in activities:
                activity_counts[activity] = activity_counts.get(activity, 0) + 1

            # Log progress for large populations
            if total_people > 10000 and (i + 1) % 50000 == 0:
                logger.info(f"  Processed {i + 1:,} / {total_people:,} people...")

        elapsed = time.perf_counter() - start_time

        return activity_counts

    def classify_geo_unit(self, geo_unit: 'GeographicalUnit') -> str:
        """Classify a geographical unit (urban/rural/etc)."""
        # Check properties
        if hasattr(geo_unit, 'properties') and geo_unit.properties:
            if 'urban_rural_classification' in geo_unit.properties:
                return geo_unit.properties['urban_rural_classification']

        # Check lookup table
        for classification, codes in self.geo_classifications.items():
            if geo_unit.name in codes:
                return classification

        # Check population density
        if hasattr(geo_unit, 'population_density'):
            density = geo_unit.population_density
            if density > 4000:
                return 'urban'
            elif density > 1000:
                return 'suburban'
            else:
                return 'rural'

        return 'unknown'

    @classmethod
    def from_yaml(cls, yaml_file: str) -> 'ActivityAssigner':
        """
        Load activity rules from YAML configuration.

        Expected format:
        ```yaml
        independent_rules:
          - activity: home
            description: Everyone needs home
            condition:
              age_min: 0
            probability: 1.0

        choice_rules:
          - name: employment_status
            description: Employment for adults
            condition:
              age: [18, 64]
            options:
              - activity: employed
                weight: 0.75
              - activity: unemployed
                weight: 0.25
        ```
        """
        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)

        assigner = cls()

        # Load geo classifications
        if 'geo_classifications' in config:
            assigner.geo_classifications = config['geo_classifications']

        # Load independent rules
        if 'independent_rules' in config:
            for rule_config in config['independent_rules']:
                condition = cls._build_condition(rule_config.get('condition', {}), assigner)
                assigner.add_independent_rule(
                    activity_name=rule_config['activity'],
                    condition=condition,
                    probability=rule_config.get('probability', 1.0),
                    description=rule_config.get('description', '')
                )

        # Load choice rules
        if 'choice_rules' in config:
            for choice_config in config['choice_rules']:
                condition = cls._build_condition(choice_config.get('condition', {}), assigner)
                options = [
                    (opt['activity'], opt['weight'])
                    for opt in choice_config['options']
                ]
                assigner.add_choice_rule(
                    choice_name=choice_config['name'],
                    condition=condition,
                    options=options,
                    description=choice_config.get('description', '')
                )

        logger.info(f"Loaded {len(assigner.independent_rules)} independent rules "
                   f"and {len(assigner.choice_rules)} choice rules from {yaml_file}")
        return assigner

    @staticmethod
    def _build_condition(cond_config: Dict, assigner: 'ActivityAssigner') -> Callable:
        """Build a condition function from configuration."""
        def condition_func(person: 'Person') -> bool:
            # Age range
            if 'age' in cond_config:
                age_range = cond_config['age']
                if isinstance(age_range, list):
                    if not (age_range[0] <= person.age <= age_range[1]):
                        return False
                elif person.age != age_range:
                    return False

            # Age min/max
            if 'age_min' in cond_config and person.age < cond_config['age_min']:
                return False
            if 'age_max' in cond_config and person.age > cond_config['age_max']:
                return False

            # Sex
            if 'sex' in cond_config and person.sex != cond_config['sex']:
                return False

            # Geo unit type
            if 'geo_unit_type' in cond_config:
                if person.geographical_unit:
                    actual = assigner.classify_geo_unit(person.geographical_unit)
                    if actual != cond_config['geo_unit_type']:
                        return False
                else:
                    return False

            # Properties
            if 'properties' in cond_config:
                if not hasattr(person, 'properties'):
                    return False
                for key, value in cond_config['properties'].items():
                    if person.properties.get(key) != value:
                        return False

            return True

        return condition_func


# =============================================================================
# Example Factory Functions
# =============================================================================

def create_simple_assigner() -> ActivityAssigner:
    """Create a simple default activity assigner."""
    assigner = ActivityAssigner()

    # Everyone gets home
    assigner.add_independent_rule('home', lambda p: True, 1.0, "Universal home")

    # Children in education
    assigner.add_independent_rule('education', lambda p: 5 <= p.age <= 18, 1.0,
                                 "School age children")

    # Working age - employment choice
    assigner.add_choice_rule(
        choice_name='employment_status',
        condition=lambda p: 19 <= p.age <= 64,
        options=[
            ('employed', 0.80),
            ('not employed', 0.20)
        ],
        description="Employment status for working age"
    )

    return assigner


def create_modern_assigner() -> ActivityAssigner:
    """Create activity assigner for modern world.

    Example creation of an activity assigner, tailored to making the modern world.

    """
    assigner = ActivityAssigner()

    # HOME - everyone
    assigner.add_independent_rule('home', lambda p: True, 1.0)

    # CHILDCARE - young children
    assigner.add_independent_rule('childcare', lambda p: 2 <= p.age <= 4, 0.64, description="Childcare centre for a young child, e.g. nursery")

    # EDUCATION - school age
    assigner.add_independent_rule('school', lambda p: 5 <= p.age <= 18, 0.95)

    # HIGHER EDUCATION - young adults
    assigner.add_independent_rule('higher_education', lambda p: 18 <= p.age <= 24, 0.49)

    # EMPLOYMENT - working age (mutually exclusive choice)
    assigner.add_choice_rule(
        choice_name='main activity',
        condition=lambda p: 19 <= p.age <= 64,
        options=[
            ('employed', 0.75), # employed
            ('unemployed', 0.05), # actively seeking employment
            ('inactivity', 0.20) # includes students            
        ]
    )

    # LEISURE - adults
    assigner.add_independent_rule('leisure', lambda p: p.age >= 18, 1.0)

    return assigner

