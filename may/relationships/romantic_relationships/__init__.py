"""
Romantic relationships submodule.

Handles sexual orientation assignment, romantic partnership creation,
and relationship dynamics including exclusive, non-exclusive, and affair relationships.
"""

from .romantic_relationship_distributor import RomanticRelationshipDistributor
from .compatibility_scorer import CompatibilityScorer

__all__ = [
    'RomanticRelationshipDistributor',
    'CompatibilityScorer'
]
