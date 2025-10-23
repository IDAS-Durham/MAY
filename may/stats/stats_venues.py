import numpy as np
from scipy import stats
import logging
import random

from .statmaker import StatMaker

logger = logging.getLogger("statsvenues")

class StatMakerVenues(StatMaker):
    """Class to collect and print some stuff about venues. 

    """
    def __init__(self, venue_manager: "VenueManager"):
        super().__init__()
        self.venue_manager = venue_manager
        
    def get_num_members(self,venue):
        total = 0
        for s in venue.subsets.values():
            total += s.num_members
        return total
        
    def get_membership_statistics(self,venue_type: str, stats_label: str=None):
        stat_id = self._generate_stat_id()
        if stats_label is None:
            stats_label = str(stat_id)
        my_venues = self.venue_manager.get_venues_by_type(venue_type)
        my_data = [self.get_num_members(venue) for venue in my_venues]
        my_stats = self.collect_statistics(my_data)
        self.stats[stats_label] = (stat_id, stats_label, my_stats)
        return (stat_id, stats_label, my_stats)

    def print_venue_comp(self, example_venue):
        logger.info("    Venue: {} , {}".format(example_venue.id, example_venue.name))
        if example_venue.properties:
            props = list(example_venue.properties.items())
            for key, value in props:
                logger.info(f"      - {key}: {value}")
        for key, subset in example_venue.subsets.items():
            logger.info("      - subset id({}), {} :  {}".format(id(subset), key, subset.num_members))

    
    def get_example_membership(self, venue_type: str, n_examples=3, stats_label: str=None):
        my_venues = self.venue_manager.get_venues_by_type(venue_type)
        for i in range(n_examples):
            example_venue = random.choice(my_venues)
            self.print_venue_comp(example_venue)
    
    def get_extreme_membership(self, venue_type: str, stats_label: str=None):
        my_venues = self.venue_manager.get_venues_by_type(venue_type)
        num_subsets = len(my_venues[0].subsets)
        subset_numbers = np.zeros((len(my_venues), num_subsets))
        for i,v in enumerate(my_venues):
            for j,s in enumerate(v.subsets.values()):
                subset_numbers[i,j] = s.num_members
        extreme_max_subset_numbers = np.argmax(subset_numbers, axis=0)
        extreme_min_subset_numbers = np.argmin(subset_numbers, axis=0)
        extreme_max_total = np.argmax(np.sum(subset_numbers, axis=1))
        extreme_min_total = np.argmin(np.sum(subset_numbers, axis=1))
        for vindex in extreme_max_subset_numbers:
            logger.info("Venue with extreme max in specific subsets membership:")
            self.print_venue_comp(my_venues[vindex])
        # for vindex in extreme_min_subset_numbers:
        #     logger.info("Venue with extreme min in specific subsets membership:")
        #     self.print_venue_comp(my_venues[vindex])
        logger.info("    Venue with extreme max in total members:")
        self.print_venue_comp(my_venues[extreme_max_total])
        logger.info("    Venue with extreme min in total members:")
        self.print_venue_comp(my_venues[extreme_min_total])                        
            
    def print_lots_of_stats(self, venue_type):
        stat_id, stats_label, my_stats = self.get_membership_statistics(venue_type)
        logger.info("")
        logger.info(f"Statistics on total membership for {venue_type}\n")
        for key, value in my_stats.items():
            logger.info(f"  {key}  =  {value}")

    def print_examples(self, venue_type):
        logger.info(f"Example {venue_type} types:")            
        self.get_example_membership(venue_type)
        
    def print_extremes(self, venue_type):
        logger.info(f"Extreme {venue_type} types:")
        self.get_extreme_membership(venue_type)

