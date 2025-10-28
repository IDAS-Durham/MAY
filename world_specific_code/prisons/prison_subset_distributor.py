from typing import Optional
from may.distributor import SubsetDistributor

class PrisonSubsetDistributor(SubsetDistributor):
    def find_subset_for_person(self,
                               activity: str,
                               venue_has_capacity: list[bool],
                               person: "Person",
                               **kwargs) -> (int, str):
        """Takes a person and assigns them into a particular subset within the venue.

        This will be filled in with a series of criteria, specific to each kind of venue, that decides how to allocate a Person object into a specific subset within the venue. 

        Args:
          activity (str): the activity the person is going to the Venue for. 
          venue (Venue): the venue which is being populated.
          person (Person): the person to be assigned a subset.

        Suggested kwargs:
          activity (str, optional):
            The label for the activity the person is doing at the Venue.
            Might affect subset category.

        Returns:
          (int): the index of the assigned subset in the list of subsets (should be the same as the index of the subset when the contact matrix is built). 
          subset_name (str): the label of the subset within the Venue that the Person should be assigned to (pending capacity). Returns "No subset available" if no subset is available for the person at the venue. 

        age_category_capacity = [

        ] # should be the same as in care_home distributor
        
        """
        if activity == 'home' and person.age > 18:
            return 0, 'prisoners'
        elif activity == 'work' and person.age > 18:
            return 1, 'staff'
        else:
            return -1, 'No subset available'
