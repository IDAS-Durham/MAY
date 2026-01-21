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
                 potential_venues: list["Venue"]=None,
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
        # The list of venues that will be considered for allocation.
        if potential_venues is not None:
            self.potential_venues = potential_venues
        else:
            self.potential_venues = self.__decide_potential_venues(**kwargs)
        # A list to keep track of any people for whom no venue is found in a pass. 
        self.unallocated_people = []

        self._assign_subsets()
        self._create_subsets_if_necessary()

    def _create_capacity_list(self):
        """
        Create a capacity list for membership tracking.

        This is a separate function (not a lambda) to make the object pickle-compatible.
        Returns a list of True values with length equal to the number of subsets.
        """
        return [True] * self.subset_distributor.n_subsets

    def _assign_subsets(self):
        self.subset_distributor = SubsetDistributor(self.venue_type,
                                                    example_venue.properties['subsets'])
        # Note: Using a method instead of lambda for pickle compatibility
        self._venue_has_membership_capacity_by_subset = defaultdict(self._create_capacity_list)
        
    def __decide_potential_venues(self):
        """ Decides which venues to consider.

        By default, it just takes all the venues of the relevant type, but one might want to limit it, for example, to only venues in a particular GeographicalUnit.

        """
        return self.venue_manager.get_venues_by_type(self.venue_type)

    def _create_subsets_if_necessary(self):
        """Goes through each venue and checks there is a Subset for each subset name. 

        This can probably be improved to make it not use loops,
        but it is only done once per venue so for now not worrying about it. 
        """
        for venue in self.potential_venues:
            if not venue.subsets: # if venue.subsets is an empty dictionary
                self.subset_distributor.generate_empty_subsets(venue)

    def sort_by_membership(self):
        """Sorts the venue indices so the lowest occupation is looked at first. """
        membership = np.zeros(len(self.available_venue_indices))
        for i,vindex in enumerate(self.available_venue_indices):
            membership[i] = self.potential_venues[vindex].num_members
        self.available_venue_indices = [self.available_venue_indices[i] for i in np.argsort(membership)]
                
    def assign_people_venues(self,
                             activity: str,
                             venue_type: str,
                             available_venue_indices: list[int] = None,
                             randomize_venue_order=True,
                             people: list["Person"]=None,
                             **kwargs):
        """Assigns people from self.people to do an activity (if they have it) at a particular venue type (if there is membership_capacity).

        Loops through the list of Persons to assign, and for each one calls `find_venues_for_person`.
        If no venue is found, `_deal_with_no_venue` is called which decides what should be done.
        By default, it just keeps track of unassigned people, but this should be edited for the specifics of the venue and activity in question.
        A key attribute set here is `self.available_venue_indices`. This is a list of the indices in `self.potential_venues` used to track which venues are considered 'available' to assign more people to. This (I think) speeds up the assignment, but also provides a handy way to disallow specific venues if desired, or randomize the order they are tried out, without changing the order of the venues held in VenueManager.

        Args:
          activity (str): The activity for which people in People will be assigned to the venue_type specified by venue_type.
          venue_type (str): The venue_type. Should match the label used in self.venue_manager.
          available_venue_indices (list[int], optional): The indices of venues that are considered 'available'. This is here so only a subset of venues can be examined if desired. Default = list(range(len(self.potential_venues))). 
          randomize_venue_order (bool, optional): If True, shuffles the available_venue_indices list. Default =True. 
          people (list[Person], optional): A list of the people to be assigned. Default = self.people. 

        """
        people = people if people is not None else self.people
        if available_venue_indices is None:
            self.available_venue_indices = list(range(len(self.potential_venues)))
        else:
            self.available_venue_indices = available_venue_indices
        if randomize_venue_order: random.shuffle(self.available_venue_indices)
        self._search_index=-1
        
        # Initialize the correct membership capacities for households.
        for venue_idx in list(self.available_venue_indices):
            venue=self.potential_venues[venue_idx]
            self._update_venue_membership_capacity(venue_idx, venue)
        logger.debug("Set venue capacities. Starting allocation...")
        # Start allocating people

        total_allocated=0
        #total_people=len(people)
        #printed=set()
        for person in people:
            if person.has_activity(activity):
                if self.find_venues_for_person(person,
                                               activity,
                                               **kwargs):
                    total_allocated += 1
                    # percent=int(total_allocated/total_people*100)
                    # milestone = (percent // 10) * 10
                    # if milestone not in printed and milestone % 10 == 0:
                    #     logger.debug(f"{milestone}% complete")
                    #     printed.add(milestone)
                else:
                    self._deal_with_no_venue(person, activity)
        logger.debug(f"Allocated {total_allocated} people to households")
        logger.debug("Number of unallocated folk: {}".format(len(self.unallocated_people)))

    def find_venues_for_person(self,
                               person: "Person",
                               activity: str,
                               maxiter: int=100,
                               **kwargs):
        """Assigns a person a venue from a list, and a subset for that venue.

        Args:
          person (Person): a person to allocate a venue for.
          activity (str): the label of the activity they are doing. 
          maxiter (int, optional): the maximum number of venues to try before giving up on finding a venue for this person to do the activity.
          randomize (bool, optional): whether the order of potential venues trialed should be randomized for each person.

        """
        i=0
        while i <= maxiter:
            i+=1
            self._search_index+=1
            if len(self.available_venue_indices) < 1:
                logger.debug("Could not find a venue for person {} as no venues available".format(person.id))
                break
            if self._search_index >= len(self.available_venue_indices):
                self._search_index = 0
            trial_venue_index=self.available_venue_indices[self._search_index]
            try:
                trial_venue = self.potential_venues[trial_venue_index]
            except:
                logger.warning("Could not find a venue for person {}".format(person.id))
                self._deal_with_no_venue(person, activity)
                
            try:
                trial_subset_index, trial_subset_name = self.subset_distributor.find_subset_for_person(
                    activity,
                    self._venue_has_membership_capacity_by_subset[trial_venue.id],
                    person,
                )
                if trial_subset_name == 'No subset available':
                    # Try a new venue
                    continue
                else:
                    # Assign venue and subset as the person's location and subset for the specified activity.
                    subset = trial_venue.subsets[trial_subset_name]
                    venue_type = trial_venue.type
                    # Initialize nested dict structure: activity_map[activity][venue_type] = [subsets]
                    if activity not in person.activity_map:
                        person.activity_map[activity] = {}
                    if venue_type not in person.activity_map[activity]:
                        person.activity_map[activity][venue_type] = []
                    person.activity_map[activity][venue_type].append(subset)
                    person.properties['housed'] = True
                    subset.add_member(person)
                    self._update_venue_membership_capacity(trial_venue_index,
                                                           trial_venue,
                                                           subset,
                                                           **kwargs)
                    return True
            except:
                logger.error("Could not assign a subset to person {} for venue {} of type {} with activity {}".format(person.id, trial_venue.id, trial_venue.type, activity))
                #self._deal_with_no_venue(person, activity)
                raise Exception("Failure of _assign_subset routine when assigning subset and venue for person {} to activity {}.".format(person.id, activity))
            
        # If exhausted the loop. 
        logger.debug("Could not find a venue for person {} within {} iterations".format(person.id, maxiter))
        return False

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
        pass
    
    def _deal_with_no_venue(self, person: "Person", *args):
        """Deal with a person who we could find no venue for their activity. 

        """
        self.unallocated_people.append(person)
        #logger.warning("Didn't allocate Person {} for activity {}".format(person.id, args[0]))
        #raise NotImplementedError("Not yet decided how to deal with people who have no venue to go to")

        



    
