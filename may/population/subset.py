from .abstract_set import AbstractSet

class Subset(AbstractSet):
    """A subset of people within a particular Venue. For example, children in a household."""
#    external = False
    __slots__ = (
        "venue",
        "subset_index",
        "people_present",
        'subset_name',
        'members'
    )

    def __init__(self,
                 venue: "Venue",
                 subset_index: int,
                 subset_name: str = None,
                 members: set["Person"]=None,
                 ):
        """
        Args:
          venue (Venue): the location in which this subset is situated.
          subset_index (int): index of the subset within the Venue's contact matrix.
          subset_name (str, optional): the string denoting which subset this is within the Venue. Default is str(subset_index).
          people_present (list[Person], optional): an optional list of people to immediately put in the subset. Default is [].
          members (set[Person], optional): an optional set of the people who might go to the subset if their activity comes up.
        """
        self.venue = venue
        self.subset_index = subset_index
        self.subset_name = subset_name if subset_name is not None else str(self.subset_index)
        self.members= members if members is not None else set()

    def _collate(self, attribute: str, ifnot=False) -> list["Person"]:
        """Collates Persons from self.people_present that have a particular attribute == True.

        Requires that the attribute called for is truthy (a boolean). 

        Args:
            attribute (str): the attribute to look at (e.g. 'dead', or 'susceptible', or 'infected').
            ifnot (bool, optional): if True, looks for people where the attribute is False. 

        Returns:
            (list[Person]) : a list of people_present filtered so the given attribute is True/False. 
        """
        if ifnot:
            return [person for person in self.members if not getattr(person, attribute)]
        else:
            return [person for person in self.members if getattr(person, attribute)]

    @property
    def size_collated(self, attribute, ifnot=False) -> int:
        """ """
        return len(self._collate(attribute, ifnot=ifnot))

    @property
    def spec(self):
        """ """
        return self.venue.type , self.subset_index
    
    def __contains__(self, item):
        return item in self.people_present

    def __iter__(self):
        return iter(self.members)

    def __len__(self):
        return len(self.members)

    def __str__(self):
        return "Class : {} , subset_name : {}, venue.id : {}, venue_name : {}, subset_membership : {}, members_present : {}".format(type(self), self.subset_name, self.venue.id, self.venue.name, len(self.members), len(self))
    
    def __eq__(self, other):
        if not self.size == other.size:            
            return False
        if not self.spec == other.spec:
            return False
        if not self.venue == other.venue:
            return False
        if not self.subset_index == other.subset_index:
            return False
        for p, p2 in zip(self.people_present, other.people_present):
            if not p == p2:
                return False
        return True

    def __getitem__(self, item):
        return list(self.members)[item]

    def add_member(self, person: "Person"):
        """ Add a person's membership to this subset"""
        self.members.add(person)

    def remove_member(self, person: "Person"):
        """ Add a person's membership to this subset"""
        self.members.remove(person)

    @property
    def num_members(self):
        return len(self.members)
