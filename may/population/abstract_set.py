from abc import abstractmethod, ABC, abstractproperty

class AbstractSet(ABC):
    """Represents properties common to sets of people.

    A set is typically going to be used as a set of people within a particular Venue who behave in a certain way.
    They will usually have something in common that means they are distinguished from other people in that Venue,
    e.g. in how they behave, or in how susceptible they are to the disease. 
    """
    @abstractmethod
    def _collate(self, attribute: str, ifnot=False) -> list["Person"]:
        """Collates Persons from the set that have a particular attribute == True.

        Requires that the attribute called for is truthy (a boolean). 

        Args:
            attribute (str): the attribute to look at (e.g. 'dead', or 'susceptible', or 'infected').
            ifnot (bool, optional): if True, looks for people where the attribute is False. 

        Returns:
            (list[Person]) : a list of people filtered so the given attribute is True/False. 
        """
        pass

    @property
    @abstractmethod
    def size_collated(self, attribute, ifnot=False) -> int:
        """ """
        return len(self._collate(attribute, ifnot=ifnot))

    
    @property
    def size(self) -> int:
        """ """
        return len(self.people)

    @property
    def contains_people(self) -> bool:
        """Whether or not the group contains people.

        """
        return self.size() > 0

    

    
    
