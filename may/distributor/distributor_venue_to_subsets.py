

from may.population import Subset
from typing import Optional

class SubsetDistributor:
    """Distributes people assigned to a potential venue into a specific subclass within that Venue. 

    """
    def __init__(self,
                 venue_type: str,
                 subset_names: list[str] = None,
                 properties: dict=None,
                 ):
        """
        Args:
          venue_type (str):
            a label for the type of venue. Should be the same as the labels
            used in VenueManager.venues_by_type, and in Venue.venue_type.
          subsets (list[str], optional):
            A list of names for the different subsets in the Venue.
            Should be the same for every venue of the same type. Default = ['everyone'].
          properties (dict, optional):
            An extensible dict to hold other properties of the class. Default = {}. 

        """
        self.venue_type = venue_type
        self.subset_names = subset_names if subset_names is not None else ['everyone']
        self.properties = properties if properties is not None else {}
        self.n_subsets = len(self.subset_names)

    def generate_empty_subsets(self,
                               venue: 'Venue'):
        venue.subsets = {}
        for i, name in enumerate(self.subset_names):
            venue.subsets[name] = Subset(venue, i, name)

    def find_subset_for_person(self,
                               activity: str,
                               venue_has_capacity: list[bool],
                               person: "Person",
                               **kwargs) -> (int, str, Optional["Subset"]):
        """Takes a person and assigns them into a particular subset within the venue.

        This will be filled in with a series of criteria, specific to each kind of venue, that decides how to allocate a Person object into a specific subset within the venue. 

        Args:
          venue (Venue): the venue which is being populated.
          person (Person): the person to be assigned a subset.

        Suggested kwargs:
          activity (str, optional):
            The label for the activity the person is doing at the Venue.
            Might affect subset category.

        Returns:
          (int): the index of the assigned subset in the list of subsets (should be the same as the index of the subset when the contact matrix is built). 
          subset_name (str): the label of the subset within the Venue that the Person should be assigned to (pending capacity). Returns "No subset available" if no subset is available for the person at the venue. 

        Examples:
          self.subset_names = ['kid', 'young_adult', 'adult', 'old']
          venue_has_capacity = [True, True, True, True]
          if person.age < 15 and venue_has_capacity[0]:
              return 'kid'
          elif person.age < 25 and venue_has_capacity[1]:
              return 'young_adult'        
          elif person.age < 60 and venue_has_capacity[2]:
              return 'adult'
          elif venue_has_capacity[3]:
              return 'old'
          else:
              return 'No subset available'

        """
        rindex = random.randint(0, self.n_subsets-1)
        if venue_has_capacity[rindex]:
            #subset_name = random.choice(subsets, weights=None)
            return rindex, self.subset_names[rindex]
        else:
            return -1, 'No subset available'

    

    
