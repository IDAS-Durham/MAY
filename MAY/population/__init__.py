"""
Population module for June Zero.

This module provides generic, aspacial, and atemporal population generation
for any geographical hierarchy.
"""

from .person import Person
from .population import PopulationManager

__all__ = ['Person', 'PopulationManager']
