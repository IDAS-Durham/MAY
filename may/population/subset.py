from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from may.geography import Venue
    from .person import Person


class Subset:
    """A subset of people within a particular Venue. For example, children in a household."""
#    external = False
    __slots__ = (
        "venue",
        "subset_index",
        'subset_name',
        'members',
        'member_metadata',
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
          members (set[Person], optional): an optional set of the people in this subset.
        """
        self.venue = venue
        self.subset_index = subset_index
        self.subset_name = subset_name if subset_name is not None else str(self.subset_index)
        self.members= members if members is not None else set()
        self.member_metadata = {}

    @property
    def spec(self):
        """ """
        return self.venue.type , self.subset_index

    def __len__(self):
        return len(self.members)

    def __str__(self):
        return "Class : {} , subset_name : {}, venue.id : {}, venue_name : {}, subset_membership : {}, members_present : {}".format(type(self), self.subset_name, self.venue.id, self.venue.name, len(self.members), len(self))
    
    def __eq__(self, other):
        if not self.num_members == other.num_members:
            return False
        if not self.spec == other.spec:
            return False
        if not self.venue == other.venue:
            return False
        if not self.subset_index == other.subset_index:
            return False
        for p, p2 in zip(self.members, other.members):
            if not p == p2:
                return False
        return True

    def add_member(self, person: "Person"):
        """ Add a person's membership to this subset"""
        self.members.add(person)

    def remove_member(self, person: "Person"):
        """ Add a person's membership to this subset"""
        self.members.remove(person)

    @property
    def num_members(self):
        return len(self.members)
