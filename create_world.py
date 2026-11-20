# -*- coding: utf-8 -*-
import cProfile
import os
import logging
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager, VenueError
from may.population import PopulationManager, PopulationError
from may.world import World
from may.social_networks import SocialNetworkBuilder
from may.serialization.preflight import warn_about_venue_property_gaps
from may.utils import path_resolver as pr
from may.utils import build_profile as bp
from may.timeline import TimelineError, require_config_path, run_timeline, step_label
#from debug_scripts.check_multiple_jobs import analyze_multiple_jobs

logger = logging.getLogger("create_world")

# Windows consoles default to cp1252, which cannot encode the non-ASCII
# characters used in log messages. Force UTF-8 on the log stream.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
    """Build the PopulationManager, failing loud on bad config or missing data.
    ``data_dir`` is resolved once and used by
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


def parse_args(argv=None):
    """Parse the CLI. Shared with the entry point below, which needs to know
    whether cProfile was asked for before the build starts."""
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
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Also record function-level cProfile data. Slows the build and shifts the timings it reports, so it is off by default."
    )
    return parser.parse_args(argv)


def main(args=None):
    """
    Main entry point for world creation.
    """

    logger.info("=" * 60)
    logger.info("MAY - World Creation")
    logger.info("=" * 60)

    if args is None:
        args = parse_args()

    logger.info(f"Loading configuration from: {args.config}")
    with open(args.config, "r", encoding="utf-8-sig") as f:
        config = yaml.safe_load(f)

    # Initialise path resolver from roots declared in config.yaml
    from pathlib import Path as _Path
    _config_yaml_dir = str(_Path(args.config).resolve().parent)
    pr.init(
        config_root=config.get("config_root", _config_yaml_dir),
        data_root=config.get("data_root", None),
        output_root=config.get("output_root", str(_Path.cwd() / "output")),
    )

    # Every build records what its stages cost. The profile lands next to the
    # world this run produces.
    profile_output_dir = pr.resolve(config.get("serialization", {}).get("output_dir", "."))
    bp.start(profile_output_dir, args.config, cprofile_enabled=getattr(args, "profile", False))

    # Setup geography from config and command-line arguments
    with bp.stage("geography_load", "pipeline"):
        geo, _ = setup_geography(config=config)

        # Load the geography data
        geo.load_from_csv()
        bp.bind(geography=geo)

    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    with bp.stage("venues_load", "pipeline"):
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
        bp.bind(venues=venues)

        # Compare the export schema with the venue files here, at the point
        # where acting on a mismatch still costs one restart.
        serial_settings = config.get("serialization", {})
        if serial_settings.get("enabled", True) and serial_settings.get("config_file"):
            with open(pr.resolve(serial_settings["config_file"]), "r",
                      encoding="utf-8-sig") as f:
                serial_schema = yaml.safe_load(f) or {}
            with open(yaml_config_file, "r", encoding="utf-8-sig") as f:
                venues_schema = yaml.safe_load(f) or {}
            warn_about_venue_property_gaps(
                serial_schema, venues_schema,
                pr.resolve(venue_config.get("data_dir", "data/venues")),
            )

    # Load population
    logger.info("")
    logger.info("Loading population...")
    with bp.stage("population_load", "pipeline"):
        try:
            population = setup_population(config, geo)
        except PopulationError as e:
            logger.error(f"Population loading failed: {e}")
            sys.exit(1)
        bp.bind(population=population)

    # Households are allocated by the explicit `residence_allocation` timeline
    # step (see run_timeline below), not implicitly before the timeline.
    # The World starts with no distributor; the step attaches it when it runs.
    household_distributor = None

    # Create World object
    logger.info("")
    logger.info("Creating World object...")
    world = World(geography=geo, population=population, venues=venues, household_distributor=household_distributor)
    bp.bind(world=world)
    logger.info(world)

    try:
        run_timeline(world, config)
    except TimelineError:
        # Already logged by the failing step.
        sys.exit(1)

    # RELATIONSHIP PIPELINE - Build agent networks
    relationship_config = config.get("relationship_pipeline", {})

    if relationship_config.get("enabled", False):
        logger.info("")
        logger.info("=" * 60)
        logger.info("RELATIONSHIP PIPELINE")
        logger.info("=" * 60)

        relationship_configs = relationship_config.get("relationships", [])

        for rel_config in relationship_configs:
            config_path = require_config_path(
                "Every `relationship_pipeline.relationships` entry", rel_config
            )

            logger.info("")
            logger.info(f"[RELATIONSHIP] {config_path}")

            with bp.stage(step_label("relationship", config_path), "relationship", detail=config_path):
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

        config_path = require_config_path(
            "`romantic_relationships.enabled: true`", romantic_config,
            " naming this scenario's romantic-relationships YAML",
        )

        with bp.stage("romantic_relationships", "romantic", detail=config_path):
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
        with bp.stage("hdf5_export", "pipeline"):
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

    recorder = bp.active()
    if recorder is not None:
        recorder.finish()
        recorder.log_summary(logger)

    return world


if __name__ == "__main__":
    # Force a deterministic hash seed for reproducible runs. This re-execs the
    # interpreter, so it must stay in the CLI entry path. Doing it at import
    # time replaces the process whenever the module is imported (e.g. by tests).
    if os.environ.get('PYTHONHASHSEED') is None:
        os.environ['PYTHONHASHSEED'] = '0'
        os.execv(sys.executable, [sys.executable] + sys.argv)

    cli_args = parse_args()

    profiler = None
    if cli_args.profile:
        profiler = cProfile.Profile()
        profiler.enable()

    world = main(cli_args)

    if profiler is not None:
        profiler.disable()
        recorder = bp.active()
        if recorder is not None:
            profiler.dump_stats(recorder.stats_path)
