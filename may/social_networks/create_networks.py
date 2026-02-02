"""
File with functions designed to build networks of contacts (usually social contacts, but could be any form of contact).
"""

import logging
from typing import TYPE_CHECKING

from .graph_relationship_builder import GraphRelationshipBuilder
from .geo_neighbors import find_neighbours
from may.serialization.export_properties import export_relationships

if TYPE_CHECKING:
    from may.geography import Geography, GeographicalUnit
    from may.world import World

logger = logging.getLogger("create networks")


def _collate_people_in_geo_units(geography: "Geography", geo_unit_ids: set["GeographicalUnit"]):
    """
    Collect all people from a set of geographical units.

    Args:
        geography (Geography): Geography object containing the geographical hierarchy.
        geo_unit_ids (set[str]): Set of geographical unit IDs to collect people from.

    Returns:
        set[Person]: Set of Person objects from all specified geographical units.
    """
    people = set()
    for geo_unit_id in geo_unit_ids:
        geo_unit = geography.get_units_by_id.get(geo_unit_id)
        people.update(geo_unit.get_people())
    return people


def build_local_social_network(
        world: "World",
        mean_connections_per_person: float = 6,
        clustering_level: float = 0.8,
        storage_key: str = f"social_contacts_local",
        store: bool = True,
        export:bool = False,
) -> None:
    """
    Build a social network using a clustered graph.

    Creates social contact networks within each smallest geographical unit (SGU).
    Each person in an SGU is connected to others in the same SGU based on the
    specified clustering parameters.

    Args:
        world (World): World object containing geography and population.
        mean_connections_per_person (float): Average number of social connections per person.
        clustering_level (float): Clustering coefficient from 0.0 (random) to 1.0 (high clustering).
        storage_key (str): Key used to store connections in person.properties.
        store (bool): If True, store relationships in person.properties[storage_key].
        export (bool): If True, export relationships to CSV file.

    Returns:
        None: Relationships are stored in person.properties[storage_key].

    Example:
        >>> from may.world import World
        >>> world = World(geography, population)
        >>> build_local_social_network(world, mean_connections_per_person=6, clustering_level=0.8)
        >>> # Access contacts for a person
        >>> contacts = world.population.people[0].properties['social_contacts_local']
    """
    geography = world.geography

    # Go through all geo units
    geo_units = geography.get_units_by_level(geography.levels[0])
    for geo_unit in geo_units.values():
        people = geo_unit.people
        logger.debug(f"Geo unit name - {geo_unit.name}, with {len(people)} people")
        
        relationships = GraphRelationshipBuilder.build_graph_relationships(
            people,
            mean_connections_per_person=mean_connections_per_person,
            clustering_level=clustering_level,
            storage_key=storage_key,
            store=store
        )

    if export:
        # Export relationships to CSV
        #storage_key = builder.config.get('storage', {}).get('key', builder.name)
        export_relationships(world, 'social_contacts_local', f"social_contacts_local.csv")


def build_bounded_distance_social_network(
        geography: "Geography",
        radius_km: float,
        mean_connections_per_person: float,
        geo_unit_level: str = None,
        clustering_level: float=0.8,
        storage_key: str=None,
        store: bool=True,
        method: str='libpysal',
) -> None:
    """
    Build a network of contacts between people in geo_units within a specified radius.

    For each geo_unit in the given geography, creates a network between its people and
    the people in all other geo_units within the specified radius (km). Contacts are then
    assigned based on this network of people, stored under person.properties[storage_key].

    Args:
        geography (Geography): Geography object containing the geographical hierarchy.
        radius_km (float): Search radius in kilometers for finding neighbouring geo_units.
        mean_connections_per_person (float): Average number of connections per person.
        geo_unit_level (str): Level of geographical units to use. Defaults to smallest level.
        clustering_level (float): Clustering coefficient from 0.0 (random) to 1.0 (high clustering).
        storage_key (str): Key used to store connections in person.properties.
        store (bool): If True, store relationships in person.properties[storage_key].
        method (str): Method for finding neighbours ('libpysal' or 'balltree').

    Returns:
        None: Relationships are stored in person.properties[storage_key].

    Example:
        >>> from may.geography import Geography
        >>> geography = Geography(data_dir="data/geography")
        >>> geography.load_from_csv()
        >>> build_bounded_distance_social_network(
        ...     geography,
        ...     radius_km=10.0,
        ...     mean_connections_per_person=4,
        ...     clustering_level=0.7
        ... )
    """
    if storage_key is None:
        storage_key = f"social_contacts_radius_km_{radius_km}"

    if geo_unit_level is None:
        geo_unit_level = geography.levels[0]

    # Create the geo_units distance network
    geo_units = geography.get_units_by_level(geo_unit_level)

    # Get geo_unit neighbours
    geo_unit_neighbours = find_neighbours(geo_units, radius_km = radius_km)

    # Go through each geographical unit, collect people and make a network. 
    for geo_unit_id, connected_ids in geo_unit_neighbours.items():
        people_in_network = _collate_people_in_geo_units(geography, connected_ids)
        relationships = GraphRelationshipBuilder.build_graph_relationships(
            people_in_network,
            avg_connections=mean_connections_per_person / 2,  # the /2 is because this process will happen twice due to double-counting.
            clustering_level=clustering_level,
            storage_key=storage_key,
            store=store,
        )
