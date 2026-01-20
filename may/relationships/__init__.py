"""
Relationships module for June Zero.

Provides generic, configurable relationship network building between agents.
All relationship types and criteria are defined via YAML configuration.
"""

from .relationship_builder import RelationshipBuilder

__all__ = ['RelationshipBuilder']
