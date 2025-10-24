import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from may.distributor import Distributor
from may.distributor import DistributorMultiPass
from may.distributor import SubsetDistributor
from may.population import Subset
from .care_home_subset_distributor import CareHomeSubsetDistributor

logger = logging.getLogger(__name__)


class CareHomeDistributor(DistributorMultiPass):
    """Class to distributor a list of people across instances of a Venue class with type 'mass housing'

    This is the child class to Distributor. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attempt to sort venues within VenueManager (yet).
    
    """
    def _assign_subsets(self):
        """Called at the end of __init__ """
        example_venue = self.venue_manager.venues_by_type[self.venue_type][0]
        self.subset_distributor = CareHomeSubsetDistributor(
            self.venue_type,
            [
                'age_50_64_female',
                'age_50_64_male',
                'age_65_74_female',
                'age_65_74_male',
                'age_75_84_female',
                'age_75_84_male',
                'age_85_94_female',
                'age_85_94_male',
                'age_95_plus_female',
                'age_95_plus_male',
                'number_staff',
            ],
        )
        self._venue_has_membership_capacity_by_subset = defaultdict(
            lambda: [True]*self.subset_distributor.n_subsets
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
        subset = args[0]

        for i, subset_name in enumerate(self.age_category):
            if venue.subsets[subset_name].num_members >= venue.properties[subset_name]:
                self._venue_has_membership_capacity_by_subset[venue.id][i] = False
        if not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            self._venue_closed_reason[venue.id] = 'composition'
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)

        # # ========================================
        # # PART 1: Set capacity based on composition
        # # ========================================
        # match composition:
        #     case '0 0 0 2':
        #         if venue.subsets[''].num_members >= 2:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
        #             composition_full = True
        #         else:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]

        #     case '0 0 2 0':
        #         if venue.subsets['adults'].num_members >= 2:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
        #             composition_full = True
        #         else:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]

        #     case '0 0 0 1':
        #         if venue.subsets['elderly'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
        #             composition_full = True
        #         else:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]

        #     case '0 0 1 0':
        #         if venue.subsets['adults'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
        #             composition_full = True
        #         else:
        #             self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]

        #     case '0 >=1 2 0':
        #         if venue.subsets['adults'].num_members >= 2:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # Check if composition constraints fully met (adults full)
        #         # if venue.subsets['adults'].num_members >= 2:
        #         #     composition_full = True

        #     case '1 >=0 2 0':
        #         if venue.subsets['adults'].num_members >= 2:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         if venue.subsets['kids'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         
        #         # if venue.subsets['adults'].num_members >= 2 and venue.subsets['kids'].num_members >= 1:
        #         #     composition_full = True

        #     case '>=2 >=0 2 0':
        #         if venue.subsets['kids'].num_members >= 3 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False                
        #         if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         if venue.subsets['adults'].num_members >= 2:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # if venue.subsets['adults'].num_members >= 2 and venue.subsets['kids'].num_members >= 2:
        #         #     composition_full = True

        #     case '0 >=1 1 0':
        #         if venue.subsets['adults'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         if venue.subsets['independent children'].num_members >= 2 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # if venue.subsets['adults'].num_members >= 1:
        #         #     composition_full = True

        #     case '1 >=0 1 0':
        #         if venue.subsets['adults'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         if venue.subsets['independent children'].num_members >= 2 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         if venue.subsets['kids'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # if venue.subsets['adults'].num_members >= 1 and venue.subsets['kids'].num_members >= 1:
        #         #     composition_full = True

        #     case '>=2 >=0 1 0':
        #         if venue.subsets['kids'].num_members >= 3 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False                
        #         if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
        #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         if venue.subsets['adults'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # if venue.subsets['adults'].num_members >= 1 and venue.subsets['kids'].num_members >= 2:
        #         #     composition_full = True

        #     case '1 >=0 >=0 >=0':
        #         if venue.subsets['kids'].num_members >= 1:
        #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False

        #     case '>=2 >=0 >=0 >=0':
        #         pass
        #         # if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):
        #         #     self._venue_has_membership_capacity_by_subset[venue.id][0] = False

        #     case '0 >=0 0 0':
        #         self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][3] = False
        #         # Never fully constrained by composition (>=0 means no limit)

        #     case '0 >=0 >=0 >=0':
        #         self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         # if venue.num_members >= 1 and bool(random.getrandbits(1)):
        #         #     self._venue_has_membership_capacity_by_subset[venue.id][random.choice([1,2,3])] = False
        #         # Never fully constrained by composition

        #     case '0 0 0 >=3':
        #         self._venue_has_membership_capacity_by_subset[venue.id][0] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][1] = False
        #         self._venue_has_membership_capacity_by_subset[venue.id][2] = False
        #         # Never fully constrained (>=3 means no limit)

        #     case _:
        #         raise KeyError(f"Composition '{composition}' not found")
        


