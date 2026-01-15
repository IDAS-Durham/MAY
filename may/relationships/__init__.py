"""
Relationships module for June Zero.

Provides generic, configurable relationship network building between agents.
All relationship types and criteria are defined via YAML configuration.
"""

from .friendship_builder import FriendshipBuilder
from .romantic_relationships import VectorizedRomanticDistributor

__all__ = [
    'FriendshipBuilder',
    'VectorizedRomanticDistributor'
]
