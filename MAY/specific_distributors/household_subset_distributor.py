


class HouseholdSubsetDistributor(SubsetDistributor):  
    
    def find_subset_for_person(self,
                               venue_has_capacity: list[bool],
                               person: "Person",
                               **kwargs) -> int, subset_name, Optional["Subset"]:
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
          self.subsets = ['kid', 'young_adult', 'adult', 'old']
          venue_has_capacity = [True, True, True, True]
          if person.age < 15 and venue_has_capacity[0]:
              return 0, 'kid'
          elif person.age < 25 and venue_has_capacity[1]:
              return 1, 'young_adult'        
          elif person.age < 60 and venue_has_capacity[2]:
              return 2, 'adult'
          elif venue_has_capacity[3]:
              return 3, 'old'
          else:
              return -1, 'No subset available'

        """
        if person.age < 18 and venue_has_capacity[0]:
            return 0, 'kids'
        elif person.age <= 25 and venue_has_capacity[1]:
            return 1, 'independent children'        
        elif person.age < 60 and venue_has_capacity[2]:
            return 2, 'adults'
        elif venue_has_capacity[3]:
            return 3, 'elderly'
        else:
            return -1, 'No subset available'

