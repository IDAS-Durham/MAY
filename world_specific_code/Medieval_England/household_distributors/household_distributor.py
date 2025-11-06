import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from may.distributor import Distributor
from may.distributor import DistributorMultiPass
from may.distributor import SubsetDistributor
from may.population import Subset
from .household_subset_distributor import HouseholdSubsetDistributor

logger = logging.getLogger(__name__)


class HouseholdDistributor(DistributorMultiPass):
    """Class to distributor a list of people across instances of a Venue class with type 'household'

    This is the child class to Distributor. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attempt to sort venues within VenueManager (yet).
    
    """
    
    def _assign_subsets(self):
        """Called at the end of __init__ """
        example_venue = self.venue_manager.venues_by_type[self.venue_type][0]
        self.subset_distributor = HouseholdSubsetDistributor(
            self.venue_type,
            ['kids','independent children','adults','elderly']
        )
        self._venue_has_membership_capacity_by_subset = defaultdict(
            lambda: [True]*self.subset_distributor.n_subsets
        )

    def _multi_pass_config(self):
        """Configures some parameters for doing multi-pass allocation.

        By default, the parameters are set up so only one pass is done, but they are
        kept here so it is easy to see how to amend them for allowing multiple passes.

        """        
        # Number of passes (first pass + N expansion passes)
        self.num_passes = 10  # Configurable

        # Current pass index (0 = first pass, 1 = second pass, etc.)
        self.current_pass = 0

        # Maximum threshold per household (first pass)
        self.backup_venue_capacity_threshold = 5

        # Composition-specific thresholds (first pass)
        self.composition_thresholds = {
            'Solo Adult': 1,    # Strict: cannot expand
            'Adult Couple': 2,    # Strict: cannot expand
            'Adult multi-house': 3,    # Can expand
            'Adult with children': 3,    # Can expand with children
            'Couple with children': 4,  # Can expand with children
            'Adults with children': 5,  # Can expand
        }

        # Threshold INCREMENT per pass (NOT absolute values)
        # These values are ADDED to the threshold for each subsequent pass
        self.threshold_increment_per_pass = {
            'Adult multi-house': 2,    # Can expand
            'Adult with children': 2,    # Can expand with children
            'Couple with children': 2,  # Can expand with children
            'Adults with children': 2,  # Can expand
        }

        # Compositions that can expand (have threshold increments defined)
        self.expandable_compositions = set(self.threshold_increment_per_pass.keys())

        # Track why each venue was closed
        self._venue_closed_reason = {}  # venue_id -> 'composition' or 'threshold'

        # Track which venues were closed due to threshold
        self._threshold_closed_venues = set()  # venue indices that can be reopened

        # Track whether to use expanded thresholds (for second pass)
        self.use_expanded_threshold = False

    def get_threshold_for_pass(self, composition: str, pass_index: int) -> int:
        """
        Calculate the threshold for a given composition at a specific pass.

        Tries to get composition-specific thresholds.
        
        Args:
            composition: The composition string (e.g., '>=2 >=0 >=0 >=0')
            pass_index: The pass number (0 = first pass, 1 = second pass, etc.)

        Returns:
            int: The threshold for this composition at this pass
        """
        base_threshold = self.composition_thresholds.get(
            composition,
            self.backup_venue_capacity_threshold
        )

        if pass_index == 0:
            # First pass: use base threshold
            return base_threshold

        # Subsequent passes: add increments
        increment = self.threshold_increment_per_pass.get(composition, 0)
        return base_threshold + (increment * pass_index)

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
        composition = venue.properties['composition'].strip()

        # Track if this venue hit composition constraints
        composition_full = False

        # ========================================
        # PART 1: Set capacity based on composition
        # ========================================
        match composition:
            case 'Solo Adult':
                if venue.subsets['adults'].num_members >= 1 or venue.subsets['elderly'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, True, True]

            case 'Adult Couple':
                if venue.subsets['adults'].num_members + venue.subsets['elderly'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, False, False]
                    composition_full = True
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [False, True, True]

            case 'Adult multi-house':
                self._venue_has_membership_capacity_by_subset[venue.id] = [False, True, True]

            case 'Adult with children':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = [True, False, False]
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [True, True, False]

            case 'Couple with Children':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                else:
                    self._venue_has_membership_capacity_by_subset[venue.id] = [True, True, False]                    

            case 'Adults with Children':
                self._venue_has_membership_capacity_by_subset[venue.id] = [True, True, True] 

            case _:
                raise KeyError(f"Composition '{composition}' not found")

        # ========================================
        # PART 2: Apply pass-specific threshold
        # ========================================

        # Get threshold for current pass
        threshold = self.get_threshold_for_pass(composition, self.current_pass)
        
        if venue.num_members >= threshold and not composition_full:
            # Closed due to THRESHOLD, not composition
            logger.debug(f"Venue {venue.name} reached threshold ({venue.num_members}/{threshold})")
            self._venue_has_membership_capacity_by_subset[venue.id] = [False] * self.subset_distributor.n_subsets
            self._venue_closed_reason[venue.id] = 'threshold'
            self._threshold_closed_venues.add(trial_venue_index)
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)
        elif composition_full or not any(self._venue_has_membership_capacity_by_subset[venue.id]):
            # Closed due to COMPOSITION constraints
            self._venue_closed_reason[venue.id] = 'composition'
            if trial_venue_index in self.available_venue_indices:
                self.available_venue_indices.remove(trial_venue_index)

    def reopen_threshold_closed_venues(self):
        """
        Reopen venues that were closed due to threshold, not composition.
        This allows flexible compositions to accept more people in a second pass.

        Returns:
            (int): Number of venues reopened
        """
        reopened_count = 0

        for venue_idx in list(self._threshold_closed_venues):
            venue = self.potential_venues[venue_idx]
            venue_id = venue.id
            composition = venue.properties['composition'].strip()

            # Check if this composition allows expansion
            can_expand = composition in self.expandable_compositions

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


    
