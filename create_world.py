import cProfile
import os
import logging
import pstats
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World, setup_households
from may.venue_distributor import VenueDistributor

if os.environ.get('PYTHONHASHSEED') is None:
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable] + sys.argv)

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

def set_random_seed(seed=999):
    """
    Sets global seeds for testing in numpy and numbaised numpy.
    """

    @nb.njit(cache=True)
    def set_seed_numba(seed):
        return np.random.seed(seed)

    np.random.seed(seed)
    set_seed_numba(seed)
    return

set_random_seed(0)


def export_venue_allocations(world, output_file="venue_allocations.csv"):
    """
    Export all venues (except households) with their allocation counts to CSV.

    Args:
        world: World object containing geography, population, and venues
        output_file: Path to output CSV file
    """
    import csv

    logger.info(f"Exporting venue allocations to {output_file}...")

    venues = world.venues.get_all_venues().values()

    # Collect venue allocation data
    venue_data = []
    for venue in venues:
        # Skip households
        if venue.type == "household":
            continue

        # Count allocated people
        allocated_count = venue.size()

        # Get capacity information from venue properties
        # Different venue types may have different capacity column names
        capacity_config = world.venues.get_capacity_config(venue.type)

        if capacity_config and 'total_capacity_column' in capacity_config:
            # Use the configured capacity column (e.g., 'bed_count' for care_home)
            capacity_column = capacity_config['total_capacity_column']
            total_capacity = venue.properties.get(capacity_column, 0)
        else:
            # Fallback to standard 'capacity' column
            total_capacity = venue.properties.get('capacity', 0)

        # Calculate utilization percentage
        if total_capacity > 0:
            utilization_pct = (allocated_count / total_capacity) * 100
        else:
            utilization_pct = 0.0

        venue_data.append({
            'venue_id': venue.id,
            'venue_name': venue.name,
            'venue_type': venue.type,
            'geographical_unit': venue.geographical_unit.name,
            'geographical_level': venue.geographical_unit.level,
            'capacity': int(total_capacity) if total_capacity else 0,
            'people_allocated': allocated_count,
            'utilization_pct': f"{utilization_pct:.1f}",
            'latitude': venue.coordinates[0] if venue.coordinates else None,
            'longitude': venue.coordinates[1] if venue.coordinates else None,
        })

    # Sort by venue type and then by allocated count
    venue_data.sort(key=lambda x: (x['venue_type'], -x['people_allocated']))

    # Write to CSV
    if venue_data:
        with open(output_file, 'w', newline='') as f:
            fieldnames = ['venue_id', 'venue_name', 'venue_type', 'geographical_unit',
                         'geographical_level', 'capacity', 'people_allocated', 'utilization_pct',
                         'latitude', 'longitude']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(venue_data)

        logger.info(f"Exported {len(venue_data)} venues to {output_file}")

        # Log summary statistics
        total_allocated = sum(v['people_allocated'] for v in venue_data)
        total_capacity = sum(v['capacity'] for v in venue_data)
        venue_types = {}
        for v in venue_data:
            vtype = v['venue_type']
            if vtype not in venue_types:
                venue_types[vtype] = {'count': 0, 'allocated': 0, 'capacity': 0}
            venue_types[vtype]['count'] += 1
            venue_types[vtype]['allocated'] += v['people_allocated']
            venue_types[vtype]['capacity'] += v['capacity']

        overall_utilization = (total_allocated / total_capacity * 100) if total_capacity > 0 else 0.0
        logger.info(f"Total capacity: {total_capacity:,}, Total allocated: {total_allocated:,} ({overall_utilization:.1f}% utilization)")
        logger.info("Breakdown by venue type:")
        for vtype, stats in sorted(venue_types.items()):
            util_pct = (stats['allocated'] / stats['capacity'] * 100) if stats['capacity'] > 0 else 0.0
            logger.info(f"  {vtype}: {stats['count']} venues, {stats['allocated']:,}/{stats['capacity']:,} people ({util_pct:.1f}%)")
    else:
        logger.info("No non-household venues to export")


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
    for vtype in sorted(venue_types)[:10]:  # Show first 10 types
        venues_of_type = venues.get_venues_by_type(vtype)
        if venues_of_type:
            example_venue = venues_of_type[0]
            logger.info(f"   {vtype.capitalize()}: {example_venue.name}")
            logger.info(f"   - Located in: {example_venue.geographical_unit.name} ({example_venue.geographical_unit.level})")
            if example_venue.coordinates:
                logger.info(f"   - Coordinates: {example_venue.coordinates}")
            if example_venue.properties:
                # Show first 2 properties
                props = list(example_venue.properties.items())
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
        for person in np.random.choice(population.get_all_people(), size=min(5, len(population.get_all_people())), replace=False):
            logger.info(f"   {person}")
            logger.info(f"     - Activities: {', '.join(person.activities)}")

    logger.info("")
    logger.info("4. Household Examples:")
    households = world.get_households()
    if households and world.household_distributor:
        total_pop = len(population.get_all_people())
        allocation_rate = (len(world.household_distributor.allocated_people) / total_pop * 100) if total_pop > 0 else 0
        logger.info(f"   Total households: {len(households)}")
        logger.info(f"   People allocated: {len(world.household_distributor.allocated_people):,} / {total_pop:,} ({allocation_rate:.1f}%)")
        logger.info("")
        logger.info("   Example households:")
        for household in np.random.choice(households, size=min(5, len(households)), replace=False):
            age_categories = household.properties.get('_age_categories', [])
            composition = household.get_composition(age_categories)
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
    if world.household_distributor and world.household_distributor.allocated_people:
        example_person_id = next(iter(world.household_distributor.allocated_people))
        example_person = next((p for p in population.get_all_people() if p.id == example_person_id), None)
        if example_person and "household" in example_person.activity_map:
            household_subsets = example_person.activity_map["household"]
            if household_subsets:
                household_venue = household_subsets[0].venue
                age_categories = household_venue.properties.get('_age_categories', [])
                logger.info(f"   person.activity_map['household'] -> Household {household_venue.id}")
                logger.info(f"      Size: {household_venue.size()}, Composition: {household_venue.get_composition(age_categories)}")

    logger.info("")
    logger.info("=" * 60)


def main():
    """
    Main entry point for world creation.
    """

    logger.info("=" * 60)
    logger.info("June Zero - World Creation")
    logger.info("=" * 60)

    # Load config file (support command-line argument)
    import argparse
    parser = argparse.ArgumentParser(description="Create a simulated world from configuration")
    parser.add_argument(
        "--config",
        type=str,
        default="world_specific_code/Modern_Day_UK/config.yaml",
        help="Path to configuration YAML file (default: world_specific_code/Modern_Day_UK/config.yaml)"
    )
    args = parser.parse_args()

    logger.info(f"Loading configuration from: {args.config}")
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Setup geography from config and command-line arguments
    geo, _ = setup_geography(config=config)

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

    # Setup and distribute households
    household_distributor = setup_households(geo, population, venues, config)

    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues, household_distributor=household_distributor)
    logger.info(world)

    # Assign attributes
    attribute_config = config.get("attributes", {})
    if attribute_config.get("enabled", True):
        # Support both single config and list of configs
        configs = attribute_config.get("configs")
        if configs is None:
            # Legacy: single config
            configs = [attribute_config.get("config", "yaml/attribute_assignment.yaml")]

        # Assign each attribute in sequence
        for config_path in configs:
            logger.info(f"Assigning attributes from: {config_path}")
            world.assign_attributes(config_path)

    # Distribute people to venues
    distributor_config = config.get("distributors", {})
    if distributor_config.get("enabled", True):
        logger.info("")
        logger.info("=" * 60)
        logger.info("VENUE DISTRIBUTION")
        logger.info("=" * 60)

        # Support list of distributor configs
        distributor_configs = distributor_config.get("configs", [])

        if not distributor_configs:
            logger.info("No distributors configured")
        else:
            # Execute each distributor in sequence
            for dist_config_path in distributor_configs:
                logger.info("")
                logger.info(f"Running distributor: {dist_config_path}")
                try:
                    distributor = VenueDistributor.from_yaml(dist_config_path)
                    distributor.allocate(world)

                    # Export allocations to CSV
                    venue_type = distributor.venue_type
                    output_file = f"{venue_type}_allocations.csv"
                    distributor.export_allocations(world, output_file)
                    logger.info(f"Saved allocations to: {output_file}")

                except Exception as e:
                    logger.error(f"Failed to run distributor {dist_config_path}: {e}")
                    logger.exception(e)

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Export venue allocations
    export_venue_allocations(world)

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
