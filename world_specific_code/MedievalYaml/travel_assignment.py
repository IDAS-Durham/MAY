import json
import pandas as pd
import logging
from collections import defaultdict


import numpy as np

logger = logging.getLogger("travel_assignment")


def assign_guest_houses(world, large_geo_units_csv_path):
    """
    Randomly designates households as guest houses in specified geo_units.

    For each geo_unit listed in the CSV, randomly selects Num_guest_houses
    households and sets venue.properties['guest_house'] = True on each.
    """
    large_geo_units_df = pd.read_csv(large_geo_units_csv_path)

    total_assigned = 0
    for _, row in large_geo_units_df.iterrows():
        geo_unit_code = row['MBD_Temp_ID']
        num_guest_houses = round(row['Num_guest_houses'])

        geo_unit = world.geography.get_unit(geo_unit_code)
        if geo_unit is None:
            logger.warning(f"Geo unit {geo_unit_code} not found in world, skipping.")
            continue

        household_venues = geo_unit.get_venues_by_type('household')
        if not household_venues:
            logger.warning(f"No households found in geo unit {geo_unit_code}.")
            continue

        num_to_select = min(num_guest_houses, len(household_venues))
        selected_indices = np.random.choice(len(household_venues), size=num_to_select, replace=False)
        for index in selected_indices:
            household_venues[index].properties['guest_house'] = True

        total_assigned += num_to_select

    logger.info(f"Assigned guest_house property to {total_assigned} households across {len(large_geo_units_df)} geo units.")


def assign_travel_activities(
    world,
    paths_names_json_path: str,
    travel_fraction: float,
    min_age: int = 18,
    max_age: int = 70,
) -> None:
    """
    Assigns multi-stop travel itineraries to a random fraction of eligible residents.

    For each geo_unit that appears as the first entry of any path in paths_names_json,
    randomly selects travel_fraction of residents aged [min_age, max_age] and assigns
    them a randomly chosen path from that geo_unit's available paths. Each stop along
    the path (excluding the departure geo_unit) produces a 'travel_day_N_stay' entry
    in the person's activity_map, pointing to a guest_house (or fallback household) in
    that stop's geo_unit. Successful travellers are marked with
    person.properties['traveller'] = True.

    Args:
        world: World object containing geography, population, and venues.
        paths_names_json_path: Path to paths_names.json (list of geo_unit code lists).
        travel_fraction: Fraction of eligible residents in each source geo_unit to assign.
        min_age: Minimum age (inclusive) for travel eligibility.
        max_age: Maximum age (inclusive) for travel eligibility.
    """
    with open(paths_names_json_path, "r") as file_handle:
        all_paths = json.load(file_handle)

    paths_by_source = defaultdict(list)
    for path in all_paths:
        if len(path) >= 2:
            paths_by_source[path[0]].append(path)

    total_travellers = 0
    total_skipped = 0

    for source_code, available_paths in paths_by_source.items():
        source_geo_unit = world.geography.get_unit(source_code)
        if source_geo_unit is None:
            logger.debug(f"Source geo_unit {source_code} not in loaded geography, skipping.")
            continue

        eligible_residents = [
            person
            for household_venue in source_geo_unit.get_venues_by_type('household')
            for subset in household_venue.subsets.values()
            for person in subset.members
            if min_age <= person.age <= max_age
        ]

        if not eligible_residents:
            continue

        num_to_select = min(max(1, round(travel_fraction * len(eligible_residents))), len(eligible_residents))
        selected_indices = np.random.choice(len(eligible_residents), size=num_to_select, replace=False)
        selected_people = [eligible_residents[i] for i in selected_indices]

        for person in selected_people:
            assigned_path = available_paths[np.random.randint(len(available_paths))]
            stops = assigned_path[1:]  # exclude departure geo_unit

            all_stops_succeeded = True
            for day_number, stop_code in enumerate(stops, start=1):
                stop_geo_unit = world.geography.get_unit(stop_code)
                if stop_geo_unit is None:
                    logger.warning(
                        f"Stop geo_unit {stop_code} not found on path from {source_code}; "
                        f"skipping traveller."
                    )
                    all_stops_succeeded = False
                    break

                guest_house_venues = [
                    venue for venue in stop_geo_unit.get_venues_by_type('household')
                    if venue.properties.get('guest_house')
                ]

                if not guest_house_venues:
                    fallback_venues = stop_geo_unit.get_venues_by_type('household')
                    if not fallback_venues:
                        logger.warning(
                            f"No households in stop geo_unit {stop_code} on path from {source_code}; "
                            f"skipping traveller."
                        )
                        all_stops_succeeded = False
                        break
                    chosen_venue = fallback_venues[np.random.randint(len(fallback_venues))]
                else:
                    chosen_venue = guest_house_venues[np.random.randint(len(guest_house_venues))]

                chosen_venue.add_to_subset(
                    person,
                    subset_key='guest',
                    activity_name=f'travel_day_{day_number}_stay',
                    activity_type='guest_house',
                )

            if all_stops_succeeded:
                person.properties['traveller'] = True
                person.properties['num_travel_days'] = len(stops)
                total_travellers += 1
            else:
                total_skipped += 1

    logger.info(
        f"Travel assignment complete: {total_travellers} travellers assigned, "
        f"{total_skipped} skipped due to missing geo_units or households."
    )


def assign_sailing_activities(
    world,
    paths_names_ports_json_path: str,
    port_manor_map_csv_path: str,
    sailing_fraction: float = 0.05,
    min_age: int = 18,
    max_age: int = 70,
) -> None:
    """
    Assigns sea-route itineraries to a fraction of eligible port residents.

    For each geo_unit in port_manor_map_csv that also appears as a source node
    in paths_names_ports_json, randomly selects sailing_fraction of residents
    aged [min_age, max_age] who are not already travellers. Each selected person
    is assigned a random sea route; each intermediate port stop produces a
    'sailing_day_N_stay' entry in their activity_map pointing to a guest_house
    (or fallback household) in that stop's geo_unit. Successful sailors are
    marked person.properties['sailor'] = True.

    Args:
        world: World object containing geography, population, and venues.
        paths_names_ports_json_path: Path to paths_names_ports.json (list of port geo_unit code lists).
        port_manor_map_csv_path: Path to port_manor_map.csv (Name, MBD_Temp_ID columns).
        sailing_fraction: Fraction of eligible residents in each port geo_unit to assign as sailors.
        min_age: Minimum age (inclusive) for sailing eligibility.
        max_age: Maximum age (inclusive) for sailing eligibility.
    """
    with open(paths_names_ports_json_path, "r") as file_handle:
        all_sea_paths = json.load(file_handle)

    port_geo_unit_codes = set(
        pd.read_csv(port_manor_map_csv_path)['MBD_Temp_ID'].tolist()
    )

    paths_by_source = defaultdict(list)
    for path in all_sea_paths:
        if len(path) >= 2 and path[0] in port_geo_unit_codes:
            paths_by_source[path[0]].append(path)

    total_sailors = 0
    total_skipped = 0

    for source_code, available_paths in paths_by_source.items():
        source_geo_unit = world.geography.get_unit(source_code)
        if source_geo_unit is None:
            logger.debug(f"Port geo_unit {source_code} not in loaded geography, skipping.")
            continue

        eligible_residents = [
            person
            for household_venue in source_geo_unit.get_venues_by_type('household')
            for subset in household_venue.subsets.values()
            for person in subset.members
            if min_age <= person.age <= max_age
            and not person.properties.get('traveller')
        ]

        if not eligible_residents:
            continue

        num_to_select = min(max(1, round(sailing_fraction * len(eligible_residents))), len(eligible_residents))
        selected_indices = np.random.choice(len(eligible_residents), size=num_to_select, replace=False)
        selected_people = [eligible_residents[i] for i in selected_indices]

        for person in selected_people:
            assigned_path = available_paths[np.random.randint(len(available_paths))]
            stops = assigned_path[1:]  # exclude departure port

            all_stops_succeeded = True
            for day_number, stop_code in enumerate(stops, start=1):
                stop_geo_unit = world.geography.get_unit(stop_code)
                if stop_geo_unit is None:
                    logger.warning(
                        f"Stop geo_unit {stop_code} not found on sea path from {source_code}; "
                        f"skipping sailor."
                    )
                    all_stops_succeeded = False
                    break

                guest_house_venues = [
                    venue for venue in stop_geo_unit.get_venues_by_type('household')
                    if venue.properties.get('guest_house')
                ]

                if not guest_house_venues:
                    fallback_venues = stop_geo_unit.get_venues_by_type('household')
                    if not fallback_venues:
                        logger.warning(
                            f"No households in stop geo_unit {stop_code} on sea path from {source_code}; "
                            f"skipping sailor."
                        )
                        all_stops_succeeded = False
                        break
                    chosen_venue = fallback_venues[np.random.randint(len(fallback_venues))]
                else:
                    chosen_venue = guest_house_venues[np.random.randint(len(guest_house_venues))]

                chosen_venue.add_to_subset(
                    person,
                    subset_key='guest',
                    activity_name=f'sailing_day_{day_number}_stay',
                    activity_type='guest_house',
                )

            if all_stops_succeeded:
                person.properties['sailor'] = True
                person.properties['num_sailing_days'] = len(stops)
                total_sailors += 1
            else:
                total_skipped += 1

    logger.info(
        f"Sailing assignment complete: {total_sailors} sailors assigned, "
        f"{total_skipped} skipped due to missing geo_units or households."
    )
