import cProfile
import os
import logging
import pstats
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "my_may"))

import numpy as np
import numba as nb
import pandas as pd
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World, setup_households
from may.venue_distributor import VenueDistributor
from may.venue_child_creator import VenueChildCreator
#from may.relationships import FriendshipBuilder
from debug_output import export_venue_allocations, export_people, print_world_examples, export_relationships
from world_specific_code.MedievalYaml.travel_assignment import assign_travel_activities, assign_guest_houses, assign_sailing_activities
from world_specific_code.MedievalYaml.lords_land_assignment import assign_lords_land_venues

from may.social_networks import SocialNetworkBuilder

if os.environ.get('PYTHONHASHSEED') is None:
    os.environ['PYTHONHASHSEED'] = '0'
    os.execv(sys.executable, [sys.executable] + sys.argv)

logger = logging.getLogger("create_world_medieval")
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
    logger.info("Medieval - World Creation (Updated Architecture)")
    logger.info("=" * 60)

    # Load config file (support command-line argument)
    import argparse
    parser = argparse.ArgumentParser(description="Create a simulated medieval world from configuration")
    parser.add_argument(
        "--config",
        type=str,
        default="../my_may/world_specific_code/MedievalYaml/config.yaml",
        help="Path to configuration YAML file (default: ../my_may/world_specific_code/MedievalYaml/config.yaml)"
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
    venues = VenueManager(geography=geo, data_dir=config.get("venues", {}).get("data_dir", "../my_may/world_specific_code/MedievalYaml/data/venues"))
    venue_config = config.get("venues", {})
    yaml_config_file = venue_config.get("config_file", "../my_may/world_specific_code/MedievalYaml/yaml/venues/venues_config.yaml")
    venues.load_from_yaml_config(yaml_config_file)

    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir=pop_config.get("data_dir", "../my_may/world_specific_code/MedievalYaml/data/population")
    )

    # Load demographic data
    male_file = pop_config.get("demographics_male_file", "demography_male.csv")
    female_file = pop_config.get("demographics_female_file", "demography_female.csv")
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

    # Assign guest house property to random households in large geo units
    assign_guest_houses(world, "../my_may/world_specific_code/MedievalYaml/data/large_geo_units.csv")

    # Assign travel itineraries to a fraction of residents in source geo_units
    assign_travel_activities(
        world,
        paths_names_json_path="../my_may/world_specific_code/MedievalYaml/data/travel/paths_names_full.json",
        travel_fraction=0.10,
        min_age=18,
        max_age=70,
    )

    assign_sailing_activities(
        world,
        paths_names_ports_json_path="../my_may/world_specific_code/MedievalYaml/data/travel/paths_names_ports.json",
        port_manor_map_csv_path="../my_may/world_specific_code/MedievalYaml/data/travel/port_manor_map.csv",
        sailing_fraction=0.05,
        min_age=18,
        max_age=70,
    )

    assign_lords_land_venues(world)

    # ========================================
    # TIMELINE - Unified Event Processing
    # ========================================
    
    timeline_config = config.get("timeline", {})

    if timeline_config.get("enabled", False) and timeline_config.get("steps"):
        logger.info("")
        logger.info("=" * 60)
        logger.info("SIMULATION TIMELINE")
        logger.info("=" * 60)
        
        for step in timeline_config.get("steps", []):
            step_type = step.get("type")
            step_config = step.get("config")
            
            if step_type == "attribute":
                logger.info("")
                logger.info(f"[ATTRIBUTE] {step_config}")
                world.assign_attributes(step_config)
                
            elif step_type == "distributor":
                logger.info("")
                logger.info(f"[DISTRIBUTOR] {step_config}")
                try:
                    distributor = VenueDistributor.from_yaml(step_config)
                    distributor.allocate(world)
                except Exception as e:
                    logger.error(f"Failed to run distributor {step_config}: {e}")
                    logger.exception(e)
                    
            elif step_type == "child_creator":
                logger.info("")
                logger.info(f"[CHILD CREATOR] {step_config}")
                try:
                    creator = VenueChildCreator.from_yaml(step_config)
                    creator.create_children(world)
                except Exception as e:
                    logger.error(f"Failed to run child creator {step_config}: {e}")
                    logger.exception(e)
                    
            else:
                logger.warning(f"Unknown timeline step type: {step_type}")

    else:
        # FALLBACK: LEGACY PIPELINE
        logger.info("No timeline configured, using pipeline attributes -> venues")

        # Assign attributes
        attribute_config = config.get("attributes", {})
        if attribute_config.get("enabled", True):
            configs = attribute_config.get("configs")
            if configs is None:
                configs = [attribute_config.get("config", "../my_may/world_specific_code/MedievalYaml/yaml/attributes/attribute_assignment.yaml")]

            for config_path in configs:
                logger.info(f"Assigning attributes from: {config_path}")
                world.assign_attributes(config_path)

        # Venue Pipeline
        pipeline_config = config.get("venue_pipeline", {})

        if pipeline_config.get("enabled", False):
            logger.info("")
            logger.info("=" * 60)
            logger.info("VENUE PIPELINE")
            logger.info("=" * 60)

            pipeline_steps = pipeline_config.get("steps", [])

            for step in pipeline_steps:
                step_type = step.get("type")
                step_config = step.get("config")

                if step_type == "distributor":
                    logger.info("")
                    logger.info(f"[DISTRIBUTOR] {step_config}")
                    try:
                        distributor = VenueDistributor.from_yaml(step_config)
                        distributor.allocate(world)
                    except Exception as e:
                        logger.error(f"Failed to run distributor {step_config}: {e}")
                        logger.exception(e)

                elif step_type == "child_creator":
                    logger.info("")
                    logger.info(f"[CHILD CREATOR] {step_config}")
                    try:
                        creator = VenueChildCreator.from_yaml(step_config)
                        creator.create_children(world)
                    except Exception as e:
                        logger.error(f"Failed to run child creator {step_config}: {e}")
                        logger.exception(e)

    # ========================================
    # RELATIONSHIP PIPELINE - Build agent networks
    # ========================================
    relationship_config = config.get("relationship_pipeline", {})

    if relationship_config.get("enabled", True):
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATIONSHIP PIPELINE")
        logger.info("=" * 60)

        config_path = relationship_config.get(
            "config",
            "../my_may/world_specific_code/MedievalYaml/yaml/relationships/social_networks.yaml",
        )
        builder = SocialNetworkBuilder.from_yaml(world, config_path)
        builder.build_all()


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

    # Export world to HDF5 for C++ simulation
    world.export_to_hdf5(
        "world_state_medieval.h5",
        config_file="../my_may/world_specific_code/MedievalYaml/yaml/serialization_config.yaml",
    )

    return world


if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()

    world = main()

    try:
        profiler.disable()
        stats = pstats.Stats(profiler).sort_stats('cumulative')
        profile_filename = 'medieval_simulation_profile.stats'
        stats.dump_stats(profile_filename)
        logger.info(f"Performance profiling data saved to {profile_filename}")
    except Exception as e:
        logger.error(f"Failed to save profiling data: {e}")
