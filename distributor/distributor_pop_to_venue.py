import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

logger = logging.getLogger(__name__)


class Distributor:
    """Class to distributor a list of people across instances of a Venue class.

    This is the parent class to specific classes for distributing people across households, schools, etc. It should be instantiated with a single instance of VenueManager that has been initialised for a GeographyUnit. Thus, it is assumed that all venues in VenueManager.venues_by_type are fair game. The distributor does not attept to sort venues within VenueManager (yet). 
    """
    def __init__(self,
                 activity: str,
                 venue_manager: "VenueManager",
                 people: list["Person"]):
        """
        Args:
          venue_type (str):
            A string denoting the venue type. Should be the same as the key used in the dict object VenueManager.venues_by_type. 
          venue_manager (VenueManager):
            the object which manages venues and their relationshiops to geographical units.
            This contains a dict of all venues sorted by type which have venue_type as keys (see VenueManager.venues_by_type).
          population (Population):
            The list of persons.
        
        """
        self.id = id(self)
        self.activity = activity
        self.venue_manager = venue_manager
        self.people = people
        self.__get_subset_list()

    def __get_subset_list(self):
        example_venue           = self.venue_manager.venues_by_type[venue_type][0]
        self._venue_subsets = example_venue.properties['subsets']
        self._venue_has_capacity_by_subset = defaultdict([True]*len(example_venue_subsets))

    def assign_people_venues(self,
                             activity: str,
                             venue_type: str,
                             **kwargs):
        """Assigns people from self.people to do an activity (if they have it) at a particular venue type (if there is capacity). 

        """
        potential_venues = self.venue_manager.get_venues_by_type(venue_type)
        available_venue_indices = list(range(len(potential_venues)))        
        for person in self.people:
            if person.has_activity(activity):
                self.find_venues(person,
                                 self.activity,
                                 potential_venues,
                                 available_venue_indices,
                                 **kwargs)
            else: continue
            

    def find_venues(self,
                    person: "Person",
                    activity: str,
                    venue_list: list["Venue"],
                    available_venue_indices: list[int],
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
        if randomize:
            random.shuffle(available_venue_indices)

        for ii, trial_venue_index in enumerate(available_venue_indices):
            if ii > maxiter:
                logger.warning("Could not find a venue for person {} within {} iterations".format(person.id, maxiter))
                self._deal_with_no_venue(person, activity)                
            try:
                trial_venue = venue_list[trial_venue_index]
            except:
                logger.warning("Could not find a venue for person {}".format(person.id))
                self._deal_with_no_venue(person, activity)
                
                
            try:
                trial_subset_index, trial_subset = self._assign_subset(trial_venue,
                                                                    activity,
                                                                    subsets,
                                                                    person)
                if trial_subset == 'No subset available':
                    # Try a new venue
                    continue
                else:
                    # Assign venue and subset as the person's location and subset for the specified activity. 
                    person.activity_map[activity] = (trial_venue.id, trial_subset_index, trial_subset)
                    break
            except:
                logger.error("Could not assign a subset to person {} for venue {} of type {} with activity {}".format(person.id, new_venue.id, new_venue.type, activity))
                self._deal_with_no_venue(person, activity)
                raise Exception("Failure of _assign_subset routine when assigning subset and venue for person {} to activity {}.".format(person.id, activity))

    def _deal_with_no_venue(person: "Person", activity: str):
        """Deal with a person who we could find no venue for their activity. 

        """
        raise NotImplementedError("Not yet decided how to deal with people who have no venue to go to")
                
    def _assign_subset(self,
                        venue: "Venue",
                        activity: str,
                        person: "Person",
                        **kwargs) -> subset_str:
        """Takes a person and assigns them into a particular subset within the venue.

        This will be filled in with a series of criteria, specific to each kind of venue, that decides how to allocate a Person object into a specific subset within the venue. 

        Args:
          venue (Venue): the venue which is being populated.
          activity (str): the 
          person (Person): the person to be assigned a subset.

        Returns:
          subset_str (str): the label of the subset within the Venue that the Person should be assigned to (pending capacity). Returns "No subset available" if no subset is available for the person at the venue. 

        Examples:
          subsets = ['kid', 'young_adult', 'adult', 'old']
          if len(subsets) == 0:
              return 'No subset available'
          try:
              if person.age < 15 and self.does_venue_have_capacity(venue.id, 'kid'):
                  return 'kid'
              elif person.age < 25 and self.does_venue_have_capacity(venue.id, 'young_adult'):
                  return 'young_adult'        
              elif person.age < 60 and self.does_venue_have_capacity(venue.id, 'adult'):
                  return 'adult'
              elif self.does_venue_have_capacity(venue.id, 'old'):
                  return 'old'
              else:
                  return 'No subset available'
          except:
              return 'No subset available'

        """
        subsets = ['kid', 'young_adult', 'adult', 'old']
        if len(subsets) == 0:
            return -1, 'No subset available'
        try:
            rindex = random.randint(0, len(subsets)-1)
            if self._venue_has_capacity_by_subset[venue.id][rindex]:
                #subset_str = random.choice(subsets, weights=None)
                return rindex, subsets[rindex]
            else:
                return -1, 'No subset available'
        except:
            return -1, 'No subset available'
        



    
