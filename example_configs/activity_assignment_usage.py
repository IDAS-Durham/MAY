"""
Example: Using the Simplified Activity Assignment Framework

Demonstrates how to use independent rules and choice rules.
"""

import logging
from may.population import Person
from may.population.activity_assigner import (
    ActivityAssigner,
    create_simple_assigner,
    create_modern_assigner,
    create_medieval_assigner,
)
from may.geography import GeographicalUnit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_unit():
    """Helper to create a test geographical unit."""
    return GeographicalUnit(id=0, name='TestArea', level='SGU')


def example_1_simple_assigner():
    """Example 1: Using the simple default assigner."""
    logger.info("\n" + "="*70)
    logger.info("Example 1: Simple Activity Assigner")
    logger.info("="*70)

    assigner = create_simple_assigner()
    unit = create_test_unit()

    Person.reset_counter()
    people = [
        Person(age=7, sex='male', geographical_unit=unit),
        Person(age=25, sex='female', geographical_unit=unit),
        Person(age=35, sex='male', geographical_unit=unit),
        Person(age=70, sex='female', geographical_unit=unit),
    ]

    for person in people:
        activities = assigner.assign_activities(person)
        logger.info(f"Person {person.id} (age {person.age}): {activities}")


def example_2_choice_rules():
    """Example 2: Demonstrating choice rules (mutually exclusive)."""
    logger.info("\n" + "="*70)
    logger.info("Example 2: Choice Rules - Employment Status")
    logger.info("="*70)

    assigner = ActivityAssigner()

    # Everyone gets home
    assigner.add_independent_rule('home', lambda p: True, 1.0)

    # Working age people get ONE employment status
    assigner.add_choice_rule(
        choice_name='employment_status',
        condition=lambda p: 25 <= p.age <= 64,
        options=[
            ('employed', 0.75),      # 75% chance
            ('unemployed', 0.15),    # 15% chance
            ('not_in_labor_force', 0.10)  # 10% chance
        ]
    )

    unit = create_test_unit()
    Person.reset_counter()

    # Create many people to see distribution
    logger.info("Creating 20 working-age people to see employment distribution:")
    employment_counts = {'employed': 0, 'unemployed': 0, 'not_in_labor_force': 0}

    for i in range(20):
        person = Person(age=35, sex='male' if i % 2 == 0 else 'female',
                       geographical_unit=unit)
        activities = assigner.assign_activities(person)

        # Count employment status
        for activity in activities:
            if activity in employment_counts:
                employment_counts[activity] += 1

        logger.info(f"  Person {person.id}: {activities}")

    logger.info(f"\nDistribution: {employment_counts}")


def example_3_multiple_choices():
    """Example 3: Multiple choice rules for different aspects."""
    logger.info("\n" + "="*70)
    logger.info("Example 3: Multiple Choice Rules")
    logger.info("="*70)

    assigner = ActivityAssigner()

    # Independent: Home for all
    assigner.add_independent_rule('home', lambda p: True, 1.0)

    # Choice 1: Employment status
    assigner.add_choice_rule(
        choice_name='employment',
        condition=lambda p: 25 <= p.age <= 64,
        options=[
            ('employed_fulltime', 0.60),
            ('employed_parttime', 0.20),
            ('unemployed', 0.20)
        ]
    )

    # Choice 2: Housing type (independent of employment)
    assigner.add_choice_rule(
        choice_name='housing',
        condition=lambda p: p.age >= 18,
        options=[
            ('own_home', 0.65),
            ('rent_home', 0.30),
            ('shared_housing', 0.05)
        ]
    )

    unit = create_test_unit()
    Person.reset_counter()

    people = [
        Person(age=30, sex='male', geographical_unit=unit),
        Person(age=35, sex='female', geographical_unit=unit),
        Person(age=45, sex='male', geographical_unit=unit),
    ]

    logger.info("Each person gets ONE from each choice group:")
    for person in people:
        activities = assigner.assign_activities(person)
        logger.info(f"Person {person.id}: {activities}")


def example_4_mixed_rules():
    """Example 4: Mixing independent and choice rules."""
    logger.info("\n" + "="*70)
    logger.info("Example 4: Mixed Independent and Choice Rules")
    logger.info("="*70)

    assigner = ActivityAssigner()

    # Independent rules (can get multiple)
    assigner.add_independent_rule('home', lambda p: True, 1.0)
    assigner.add_independent_rule('leisure', lambda p: p.age >= 18, 0.70)
    assigner.add_independent_rule('shopping', lambda p: p.age >= 18, 0.50)

    # Choice rule (get exactly one)
    assigner.add_choice_rule(
        choice_name='daytime_activity',
        condition=lambda p: 25 <= p.age <= 64,
        options=[
            ('work', 0.80),
            ('homemaker', 0.15),
            ('student', 0.05)
        ]
    )

    unit = create_test_unit()
    Person.reset_counter()

    person = Person(age=35, sex='female', geographical_unit=unit)
    activities = assigner.assign_activities(person)

    logger.info(f"Person gets multiple independent activities AND one choice:")
    logger.info(f"  Activities: {activities}")
    logger.info(f"  - 'home': always assigned (independent, prob=1.0)")
    logger.info(f"  - 'leisure': maybe assigned (independent, prob=0.70)")
    logger.info(f"  - 'shopping': maybe assigned (independent, prob=0.50)")
    logger.info(f"  - ONE OF work/homemaker/student: from choice rule")


def example_5_yaml_loading():
    """Example 5: Loading from YAML configuration."""
    logger.info("\n" + "="*70)
    logger.info("Example 5: Loading from YAML")
    logger.info("="*70)

    try:
        assigner = ActivityAssigner.from_yaml('configs/activities_simple_example.yaml')

        logger.info(f"Loaded configuration successfully")
        logger.info(f"  Independent rules: {len(assigner.independent_rules)}")
        logger.info(f"  Choice rules: {len(assigner.choice_rules)}")

        unit = create_test_unit()
        Person.reset_counter()

        people = [
            Person(age=2, sex='male', geographical_unit=unit),
            Person(age=10, sex='female', geographical_unit=unit),
            Person(age=30, sex='male', geographical_unit=unit),
        ]

        for person in people:
            activities = assigner.assign_activities(person)
            logger.info(f"Person {person.id} (age {person.age}): {activities}")

    except FileNotFoundError as e:
        logger.warning(f"Config file not found: {e}")


def example_6_medieval_vs_modern():
    """Example 6: Comparing medieval and modern activity patterns."""
    logger.info("\n" + "="*70)
    logger.info("Example 6: Medieval vs Modern Activity Patterns")
    logger.info("="*70)

    modern_assigner = create_modern_assigner()
    medieval_assigner = create_medieval_assigner()

    unit = create_test_unit()

    # Test same person profiles in both worlds
    test_people = [
        (12, 'male'),
        (25, 'female'),
        (40, 'male'),
    ]

    for age, sex in test_people:
        logger.info(f"\nPerson: age {age}, sex {sex}")

        Person.reset_counter()
        modern_person = Person(age=age, sex=sex, geographical_unit=unit)
        modern_activities = modern_assigner.assign_activities(modern_person)

        Person.reset_counter()
        medieval_person = Person(age=age, sex=sex, geographical_unit=unit)
        medieval_activities = medieval_assigner.assign_activities(medieval_person)

        logger.info(f"  Modern:   {modern_activities}")
        logger.info(f"  Medieval: {medieval_activities}")


def example_7_custom_with_properties():
    """Example 7: Using person properties in conditions."""
    logger.info("\n" + "="*70)
    logger.info("Example 7: Custom Rules with Person Properties")
    logger.info("="*70)

    assigner = ActivityAssigner()

    # Basic activities
    assigner.add_independent_rule('home', lambda p: True, 1.0)

    # Occupation-based choice (using properties)
    assigner.add_choice_rule(
        choice_name='work_type',
        condition=lambda p: (
            25 <= p.age <= 64 and
            p.properties.get('employment_status') == 'employed'
        ),
        options=[
            ('office_work', 0.40),
            ('manual_work', 0.35),
            ('service_work', 0.25)
        ]
    )

    unit = create_test_unit()
    Person.reset_counter()

    # Create people with different employment statuses
    people = [
        Person(age=30, sex='male', geographical_unit=unit,
               properties={'employment_status': 'employed'}),
        Person(age=35, sex='female', geographical_unit=unit,
               properties={'employment_status': 'employed'}),
        Person(age=28, sex='male', geographical_unit=unit,
               properties={'employment_status': 'unemployed'}),
    ]

    for person in people:
        activities = assigner.assign_activities(person)
        status = person.properties.get('employment_status', 'unknown')
        logger.info(f"Person {person.id} ({status}): {activities}")


if __name__ == '__main__':
    example_1_simple_assigner()
    example_2_choice_rules()
    example_3_multiple_choices()
    example_4_mixed_rules()
    example_5_yaml_loading()
    example_6_medieval_vs_modern()
    example_7_custom_with_properties()

    logger.info("\n" + "="*70)
    logger.info("All examples completed!")
    logger.info("="*70)
