"""
Attribute Assignment System for June Zero.

This module provides a generic, rule-based system for assigning attributes
(ethnicity, religion, language, etc.) to people AFTER they have been allocated
to households and venues.

Key components:
- assignment_config: Parse YAML configuration files
- data_sources: Load demographic data from CSV files
- strategies: Assignment strategy implementations
- assigner: Main orchestrator for attribute assignment

Usage:
    from attribute_assignment import assign_attributes

    stats = assign_attributes(
        venue_manager=venue_manager,
        config_path="yaml/attribute_assignment.yaml",
        geo_units={'E00000001', 'E00000002'}  # Optional
    )
"""

from attribute_assignment.assignment_config import AttributeAssignmentConfig
from attribute_assignment.strategies import StrategyFactory
from attribute_assignment.assigner import AttributeAssigner, assign_attributes

__all__ = [
    'AttributeAssignmentConfig',
    'StrategyFactory',
    'AttributeAssigner',
    'assign_attributes',
]
