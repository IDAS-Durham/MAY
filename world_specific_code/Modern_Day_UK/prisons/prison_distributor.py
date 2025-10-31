import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from may.distributor import Distributor
from may.distributor import DistributorMultiPass
from may.distributor import SubsetDistributor
from may.population import Subset
from .prison_subset_distributor import PrisonSubsetDistributor

logger = logging.getLogger(__name__)


class PrisonDistributor(DistributorMultiPass):
    """Class to distributor a list of people across instances of a Venue class with type 'mass housing'

    This is the child class to Distributor. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attempt to sort venues within VenueManager (yet).
    
    """
    
    subset_names=[
        'prisoners',
        'staff',
    ]
    
    def _assign_subsets(self):
        """Called at the end of __init__ """
        self.subset_distributor = PrisonSubsetDistributor(
            self.venue_type,
            PrisonDistributor.subset_names,
        )
        self._venue_has_membership_capacity_by_subset = defaultdict(
            lambda: [True for i in range(self.subset_distributor.n_subsets)]
        )


    def _update_venue_membership_capacity(self, trial_venue_index, venue, *args, **kwargs):
        """Decides if a venue is at capacity for each individual subclass.

        Also tracks why a venue might be at capacity, to enable multi-pass distribution for expandable households. The method looks at the composition. Then, for each composition, it checks the membership size of each subset and decides whether or not there is still capacity. If not, it changes the relevant boolean in `_venue_has_membership_capacity_by_subset` for `venue.id` to False.
        
        Args:
          trial_venue_index (int):
            The index of the venue in the venue_list passed to HouseholdDistributor. This is important for removing venues when they are full.
          venue (Venue):
            Instance of the venue class. Important to get properties (used to decide capacity), and current occupation of the subsets. 

        Raises:
          KeyError: if the composition is not recognized.
        
        """
        if venue.subsets['prisoners'].num_members >= venue.properties['prisoner_capacity']:
            self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        if venue.subsets['staff'].num_members >= venue.properties['staff']:            
            self._venue_has_membership_capacity_by_subset[venue.id][1] = False
            
        if not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            self._venue_closed_reason[venue.id] = 'composition'
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)
