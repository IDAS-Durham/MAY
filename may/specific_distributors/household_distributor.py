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
    def _post_init(self):
        """Initialize subset distributor and set thresholds."""
        example_venue = self.venue_manager.venues_by_type[self.venue_type][0]
        self.subset_distributor = HouseholdSubsetDistributor(
            self.venue_type,
            ['kids','independent children','adults','elderly']
        )
        self._venue_has_membership_capacity_by_subset = defaultdict(
            lambda: [True]*self.subset_distributor.n_subsets
        )

        # Maximum threshold per household (first pass)
        self.backup_venue_capacity_threshold = 5

        # Composition-specific thresholds (first pass)
        self.composition_thresholds = {
            '0 0 0 2': 2,    # Strict: cannot expand
            '0 0 2 0': 2,    # Strict: cannot expand
            '0 0 0 1': 1,    # Strict: cannot expand
            '0 0 1 0': 1,    # Strict: cannot expand
            '0 >=1 2 0': 4,  # Can expand ind children
            '1 >=0 2 0': 4,  # Can expand ind children
            '>=2 >=0 2 0': 5,  # Can expand kids and ind children
            '0 >=1 1 0': 4,
            '1 >=0 1 0': 4,
            '>=2 >=0 1 0': 4,
            '1 >=0 >=0 >=0': 3,   # Very flexible
            '>=2 >=0 >=0 >=0': 4,  # Very flexible
            '0 >=0 0 0': 3,
            '0 >=0 >=0 >=0': 3,
            '0 0 0 >=3': 5,
        }

        # Expanded thresholds for second pass (allow more people)
        self.expanded_thresholds = {
            '0 >=1 2 0': 6,  # More ind children
            '1 >=0 2 0': 8,
            '>=2 >=0 2 0': 12,  # More kids and ind children
            '>=2 >=0 1 0': 10,
            '1 >=0 >=0 >=0': 10,   # Much larger
            '>=2 >=0 >=0 >=0': 10,  # Much larger
            '0 >=0 0 0': 12,
            '0 >=0 >=0 >=0': 12,
            '0 0 0 >=3': 12,
        }

        # NEW: Track why each venue was closed
        self._venue_closed_reason = {}  # venue_id -> 'composition' or 'threshold'

        # NEW: Track which venues were closed due to threshold
        self._threshold_closed_venues = set()  # venue indices that can be reopened

        # Track whether to use expanded thresholds (for second pass)
        self.use_expanded_threshold = False

    
    def _update_venue_membership_capacity(self, trial_venue_index, venue, *args, **kwargs):
        """
        Updated to track WHY a venue is closed.
        """
        subset = args[0]
        composition = venue.properties['composition'].strip()

        # Track if this venue hit composition constraints
        composition_full = False

        # ========================================
        # PART 1: Set capacity based on composition
        # ========================================

        match composition:
            case '0 0 0 2':
                if venue.subsets['elderly'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]

            case '0 0 2 0':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]

            case '0 0 0 1':
                if venue.subsets['elderly'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]

            case '0 0 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]

            case '0 >=1 2 0':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # Check if composition constraints fully met (adults full)
                # if venue.subsets['adults'].num_members >= 2:
                #     composition_full = True

            case '1 >=0 2 0':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # if venue.subsets['adults'].num_members >= 2 and venue.subsets['kids'].num_members >= 1:
                #     composition_full = True

            case '>=2 >=0 2 0':
                if venue.subsets['kids'].num_members >= 3 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False                
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # if venue.subsets['adults'].num_members >= 2 and venue.subsets['kids'].num_members >= 2:
                #     composition_full = True

            case '0 >=1 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 2 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # if venue.subsets['adults'].num_members >= 1:
                #     composition_full = True

            case '1 >=0 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 2 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # if venue.subsets['adults'].num_members >= 1 and venue.subsets['kids'].num_members >= 1:
                #     composition_full = True

            case '>=2 >=0 1 0':
                if venue.subsets['kids'].num_members >= 3 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False                
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # if venue.subsets['adults'].num_members >= 1 and venue.subsets['kids'].num_members >= 2:
                #     composition_full = True

            case '1 >=0 >=0 >=0':
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False

            case '>=2 >=0 >=0 >=0':
                pass
                # if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):
                #     self._venue_has_membership_capacity_by_subset[venue.id][0] = False

            case '0 >=0 0 0':
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                # Never fully constrained by composition (>=0 means no limit)

            case '0 >=0 >=0 >=0':
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                # if venue.num_members >= 1 and bool(random.getrandbits(1)):
                #     self._venue_has_membership_capacity_by_subset[venue.id][random.choice([1,2,3])] = False
                # Never fully constrained by composition

            case '0 0 0 >=3':
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                # Never fully constrained (>=3 means no limit)

            case _:
                raise KeyError(f"Composition '{composition}' not found")

        # ========================================
        # PART 2: Apply threshold
        # ========================================

        # Determine which threshold to use (first pass vs expanded)
        if self.use_expanded_threshold:
            threshold = self.expanded_thresholds.get(
                composition,
                self.backup_venue_capacity_threshold * 2  # Double the default for expansion
            )
        else:
            threshold = self.composition_thresholds.get(
                composition,
                self.backup_venue_capacity_threshold
            )
        
        if venue.num_members >= threshold and not composition_full:
            # Closed due to THRESHOLD, not composition
            logger.debug(f"Venue {venue.name} reached threshold ({venue.num_members}/{threshold})")
            self._venue_has_membership_capacity_by_subset[venue.id] = [False] * self.subset_distributor.n_subsets
            self._venue_closed_reason[venue.id] = 'threshold'
            self._threshold_closed_venues.add(trial_venue_index)
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)
                self._search_index -=1
        elif composition_full or not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            # Closed due to COMPOSITION constraints
            self._venue_closed_reason[venue.id] = 'composition'
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)
                self._search_index -=1


    def reopen_threshold_closed_venues(self):
        """
        Reopen venues that were closed due to threshold, not composition.
        This allows flexible compositions to accept more people in a second pass.

        Returns:
            int: Number of venues reopened
        """
        reopened_count = 0

        for venue_idx in list(self._threshold_closed_venues):
            venue = self.potential_venues[venue_idx]
            venue_id = venue.id
            composition = venue.properties['composition'].strip()

            # Check if this composition allows expansion
            can_expand = composition in self.expanded_thresholds

            if can_expand:
                # Reopen this venue with expanded capacity
                # Reset capacity based on current state
                self._venue_has_membership_capacity_by_subset[venue_id] = [True, True, True, True]

                # Add back to available venues
                if venue_idx not in self.available_venue_indices:
                    self.available_venue_indices.append(venue_idx)
                    reopened_count += 1
                    logger.debug(f"Reopened venue {venue.name} for expansion (current: {venue.num_members})")

        # Clear the threshold-closed set (they've been processed)
        self._threshold_closed_venues.clear()

        return reopened_count

    def sort_by_membership(self):
        membership = np.zeros(len(self.available_venue_indices))
        for i,vindex in enumerate(self.available_venue_indices):
            membership[i] = self.potential_venues[vindex].num_members
        self.available_venue_indices = [self.available_venue_indices[i] for i in np.argsort(membership)]
    
    def assign_people_venues_with_expansion(self, activity: str, venue_type: str, **kwargs):
        """
        Two-pass assignment:
        1. First pass: Assign with strict thresholds
        2. Second pass: Reopen threshold-closed venues and assign remaining people with expanded thresholds
        """

        # FIRST PASS: Strict thresholds
        logger.info("="*70)
        logger.info("FIRST PASS: Assigning with strict composition thresholds")
        logger.info("="*70)

        self.use_expanded_threshold=False
        
        self.assign_people_venues(activity, venue_type, **kwargs)

        first_pass_unallocated = len(self.unallocated_people)
        logger.info(f"After first pass: {first_pass_unallocated} people unallocated")

        # SECOND PASS: Expand flexible households
        if first_pass_unallocated > 0:
            logger.info("")
            logger.info("="*70)
            logger.info("SECOND PASS: Reopening flexible households with expanded capacity")
            logger.info("="*70)

            reopened = self.reopen_threshold_closed_venues()
            logger.info(f"Reopened {reopened} flexible households for expansion")

            if reopened > 0:
                remaining_people = self.unallocated_people.copy()
                self.unallocated_people = []
                self.sort_by_membership()
                # Use expanded thresholds for this pass.
                # Only assign remaining people.
                self.use_expanded_threshold=True
                self.assign_people_venues(activity,
                                          venue_type,
                                          people=remaining_people,
                                          available_venue_indices=self.available_venue_indices,
                                          randomize_venue_order=False,
                                          maxiter=2000,
                                          **kwargs)

                second_pass_unallocated = len(self.unallocated_people)
                logger.info(f"Second pass allocated: {first_pass_unallocated - second_pass_unallocated} additional people")
                logger.info(f"After second pass: {second_pass_unallocated} people unallocated")


            
    # def _get_subset_dist(self):
    #     example_venue           = self.venue_manager.venues_by_type[self.venue_type][0]
    #     self.subset_distributor = HouseholdSubsetDistributor(self.venue_type, ['kids','independent children','adults','elderly'])
    #     self._venue_has_membership_capacity_by_subset = defaultdict(lambda: [True]*self.subset_distributor.n_subsets)
    
    # def _update_venue_membership_capacity(self, trial_venue_index, venue, *args, **kwargs):
    #     """ Called after a person is successfully assigned a subset, or once at the beginning. 
        
    #     subsets = ['kids', 'independent children', 'adults', elderly']
        
    #     """
    #     subset = args[0]
        
    #     match venue.properties['composition'].strip():
    #         case '0 0 0 2':
    #             if venue.subsets['elderly'].num_members >= 2:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
    #             else:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]
                    
    #         case '0 0 2 0':
    #             if venue.subsets['adults'].num_members >= 2:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
    #             else:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]
                
    #         case '0 0 0 1':
    #             if venue.subsets['elderly'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
    #             else:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, True]
                
    #         case '0 0 1 0':
    #             if venue.subsets['adults'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False, False]
    #             else:
    #                 self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, True, False]
                
    #         case '0 >=1 2 0':
    #             if venue.subsets['adults'].num_members >= 2:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False                
                
    #         case '1 >=0 2 0':
    #             if venue.subsets['adults'].num_members >= 2:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             if venue.subsets['kids'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                
    #         case '>=2 >=0 2 0':
    #             if venue.subsets['adults'].num_members >= 2:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False

    #         case '0 >=1 1 0':
    #             if venue.subsets['adults'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False

    #         case '1 >=0 1 0':
    #             if venue.subsets['adults'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 0 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             if venue.subsets['kids'].num_members >= 1:                    
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False
                
    #         case '>=2 >=0 1 0':
    #             if venue.subsets['adults'].num_members >= 1:
    #                 self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):                    
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False

    #         case '1 >=0 >=0 >=0':
    #             if venue.subsets['kids'].num_members >= 1:                    
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                    
    #         case '>=2 >=0 >=0 >=0':
    #             if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):                 
    #                 self._venue_has_membership_capacity_by_subset[venue.id][0] = False

    #         case '0 >=0 0 0':
    #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][3] = False
    #             # if venue.num_members >= 1 and bool(random.getrandbits(1)):
    #             #     self._venue_has_membership_capacity_by_subset[venue.id][random.choice([1,2,3])] = False 

    #         case '0 >=0 >=0 >=0':                
    #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             if venue.num_members >= 1 and bool(random.getrandbits(1)):
    #                 self._venue_has_membership_capacity_by_subset[venue.id][random.choice([1,2,3])] = False 

    #         case '0 0 0 >=3':
    #             self._venue_has_membership_capacity_by_subset[venue.id][0] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][1] = False
    #             self._venue_has_membership_capacity_by_subset[venue.id][2] = False

    #         case _:
    #             raise KeyError("Column title {} is not found within the list of programmed household types. See household_distributor.py".format(venue.properties['composition'].strip()))

    #     # Removes the venue from the list of potential venues if it has no membership capacity. 
    #     if not any(self._venue_has_membership_capacity_by_subset[venue.id]):
    #         self.available_venue_indices.remove(trial_venue_index)
        
        
    
        

    
