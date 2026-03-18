"""
Simple test script for World HDF5 loading.

This script tests that the world_loader.py module can successfully
load a World object from an HDF5 file without errors.

Usage:
    python test_world_loader.py world_state.h5
"""

import sys
import os
import logging
from pathlib import Path

from may.world import World

import pytest
pytestmark = pytest.mark.skip(reason="CommandLine script, not a Pytest suite")

# Set up logging
logger = logging.getLogger("test_loader")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
def test_load_world(hdf5_file):
    """
    Test loading a World from HDF5 file.

    Args:
        hdf5_file: Path to HDF5 file

    Returns:
        tuple: (success: bool, world: World or None, error_msg: str or None)
    """
    logger.info("=" * 80)
    logger.info("TESTING WORLD LOADER")
    logger.info("=" * 80)
    logger.info(f"HDF5 file: {hdf5_file}")

    # Check file exists
    if not os.path.exists(hdf5_file):
        error_msg = f"File not found: {hdf5_file}"
        logger.error(f" FAILED: {error_msg}")
        return False, None, error_msg

    # Check file size
    file_size_mb = os.path.getsize(hdf5_file) / (1024 * 1024)
    logger.info(f"File size: {file_size_mb:.2f} MB")

    # Attempt to load
    logger.info("")
    logger.info("Attempting to load World from HDF5...")
    logger.info("-" * 50)

    try:
        world = World.load_from_hdf5(hdf5_file)
        logger.info("-" * 50)
        logger.info("Successfully loaded world")
        return True, world, None

    except Exception as e:
        logger.error("-" * 50)
        logger.error(f"Failed to load World: {e}")
        logger.exception(e)
        return False, None, str(e)


def print_world_summary(world):
    """Print summary information about the loaded World."""
    logger.info("")
    logger.info("=" * 80)
    logger.info("WORLD SUMMARY")
    logger.info("=" * 80)

    # Basic info
    logger.info("")
    logger.info(f"World object: {world}")

    # Geography
    if world.geography:
        logger.info("")
        logger.info("Geography:")
        all_units = world.geography.get_all_units()
        logger.info(f"  Total units: {len(all_units)}")

        # Units by level
        levels = {}
        for unit in all_units.values():
            levels[unit.level] = levels.get(unit.level, 0) + 1

        for level, count in sorted(levels.items()):
            logger.info(f"    {level}: {count}")

        # Sample unit
        if all_units:
            sample_unit = next(iter(all_units.values()))
            logger.info(f"  Sample unit: {sample_unit}")
    else:
        logger.info("")
        logger.info("Geography: None")

    # Population
    if world.population:
        logger.info("")
        logger.info("Population:")
        people = world.population.people
        logger.info(f"  Total people: {len(people):,}")

        # Age/sex breakdown
        if people:
            males = sum(1 for p in people if p.sex == 'male')
            females = sum(1 for p in people if p.sex == 'female')
            logger.info(f"    Males: {males:,}")
            logger.info(f"    Females: {females:,}")

            ages = [p.age for p in people]
            logger.info(f"    Age range: {min(ages):.1f} - {max(ages):.1f}")
            logger.info(f"    Mean age: {sum(ages)/len(ages):.1f}")

            # Sample person
            sample_person = people[0]
            logger.info(f"  Sample person: {sample_person}")
    else:
        logger.info("")
        logger.info("Population: None")

    # Venues
    if world.venues:
        logger.info("")
        logger.info("Venues:")
        all_venues = world.venues.get_all_venues_list()
        logger.info(f"  Total venues: {len(all_venues)}")

        # Venues by type
        venue_types = {}
        for venue in all_venues:
            venue_types[venue.type] = venue_types.get(venue.type, 0) + 1

        logger.info("  By type:")
        for vtype, count in sorted(venue_types.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"    {vtype}: {count}")

        # Sample venue
        if all_venues:
            sample_venue = all_venues[0]
            logger.info(f"  Sample venue: {sample_venue}")

            # Subsets in sample venue
            if sample_venue.subsets:
                logger.info(f"    Subsets: {list(sample_venue.subsets.keys())}")
                for subset_name, subset in sample_venue.subsets.items():
                    logger.info(f"      {subset_name}: {len(subset.members)} members")
    else:
        logger.info("")
        logger.info("Venues: None")

    logger.info("")
    logger.info("=" * 80)


def verify_data_integrity(world):
    """
    Perform basic integrity checks on loaded data.

    Returns:
        tuple: (success: bool, issues: list of str)
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("DATA INTEGRITY CHECKS")
    logger.info("=" * 80)

    issues = []

    # Check 1: All people have geographical units
    logger.info("")
    logger.info("Check 1: All people have geographical units...")
    if world.population:
        people_without_geo = [p for p in world.population.people if p.geographical_unit is None]
        if people_without_geo:
            issue = f"  ✗ {len(people_without_geo)} people have no geographical unit"
            logger.warning(issue)
            issues.append(issue)
        else:
            logger.info("  ✓ All people have geographical units")

    # Check 2: All venues have geographical units
    logger.info("")
    logger.info("Check 2: All venues have geographical units...")
    if world.venues:
        venues_without_geo = [v for v in world.venues.get_all_venues_list() if v.geographical_unit is None]
        if venues_without_geo:
            issue = f"  ✗ {len(venues_without_geo)} venues have no geographical unit"
            logger.warning(issue)
            issues.append(issue)
        else:
            logger.info("  ✓ All venues have geographical units")

    # Check 3: Person IDs are unique
    logger.info("")
    logger.info("Check 3: Person IDs are unique...")
    if world.population:
        person_ids = [p.id for p in world.population.people]
        unique_ids = set(person_ids)
        if len(person_ids) != len(unique_ids):
            issue = f"  ✗ Duplicate person IDs found: {len(person_ids)} total, {len(unique_ids)} unique"
            logger.warning(issue)
            issues.append(issue)
        else:
            logger.info(f"  ✓ All {len(person_ids):,} person IDs are unique")

    # Check 4: Venue names are unique
    logger.info("")
    logger.info("Check 4: Venue names are unique...")
    if world.venues:
        venue_names = [v.name for v in world.venues.get_all_venues_list()]
        unique_names = set(venue_names)
        if len(venue_names) != len(unique_names):
            issue = f"  ✗ Duplicate venue names found: {len(venue_names)} total, {len(unique_names)} unique"
            logger.warning(issue)
            issues.append(issue)
        else:
            logger.info(f"  ✓ All {len(venue_names)} venue names are unique")

    # Check 5: Activity maps are consistent
    logger.info("")
    logger.info("Check 5: Activity maps have valid structure...")
    if world.population:
        invalid_activity_maps = 0
        for person in world.population.people[:100]:  # Sample first 100
            for activity_name, activity_content in person.activity_map.items():
                if not isinstance(activity_content, dict):
                    invalid_activity_maps += 1
                    break

        if invalid_activity_maps > 0:
            issue = f"  ✗ {invalid_activity_maps} people have invalid activity_map structure (sample of 100)"
            logger.warning(issue)
            issues.append(issue)
        else:
            logger.info("  ✓ Activity maps have valid structure (sample of 100)")

    # Summary
    logger.info("")
    logger.info("=" * 80)
    if issues:
        logger.warning(f"⚠ Found {len(issues)} integrity issues")
        return False, issues
    else:
        logger.info("✓ All integrity checks passed")
        return True, []


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test loading a World object from HDF5 file"
    )
    parser.add_argument(
        "hdf5_file",
        type=str,
        help="Path to HDF5 file to load"
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip printing world summary"
    )
    parser.add_argument(
        "--no-integrity-check",
        action="store_true",
        help="Skip data integrity checks"
    )
    args = parser.parse_args()

    try:
        # Test loading
        success, world, error_msg = test_load_world(args.hdf5_file)

        if not success:
            logger.error("")
            logger.error("=" * 80)
            logger.error("✗✗✗ LOAD TEST FAILED ✗✗✗")
            logger.error(f"Error: {error_msg}")
            logger.error("=" * 80)
            sys.exit(1)

        # Print summary if requested
        if not args.no_summary:
            print_world_summary(world)

        # Verify integrity if requested
        integrity_ok = True
        if not args.no_integrity_check:
            integrity_ok, issues = verify_data_integrity(world)

        # Final result
        logger.info("")
        logger.info("=" * 80)
        if integrity_ok:
            logger.info("✓✓✓ LOAD TEST PASSED ✓✓✓")
            logger.info("World loaded successfully with no integrity issues!")
        else:
            logger.warning("⚠⚠⚠ LOAD TEST PASSED WITH WARNINGS ⚠⚠⚠")
            logger.warning("World loaded but integrity checks found issues (see above)")
        logger.info("=" * 80)

        sys.exit(0)

    except Exception as e:
        logger.error("")
        logger.error("=" * 80)
        logger.error("✗✗✗ TEST FAILED WITH EXCEPTION ✗✗✗")
        logger.error(f"Error: {e}")
        logger.exception(e)
        logger.error("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
