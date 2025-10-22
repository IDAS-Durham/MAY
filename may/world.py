"""
World module for June Zero.

The World class is the main container for geography and population.
"""

import logging

logger = logging.getLogger("world")


class World:
    """
    The World object is the main container for a simulation.

    It holds references to the geography structure, population,
    and venues, along with any other world-level data needed for simulation.

    Attributes:
        geography (Geography): The geographical hierarchy
        population (PopulationManager): The population manager
        venues (VenueManager): The venue manager (optional)
        households (HouseholdDistributor): The household distributor (optional)
    """

    def __init__(self, geography=None, population=None, venues=None, households=None):
        """
        Initialize a World object.

        Args:
            geography (Geography): Geography object containing geographical units
            population (PopulationManager): PopulationManager object containing people
            venues (VenueManager): VenueManager object containing venues (optional)
            households (HouseholdDistributor): HouseholdDistributor with allocated households (optional)
        """
        self.geography = geography
        self.population = population
        self.venues = venues
        self.households = households

    def __repr__(self):
        geo_str = f"{len(self.geography.get_all_units())} units" if self.geography else "no geography"
        pop_str = f"{len(self.population.get_all_people()):,} people" if self.population else "no population"
        venue_str = f"{len(self.venues.get_all_venues())} venues" if self.venues else "no venues"
        household_str = f"{len(self.households.households)} households" if self.households else "no households"
        return f"<World: {geo_str}, {pop_str}, {venue_str}, {household_str}>"

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

        if self.households:
            total_allocated = len(self.households.allocated_people)
            total_people = sum(len(pool) for pool in self.households.person_pool_by_area.values())
            stats['households'] = {
                'total_households': len(self.households.households),
                'people_allocated': total_allocated,
                'people_unallocated': total_people - total_allocated,
                'allocation_rate': total_allocated / max(total_people, 1),
                'average_household_size': sum(h.size() for h in self.households.households) / max(len(self.households.households), 1)
            }

        return stats
