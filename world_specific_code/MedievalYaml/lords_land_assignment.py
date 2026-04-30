import logging

logger = logging.getLogger("lords_land")


def assign_lords_land_venues(world, population_threshold=1000, min_age=13):
    """
    Create one lords_land venue per small geo_unit and assign lords_land_work
    activity to all residents aged > 12.

    Args:
        world: World object
        population_threshold: Only create venue for geo_units with fewer people than this
        min_age: Minimum age (inclusive) to assign the activity (13 = strictly over 12)
    """
    smallest_level = world.geography.levels[0]
    geo_units = world.geography.get_units_by_level(smallest_level).values()

    venues_created = 0
    people_assigned = 0

    for geo_unit in geo_units:
        people = list(geo_unit.get_people())
        if len(people) >= population_threshold:
            continue

        venue = world.venues.create_venue(
            venue_type="lords_land",
            geo_unit=geo_unit,
        )
        venues_created += 1

        for person in people:
            if person.age >= min_age:
                venue.add_to_subset(
                    person,
                    subset_key="worker",
                    activity_name="lords_land_work",
                )
                people_assigned += 1

    logger.info(f"lords_land: created {venues_created} venues, assigned {people_assigned} people")
