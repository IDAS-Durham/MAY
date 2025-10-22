import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from may.distributor import Distributor
from may.distributor import SubsetDistributor
from may.population import Subset
from may.specific_distributors.household_subset_distributor import HouseholdSubsetDistributor

logger = logging.getLogger(__name__)


class HouseholdDistributor(Distributor):
    """Class to distributor a list of people across instances of a Venue class with a particular type.

    This is the parent class to specific classes for distributing people across households, schools, etc. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attempt to sort venues within VenueManager (yet). 
    """

    # def distribute(self):
    #     first_run_available_venues = 
    
    def _get_subset_dist(self):
        example_venue           = self.venue_manager.venues_by_type[self.venue_type][0]
        self.subset_distributor = HouseholdSubsetDistributor(self.venue_type, ['kids','independent children','adults','elderly'])
        self._venue_has_membership_capacity_by_subset = defaultdict(lambda: [True]*self.subset_distributor.n_subsets)
    
    def _update_venue_membership_capacity(self, trial_venue_index, venue, subset, **kwargs):
        """ Called after a person is successfully assigned a subset, or once at the beginning. 
        
        subsets = ['kids', 'independent children', 'adults', elderly']
        
        """
        match venue.properties['composition'].strip():
            case '0 0 0 2':
                if len(subset.members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False]*self.subset_distributor.n_subsets
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]
                    
            case '0 0 2 0':
                if len(subset.members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False]*self.subset_distributor.n_subsets
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]
                
            case '0 0 0 1':
                if len(subset.members) >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False]*self.subset_distributor.n_subsets
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]
                
            case '0 0 1 0':
                if len(subset.members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False]*self.subset_distributor.n_subsets
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]
                
            case '0 >=1 2 0':
                if len(venue.subsets['adults'].members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False                
                
            case '1 >=0 2 0':
                if len(venue.subsets['adults'].members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 0 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if len(venue.subsets['kids']) >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                
            case '>=2 >=0 2 0':
                if len(venue.subsets['adults'].members) >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 0 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if len(venue.subsets['kids']) >= 2 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '0 >=1 1 0':
                if len(venue.subsets['adults'].members) >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '1 >=0 1 0':
                if len(venue.subsets['adults'].members) >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 0 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if len(venue.subsets['kids']) >= 1:                    
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                
            case '>=2 >=0 1 0':
                if len(venue.subsets['adults'].members) >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if len(venue.subsets['independent children']) >= 0 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if len(venue.subsets['kids']) >= 2 and bool(random.getrandbits(1)):                    
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '1 >=0 >=0 >=0':
                if len(venue.subsets['kids']) >= 1:                    
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                    
            case '>=2 >=0 >=0 >=0':
                if len(venue.subsets['kids']) >= 2 and bool(random.getrandbits(1)):                 
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False

            case '0 >=0 0 0':
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '0 >=0 >=0 >=0':                
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False

            case '0 0 0 >=3':
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][2] = False

            case _:
                raise KeyError("Column title {} is not found within the list of programmed household types. See household_distributor.py".format(venue.properties['composition'].strip()))

        # Removes the venue from the list of potential venues if it has no membership capacity. 
        if not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            self.available_venue_indices.remove(trial_venue_index)
        
        
    
        

    
