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
from may.venue_child_creator import VenueChildCreator
from may.relationships import FriendshipBuilder
from debug_output import export_venue_allocations, export_people, print_world_examples, export_relationships
#from debug_scripts.check_multiple_jobs import analyze_multiple_jobs

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
        default="yaml/config.yaml",
        help="Path to configuration YAML file (default: yaml/config.yaml)"
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

    # ========================================
    # VENUE PIPELINE - Unified distributors and child creators
    # ========================================
    # Interleave distributors and child creators in any order
    # Each step runs sequentially in the order specified

    pipeline_config = config.get("venue_pipeline", {})

    if pipeline_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("VENUE PIPELINE")
        logger.info("=" * 60)

        pipeline_steps = pipeline_config.get("steps", [])

        if not pipeline_steps:
            logger.info("No pipeline steps configured")
        else:
            # Execute each step in sequence
            for step in pipeline_steps:
                step_type = step.get("type")
                step_config = step.get("config")

                if step_type == "distributor":
                    logger.info("")
                    logger.info(f"[DISTRIBUTOR] {step_config}")
                    try:
                        distributor = VenueDistributor.from_yaml(step_config)
                        distributor.allocate(world)

                        # Export allocations to CSV
                        venue_type = distributor.venue_type
                        output_file = f"{venue_type}_allocations.csv"
                        #distributor.export_allocations(world, output_file)
                        #logger.info(f"Saved allocations to: {output_file}")

                    except Exception as e:
                        logger.error(f"Failed to run distributor {step_config}: {e}")
                        logger.exception(e)

                elif step_type == "child_creator":
                    logger.info("")
                    logger.info(f"[CHILD CREATOR] {step_config}")
                    try:
                        creator = VenueChildCreator.from_yaml(step_config)
                        creator.create_children(world)

                        # Export allocations to CSV
                        child_type = creator.child_venue_type
                        output_file = f"{child_type}_allocations.csv"
                        #creator.export_allocations(world, output_file)
                        #logger.info(f"Saved allocations to: {output_file}")

                    except Exception as e:
                        logger.error(f"Failed to run child creator {step_config}: {e}")
                        logger.exception(e)

                else:
                    logger.warning(f"Unknown pipeline step type: {step_type}")

        # Analyze multiple jobs after venue pipeline completes
        """ logger.info("")
        logger.info("=" * 60)
        logger.info("MULTIPLE JOBS ANALYSIS")
        logger.info("=" * 60)
        analyze_multiple_jobs(world) """

    # ========================================
    # RELATIONSHIP PIPELINE - Build agent networks
    # ========================================
    relationship_config = config.get("relationship_pipeline", {})

    if relationship_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATIONSHIP PIPELINE")
        logger.info("=" * 60)

        relationship_configs = relationship_config.get("relationships", [])

        for rel_config in relationship_configs:
            config_path = rel_config.get("config")

            logger.info("")
            logger.info(f"[RELATIONSHIP] {config_path}")

            try:
                builder = FriendshipBuilder(world, config_path)
                builder.build_all(store=True)

                # Export relationships to CSV
                storage_key = builder.config.get('storage', {}).get('key', builder.name)
                #export_relationships(world, storage_key, f"{storage_key}.csv")

            except Exception as e:
                logger.error(f"Failed to build relationships from {config_path}: {e}")
                logger.exception(e)

    # ========================================
    # ROMANTIC RELATIONSHIPS - Sexual orientation and partnerships
    # ========================================
    romantic_config = config.get("romantic_relationships", {})

    if romantic_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("ROMANTIC RELATIONSHIPS")
        logger.info("=" * 60)

        config_path = romantic_config.get("config", "yaml/relationships/romantic_relationships.yaml")

        try:
            from may.relationships.romantic_relationships import RomanticDistributor
            distributor = RomanticDistributor(world, config_path)
            distributor.distribute_all()

        except Exception as e:
            logger.error(f"Failed to distribute romantic relationships: {e}")
            logger.exception(e)

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Export venue allocations
    #export_venue_allocations(world)

    # Export people data
    #export_people(world)

    # Show examples of what was created
    #print_world_examples(world)

    # Export world to HDF5 for C++ simulation
    # Uncomment to enable HDF5 export:
    world.export_to_hdf5("world_state.h5")

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
