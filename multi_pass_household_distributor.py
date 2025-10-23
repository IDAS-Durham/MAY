"""
Multi-Pass Household Distributor with Configurable Threshold Expansion

This implementation allows for a flexible number of passes with configurable
threshold increments for each pass.

Key Features:
1. Configure number of passes upfront
2. Define threshold increment per pass for each expandable composition
3. Automatic threshold calculation for each pass
4. Tracks closure reasons and allows selective reopening
"""

import logging
from collections import defaultdict
import random

from may.distributor import Distributor, SubsetDistributor
from may.population import Subset
from may.specific_distributors.household_subset_distributor import HouseholdSubsetDistributor

logger = logging.getLogger(__name__)


class MultiPassHouseholdDistributor(Distributor):
    """
    Household distributor with flexible multi-pass assignment.

    Each pass increases thresholds for expandable compositions,
    allowing gradual filling of flexible households while
    maintaining even distribution.
    """

    def _post_init(self):
        """Initialize subset distributor and configure multi-pass thresholds."""
        example_venue = self.venue_manager.venues_by_type[self.venue_type][0]
        self.subset_distributor = HouseholdSubsetDistributor(
            self.venue_type,
            ['kids', 'independent children', 'adults', 'elderly']
        )
        self._venue_has_membership_capacity_by_subset = defaultdict(
            lambda: [True] * self.subset_distributor.n_subsets
        )

        # ========================================
        # MULTI-PASS CONFIGURATION
        # ========================================

        # Number of passes (first pass + N expansion passes)
        self.num_passes = 3  # Configurable

        # Current pass index (0 = first pass, 1 = second pass, etc.)
        self.current_pass = 0

        # Default backup threshold
        self.backup_venue_capacity_threshold = 8

        # Initial thresholds (first pass)
        self.composition_thresholds = {
            '0 0 0 2': 2,       # Strict: cannot expand
            '0 0 2 0': 2,       # Strict: cannot expand
            '0 0 0 1': 1,       # Strict: cannot expand
            '0 0 1 0': 1,       # Strict: cannot expand
            '0 >=1 2 0': 6,     # Can expand
            '1 >=0 2 0': 6,     # Can expand
            '>=2 >=0 2 0': 8,   # Can expand
            '0 >=1 1 0': 5,     # Can expand
            '1 >=0 1 0': 5,     # Can expand
            '>=2 >=0 1 0': 8,   # Can expand
            '1 >=0 >=0 >=0': 8,    # Very flexible
            '>=2 >=0 >=0 >=0': 10,  # Very flexible
            '0 >=0 0 0': 6,     # Can expand
            '0 >=0 >=0 >=0': 8, # Very flexible
            '0 0 0 >=3': 6,     # Very flexible
        }

        # Threshold INCREMENT per pass (NOT absolute values)
        # These values are ADDED to the threshold for each subsequent pass
        self.threshold_increment_per_pass = {
            '0 >=1 2 0': 2,        # +2 per pass (6 → 8 → 10)
            '1 >=0 2 0': 2,        # +2 per pass (6 → 8 → 10)
            '>=2 >=0 2 0': 3,      # +3 per pass (8 → 11 → 14)
            '0 >=1 1 0': 2,        # +2 per pass (5 → 7 → 9)
            '1 >=0 1 0': 2,        # +2 per pass (5 → 7 → 9)
            '>=2 >=0 1 0': 3,      # +3 per pass (8 → 11 → 14)
            '1 >=0 >=0 >=0': 4,    # +4 per pass (8 → 12 → 16)
            '>=2 >=0 >=0 >=0': 5,  # +5 per pass (10 → 15 → 20)
            '0 >=0 0 0': 3,        # +3 per pass (6 → 9 → 12)
            '0 >=0 >=0 >=0': 4,    # +4 per pass (8 → 12 → 16)
            '0 0 0 >=3': 10,       # +10 per pass (6 → 16 → 26)
        }

        # Compositions that can expand (have threshold increments defined)
        self.expandable_compositions = set(self.threshold_increment_per_pass.keys())

        # Track why each venue was closed
        self._venue_closed_reason = {}  # venue_id -> 'composition' or 'threshold'

        # Track which venues were closed due to threshold (can be reopened)
        self._threshold_closed_venues = set()  # venue indices

        logger.info(f"Configured multi-pass distributor with {self.num_passes} passes")
        logger.info(f"Expandable compositions: {len(self.expandable_compositions)}")

    def get_threshold_for_pass(self, composition: str, pass_index: int) -> int:
        """
        Calculate the threshold for a given composition at a specific pass.

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
        """
        Updated to track WHY a venue is closed and use pass-specific thresholds.
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

            case '1 >=0 2 0':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '>=2 >=0 2 0':
                if venue.subsets['adults'].num_members >= 2:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '0 >=1 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '1 >=0 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '>=2 >=0 1 0':
                if venue.subsets['adults'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][2] = False
                if venue.subsets['independent children'].num_members >= 1 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][1] = False
                if venue.subsets['kids'].num_members >= 2 and bool(random.getrandbits(1)):
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False
                self._venue_has_membership_capacity_by_subset[venue.id][3] = False

            case '1 >=0 >=0 >=0':
                if venue.subsets['kids'].num_members >= 1:
                    self._venue_has_membership_capacity_by_subset[venue.id][0] = False

            case '>=2 >=0 >=0 >=0':
                pass  # Most flexible - only limited by threshold

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
                raise KeyError(f"Composition '{composition}' not found")

        # ========================================
        # PART 2: Apply pass-specific threshold
        # ========================================

        # Get threshold for current pass
        threshold = self.get_threshold_for_pass(composition, self.current_pass)

        if venue.num_members >= threshold and not composition_full:
            # Closed due to THRESHOLD, not composition
            logger.debug(f"Venue {venue.name} reached threshold ({venue.num_members}/{threshold}) on pass {self.current_pass}")
            self._venue_has_membership_capacity_by_subset[venue.id] = [False] * self.subset_distributor.n_subsets

            # Only mark as threshold-closed if composition is expandable
            if composition in self.expandable_compositions:
                self._venue_closed_reason[venue.id] = 'threshold'
                self._threshold_closed_venues.add(trial_venue_index)
            else:
                self._venue_closed_reason[venue.id] = 'composition'

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

        Returns:
            int: Number of venues reopened
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

                    new_threshold = self.get_threshold_for_pass(composition, self.current_pass + 1)
                    logger.debug(f"Reopened venue {venue.name} for pass {self.current_pass + 1} "
                                f"(current: {venue.num_members}, new threshold: {new_threshold})")

        # Clear the threshold-closed set (they've been processed)
        self._threshold_closed_venues.clear()

        return reopened_count

    def assign_people_venues_multi_pass(self, activity: str, venue_type: str, **kwargs):
        """
        Multi-pass assignment with configurable number of passes.

        Each pass:
        1. Assigns people with current threshold
        2. If unallocated people remain and more passes available:
           - Reopens threshold-closed venues
           - Increments pass counter
           - Continues with expanded thresholds
        """
        initial_people_count = len(self.people)
        logger.info("="*70)
        logger.info(f"MULTI-PASS ASSIGNMENT: {self.num_passes} passes configured")
        logger.info(f"Total people to allocate: {initial_people_count}")
        logger.info("="*70)

        for pass_num in range(self.num_passes):
            self.current_pass = pass_num

            logger.info("")
            logger.info("="*70)
            logger.info(f"PASS {pass_num + 1}/{self.num_passes}")
            logger.info("="*70)

            # Log threshold examples for this pass
            example_compositions = ['>=2 >=0 >=0 >=0', '1 >=0 >=0 >=0', '0 0 0 >=3']
            for comp in example_compositions:
                if comp in self.composition_thresholds:
                    threshold = self.get_threshold_for_pass(comp, pass_num)
                    logger.info(f"  Threshold for '{comp}': {threshold}")

            # Run assignment for this pass
            self.assign_people_venues(activity, venue_type, **kwargs)

            unallocated_count = len(self.unallocated_people)
            allocated_this_pass = len(self.people) - unallocated_count

            logger.info(f"Pass {pass_num + 1} results:")
            logger.info(f"  Allocated: {allocated_this_pass} people")
            logger.info(f"  Unallocated: {unallocated_count} people")

            # Check if we should continue to next pass
            if unallocated_count == 0:
                logger.info(f"All people allocated after {pass_num + 1} passes!")
                break

            if pass_num < self.num_passes - 1:
                # Not the last pass - reopen venues for next pass
                logger.info("")
                logger.info(f"Preparing for pass {pass_num + 2}...")

                reopened = self.reopen_threshold_closed_venues()
                logger.info(f"  Reopened {reopened} flexible households")

                if reopened > 0:
                    # Prepare remaining people for next pass
                    remaining_people = self.unallocated_people.copy()
                    self.unallocated_people = []
                    self.people = remaining_people
                else:
                    logger.info("  No venues available to reopen - stopping")
                    break
            else:
                # Last pass completed
                logger.info(f"Completed all {self.num_passes} passes")

        # Final summary
        logger.info("")
        logger.info("="*70)
        logger.info("MULTI-PASS ASSIGNMENT COMPLETE")
        logger.info("="*70)
        logger.info(f"Total allocated: {initial_people_count - len(self.unallocated_people)}")
        logger.info(f"Total unallocated: {len(self.unallocated_people)}")
        if initial_people_count > 0:
            allocation_rate = ((initial_people_count - len(self.unallocated_people)) / initial_people_count) * 100
            logger.info(f"Allocation rate: {allocation_rate:.1f}%")
