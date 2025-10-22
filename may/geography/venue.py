"""
Venue management for June Zero.
Venues are places where people live, work, learn, or receive services.
"""

import logging
import pandas as pd
import os

logger = logging.getLogger("venue")

class Venue:
    """
    Represents a place where people live, work, learn, or receive services.
    Generic design that works for any geography, past or present.

    Attributes:
      id (id):
        Unique numeric ID for the venue. Generated using id(),
        so will essentially be the memory location of the Venue instance.
      name (str):
        A string giving the name of the venue, e.g. "St Mary's Hospital".
      type :
        A label for the type of venue. Usually a string e.g. "hospital", "school", "household".
      geographical_unit :
        Reference to the GeographicalUnit in which the Venue is located.
      coordinates (tuple[float, float], optional):
        Latitude, longitude tuple. Default is None.
      properties (dict, optional):
        Extensible dict for venue-specific data. Default is {'subgroups':['default']}, which gives a list of the subgroup names for that specific venue. By default, the Venue object has a single subgroup called 'everyone' 
    """
    def __init__(self,
                 name: str,
                 venue_type,
                 geographical_unit,
                 coordinates=None,
                 properties: dict={},
                 subsets: dict[str,"Subset"] = {},
                 ):
        self.id = id(self)              # Unique numeric ID (generated)
        self.name = name                # Name of the venue (e.g., "St Mary's Hospital")
        self.type = venue_type          # Type of venue (e.g., "hospital", "school")
        self.geographical_unit = geographical_unit  # Reference to GeographicalUnit
        self.coordinates = coordinates  # Optional (latitude, longitude) tuple
        self.subsets = subsets # dict(subset_name, Subset object)
        self.properties = properties

    def __repr__(self):
        geo_name = self.geographical_unit.name if self.geographical_unit else "None"
        return f"<Venue #{self.id}: {self.name} ({self.type}) in {geo_name}>"

    def __eq__(self, other):
        """Tests the equality of two Venue objects. """
        for attribute in ['id', 'name', 'type', 'geographic_unit', 'coordinates']:
            if hasattr(self, attribute) ^ hasattr(other, attribute):
                return False
            elif hasattr(self, attribute) and hasattr(other, attribute):
                if not (getattr(self, attribute) == getattr(other, attribute)):
                    return False
        if not (self.properties == other.properties):
            return False
        return True
