from abstract_set import AbstractSet

class Subset(AbstractSet):
    """A group within a group. For example, children in a household. """
#    external = False
    __slots__ = ("venue", "subset_type", "people")

    def __init__(self, venue: "Venue", subset_index: int, subset_name: str = None, people: list["Person"]=[]):
        """
        Args:
          venue (Venue): the location in which this subset is situated.
          subset_index (int): index of the subset within the Venue's contact matrix.
          subset_name (str, optional): the string denoting which subset this is within the Venue. Default is str(subset_index).
          people (list[Person], optional): an optional list of people to immediately put in the subset. Default is []. 
        """
        self.venue = venue
        self.subset_index = subset_index
        self.people = people
        if subset_name is None:
            self.subset_name = str(self.subset_index)

    def _collate(self, attribute: str, ifnot=False) -> list[Person]:
        """Collates Persons from self.people that have a particular attribute == True.

        Requires that the attribute called for is truthy (a boolean). 

        Args:
            attribute (str): the attribute to look at (e.g. 'dead', or 'susceptible', or 'infected').
            ifnot (bool, optional): if True, looks for people where the attribute is False. 

        Returns:
            (list[Person]) : a list of people filtered so the given attribute is True/False. 
        """
        if ifnot:
            return [person for person in self.people if not getattr(person, attribute)]
        else:
            return [person for person in self.people if getattr(person, attribute)]

    @property
    def size_collated(self, attribute, ifnot=False) -> int:
        """ """
        return len(self._collate(attribute, ifnot=ifnot))

    @property
    def spec(self):
        """ """
        return self.venue.type , self.subset_index

    @property
    def infected(self):
        """ """
        return self._collate("infected")

    @property
    def susceptible(self):
        """ """
        return self._collate("susceptible")

    @property
    def recovered(self):
        """ """
        return self._collate("recovered")

    @property
    def dead(self):
        """ """
        return self._collate("dead")

    
    # @property
    # def in_hospital(self):
    #     """ """
    #     return self._collate("in_hospital")

    def __contains__(self, item):
        return item in self.people

    def __iter__(self):
        return iter(self.people)

    def __len__(self):
        return len(self.people)

    def __eq__(self, other):
        if not self.size() == other.size():
            return False
        if not all(self.spec() == other.spec()):
            return False
        if not self.venue == other.venue:
            return False
        if not self.subset_index == other.subset_index:
            return False
        for p, p2 in zip(self.people, other.people):
            if not p == p2:
                return False
        return True

    def clear(self):
        """ """
        self.people = []

    def append(self, person: "Person"):
        """Add a person to this subset

        Args:
            person (Person): 
        
        """
        self.people.append(person)
        person.busy = True

    def extend(self, people: list["Person"]):
        """Add a list of people to the subset

        Args:
            people (list[Person]): 
        
        """
        self.people.extend(person)
        for person in people:
            person.busy = True

    def remove(self, person: "Person"):
        """

        Args:
            person (Person): 
        
        """
        self.people.remove(person)
        person.busy = False

    def __getitem__(self, item):
        return list(self.people)[item]

