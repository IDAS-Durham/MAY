"""
Population module for MAY.

This module provides generic, aspacial, and atemporal population generation
for any geographical hierarchy.
"""

from .subset import Subset  # noqa: F401
from .person import Person
from .population import PopulationManager, PopulationError

__all__ = ["Person", "PopulationManager", "PopulationError"]
