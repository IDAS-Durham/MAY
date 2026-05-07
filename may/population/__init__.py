"""
Population module for MAY.

This module provides generic, aspacial, and atemporal population generation
for any geographical hierarchy.
"""
from .abstract_set import AbstractSet
from .subset import Subset
from .person import Person
from .population import PopulationManager

__all__ = ['Person', 'PopulationManager']
