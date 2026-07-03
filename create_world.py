# -*- coding: utf-8 -*-
import cProfile
import os
import logging
import pstats
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager, VenueError
from may.population import PopulationManager, PopulationError
from may.world import World, setup_households
from may.residence.household_distributor import HouseholdError
from may.attribute_assignment import AttributeAssignmentError
from may.venue_distributor import VenueDistributor
from may.venue_child_creator import VenueChildCreator
from may.social_networks import SocialNetworkBuilder
from may.utils.debug_output import export_residence_venues, export_commute_mode_debug
from may.utils import path_resolver as pr
#from debug_scripts.check_multiple_jobs import analyze_multiple_jobs

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


VALID_POPULATION_TYPES = {"matrix", "explicit", "explicit_batch"}


def setup_population(config, geo):
    """Build the PopulationManager, failing loud on bad config or missing data
    (adr/0010, adr/0004, adr/0005). ``data_dir`` is resolved once and used by
    every mode; ``type`` is validated against the closed set rather than
    silently dispatching to matrix. Raises PopulationError on any miss."""
    pop_config = config.get("population", {})
    data_dir = pr.resolve(pop_config.get("data_dir", "data/population"))
    population = PopulationManager(geography=geo, data_dir=data_dir)

    pop_type = pop_config.get("type", "matrix")
    if pop_type not in VALID_POPULATION_TYPES:
        raise PopulationError(
            f"Unknown population.type {pop_type!r}; expected one of "
            f"{sorted(VALID_POPULATION_TYPES)}."
        )

    column_mapping = pop_config.get("column_mapping", {})
    if pop_type == "explicit_batch":
        population.load_batch_explicit_from_csv(
            data_dir=data_dir, column_mapping=column_mapping
        )
    elif pop_type == "explicit":
        filename = pop_config.get("filename")
        if not filename:
            raise PopulationError(
                "population.type 'explicit' requires a 'filename' in configuration."
            )
        population.load_explicit_from_csv(
            filename=filename, column_mapping=column_mapping
        )
    else:  # matrix
        male_file = pop_config.get("demographics_male_file", "demographics_male.csv")
        female_file = pop_config.get("demographics_female_file", "demographics_female.csv")
        population.load_demographics_from_csv(male_file, female_file)
        population.generate_population()

    return population


def main():
    """
    Main entry point for world creation.
    """

    logger.info("=" * 60)
    logger.info("MAY - World Creation")
    logger.info("=" * 60)

    # Load config file (support command-line argument)
    import argparse
    parser = argparse.ArgumentParser(description="Create a simulated world from configuration")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/2021/config.yaml",
        help="Path to configuration YAML file (default: configs/2021/config.yaml)"
    )
    parser.add_argument(
        "--filename",
        type=str,
        default=None,
        help="Output HDF5 filename. Overrides serialization.filename in config. Defaults to world_state.h5 if neither is set."
    )
    args = parser.parse_args()

    logger.info(f"Loading configuration from: {args.config}")
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Initialise path resolver from roots declared in config.yaml
    from pathlib import Path as _Path
    _config_yaml_dir = str(_Path(args.config).resolve().parent)
    pr.init(
        config_root=config.get("config_root", _config_yaml_dir),
        data_root=config.get("data_root", None),
        output_root=config.get("output_root", str(_Path.cwd() / "output")),
    )

    # Setup geography from config and command-line arguments
    geo, _ = setup_geography(config=config)

    # Load the geography data
    geo.load_from_csv()

    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venue_config = config.get("venues", {})
    venues = VenueManager(
        geography=geo,
        data_dir=pr.resolve(venue_config.get("data_dir", "data/venues"))
    )

    yaml_config_file = pr.resolve(venue_config.get("config_file", "venues_config.yaml"))
    try:
        venues.load_from_yaml_config(yaml_config_file)
    except VenueError as e:
        logger.error(f"Venue loading failed: {e}")
        sys.exit(1)

    # Load population
    logger.info("")
    logger.info("Loading population...")
    try:
        population = setup_population(config, geo)
    except PopulationError as e:
        logger.error(f"Population loading failed: {e}")
        sys.exit(1)

    # Households are allocated by the explicit `residence_allocation` timeline
    # step (see the timeline loop below), not implicitly before the timeline.
    # The World starts with no distributor; the step attaches it when it runs.
    household_distributor = None

    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues, household_distributor=household_distributor)
    logger.info(world)

    # TIMELINE - Unified Event Processing
    # This replaces the separate "attributes" and "venue_pipeline" sections if "timeline" is present.
    
    timeline_config = config.get("timeline", {})

    if timeline_config.get("enabled", False) and timeline_config.get("steps"):
        logger.info("")
        logger.info("=" * 60)
        logger.info("SIMULATION TIMELINE")
        logger.info("=" * 60)

        # Households/residence venues are allocated by an explicit
        # `residence_allocation` step. A households: block only exists to wire
        # data for that step, so a block with no step is almost always a mistake.
        step_types = [s.get("type") for s in timeline_config.get("steps", [])]
        if config.get("households") and "residence_allocation" not in step_types:
            logger.warning(
                "a households: block is configured but the timeline has no "
                "'residence_allocation' step — households will NOT be allocated."
            )

        for step in timeline_config.get("steps", []):
            step_type = step.get("type")
            step_config = pr.resolve(step.get("config"))

            if step_type == "residence_allocation":
                # Runs the full household + residence-venue allocation strategy
                # at this point in the timeline. The step's `config:` points at
                # the allocation-strategy YAML (any filename, must follow that
                # format) — the single source of truth for which strategy runs.
                # Placing attribute steps before it lets residence allocation
                # read those attributes.
                logger.info("")
                logger.info(f"[RESIDENCE ALLOCATION] {step_config}")
                if not step_config:
                    raise ValueError(
                        "A `residence_allocation` timeline step must set "
                        "`config:` to an allocation-strategy YAML file "
                        "(e.g. configs/<scenario>/households/allocation_strategy.yaml)."
                    )
                try:
                    world.household_distributor = setup_households(
                        geo, population, venues, config, strategy_file=step_config
                    )
                except HouseholdError as e:
                    logger.error(f"Household allocation failed: {e}")
                    sys.exit(1)

            elif step_type == "attribute":
                logger.info("")
                logger.info(f"[ATTRIBUTE] {step_config}")
                try:
                    world.assign_attributes(step_config)
                except AttributeAssignmentError as e:
                    logger.error(f"Attribute assignment failed: {e}")
                    sys.exit(1)

            elif step_type == "distributor":
                logger.info("")
                logger.info(f"[DISTRIBUTOR] {step_config}")
                try:
                    distributor = VenueDistributor.from_yaml(step_config)
                    distributor.allocate(world)
                    
                    # If this is the residence distributor, optionally export detailed allocations
                    # Skipped by default for large worlds (build a DataFrame over every person).
                    if (
                        getattr(distributor, 'activity_name', None) == "residence"
                        and config.get("debug_outputs", {}).get("enabled", False)
                    ):
                        serial_config = config.get("serialization", {})
                        output_dir = pr.resolve(serial_config.get("output_dir", "."))
                        res_export_file = os.path.join(output_dir, "residence_venues.csv")
                        export_residence_venues(world, res_export_file)
                except Exception as e:
                    logger.error(f"Failed to run distributor {step_config}: {e}")
                    logger.exception(e)
                    sys.exit(1)

            elif step_type == "child_creator":
                logger.info("")
                logger.info(f"[CHILD CREATOR] {step_config}")
                try:
                    creator = VenueChildCreator.from_yaml(step_config)
                    creator.create_children(world)
                except Exception as e:
                    logger.error(f"Failed to run child creator {step_config}: {e}")
                    logger.exception(e)
                    sys.exit(1)

            else:
                logger.warning(f"Unknown timeline step type: {step_type}")

        # Commute-mode verification dump (after all assignments/distributors)
        if config.get("debug_outputs", {}).get("enabled", False):
            serial_config = config.get("serialization", {})
            output_dir = pr.resolve(serial_config.get("output_dir", "."))
            os.makedirs(output_dir, exist_ok=True)
            export_commute_mode_debug(
                world, os.path.join(output_dir, "commute_mode_debug.csv")
            )

    else:
        # Every scenario drives all events through the timeline, including an
        # explicit `residence_allocation` step for households.
        raise ValueError(
            "No enabled timeline with steps found. The legacy "
            "attributes/venue_pipeline path has been removed — every config "
            "must define `timeline.enabled: true` with `timeline.steps`, "
            "including an explicit `residence_allocation` step when "
            "households are enabled."
        )

    # RELATIONSHIP PIPELINE - Build agent networks
    relationship_config = config.get("relationship_pipeline", {})

    if relationship_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATIONSHIP PIPELINE")
        logger.info("=" * 60)

        relationship_configs = relationship_config.get("relationships", [])

        for rel_config in relationship_configs:
            config_path = pr.resolve(rel_config.get("config"))

            logger.info("")
            logger.info(f"[RELATIONSHIP] {config_path}")

            try:
                builder = SocialNetworkBuilder.from_yaml(world, config_path)
                builder.build_all()

            except Exception as e:
                logger.error(f"Failed to build relationships from {config_path}: {e}")
                logger.exception(e)
                sys.exit(1)

    # ROMANTIC RELATIONSHIPS - Sexual orientation and partnerships
    romantic_config = config.get("romantic_relationships", {})

    if romantic_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("ROMANTIC RELATIONSHIPS")
        logger.info("=" * 60)

        config_path = pr.resolve(romantic_config.get("config", "configs/2021/relationships/romantic_relationships.yaml"))

        try:
            from may.relationships.romantic_relationships import RomanticDistributor
            distributor = RomanticDistributor(world, config_path)
            distributor.distribute_all()

        except Exception as e:
            logger.error(f"Failed to distribute romantic relationships: {e}")
            logger.exception(e)
            sys.exit(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("World creation complete!")
    logger.info(f"Geography: {len(world.geography.get_all_units())} units")
    logger.info(f"Venues: {sum(len(d) for d in world.venues.venues_by_type_and_id.values())} venues across {len(venues.get_venue_types())} types")
    logger.info(f"Population: {len(world.population.get_all_people()):,} people")
    logger.info("=" * 60)

    # Export world to HDF5 for C++ simulation
    serial_config = config.get("serialization", {})
    if serial_config.get("enabled", True):
        logger.info("")
        logger.info("Exporting world to HDF5...")
        try:
            config_file = serial_config.get("config_file")
            if not config_file:
                raise ValueError(
                    "serialization.enabled is true but serialization.config_file "
                    "is missing — a serialization schema is required."
                )
            output_dir = pr.resolve(serial_config.get("output_dir", "."))
            filename = args.filename or serial_config.get("filename", "world_state.h5")

            if output_dir != ".":
                os.makedirs(output_dir, exist_ok=True)

            export_path = os.path.join(output_dir, filename)
            world.export_to_hdf5(export_path, config_file=pr.resolve(config_file))
        except Exception as e:
            logger.error(f"Failed to serialize world to HDF5: {e}")
            logger.exception(e)
            sys.exit(1)

    return world


if __name__ == "__main__":
    # Force a deterministic hash seed for reproducible runs. This re-execs the
    # interpreter, so it must stay in the CLI entry path — doing it at import
    # time replaces the process whenever the module is imported (e.g. by tests).
    if os.environ.get('PYTHONHASHSEED') is None:
        os.environ['PYTHONHASHSEED'] = '0'
        os.execv(sys.executable, [sys.executable] + sys.argv)

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
