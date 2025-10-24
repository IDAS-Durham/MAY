from typing import Optional
from may.distributor import SubsetDistributor

class CareHomeSubsetDistributor(SubsetDistributor):

    def __init__(self,*args, **kwargs):
        super().__init__(self,*args, **kwargs)
        self.age_category_capacity = [
#            ('under 50', 0, 50, 'unknown'),
            ('age_50_64_female', 50, 65, 'female'),
            ('age_50_64_male', 50, 65, 'male'),
            ('age_65_74_female', 65, 75, 'female'),
            ('age_65_74_male', 65, 74, 'male'),
            ('age_75_84_female', 75, 84, 'female'),
            ('age_75_84_male', 75, 84, 'male'),
            ('age_85_94_female', 85, 94, 'female'),
            ('age_85_94_male', 85, 94, 'male'),
            ('age_95_plus_female', 95, 1000, 'female'),
            ('age_95_plus_male', 95, 1000, 'male'),
        ] # should be the same as in care_home distributor

    def person_in_age_range(self, person, minage, maxage):
        return minage <= person.age < maxage
    
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
            'under 50',
            'age_50_64_female',
            'age_50_64_male',
            'age_65_74_female',
            'age_65_74_male',
            'age_75_84_female',
            'age_75_84_male',
            'age_85_94_female',
            'age_85_94_male',
            'age_95_plus_female',
            'age_95_plus_male',
        ] # should be the same as in care_home distributor
        
        """
        if activity == 'home':
            for i, tup in enumerate(self.age_category_capacity):
                if person_in_age_range(person, tup[1], tup[2]):
                    if tup[3] == unknown:
                        has_capacity = venue_has_capacity[i]
                    elif person.sex == tup[3]:
                        has_capacity = venue_has_capacity[i]
            if person.sex == 'male' and has_capacity:
                return i, tup[0]
            elif person.sex == 'female' and has_capacity:
                return i, tup[0]
            else:
                return -1, 'No subset available'

        if activity == 'work' and venue_has_capacity[-1]:
            return len(venue_has_capacity)-1, 'number_staff'
        else:
            return -1, 'No subset available'
