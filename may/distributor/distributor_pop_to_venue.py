import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

from .distributor_venue_to_subsets import SubsetDistributor
from may.population import Subset

logger = logging.getLogger(__name__)


class Distributor:
    """Class to distribute a list of people across instances of a Venue class with a particular type.

    This is the parent class to specific classes for distributing people across households, schools, etc. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attept to sort venues within VenueManager (yet). 
    """
    def __init__(self,
                 venue_type: str,
                 venue_manager: "VenueManager",
                 people: list["Person"],
                 **kwargs):
        """
        Args:
          venue_type (str):
            A string denoting the venue type. Should be the same as the
            key used in the dict object VenueManager.venues_by_type. 
          venue_manager (VenueManager):
            the object which manages venues and their relationshiops to
            geographical units. This contains a dict of all venues sorted
            by type which have venue_type as keys
            (see VenueManager.venues_by_type).
          population (Population):
            The list of persons.
        
        """
        self.id = id(self)
        self.venue_type = venue_type
        self.venue_manager = venue_manager
        self.people = people
        self.potential_venues = self.__decide_potential_venues()
        self.unallocated_people = []
        
        self._get_subset_dist()
        self._create_subsets_if_necessary()

    def _get_subset_dist(self):
        example_venue           = self.potential_venues[0] # just the first potential venue
        self.subset_distributor = SubsetDistributor(self.venue_type,
                                                    example_venue.properties['subsets'])
        self._venue_has_membership_capacity_by_subset = defaultdict(lambda: [True]*self.subset_distributor.n_subsets)

    def __decide_potential_venues(self):
        return self.venue_manager.get_venues_by_type(self.venue_type)

    def _create_subsets_if_necessary(self):
        """Goes through each venue and checks there is a Subset for each subset name. 

        This can probably be improved to make it not use loops,
        but it is only done once per venue so for now not worrying about it. 
        """
        for venue in self.potential_venues:
            if not venue.subsets: # if venue.subsets is an empty dictionary
                self.subset_distributor.generate_empty_subsets(venue)
                
    def assign_people_venues(self,
                             activity: str,
                             venue_type: str,
                             available_venue_indices: list[int] = None,
                             **kwargs):
        """Assigns people from self.people to do an activity (if they have it) at a particular venue type (if there is membership_capacity). 

        """
        if available_venue_indices is None:
            self.available_venue_indices = list(range(len(self.potential_venues)))
        else:
            self.available_venue_indices = available_venue_indices
        for person in self.people:
            if person.has_activity(activity):
                self.find_venues_for_person(person,
                                            activity,
                                            self.potential_venues,
                                            **kwargs)
            else: continue

    def find_venues_for_person(self,
                               person: "Person",
                               activity: str,
                               venue_list: list["Venue"],
                               maxiter: int = 100,
                               randomize: bool = True,
                               **kwargs):
        """Assigns a person a venue from a list, and a subset for that venue.

        Args:
          person (Person): a person to allocate a venue for.
          activity (str): the label of the activity they are doing. 
          venue_list (list[Venue]): a list of possible venues to choose from.
          maxiter (int, optional): the maximum number of venues to try before giving up on finding a venue for this person to do the activity.
          randomize (bool, optional): whether the order of potential venues trialed should be randomized for each person.

        """
        
        available_indices_this_time = self.available_venue_indices[:maxiter]
        if randomize:
            random.shuffle(available_indices_this_time)

        for ii, trial_venue_index in enumerate(available_indices_this_time):
            try:
                trial_venue = venue_list[trial_venue_index]
            except:
                logger.warning("Could not find a venue for person {}".format(person.id))
                self._deal_with_no_venue(person, activity)
                
            try:
                trial_subset_index, trial_subset_name = self.subset_distributor.find_subset_for_person(
                    self._venue_has_membership_capacity_by_subset[trail_venue.id],
                    person,
                )
                print(trial_subset_index, trial_subset_name)
                if trial_subset_name == 'No subset available':
                    # Try a new venue
                    continue
                else:
                    # Assign venue and subset as the person's location and subset for the specified activity.
                    subset = trial_venue.subsets[trial_subset_name]
                    person.activity_map[activity].append(subset)
                    subset.add_member(person)
                    self._update_venue_membership_capacity(trial_venue_index, trial_venue, subset)
                    break
            except:
                logger.error("Could not assign a subset to person {} for venue {} of type {} with activity {}".format(person.id, trial_venue.id, trial_venue.type, activity))
                #self._deal_with_no_venue(person, activity)
                raise Exception("Failure of _assign_subset routine when assigning subset and venue for person {} to activity {}.".format(person.id, activity))
        # If exhausted the loop. 
        logger.warning("Could not find a venue for person {} within {} iterations".format(person.id, maxiter))
        self._deal_with_no_venue(person, activity)
                

    def _update_venue_membership_capacity(self, trial_venue_index, venue, subset, **kwargs):
        """Update the venue membership_capacity after adding a person to subset membership.

        Venue membership capacity is held by the object self._venue_has_membership_capacity_by_subset, which is a list of boolean
        values where True means more members can be assigned to the venue's subset. E.g. if a venue has three subsets ['kids', 'adults', 'elderly'], then self._venue_has_membership_capacity_by_subset[venue.id] = [True,True,False] means that more members can be added to the 'kids' and 'adults' subsets, but no more can be added to the 'elderly' subset. 

        Args:
          subset (Subset): the subset that a Person has just been assigned as a member of the subset.

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
        pass
        
    def _deal_with_no_venue(self, person: "Person", *args):
        """Deal with a person who we could find no venue for their activity. 

        """
        self.unallocated_people.append(person)
        print("Didn't allocate Person {} for activity {}".format(person.id, args[0]))
        #raise NotImplementedError("Not yet decided how to deal with people who have no venue to go to")

        



    
