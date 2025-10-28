import os
import logging
import random
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World
from world_specific_code.household_distributors import HouseholdDistributor, HouseholdSubsetDistributor, HouseholdManager
from world_specific_code.care_home_distributor import CareHomeDistributor, CareHomeSubsetDistributor
from world_specific_code.student_dorms import StudentDormDistributor, StudentDormSubsetDistributor
from world_specific_code.prisons import PrisonDistributor, PrisonSubsetDistributor

from may.stats import StatMakerVenues, StatMaker, StatMakerPop

import time



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

# if os.environ.get('PYTHONHASHSEED') is None:
#     os.environ['PYTHONHASHSEED'] = '0'
#     os.execv(sys.executable, [sys.executable] + sys.argv)

# def set_random_seed(seed=999):
#     """
#     Sets global seeds for testing in numpy, random, and numbaised numpy.
#     """

#     @nb.njit(cache=True)
#     def set_seed_numba(seed):
#         random.seed(seed)
#         return np.random.seed(seed)

#     np.random.seed(seed)
#     set_seed_numba(seed)
#     random.seed(seed)
#     return

#set_random_seed(0)


def print_world_examples(world):
    """
    Print examples of the created world to help users understand the data.

    Args:
        world: World object containing geography, population, and venues
    """
    geo = world.geography
    venues = world.venues
    population = world.population
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXAMPLES")
    logger.info("=" * 60)

    # Example 1: Show geographical hierarchy
    logger.info("")
    logger.info("1. Geographical Hierarchy:")
    all_units = geo.get_all_units_list()
    if all_units:
        # Get an example SGU
        sgu_units = [u for u in all_units if u.level == "SGU"]
        if sgu_units:
            example_sgu = sgu_units[0]
            logger.info(f"   SGU Example: {example_sgu}")
            logger.info(f"   - Coordinates: {example_sgu.coordinates}")
            if example_sgu.parent:
                logger.info(f"   - Parent MGU: {example_sgu.parent.name}")
                if example_sgu.parent.parent:
                    logger.info(f"   - Parent LGU: {example_sgu.parent.parent.name}")

        # Get an example MGU with venues
        mgu_with_venues = [u for u in all_units if u.level == "MGU" and len(u.venues) > 0]
        if mgu_with_venues:
            example_mgu = mgu_with_venues[0]
            logger.info("")
            logger.info(f"   MGU Example: {example_mgu}")
            logger.info(f"   - Has {len(example_mgu.children)} SGU children")
            logger.info(f"   - Has {len(example_mgu.venues)} venues")

    # Example 2: Show venues
    logger.info("")
    logger.info("2. Venue Examples:")
    venue_types = venues.get_venue_types()
    for vtype in sorted(venue_types):  # Show all types
        venues_of_type = venues.get_venues_by_type(vtype)
        if venues_of_type:
            example_venue = random.choice(venues_of_type)
            logger.info(f"   {vtype.capitalize()}: {example_venue.name}")
            logger.info(f"   - Located in: {example_venue.geographical_unit.name} ({example_venue.geographical_unit.level})")
            if example_venue.coordinates:
                logger.info(f"   - Coordinates: {example_venue.coordinates}")
            if example_venue.properties:
                # Show first 2 properties
                props = list(example_venue.properties.items())
                for key, value in props:
                    logger.info(f"   - {key}: {value}")
            # Show membership
            if example_venue.subsets:
                for key, value in example_venue.subsets.items():
                    logger.info(f"   - Number of assigned {key} =  {value.num_members}")

    # Example 3: Show how to query
    logger.info("")
    logger.info("3. Population Examples:")
    stats = population.get_statistics()
    if stats:
        logger.info(f"   Total population: {stats['total_population']:,}")
        logger.info(f"   Mean age: {stats['mean_age']:.1f} years")
        logger.info(f"   Median age: {stats['median_age']:.1f} years")
        logger.info(f"   Sex distribution:")
        for sex, count in stats['sex_distribution'].items():
            pct = 100 * count / stats['total_population']
            logger.info(f"     - {sex}: {count:,} ({pct:.1f}%)")
        logger.info(f"   Activity distribution:")
        for activity, count in sorted(stats['activity_counts'].items()):
            logger.info(f"     - {activity}: {count:,}")

        # Show example people
        logger.info("")
        logger.info("   Example people:")
        for person in random.choices(population.get_all_people(), k=5):
            logger.info(f"   {person}")
            logger.info(f"    - Activities: {', '.join(person.activities)}")
            logger.info(f"    - Activity map:")
            for activity, place in person.activity_map.items():
                logger.info(f"        ~ {activity} : {place} ")
            logger.info(f"    - Properties:")                
            for prop, propy in person.properties.items():
                logger.info(f"        ~ {prop} : {propy} ")
            

    logger.info("")
    logger.info("4. Household Examples:")
    venue_stats = StatMakerVenues(venues)
    venue_stats.print_lots_of_stats('household')
    venue_stats.print_examples('household')
    venue_stats.print_extremes('household')

    number_of_empty_houses = 0
    for v in venues.get_venues_by_type('household'):
        if v.num_members == 0:
            number_of_empty_houses += 1
    logger.info(f"Number of empty houses = {number_of_empty_houses} out of {len(venues.get_venues_by_type('household'))}")

    # if world.households and world.households.households:
    #     logger.info(f"   Total households: {len(world.households.households)}")
    #     logger.info(f"   Allocation rate: {len(world.households.allocated_people) / max(sum(len(p) for p in world.households.person_pool_by_area.values()), 1) * 100:.1f}%")
    #     logger.info("")
    #     logger.info("   Example households:")
    #     for household in random.choices(world.households.households, k=5):
    #         composition = household.get_composition()
    #         logger.info(f"   Household {household.id} in {household.geographical_unit.name}")
    #         logger.info(f"     - Size: {household.size()} people")
    #         logger.info(f"     - Composition: {composition}")
    #         if household.properties.get('original_pattern'):
    #             logger.info(f"     - Pattern: {household.properties['original_pattern']}")

    logger.info("")
    logger.info("5. Query Examples:")
    for key in venues.get_venue_types():
        logger.info("")
        logger.info("   # Get all {}s".format(key))
        all_venues = venues.get_venues_by_type(key)
        logger.info(f"   venues.get_venues_by_type({key}) -> {len(all_venues)} {key}s")

    logger.info("")
    logger.info("   # Get venues in a specific area")
    mgu_with_venues = [u for u in all_units if u.level == "MGU" and len(u.venues) > 0]
    if mgu_with_venues:
        unit_venues = mgu_with_venues[0].venues
        logger.info(f"   geo.get_unit('{mgu_with_venues[0].name}').venues -> {len(unit_venues)} venues")
        if unit_venues:
            logger.info(f"      e.g., {unit_venues[0].name} ({unit_venues[0].type})")

    logger.info("")
    logger.info("   # Get people by activity")
    workers = population.get_people_by_activity("work")
    logger.info(f"   population.get_people_by_activity('work') -> {len(workers)} people")

    logger.info("")
    logger.info("   # Get people by housed or not")
    n=0
    for p in population.get_people_by_activity("home"):
        if p.activity_map['home']:
            n+=1
    logger.info(f"   population.get_people_by_activity('home') -> {n} people out of {len(population)} with 'home' activity set")
    

    # logger.info("")
    # logger.info("   # Get person's household")
    # if world.households and world.households.allocated_people:
    #     example_person_id = next(iter(world.households.allocated_people))
    #     example_person = next((p for p in population.get_all_people() if p.id == example_person_id), None)
    #     if example_person and hasattr(example_person, 'residence') and example_person.residence:
    #         logger.info(f"   person.residence -> Household {example_person.residence.id}")
    #         logger.info(f"      Size: {example_person.residence.size()}, Composition: {example_person.residence.get_composition()}")

    logger.info("")
    logger.info("=" * 60)


def main():
    starttime = time.perf_counter()
    """
    Main entry point for world creation.
    """
    logger.info("=" * 60)
    logger.info("June Zero - World Creation")
    logger.info("=" * 60)

    # Load config file
    with open("may/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Setup geography from config and command-line arguments
    geo, filters = setup_geography()

    # Load the geography data
    geo.load_from_csv()

    logger.info("Setting up Geography took {:.2g}s".format(time.perf_counter()-starttime))
    laptime = time.perf_counter()
    
    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venues = VenueManager(geography=geo, data_dir="data/venues")
    for venue_type, phile in [('care_home', 'msoa_care_homes.csv'),
                              ('hospital', 'hospitals.csv'),
                              ('company', 'companies.csv'),
                              ('prison', 'prisons.csv'),
                              ('university', 'universities.csv'),
                              ('school', 'schools.csv'),
                              ('student_dorm', 'msoa_student_dorms.csv')]:
        venues.load_venue_type_from_csv(venue_type, filename=phile)
    #venues.load_from_csv()
    logger.info("Loading venues took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir=pop_config.get("data_dir", "data/population")
    )
    logger.info("Loading population took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Load demographic data
    male_file = pop_config.get("demographics_male_file", "demographics_male.csv")
    female_file = pop_config.get("demographics_female_file", "demographics_female.csv")
    population.load_demographics_from_csv(male_file, female_file)

    logger.info("Loading demographic data took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Generate population
    population.generate_population(activities=['home'])

    logger.info("Creating population took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Create Households
    logger.info("Loading households...")
    household_manager = HouseholdManager(geography=geo, data_dir='data/households', filter_by_geography=True)
    household_manager.load_venue_type_from_csv('household', 'households.csv')

    logger.info("Loading and creating household data took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    # Extend the venues object to add the households on. 
    venues.extend(household_manager)
    # Distribute people to households by smallest geographical unit.
    smallest_geo_unit_dict = geo.units_by_level[geo.levels[0]]
    
    logger.info("Allocating people to venues geo-unit by geo-unit...")
    i, printed, num_geo_units = 0, set(), len(smallest_geo_unit_dict)
    for geo_unit in smallest_geo_unit_dict.values():
        still_unallocated_people = geo_unit.people

        # Distribute people to Student Dorms
        potential_venues = geo_unit.get_venues_by_type('student_dorm')
        if potential_venues:
            logger.debug(f"Doing student dorm {potential_venues[0].name} in {potential_venues[0].geographical_unit.name}")
            student_dorm_distributor = StudentDormDistributor(
                'student_dorm',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues
            )
            student_dorm_distributor.assign_people_venues(
                'home',
                'student_dorm',
                people=still_unallocated_people
            )
            still_unallocated_people = student_dorm_distributor.unallocated_people

        # Distribute people to Care Homes
        potential_venues = geo_unit.get_venues_by_type('care_home')
        if potential_venues:
            logger.debug(f"Doing care home {potential_venues[0].name} in {potential_venues[0].geographical_unit.name}")            
            care_home_distributor = CareHomeDistributor(
                'care_home',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues
            )
            care_home_distributor.assign_people_venues(
                'home',
                'care_home',
                people=still_unallocated_people
            )
            still_unallocated_people = care_home_distributor.unallocated_people
        
        # Distribute people to Households with expansion
        potential_venues = geo_unit.get_venues_by_type('household')
        if potential_venues:
            household_distributor = HouseholdDistributor(
                'household',
                venues,
                still_unallocated_people,
                potential_venues=geo_unit.get_venues_by_type('household')
            )
            # Use multi-pass assignment (configured in HouseholdDistributor._multi_pass_config)
            # Don't do too many passes, as will go through them again after allocating to prisons. 
            household_distributor.num_passes = 2
            household_distributor.assign_people_venues_multi_pass('home', 'household')
            still_unallocated_people = household_distributor.unallocated_people
        
        # Fill prisons
        potential_venues = geo_unit.parent.get_venues_by_type('prison')
        if potential_venues:
            prison_distributor = PrisonDistributor(
                'prison',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues,
            )
            prison_distributor.assign_people_venues('home','prison')
            still_unallocated_people = prison_distributor.unallocated_people

        # Restart household distributor
        potential_venues = geo_unit.get_venues_by_type('household')
        if potential_venues and still_unallocated_people:
            household_distributor = HouseholdDistributor(
                'household',
                venues,
                still_unallocated_people,
                potential_venues=geo_unit.get_venues_by_type('household')
            )
            # Use multi-pass assignment (configured in HouseholdDistributor._multi_pass_config)
            # Don't do too many passes, as will go through them again after allocating to prisons. 
            household_distributor.num_passes = 3
            household_distributor.assign_people_venues_multi_pass('home',
                                                                  'household')
            still_unallocated_people = household_distributor.unallocated_people

            if household_distributor.allocation_rate < 99.999999:
                logger.info(f"--Low allocation rate of {household_distributor.allocation_rate:.1f}% in geo_unit {geo_unit.name}")
                logger.info(f"--Printing stats of unallocated people: ")
                my_statmaker = StatMakerPop(household_distributor.unallocated_people)
                my_statmaker.get_sex_breakdown()
                my_statmaker.get_age_group_breakdown()
                for p in household_distributor.unallocated_people:
                    logger.info(f"Person = {p}")
                # morestats = my_statmaker.get_age_stats()
                # for key, val in morestats.items():
                #     logger.info(f"    {key} : {val}")
                    
        i+=1
        percent=int(i/num_geo_units*100)
        milestone = (percent // 10) * 10
        if milestone not in printed and milestone % 10 == 0:
            logger.info(f"             ...{milestone}% complete")
            printed.add(milestone)              
            
    
            
    logger.info("Distributing pop to venues took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues)
    logger.info(world)

    logger.info("Creating world took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Show examples of what was created
    print_world_examples(world)

    logger.info("Script completed in {:.2g}s".format(time.perf_counter()-starttime))

    return world


if __name__ == "__main__":
    world = main()
