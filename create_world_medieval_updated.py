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

# Gavin social network version
from may.social_networks import (
    allocate_random_bounded_distance_contacts,
    build_local_social_network,
    build_spatial_social_network,
)

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
        default="world_specific_code/MedievalYaml/config.yaml",
        help="Path to configuration YAML file (default: world_specific_code/MedievalYaml/config.yaml)"
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
    venues = VenueManager(geography=geo, data_dir=config.get("venues", {}).get("data_dir", "world_specific_code/MedievalYaml/data/venues"))
    venue_config = config.get("venues", {})
    yaml_config_file = venue_config.get("config_file", "world_specific_code/MedievalYaml/yaml/venues/venues_config.yaml")
    venues.load_from_yaml_config(yaml_config_file)

    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir=pop_config.get("data_dir", "world_specific_code/MedievalYaml/data/population")
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
                configs = [attribute_config.get("config", "world_specific_code/MedievalYaml/yaml/attributes/attribute_assignment.yaml")]

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
        logger.info("RELATIONSHIP PIPELINE (Gavin Version)")
        logger.info("=" * 60)

        # Builds a local network based on a particular clustering algorithm.
        # This creates realistic closed graphs. 
        build_local_social_network(
            world.geography,
            mean_connections_per_person=6,
            clustering_level=0.6,
            storage_key = 'social_contacts_local',
            algorithm = 'watts_strogatz',
        )

        # Assign activity_map for social contacts.
        # Must be run after household allocation as it maps to the contact's household. 
        for person in world.population.people:
            if 'social_contacts_local' in person.properties:
                person.activities.add('social_contacts_local')
                person.activity_map['social_contacts_local'] = {}
                for contact_id in person.properties['social_contacts_local']:
                    contact = world.population.people_by_id[contact_id]
                    if 'residence' in contact.activity_map:
                        person.activity_map['social_contacts_local'].update(contact.activity_map['residence'])

        # Near-range inter-unit network: annulus [1, 15] km, W-S clustering
        build_spatial_social_network(
            world.geography,
            min_radius_km=1.0,
            max_radius_km=15.0,
            mean_connections_per_person=6,
            clustering_level=0.6,
            storage_key='social_contacts_near',
        )

        for person in world.population.people:
            if 'social_contacts_near' in person.properties and person.properties['social_contacts_near']:
                person.activities.add('social_contacts_near')
                person.activity_map['social_contacts_near'] = {}
                for contact in person.properties['social_contacts_near']:
                    if 'residence' in contact.activity_map:
                        person.activity_map['social_contacts_near'].update(contact.activity_map['residence'])

        # Far-range inter-unit network: annulus [15, 30] km, W-S clustering
        build_spatial_social_network(
            world.geography,
            min_radius_km=15.0,
            max_radius_km=30.0,
            mean_connections_per_person=6,
            clustering_level=0.6,
            storage_key='social_contacts_far',
        )

        for person in world.population.people:
            if 'social_contacts_far' in person.properties and person.properties['social_contacts_far']:
                person.activities.add('social_contacts_far')
                person.activity_map['social_contacts_far'] = {}
                for contact in person.properties['social_contacts_far']:
                    if 'residence' in contact.activity_map:
                        person.activity_map['social_contacts_far'].update(contact.activity_map['residence'])

    

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {len(world.venues.get_all_venues())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Export venue allocations
    export_venue_allocations(world)

    # Export people data
    export_people(world)

    # Export world to HDF5 for C++ simulation
    world.export_to_hdf5("world_state_medieval_updated.h5")

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
