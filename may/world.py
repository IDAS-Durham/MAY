"""
World module for June Zero.

The World class is the main container for geography and population.
This module also contains setup functions for orchestrating world creation.
"""

import logging
from may.residence.household_distributor import HouseholdDistributor
from may.residence.allocation_strategy import execute_allocation_strategy

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

    def get_households(self):
        """Get all household venues from VenueManager."""
        if self.venues:
            return self.venues.get_venues_by_type("household")
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


def setup_households(geo, population, venues, config):
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
        data_dir=household_config.get("data_dir", "data/households"),
        config_file=household_config.get("config_file", "households_config.yaml")
    )

    # Load household data
    household_data_file = household_config.get("data_file", "households.csv")
    household_distributor.load_household_data(household_data_file)

    # Distribute households and venues based on configuration mode
    strategy_file = household_config.get("strategy_file")

    if strategy_file:
        # Mode 1: Unified strategy (households + venues in order)
        logger.info(f"Using unified allocation strategy from {strategy_file}")
        execute_allocation_strategy(population, venues, household_distributor, strategy_file)

    # Export household allocations
    #export_file = household_config.get("export_file", "household_allocations.csv")
    #household_distributor.export_households_to_csv(export_file)

    # Export venue allocations
    venue_export_file = config.get("venues", {}).get("export_file", "venue_allocations.csv")
    venues.export_venues_to_csv(venue_export_file)

    return household_distributor
