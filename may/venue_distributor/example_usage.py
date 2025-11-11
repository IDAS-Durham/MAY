"""
Example usage of VenueDistributor

This script demonstrates how to use the VenueDistributor system
to allocate people to venues based on YAML configuration.
"""

import logging
from may.venue_distributor import VenueDistributor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def allocate_schools(world):
    """
    Allocate people to schools using the school distributor YAML.

    Args:
        world: World object with geography, population, and venues loaded
    """
    logger.info("=" * 60)
    logger.info("ALLOCATING PEOPLE TO SCHOOLS")
    logger.info("=" * 60)

    # Load distributor from YAML
    distributor = VenueDistributor.from_yaml("yaml/distributors/school_distributor.yaml")

    # Run allocation
    distributor.allocate(world)

    # Check results
    logger.info("\n" + "=" * 60)
    logger.info("ALLOCATION RESULTS")
    logger.info("=" * 60)

    allocated_count = 0
    for person in world.people:
        if 'primary_activity' in person.activity_map:
            allocated_count += 1
            school = person.activity_map['primary_activity']
            if allocated_count <= 10:  # Show first 10 examples
                logger.info(f"  Person {person.id} (age {person.age}) -> {school.name}")

    logger.info(f"\nTotal allocated: {allocated_count}/{len(world.people)}")


def allocate_multiple_venue_types(world):
    """
    Example: Allocate people to multiple venue types in sequence.

    Args:
        world: World object with geography, population, and venues loaded
    """
    # 1. Schools
    logger.info("Step 1: Allocating to schools...")
    school_distributor = VenueDistributor.from_yaml("yaml/distributors/school_distributor.yaml")
    school_distributor.allocate(world)

    # 2. Workplaces (if you create workplace_distributor.yaml)
    # logger.info("\nStep 2: Allocating to workplaces...")
    # work_distributor = VenueDistributor.from_yaml("yaml/distributors/workplace_distributor.yaml")
    # work_distributor.allocate(world)

    # 3. Hospitals
    # logger.info("\nStep 3: Allocating to hospitals...")
    # hospital_distributor = VenueDistributor.from_yaml("yaml/distributors/hospital_distributor.yaml")
    # hospital_distributor.allocate(world)

    logger.info("\nAll venue allocations complete!")


# Example integration into create_world.py:
"""
# In create_world.py, after creating world:

from may.venue_distributor import VenueDistributor

# ... create geography, population, venues ...

# Create world
world = World(geography=geo, population=population, venues=venues)

# Allocate to venues using distributors
logger.info("Allocating people to venues...")

# Schools
school_distributor = VenueDistributor.from_yaml("yaml/distributors/school_distributor.yaml")
school_distributor.allocate(world)

# Add more distributors as needed
# workplace_distributor = VenueDistributor.from_yaml("yaml/distributors/workplace_distributor.yaml")
# workplace_distributor.allocate(world)

logger.info("Venue allocation complete!")

# Save world
world.save("output/world.pkl")
"""
