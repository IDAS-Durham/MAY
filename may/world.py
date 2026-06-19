"""
World module for MAY.

The World class is the main container for geography and population.
This module also contains setup functions for orchestrating world creation.
"""

import logging
from typing import Optional, Set
from may.residence.household_distributor import HouseholdDistributor
from may.residence.allocation_strategy import execute_allocation_strategy
from may.utils import path_resolver as pr
from random import sample

logger = logging.getLogger("world")


class World:
    """
    The World object is the main container for a simulation.

    It holds references to the geography structure, population,
    and venues, along with any other world-level data needed for simulation.

    Attributes:
        geography (Geography): The geographical hierarchy
        population (PopulationManager): The population manager
        venues (VenueManager): The venue manager (includes all venues including households)
        household_distributor (HouseholdDistributor): The household distributor for allocation logic
    """

    def __init__(self, geography=None, population=None, venues=None, household_distributor=None):
        """
        Initialize a World object.

        Args:
            geography (Geography): Geography object containing geographical units
            population (PopulationManager): PopulationManager object containing people
            venues (VenueManager): VenueManager object containing all venues (including households)
            household_distributor (HouseholdDistributor): HouseholdDistributor for allocation logic (optional)
        """
        self.geography = geography
        self.population = population
        self.venues = venues
        self.household_distributor = household_distributor

        # Register residence types from venue configuration with Person class
        if venues:
            from may.population.person import Person
            residence_types = venues.get_residence_types()
            Person.register_residence_types(residence_types)
            logger.info(f"Registered {len(residence_types)} residence types: {residence_types}")

    def get_households(self):
        """
        Get household-type residences (backwards compatible).

        Returns:
            List of Venue objects with type='household'
        """
        if self.venues:
            return self.venues.get_venues_by_type("household")
        return []

    def get_all_residences(self):
        """
        Get all residence venues (households, care homes, dorms, etc.).

        Returns:
            List of all residence Venue objects
        """
        if self.venues:
            return self.venues.get_all_residences()
        return []

    def get_residences_by_type(self, residence_type: str):
        """
        Get all residences of a specific type.

        Args:
            residence_type: Type of residence (e.g., 'care_home', 'prison', 'farm')

        Returns:
            List of Venue objects

        Example:
            >>> world.get_residences_by_type('care_home')
            [<Venue #0: care_home_0 (care_home) in E02000173>, ...]
        """
        if self.venues:
            return self.venues.get_venues_by_type(residence_type)
        return []

    def venues_by_type(self, venue_type: str):
        """
        Get all venues of a specific type.

        Args:
            venue_type: Type of venue (e.g., 'school', 'hospital', 'company')

        Returns:
            List of venues of the specified type
        """
        if self.venues:
            return self.venues.get_venues_by_type(venue_type)
        return []

    @property
    def people(self):
        """Convenience property to access all people in the population."""
        if self.population:
            return self.population.get_all_people()
        return []

    def __repr__(self):
        geo_str = f"{len(self.geography.get_all_units())} units" if self.geography else "no geography"
        pop_str = f"{len(self.population.get_all_people()):,} people" if self.population else "no population"

        if self.venues:
            total_venues = len(self.venues.get_all_venues())
            households = self.get_households()
            household_str = f"{len(households)} households"
            other_venues = total_venues - len(households)
            venue_str = f"{total_venues} venues ({household_str}, {other_venues} other)"
        else:
            venue_str = "no venues"

        return f"<World: {geo_str}, {pop_str}, {venue_str}>"

    def get_statistics(self):
        """
        Get comprehensive statistics about the world.

        Returns:
            dict: Dictionary containing geography, population, and venue statistics
        """
        stats = {}

        if self.geography:
            stats['geography'] = {
                'total_units': len(self.geography.get_all_units()),
                'units_by_level': {
                    level: len(self.geography.get_units_by_level(level))
                    for level in self.geography.levels
                }
            }

        if self.population:
            stats['population'] = self.population.get_statistics()

        if self.venues:
            stats['venues'] = {
                'total_venues': len(self.venues.get_all_venues()),
                'venue_types': len(self.venues.get_venue_types())
            }

        if self.household_distributor:
            households = self.get_households()
            total_allocated = len(self.household_distributor.allocated_people)
            total_people = sum(len(pool) for pool in self.household_distributor.person_pool_by_geo_unit.values())
            stats['households'] = {
                'total_households': len(households),
                'people_allocated': total_allocated,
                'people_unallocated': total_people - total_allocated,
                'allocation_rate': total_allocated / max(total_people, 1),
                'average_household_size': sum(h.size() for h in households) / max(len(households), 1)
            }

        return stats

    def assign_attributes(self, config_path: str, geo_units: Optional[Set[str]] = None):
        """
        Assign attributes to all people in the world.

        This method uses the attribute assignment system to assign attributes
        (e.g., ethnicity) to all people based on YAML configuration.

        Args:
            config_path: Path to attribute assignment YAML config file
            geo_units: Optional set of geo unit codes to preload data for

        Returns:
            Dictionary with assignment statistics
        """
        from may.attribute_assignment import assign_attributes

        logger.info("")
        logger.info("="*60)
        logger.info(f"Assigning attributes...")
        logger.info("="*60)

        # Get geo units from geography if not provided
        # Include all hierarchy levels (SGU, MGU, LGU) for efficient filtering across all data sources
        if geo_units is None and self.geography:
            geo_units = set()
            for unit in self.geography.get_all_units_list():
                # Add the unit's name/code
                geo_units.add(unit.name)
                # Also add parent names at all levels for O-D matrix filtering
                current = unit
                while current.parent:
                    geo_units.add(current.parent.name)
                    current = current.parent

        # Run attribute assignment
        stats = assign_attributes(
            venue_manager=self.venues,
            config_path=config_path,
            geo_units=geo_units
        )

        return stats

    def export_to_hdf5(self, output_file, config_file="configs/2021/serialization_config.yaml"):
        """
        Export world state to HDF5 file for C++ simulation.

        This method serializes the complete world state (geography, population,
        venues, and relationships) to an HDF5 file that can be efficiently loaded
        by the C++ simulation engine.

        The serialization configuration (config_file) determines which properties
        and attributes are included in the export.

        Args:
            output_file: Path to output HDF5 file
            config_file: Path to serialization YAML config (default: yaml/serialization_config.yaml)

        Returns:
            dict: Export statistics (num_people, num_venues, etc.)

        Example:
            >>> world.export_to_hdf5("world_state.h5")
            >>> world.export_to_hdf5("output/world.h5", "custom_serialization.yaml")
        """
        from may.serialization import WorldSerializer

        logger.info("")
        logger.info("=" * 60)
        logger.info("EXPORTING WORLD TO HDF5")
        logger.info("=" * 60)

        serializer = WorldSerializer(config_file=pr.resolve(config_file))
        stats = serializer.export(self, output_file)

        logger.info("")
        logger.info(f"Successfully exported world to: {output_file}")
        logger.info("=" * 60)

        return stats


def setup_households(geo, population, venues, config, strategy_file=None):
    """
    Setup and distribute households based on configuration.

    This orchestration function:
    - Creates a HouseholdDistributor
    - Loads household data
    - Executes allocation strategy
    - Exports venue allocations

    Args:
        geo: Geography object
        population: PopulationManager object
        venues: VenueManager object
        config: Configuration dictionary
        strategy_file: Path to the allocation-strategy YAML to execute. This is
            the `config:` of the timeline's `residence_allocation` step — the
            single source of truth for which strategy runs and where it runs in
            the timeline. When ``None`` (e.g. a direct programmatic caller),
            falls back to ``config["households"]["strategy_file"]``.

    Returns:
        HouseholdDistributor object with allocated households
    """
    logger.info("")
    logger.info("Distributing households...")
    household_config = config.get("households", {})

    household_distributor = HouseholdDistributor(
        geography=geo,
        population=population,
        venue_manager=venues,
        data_dir=pr.resolve(household_config.get("data_dir", "data/households")),
        config_file=pr.resolve(household_config.get("config_file", "households_config.yaml")),
        rules_file=pr.resolve(household_config.get("rules_file")) if household_config.get("rules_file") else None,
    )

    # Load household data
    household_data_file = household_config.get("data_file", "households.csv")
    household_distributor.load_household_data(household_data_file)

    # Distribute households and venues based on configuration mode.
    # The strategy file comes from the residence_allocation timeline step;
    # fall back to the households block only for direct programmatic callers.
    if strategy_file is None and household_config.get("strategy_file"):
        strategy_file = pr.resolve(household_config.get("strategy_file"))

    debug_outputs_enabled = config.get("debug_outputs", {}).get("enabled", False)

    if strategy_file:
        # Mode 1: Unified strategy (households + venues in order)
        logger.info(f"Using unified allocation strategy from {strategy_file}")
        execute_allocation_strategy(
            population,
            venues,
            household_distributor,
            strategy_file,
            export_debug_csv=debug_outputs_enabled,
        )

    # Export household + venue allocation CSVs (debug aid; skipped for large worlds
    # because each builds a DataFrame across the whole population/venue set).

    if debug_outputs_enabled:
        export_file = household_config.get("export_file", "household_allocations.csv")
        household_distributor.export_households_to_csv(export_file)

        venue_export_file = config.get("venues", {}).get("export_file", "venue_allocations.csv")
        venues.export_venues_to_csv(venue_export_file)
    else:
        logger.info("Skipping household/venue allocation CSV exports (debug_outputs.enabled=false)")

    # Show where households are located and examples
    logger.info("")
    logger.info("=" * 60)
    logger.info("HOUSEHOLD STORAGE LOCATIONS")
    logger.info("=" * 60)

    # Get all households from VenueManager
    all_households = venues.get_venues_by_type("household")
    logger.info(f"Total households created: {len(all_households):,}")
    logger.info("")

    logger.info("Households are stored in VenueManager:")
    logger.info("  1. venues.get_venues_by_type('household')  -> List of all household Venues")
    logger.info("  2. venues.get_venue_by_type_and_id('household', id)  -> Specific household by ID")
    logger.info("  3. venues.venues['household_0']  -> Specific household by name")
    logger.info("")

    # Show a few example households
    if all_households:
        logger.info("Example Households (5 random):")
        for household in sample(all_households, min(5, len(all_households))):
            age_categories = household.properties.get('_age_categories', [])
            composition = household.get_composition(age_categories)
            members = household.get_all_members()

            logger.info(f"")
            logger.info(f"  Household ID: {household.id} (type-scoped ID)")
            logger.info(f"  Venue ID: {id(household)} (Python object ID)")
            logger.info(f"  Name: {household.name}")
            logger.info(f"  Type: {household.type}")
            logger.info(f"  Location: {household.geographical_unit.name}")
            logger.info(f"  Size: {household.size()} people")
            logger.info(f"  Composition: {composition}")
            if members:
                logger.info(f"  Members: {', '.join([f'Person_{p.id}({p.age}{'m' if p.sex=='male' else 'f'})' for p in members])}")
    logger.info("")
    logger.info("=" * 60)
    logger.info("PEOPLE IN HOUSEHOLDS - How to find where someone lives")
    logger.info("=" * 60)

    # Show how to access people's households
    if household_distributor.allocated_people:
        example_person_ids = sample(list(household_distributor.allocated_people), 5)

        for person_id in example_person_ids:
            person = population.get_person(person_id)
            # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
            if person and "residence" in person.activity_map and "household" in person.activity_map["residence"]:
                household_subsets = person.activity_map["residence"]["household"]
                if household_subsets:
                    household_venue = household_subsets[0].venue
                    age_categories = household_venue.properties.get('_age_categories', [])

                    logger.info(f"")
                    logger.info(f"  Person {person.id} (age={person.age}, sex={person.sex})")
                    logger.info(f"  Activity map: {person.activity_map}")
                    logger.info(f"  Lives in: {household_venue.name} (ID={household_venue.id})")
                    logger.info(f"  Location: {household_venue.geographical_unit.name}")
                    logger.info(f"  Household size: {household_venue.size()}")
                    logger.info(f"  Household composition: {household_venue.get_composition(age_categories)}")

    logger.info("")
    logger.info("=" * 60)

    return household_distributor
