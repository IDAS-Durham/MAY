"""
Test script to verify World HDF5 serialization round-trip.

This script:
1. Creates a World object
2. Saves it to HDF5 format
3. Loads it back from the file
4. Compares the original with the loaded version using World.__eq__
5. Reports whether they are equivalent

This validates that the serialization/deserialization process preserves
all world state correctly.
"""

import os
import sys
import logging
import yaml
import numpy as np
import numba as nb
from pathlib import Path

from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World, setup_households

import pytest
pytestmark = pytest.mark.skip(reason="CommandLine script, not a Pytest suite")

# Set up logging
logger = logging.getLogger("test_serialization")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Suppress numexpr logging
logging.getLogger('numexpr').setLevel(logging.WARNING)

# Set random seed for reproducibility
def set_random_seed(seed=42):
    """Set global seeds for testing in numpy and numba."""
    @nb.njit(cache=True)
    def set_seed_numba(seed):
        return np.random.seed(seed)

    np.random.seed(seed)
    set_seed_numba(seed)

set_random_seed(42)


def create_world(config_path):
    """
    Create a World object from configuration.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        World: Created world object
    """
    logger.info("=" * 80)
    logger.info("CREATING WORLD")
    logger.info("=" * 80)

    # Load config
    logger.info(f"Loading configuration from: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Setup geography
    geo, _ = setup_geography(config=config)
    geo.load_from_csv()
    logger.info(f"Geography loaded: {len(geo.get_all_units())} units")

    # Load venues
    logger.info("Loading venues...")
    venue_config = config.get("venues", {})
    venues = VenueManager(
        geography=geo,
        data_dir=venue_config.get("data_dir", "data/venues")
    )
    yaml_config_file = venue_config.get("config_file", "venues_config.yaml")
    venues.load_from_yaml_config(yaml_config_file)
    logger.info(f"Venues loaded: {sum(len(d) for d in venues.venues_by_type_and_id.values())} venues")

    # Load population
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
    logger.info(f"Population generated: {len(population.people):,} people")

    # Setup and distribute households
    household_distributor = setup_households(geo, population, venues, config)

    # Create World object
    logger.info("Creating World object...")
    world = World(
        geography=geo,
        population=population,
        venues=venues,
        household_distributor=household_distributor
    )

    logger.info("")
    logger.info("World created successfully:")
    logger.info(f"  {world}")
    logger.info("=" * 80)

    return world


def test_serialization_roundtrip(world, output_file="test_world_roundtrip.h5"):
    """
    Test that saving and loading preserves World state.

    Args:
        world: Original World object
        output_file: Path to temporary HDF5 file

    Returns:
        tuple: (success: bool, loaded_world: World, error_message: str)
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TESTING SERIALIZATION ROUND-TRIP")
    logger.info("=" * 80)

    # Step 1: Export to HDF5
    logger.info("")
    logger.info("Step 1: Exporting World to HDF5...")
    try:
        world.export_to_hdf5(output_file)
        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        logger.info(f"✓ Successfully saved to {output_file} ({file_size_mb:.2f} MB)")
    except Exception as e:
        logger.error(f"✗ Failed to export World: {e}")
        return False, None, f"Export failed: {e}"

    # Step 2: Load from HDF5
    logger.info("")
    logger.info("Step 2: Loading World from HDF5...")
    try:
        loaded_world = World.load_from_hdf5(output_file)
        logger.info(f"✓ Successfully loaded from {output_file}")
        logger.info(f"  {loaded_world}")
    except Exception as e:
        logger.error(f"✗ Failed to load World: {e}")
        return False, None, f"Load failed: {e}"

    # Step 3: Compare worlds
    logger.info("")
    logger.info("Step 3: Comparing original and loaded worlds...")
    logger.info("-" * 80)

    try:
        # Enable debug logging to see detailed comparison
        logging.getLogger("world").setLevel(logging.DEBUG)

        worlds_equal = (world == loaded_world)

        # Restore logging level
        logging.getLogger("world").setLevel(logging.INFO)

        if worlds_equal:
            logger.info("✓ PASS: Original and loaded worlds are EQUAL")
            logger.info("  All geographical units, people, and venues match!")
            return True, loaded_world, None
        else:
            logger.error("✗ FAIL: Original and loaded worlds are NOT EQUAL")
            logger.error("  Check debug logs above for specific differences")
            return False, loaded_world, "Worlds differ (see logs for details)"

    except Exception as e:
        logger.error(f"✗ Comparison failed with exception: {e}")
        logger.exception(e)
        return False, loaded_world, f"Comparison error: {e}"


def print_detailed_comparison(world, loaded_world):
    """Print detailed comparison statistics."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("DETAILED COMPARISON")
    logger.info("=" * 80)

    # Geography comparison
    logger.info("")
    logger.info("Geography:")
    if world.geography and loaded_world.geography:
        orig_units = world.geography.get_all_units()
        loaded_units = loaded_world.geography.get_all_units()
        logger.info(f"  Original units: {len(orig_units)}")
        logger.info(f"  Loaded units:   {len(loaded_units)}")
        logger.info(f"  Match: {'✓' if len(orig_units) == len(loaded_units) else '✗'}")

    # Population comparison
    logger.info("")
    logger.info("Population:")
    if world.population and loaded_world.population:
        orig_people = world.population.people
        loaded_people = loaded_world.population.people
        logger.info(f"  Original people: {len(orig_people):,}")
        logger.info(f"  Loaded people:   {len(loaded_people):,}")
        logger.info(f"  Match: {'✓' if len(orig_people) == len(loaded_people) else '✗'}")

        # Sample a few people for detailed comparison
        if orig_people and loaded_people:
            sample_ids = list(range(min(3, len(orig_people))))
            logger.info("")
            logger.info("  Sample people comparison:")
            for person_id in sample_ids:
                orig_person = next((p for p in orig_people if p.id == person_id), None)
                loaded_person = next((p for p in loaded_people if p.id == person_id), None)
                if orig_person and loaded_person:
                    match = orig_person == loaded_person
                    logger.info(f"    Person {person_id}: {'✓ Equal' if match else '✗ Different'}")
                    if not match:
                        logger.info(f"      Original: age={orig_person.age}, sex={orig_person.sex}")
                        logger.info(f"      Loaded:   age={loaded_person.age}, sex={loaded_person.sex}")

    # Venues comparison
    logger.info("")
    logger.info("Venues:")
    if world.venues and loaded_world.venues:
        orig_venues = world.venues.get_all_venues_list()
        loaded_venues = loaded_world.venues.get_all_venues_list()
        logger.info(f"  Original venues: {len(orig_venues)}")
        logger.info(f"  Loaded venues:   {len(loaded_venues)}")
        logger.info(f"  Match: {'✓' if len(orig_venues) == len(loaded_venues) else '✗'}")

        # Venue types breakdown
        orig_types = {}
        for v in orig_venues:
            orig_types[v.type] = orig_types.get(v.type, 0) + 1

        loaded_types = {}
        for v in loaded_venues:
            loaded_types[v.type] = loaded_types.get(v.type, 0) + 1

        logger.info("")
        logger.info("  Venues by type:")
        all_types = set(orig_types.keys()) | set(loaded_types.keys())
        for vtype in sorted(all_types):
            orig_count = orig_types.get(vtype, 0)
            loaded_count = loaded_types.get(vtype, 0)
            match = '✓' if orig_count == loaded_count else '✗'
            logger.info(f"    {vtype:20s}: {orig_count:6d} vs {loaded_count:6d} {match}")

    logger.info("=" * 80)


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Test World serialization round-trip"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="world_specific_code/MedievalYaml/config.yaml",
        help="Path to world configuration YAML file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="test_world_roundtrip.h5",
        help="Path for temporary HDF5 file (default: test_world_roundtrip.h5)"
    )
    parser.add_argument(
        "--keep-file",
        action="store_true",
        help="Keep the HDF5 file after testing (default: delete)"
    )
    args = parser.parse_args()

    # Check if config exists
    if not os.path.exists(args.config):
        logger.error(f"Configuration file not found: {args.config}")
        logger.error("Please provide a valid config file with --config")
        sys.exit(1)

    try:
        # Create world
        world = create_world(args.config)

        # Test serialization round-trip
        success, loaded_world, error_msg = test_serialization_roundtrip(
            world,
            output_file=args.output
        )

        # Print detailed comparison
        if loaded_world:
            print_detailed_comparison(world, loaded_world)

        # Final result
        logger.info("")
        logger.info("=" * 80)
        if success:
            logger.info("✓✓✓ SERIALIZATION ROUND-TRIP TEST: PASSED ✓✓✓")
            logger.info("The World object is correctly preserved through HDF5 save/load!")
        else:
            logger.error("✗✗✗ SERIALIZATION ROUND-TRIP TEST: FAILED ✗✗✗")
            if error_msg:
                logger.error(f"Error: {error_msg}")
        logger.info("=" * 80)

        # Clean up temporary file unless --keep-file specified
        if not args.keep_file and os.path.exists(args.output):
            os.remove(args.output)
            logger.info(f"Cleaned up temporary file: {args.output}")
        elif args.keep_file:
            logger.info(f"Kept HDF5 file: {args.output}")

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error("=" * 80)
        logger.error("✗✗✗ TEST FAILED WITH EXCEPTION ✗✗✗")
        logger.error(f"Error: {e}")
        logger.exception(e)
        logger.error("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
