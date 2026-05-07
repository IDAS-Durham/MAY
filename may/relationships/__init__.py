"""
Relationships module for MAY.

Provides generic, configurable relationship network building between agents.
All relationship types and criteria are defined via YAML configuration.
"""

from .friendship_builder import FriendshipBuilder
from .romantic_relationships import RomanticDistributor

__all__ = [
    'FriendshipBuilder',
    'RomanticDistributor'
]
