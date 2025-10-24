import cProfile
import os
import logging
import pstats
import random
import sys
import numpy as np
import numba as nb
import yaml
from config_loader import setup_geography
from geography import VenueManager
from population import PopulationManager
from residence.allocation_strategy import execute_allocation_strategy
from residence.household import HouseholdDistributor
from world import World

if os.environ.get('PYTHONHASHSEED') is None:
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable] + sys.argv)

logger = logging.getLogger("create_world")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Suppress numexpr logging
logging.getLogger('numexpr').setLevel(logging.WARNING)

def set_random_seed(seed=999):
    """
    Sets global seeds for testing in numpy, random, and numbaised numpy.
    """

    @nb.njit(cache=True)
    def set_seed_numba(seed):
        random.seed(seed)
        return np.random.seed(seed)

    np.random.seed(seed)
    set_seed_numba(seed)
    random.seed(seed)
    return

set_random_seed(0)


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
    for vtype in sorted(venue_types)[:10]:  # Show first 3 types
        venues_of_type = venues.get_venues_by_type(vtype)
        if venues_of_type:
            example_venue = venues_of_type[0]
            logger.info(f"   {vtype.capitalize()}: {example_venue.name}")
            logger.info(f"   - Located in: {example_venue.geographical_unit.name} ({example_venue.geographical_unit.level})")
            if example_venue.coordinates:
                logger.info(f"   - Coordinates: {example_venue.coordinates}")
            if example_venue.properties:
                # Show first 2 properties
                props = list(example_venue.properties.items())[:2]
                for key, value in props:
                    logger.info(f"   - {key}: {value}")

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
        for person in population.get_all_people()[:3]:
            logger.info(f"   {person}")
            logger.info(f"     - Activities: {', '.join(person.activities)}")

    logger.info("")
    logger.info("4. Household Examples:")
    if world.households and world.households.households:
        total_pop = len(population.get_all_people())
        allocation_rate = (len(world.households.allocated_people) / total_pop * 100) if total_pop > 0 else 0
        logger.info(f"   Total households: {len(world.households.households)}")
        logger.info(f"   People allocated: {len(world.households.allocated_people):,} / {total_pop:,} ({allocation_rate:.1f}%)")
        logger.info("")
        logger.info("   Example households:")
        for household in world.households.households[:5]:
            composition = household.get_composition()
            logger.info(f"   Household {household.id} in {household.geographical_unit.name}")
            logger.info(f"     - Size: {household.size()} people")
            logger.info(f"     - Composition: {composition}")
            if household.properties.get('original_pattern'):
                logger.info(f"     - Pattern: {household.properties['original_pattern']}")

    logger.info("")
    logger.info("5. Query Examples:")
    logger.info("   # Get all hospitals")
    all_hospitals = venues.get_venues_by_type("hospital")
    logger.info(f"   venues.get_venues_by_type('hospital') -> {len(all_hospitals)} hospitals")

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
    logger.info("   # Get person's household")
    if world.households and world.households.allocated_people:
        example_person_id = next(iter(world.households.allocated_people))
        example_person = next((p for p in population.get_all_people() if p.id == example_person_id), None)
        if example_person and hasattr(example_person, 'residence') and example_person.residence:
            logger.info(f"   person.residence -> Household {example_person.residence.id}")
            logger.info(f"      Size: {example_person.residence.size()}, Composition: {example_person.residence.get_composition()}")

    logger.info("")
    logger.info("=" * 60)


def main():
    """
    Main entry point for world creation.
    """

    logger.info("=" * 60)
    logger.info("June Zero - World Creation")
    logger.info("=" * 60)

    # Load config file
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Setup geography from config and command-line arguments
    geo, filters = setup_geography()

    # Load the geography data
    geo.load_from_csv()

    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venues = VenueManager(geography=geo, data_dir="data/venues")
    venue_config = config.get("venues", {})
    yaml_config_file = venue_config.get("config_file", "venues_config.yaml")
    venues.load_from_yaml_config(yaml_config_file)

    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir=pop_config.get("data_dir", "data/population")
    )

    # Load demographic data
    male_file = pop_config.get("demographics_male_file", "demographics_male.csv")
    female_file = pop_config.get("demographics_female_file", "demographics_female.csv")
    population.load_demographics_from_csv(male_file, female_file)

    # Generate population
    population.generate_population()

    # Distribute households
    logger.info("")
    logger.info("Distributing households...")
    household_config = config.get("households", {})
    households = HouseholdDistributor(
        geography=geo,
        population=population,
        data_dir=household_config.get("data_dir", "data/households"),
        config_file=household_config.get("config_file", "households_config.yaml")
    )

    # Load household data
    household_data_file = household_config.get("data_file", "households.csv")
    households.load_household_data(household_data_file)

    # Distribute households and venues based on configuration mode
    strategy_file = household_config.get("strategy_file")

    if strategy_file:
        # Mode 1: Unified strategy (households + venues in order)
        logger.info(f"Using unified allocation strategy from {strategy_file}")
        execute_allocation_strategy(population, venues, households, strategy_file)

    # Export household allocations
    export_file = household_config.get("export_file", "household_allocations.csv")
    households.export_households_to_csv(export_file)

    # Export venue allocations
    venue_export_file = config.get("venues", {}).get("export_file", "venue_allocations.csv")
    venues.export_venues_to_csv(venue_export_file)

    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues, households=households)
    logger.info(world)

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Show examples of what was created
    #print_world_examples(world)

    return world


if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()
    
    world = main()

    try:
        profiler.disable()
        stats = pstats.Stats(profiler).sort_stats('cumulative')
        profile_filename = 'simulation_profile.stats'
        stats.dump_stats(profile_filename)
        logger.info(f"Performance profiling data saved to {profile_filename}")
    except Exception as e:
        logger.error(f"Failed to save profiling data: {e}")