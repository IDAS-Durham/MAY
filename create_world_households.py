import os
import time
import logging
import random
import sys
import numpy as np
import numba as nb
import yaml
import joblib
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World
from world_specific_code.Modern_Day_UK.household_distributors import HouseholdDistributor, HouseholdSubsetDistributor, HouseholdManager, assign_home_activity
from world_specific_code.Modern_Day_UK.care_home_distributor import CareHomeDistributor, CareHomeSubsetDistributor
from world_specific_code.Modern_Day_UK.student_dorms import StudentDormDistributor, StudentDormSubsetDistributor
from world_specific_code.Modern_Day_UK.prisons import PrisonDistributor, PrisonSubsetDistributor

# NEW: Import activity assigner
from may.distributor.activity_assigner import (
    ActivityAssigner,
    create_simple_assigner,
    create_modern_assigner
)

from may.stats import StatMakerVenues, StatMaker, StatMakerPop, print_world_examples


logger = logging.getLogger("create_world")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Suppress numexpr logging
logging.getLogger('numexpr').setLevel(logging.WARNING)


def create_custom_activity_assigner():
    """
    Create a custom activity assigner tailored to your specific needs.

    This example shows how to create a modern UK activity assigner with
    custom probabilities and rules.

    Returns:
        ActivityAssigner: Configured activity assigner
    """
    assigner = ActivityAssigner()

    # INDEPENDENT RULES - Activities that can coexist

    # Everyone needs a home
    assigner.add_independent_rule(
        'home',
        lambda p: True,
        probability=1.0,
        description="Universal home activity"
    )

    # Childcare for young children
    assigner.add_independent_rule(
        'childcare',
        lambda p: 2 <= p.age <= 4,
        probability=0.64,
        description="Childcare/nursery for young children"
    )

    # School for children
    assigner.add_independent_rule(
        'school',
        lambda p: 5 <= p.age <= 18,
        probability=0.95,
        description="School education"
    )

    # Higher education for young adults
    assigner.add_independent_rule(
        'higher_education',
        lambda p: 18 <= p.age <= 25,
        probability=0.49,
        description="University/college education"
    )

    # Leisure activities for adults
    assigner.add_independent_rule(
        'leisure',
        lambda p: 18 <= p.age,
        probability=1.0,
        description="Leisure and social activities"
    )

    # CHOICE RULES - Mutually exclusive activities

    # Employment status for working-age adults (only ONE will be assigned)
    assigner.add_choice_rule(
        choice_name='employment_status',
        condition=lambda p: 19 <= p.age <= 64,
        options=[
            ('employed', 0.75),      # 75% employed
            ('unemployed', 0.05),    # 5% unemployed (actively seeking)
            ('inactive', 0.20)       # 20% economically inactive
        ],
        description="Employment status for working-age adults"
    )
 
    return assigner



def main():
    starttime = time.perf_counter()
    """
    Main entry point for world creation with activity assignment.
    """
    logger.info("=" * 60)
    logger.info("June Zero - World Creation with Activity Assigner")
    logger.info("=" * 60)

    # Load config file
    with open("world_specific_code/Modern_Day_UK/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Setup geography from config and command-line arguments
    geo, filters = setup_geography(config=config)

    # Load the geography data
    geo.load_from_csv()

    logger.info("Setting up Geography took {:.2g}s".format(time.perf_counter()-starttime))
    laptime = time.perf_counter()

    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venues = VenueManager(geography=geo, data_dir='world_specific_code/Modern_Day_UK/data/venues')
    for venue_type, phile in [('care_home', 'msoa_care_homes.csv'),
                              ('hospital', 'hospitals.csv'),
                              ('company', 'companies.csv'),
                              ('prison', 'prisons.csv'),
                              ('university', 'universities.csv'),
                              ('school', 'schools.csv'),
                              ('student_dorm', 'msoa_student_dorms.csv')]:
        venues.load_venue_type_from_csv(venue_type, filename=phile)
    logger.info("Loading venues took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir="world_specific_code/Modern_Day_UK/data/population"
    )

    # Load demographic data
    male_file = pop_config.get("demographics_male_file", "demographics_male.csv")
    female_file = pop_config.get("demographics_female_file", "demographics_female.csv")
    population.load_demographics_from_csv(male_file, female_file)

    # Generate population WITHOUT activities (we'll assign them next)
    logger.info("")
    logger.info("Generating population...")
    population.generate_population()  

    logger.info("Creating population took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    logger.info("")
    logger.info("Creating activity assigner...")
    activity_assigner = create_custom_activity_assigner()

    # Apply activity assigner to population
    activity_stats = activity_assigner.assign_activities_to_population(population.get_all_people())
    # Print activity stats
    logger.info("Activity stats:")        
    for key, value in activity_stats.items():
        logger.info(f"    {key}    {value:,}")

    logger.info("Activity assignment took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    # ==========================================================================

    # Create Households
    logger.info("Loading households...")
    household_manager = HouseholdManager(geography=geo, data_dir=config.get("households",{}).get("data_dir",'data/households'), filter_by_geography=True)
    household_manager.load_venue_type_from_csv('household', 'households.csv')

    # Extend the venues object to add the households on. 
    venues.extend(household_manager)
    
    logger.info("Loading and creating household data took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    # Assign home activity to venues
    logger.info("Distributing pop to households")
    assign_home_activity(geo, venues)
    logger.info("Distributing pop to households took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    
    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues)
    logger.info(world)

    logger.info("Creating world took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    # Save world
    output_file = 'my_world_with_activities.joblib'
    joblib.dump(world, output_file, compress=0)
    logger.info(f"Saved world to {output_file}")
    logger.info("Saving world took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Show examples of what was created
    logger.info("")
    logger.info("Sample people with activities:")
    for i, person in enumerate(random.sample(population.get_all_people(),10)):
        logger.info(f"  Person {i+1}: Age {person.age}, Sex {person.sex}, Activities: {person.activities}")

    logger.info("")
    logger.info("Script completed in {:.2g}s".format(time.perf_counter()-starttime))

    return world


if __name__ == "__main__":
    world = main()
