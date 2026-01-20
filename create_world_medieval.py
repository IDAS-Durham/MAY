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
from world_specific_code.Medieval_England.household_distributors import HouseholdDistributor, HouseholdSubsetDistributor, HouseholdManager

from may.stats import StatMakerVenues, StatMaker, StatMakerPop, print_world_examples





logger = logging.getLogger("create_world")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Used for timing parts of the code. 
def timer_dec(base_fn):
    def enhanced_fn(*args, **kwargs):
        start_time = time.perf_counter()
        result = base_fn(*args, **kwargs)
        end_time = time.perf_counter()
        logger.info(f'                       ... {end_time - start_time:.2g} s')
        return result
    return enhanced_fn


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

def main():
    starttime = time.perf_counter()
    """
    Main entry point for world creation.
    """
    logger.info("=" * 60)
    logger.info("June Zero - World Creation")
    logger.info("=" * 60)

    # Load config file
    with open("world_specific_code/Medieval_England/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    logger.info("Setting up geography... ")
    # Setup geography from config and command-line arguments
    geo, filters = setup_geography(config=config)
    # Load the geography data
    geo.load_from_csv()

    logger.info("Setting up Geography took {:.2g}s".format(time.perf_counter()-starttime))
    laptime = time.perf_counter()
    
    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venues = VenueManager(geography=geo, data_dir=config.get("venues",{}).get('data_dir','data/venues'))
    # for venue_type, phile in [('care_home', 'msoa_care_homes.csv'),
    #                           ('hospital', 'hospitals.csv'),
    #                           ('company', 'companies.csv'),
    #                           ('prison', 'prisons.csv'),
    #                           ('university', 'universities.csv'),
    #                           ('school', 'schools.csv'),
    #                           ('student_dorm', 'msoa_student_dorms.csv')]:
    #     venues.load_venue_type_from_csv(venue_type, filename=phile)

    logger.info("                      ... {:.2g}s".format(time.perf_counter()-laptime))
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
    male_file = pop_config.get("demographics_male_file", "demography_male.csv")
    female_file = pop_config.get("demographics_female_file", "demography_female.csv")
    population.load_demographics_from_csv(male_file, female_file)

    logger.info("Loading demographic data took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # Generate population
    population.generate_population(activities=['home'])

    logger.info("Creating population took {:.2g}s".format(time.perf_counter()-laptime))
    laptime = time.perf_counter()
    
    # # Create Households
    logger.info("Loading households...")
    household_manager = HouseholdManager(geography=geo, data_dir=config.get("households",{}).get("data_dir",'data/venues'), filter_by_geography=True)
    household_manager.load_venue_type_from_csv('household', 'household_composition_1348.csv')

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
            household_distributor.num_passes = 5
            household_distributor.assign_people_venues_multi_pass('home', 'household')
            still_unallocated_people = household_distributor.unallocated_people
        
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
            household_distributor.num_passes = 10
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

    # Exporting world object
    logger.info("Exporting world...")
#    joblib.dump(world, 'my_medieval_world.joblib', compress=3)
#    logger.info("Saving world to took {:.2g}s".format(time.perf_counter()-laptime))

    laptime = time.perf_counter()

    # Show examples of what was created
    print_world_examples(world)

    logger.info("Script completed in {:.2g}s".format(time.perf_counter()-starttime))

    return world


if __name__ == "__main__":
    world = main()
