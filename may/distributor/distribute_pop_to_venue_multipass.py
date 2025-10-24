import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from may.distributor import Distributor
from .distributor_venue_to_subsets import SubsetDistributor
from may.population import Subset
from may.stats import StatMakerPop, StatMakerVenues

logger = logging.getLogger(__name__)

class DistributorMultiPass(Distributor):
    """Class to distribute a list of people across instances of a Venue class with a particular type.

    This is the child class to Distributor, adding in functionality to do multiple passes with expanding threshholds.
    There should be children of this class used as specific classes for distributing people across households, schools, etc. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attept to sort venues within VenueManager (yet).
    
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._multi_pass_config()
    
    def _multi_pass_config(self):
        """Configures some parameters for doing multi-pass allocation.

        By default, the parameters are set up so only one pass is done, but they are
        kept here so it is easy to see how to amend them for allowing multiple passes.

        """
        # Maximum number of passes (first pass + N expansion passes)
        self.num_passes = 1
        # Current pass index (0 = first pass, 1 = second pass, etc.)
        self.current_pass = 0
        # Maximum threshold per household (first pass, will increment in future passes)
        self.backup_venue_capacity_threshold = 1000000000 # set absurdly large so there is effectively no max capacity.
        # Track why each venue was closed
        self._venue_closed_reason = {}  # venue_id -> 'threshold' or 'some other reason' e.g. 'compsition' or 'max capacity'
        # Track which venues were closed due to threshold
        self._threshold_closed_venues = set()  # venue indices that can be reopened        
        # The amount it increments each pass
        self.backup_venue_capactity_increment = 0
        # Track whether to use expanded thresholds (for future passes)
        self.use_expanded_threshold = False

    def _update_venue_membership_capacity(self,
                                          trial_venue_index: int,
                                          venue: "Venue",
                                          *args,
                                          **kwargs):
        """Update the venue membership_capacity after adding a person to subset membership.

        Venue membership capacity is held by the object self._venue_has_membership_capacity_by_subset, which is a list of boolean
        values where True means more members can be assigned to the venue's subset. E.g. if a venue has three subsets ['kids', 'adults', 'elderly'], then self._venue_has_membership_capacity_by_subset[venue.id] = [True,True,False] means that more members can be added to the 'kids' and 'adults' subsets, but no more can be added to the 'elderly' subset. 

        Args:
          trial_venue_index (int):
            The index corresponding to the venue's position in self.potential venues. Should correspond to the index in self.available_venue_indices.
          venue (Venue):
            The Venue being updated
          *args:
            Other arguments. Common one is subset (Subset), the subset that a person has just been added to. 

        Examples:
          If one wanted to limit the membership of each individual subset to 10 max.
        
          if len(subset.members) >= 10:
            self._venue_has_membership_capacity_by_subset[subset.venue.id][subset.subset_index] = False
          if not any(self._venue_has_membership_capacity_by_subset[subset.venue.id]):
            self.available_venue_indices.remove(trial_venue_index)

          Limiting the membership of all subsets to a total of 10.

          total=0
          for s in subset.venue.subsets:
            total += len(s.members)
          if total >= 10:
            self._venue_has_membership_capacity_by_subset[subset.venue.id] = [False]*self.subset_distributor.n_subsets
            self.available_venue_indices.remove(trial_venue_index)
        
        """
        # Get threshold for current pass
        threshold = self.get_threshold_for_pass(self.current_pass)
        
        if venue.num_members >= threshold:
            # Closed due to THRESHOLD, not composition
            logger.debug(f"Venue {venue.name} reached threshold ({venue.num_members}/{threshold})")
            self._venue_has_membership_capacity_by_subset[venue.id] = [False] * self.subset_distributor.n_subsets
            self._venue_closed_reason[venue.id] = 'threshold'
            self._threshold_closed_venues.add(trial_venue_index)
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)
        elif not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            # Closed due to COMPOSITION constraints
            self._venue_closed_reason[venue.id] = 'composition'
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)

    def get_threshold_for_pass(self, pass_index: int) -> int:
        """
        Calculate the threshold for a given composition at a specific pass.

        As written, all venues of venue_type are treated as having the same threshold.
        
        Args:
            pass_index: The pass number (0 = first pass, 1 = second pass, etc.)

        Returns:
            int: The threshold for this composition at this pass
        """
        return self.backup_venue_capacity_threshold + (self.backup_venue_capacity_increment * pass_index)

    def reopen_threshold_closed_venues(self) -> int:
        """
        Reopen venues that were closed due to threshold, not composition.
        This allows flexible compositions to accept more people in a second pass.

        Returns:
            (int): Number of venues reopened
        """
        reopened_count = 0

        for venue_idx in list(self._threshold_closed_venues):
            venue_id = self.potential_venues[venue_idx].id

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

    def assign_people_venues_multi_pass(self,
                                        activity: str,
                                        venue_type: str,
                                        people=None,
                                        **kwargs):
        """
        Multi-pass assignment with configurable number of passes.

        Each pass:
        1. Assigns people with current threshold
        2. If unallocated people remain and more passes available:
           - Reopens threshold-closed venues
           - Adds back the indices of threshold-closed venues to self.available_venue_indices
           - Increments pass counter
           - Continues to assign unassigned people with expanded thresholds added back in.

        Args:
          activity (str):
            The activity the Person is undertaking when visiting this type of venue.
          venue_type (str):
            Label for the type of venue.
          people (list[Person]):
            A list of people to assign. 
          
        """
        people = people if people is not None else self.people
        initial_people_count = len(people)
        logger.debug("="*70)
        logger.debug(f"MULTI-PASS ASSIGNMENT: {self.num_passes} passes configured")
        logger.debug(f"Total people to allocate: {initial_people_count}")
        logger.debug("="*70)

        for pass_num in range(self.num_passes):
            self.current_pass = pass_num

            logger.debug("")
            logger.debug(f"PASS {pass_num + 1}/{self.num_passes}")
            logger.debug("")
            
            # Log threshold examples for this pass
            example_compositions = ['>=2 >=0 >=0 >=0', '1 >=0 >=0 >=0', '0 >=0 >=0 >=0']
            for comp in example_compositions:
                if comp in self.composition_thresholds:
                    threshold = self.get_threshold_for_pass(comp, pass_num)
                    logger.debug(f"  Threshold for '{comp}': {threshold}")

            # Run assignment for this pass
            if pass_num == 0:
                # First pass: use all people
                self.assign_people_venues(activity,
                                          venue_type,
                                          people=people,
                                          maxiter=10,
                                          **kwargs)
            else:
                # Subsequent passes: use remaining people, sorted venues, no randomization
                remaining_people = self.unallocated_people.copy()
                self.unallocated_people = []
#                self.sort_by_membership()
                self.assign_people_venues(activity,
                                          venue_type,
                                          people=remaining_people,
                                          available_venue_indices=self.available_venue_indices,
                                          maxiter=50,
#                                          randomize_venue_order=False,
                                          **kwargs)

            unallocated_count = len(self.unallocated_people)
            allocated_this_pass = len(people) if pass_num == 0 else len(remaining_people)
            allocated_this_pass = allocated_this_pass - unallocated_count

            logger.debug(f"Pass {pass_num + 1} results:")
            logger.debug(f"  Allocated: {allocated_this_pass} people")
            logger.debug(f"  Unallocated: {unallocated_count} people")

            # Check if we should continue to next pass
            if unallocated_count == 0:
                logger.debug(f"All people allocated after {pass_num + 1} passes!")
                break

            if pass_num < self.num_passes - 1:
                # Not the last pass - reopen venues for next pass
                logger.debug("")
                logger.debug(f"Preparing for pass {pass_num + 2}...")

                reopened = self.reopen_threshold_closed_venues()
                logger.debug(f"  Reopened {reopened} flexible households")

            else:
                # Last pass completed
                logger.debug(f"Completed all {self.num_passes} passes")

        # Final summary
        logger.debug("")
        logger.debug("MULTI-PASS ASSIGNMENT COMPLETE")
        logger.debug("")        
        logger.debug(f"Total allocated: {initial_people_count - len(self.unallocated_people)}")
        logger.debug(f"Total unallocated: {len(self.unallocated_people)}")
        if initial_people_count > 0:
            allocation_rate = ((initial_people_count - len(self.unallocated_people)) / initial_people_count) * 100
            logger.debug(f"Allocation rate: {allocation_rate:.1f}%")
            if allocation_rate < 99.999999:
                logger.warning(f"--Low allocation rate of {allocation_rate:.1f}%")
                logger.warning(f"--Printing stats of unallocated people: ")
                my_statmaker = StatMakerPop(self.unallocated_people)
                my_statmaker.get_sex_breakdown()
                my_statmaker.get_age_group_breakdown()
                morestats = my_statmaker.get_age_stats()
                for key, val in morestats.items():
                    logger.info(f"    {key} : {val}")
        logger.debug("="*70)            
