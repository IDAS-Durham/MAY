"""
Venue Distributor Module

This module provides a flexible, YAML-driven system for distributing people to venues.
The system reads configuration from YAML files in yaml/distributors/ and allocates
people to venues based on attributes, distance, and capacity constraints.

Classes:
    VenueDistributor: Main class for venue allocation
"""

from .venue_distributor import VenueDistributor

__all__ = ['VenueDistributor']
