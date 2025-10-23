from abc import abstractmethod, ABC, abstractproperty

import logging
import pandas as pd
import numpy as np
import random
from collections import defaultdict

logger = logging.getLogger(__name__)


class AbstractDistributor(ABC):
    """Represents properties and methods common to most distributor classes.

    """
    
    @abstractmethod
    def assign_people_venues(self,
                             activity: str,
                             venue_type: str,
                             **kwargs):
        """Assigns people from self.people to do an activity (if they have it) at a particular venue type (if there is capacity). 

        """
        pass

    @abstractmethod
    def find_venues(self,
                    person: "Person",
                    activity: str,
                    venue_list: list["Venue"],
                    available_venue_indices: list[int],
                    maxiter: int = 100,
                    randomize: bool = True,
                    **kwargs):
        """Assigns a person a venue from a list, and a subgroup for that venue.

        Args:
          person (Person): a person to allocate a venue for.
          activity (str): the label of the activity they are doing. 
          venue_list (list[Venue]): a list of possible venues to choose from.
          maxiter (int, optional): the maximum number of venues to try before giving up on finding a venue for this person to do the activity.
          randomize (bool, optional): whether the order of potential venues trialed should be randomized for each person.

        """
        pass

    @abstractmethod
    def _deal_with_no_venue(person: "Person", activity: str):
        """Deal with a person who we could find no venue for their activity. 

        """
        pass


    @abstractmethod
    def _assign_subset(self,
                        venue: "Venue",
                        activity: str,
                        person: "Person",
                        **kwargs) -> subset:
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
        pass
