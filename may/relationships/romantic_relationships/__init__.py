"""
Romantic relationships submodule.

Handles sexual orientation assignment, romantic partnership creation,
and relationship dynamics including exclusive, non-exclusive, and affair relationships.

Two implementations available:
- RomanticRelationshipDistributor: Original implementation (flexible but slower)
- VectorizedRomanticDistributor: NumPy/Numba optimized (60M+ scale)
"""

from .vectorized_distributor import VectorizedRomanticDistributor

__all__ = [
    'VectorizedRomanticDistributor'
]
