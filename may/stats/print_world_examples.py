import logging
import random

from .stats_venues import StatMakerVenues

logger = logging.getLogger(__name__)


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

    logger.info("")
    logger.info("1. Geographical Hierarchy:")
    all_units = geo.get_all_units_list()
    if all_units:
        sgu_units = [u for u in all_units if u.level == geo.levels[0]]
        if sgu_units:
            example_sgu = sgu_units[0]
            logger.info(f"   SGU Example: {example_sgu}")
            logger.info(f"   - Coordinates: {example_sgu.coordinates}")
            if example_sgu.parent:
                logger.info(f"   - Parent MGU: {example_sgu.parent.name}")
                if example_sgu.parent.parent:
                    logger.info(f"   - Parent LGU: {example_sgu.parent.parent.name}")

        mgu_with_venues = [
            u for u in all_units if u.level == geo.levels[1] and len(u.venues) > 0
        ]
        if mgu_with_venues:
            example_mgu = mgu_with_venues[0]
            logger.info("")
            logger.info(f"   MGU Example: {example_mgu}")
            logger.info(f"   - Has {len(example_mgu.children)} SGU children")
            logger.info(f"   - Has {len(example_mgu.venues)} venues")

    logger.info("")
    logger.info("2. Venue Examples:")
    try:
        venue_types = venues.get_venue_types()
        for vtype in sorted(venue_types):  # Show all types
            venues_of_type = venues.get_venues_by_type(vtype)
            if venues_of_type:
                example_venue = random.choice(venues_of_type)
                logger.info(f"   {vtype.capitalize()}: {example_venue.name}")
                logger.info(
                    f"   - Located in: {example_venue.geographical_unit.name} ({example_venue.geographical_unit.level})"
                )
                if example_venue.coordinates:
                    logger.info(f"   - Coordinates: {example_venue.coordinates}")
                if example_venue.properties:
                    props = list(example_venue.properties.items())
                    for key, value in props:
                        logger.info(f"   - {key}: {value}")
                if example_venue.subsets:
                    for key, value in example_venue.subsets.items():
                        logger.info(
                            f"   - Number of assigned {key} =  {value.num_members}"
                        )
    except Exception:
        logger.info("Failed: Could not print venue examples")

    logger.info("")
    logger.info("3. Population Examples:")
    try:
        stats = population.get_statistics()
        if stats:
            logger.info(f"   Total population: {stats['total_population']:,}")
            logger.info(f"   Mean age: {stats['mean_age']:.1f} years")
            logger.info(f"   Median age: {stats['median_age']:.1f} years")
            logger.info(f"   Sex distribution:")
            for sex, count in stats["sex_distribution"].items():
                pct = 100 * count / stats["total_population"]
                logger.info(f"     - {sex}: {count:,} ({pct:.1f}%)")
            logger.info(f"   Activity distribution:")
            for activity, count in sorted(stats["activity_counts"].items()):
                logger.info(f"     - {activity}: {count:,}")

            logger.info("")
            logger.info("   Example people:")
            for person in random.choices(population.get_all_people(), k=5):
                logger.info(f"   {person}")
                logger.info(f"    - Activities: {', '.join(person.activities)}")
                logger.info(f"    - Activity map:")
                for activity, place in person.activity_map.items():
                    logger.info(f"        ~ {activity} : {place} ")
                logger.info(f"    - Properties:")
                for prop, propy in person.properties.items():
                    logger.info(f"        ~ {prop} : {propy} ")
    except Exception:
        logger.info("Failed: Could not print population statistics")

    logger.info("")
    logger.info("4. Household Examples:")
    try:
        venue_stats = StatMakerVenues(venues)
        venue_stats.print_lots_of_stats("household")
        venue_stats.print_examples("household")
        venue_stats.print_extremes("household")

        number_of_empty_houses = 0
        for v in venues.get_venues_by_type("household"):
            if v.num_members == 0:
                number_of_empty_houses += 1
        logger.info(
            f"Number of empty houses = {number_of_empty_houses} out of {len(venues.get_venues_by_type('household'))}"
        )

    except Exception:
        logger.info("Failed: could not print household examples")

    try:
        logger.info("")
        logger.info("5. Query Examples:")
        for key in venues.get_venue_types():
            logger.info("")
            logger.info("   # Get all {}s".format(key))
            all_venues = venues.get_venues_by_type(key)
            logger.info(
                f"   venues.get_venues_by_type({key}) -> {len(all_venues)} {key}s"
            )

        logger.info("")
        logger.info("   # Get venues in a specific area")
        mgu_with_venues = [
            u for u in all_units if u.level == geo.levels[1] and len(u.venues) > 0
        ]
        if mgu_with_venues:
            unit_venues = mgu_with_venues[0].venues
            logger.info(
                f"   geo.get_unit('{mgu_with_venues[0].name}').venues -> {len(unit_venues)} venues"
            )
            if unit_venues:
                logger.info(
                    f"      e.g., {unit_venues[0].name} ({unit_venues[0].type})"
                )

        logger.info("")
        logger.info("   # Get people by activity")
        workers = population.get_people_by_activity("work")
        logger.info(
            f"   population.get_people_by_activity('work') -> {len(workers)} people"
        )

        logger.info("")
        logger.info("   # Get people by housed or not")
        n = 0
        for p in population.get_people_by_activity("home"):
            if p.activity_map["home"]:
                n += 1
        logger.info(
            f"   population.get_people_by_activity('home') -> {n} people out of {len(population)} with 'home' activity set"
        )
    except Exception:
        logger.info("Failed: Could not do query examples")

    logger.info("")
    logger.info("=" * 60)
