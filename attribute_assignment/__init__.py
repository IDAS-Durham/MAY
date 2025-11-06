"""
Attribute Assignment System for June Zero.

This module provides a generic, rule-based system for assigning attributes
(ethnicity, religion, language, etc.) to people AFTER they have been allocated
to households and venues.

Key components:
- assignment_config: Parse YAML configuration files (V1)
- assignment_config_v2: Parse V2 YAML configuration files (V2 - simplified)
- data_sources: Load demographic data from CSV files
- strategies: Assignment strategy implementations (V1)
- strategies_v2: Assignment strategy implementations (V2 - simplified)
- assigner: Main orchestrator for attribute assignment (V1)
- assigner_v2: Main orchestrator for attribute assignment (V2 - simplified)

Usage (V1):
    from attribute_assignment import assign_attributes

    stats = assign_attributes(
        venue_manager=venue_manager,
        config_path="yaml/attribute_assignment_ethnicity.yaml",
        geo_units={'E00000001', 'E00000002'}  # Optional
    )

Usage (V2 - Recommended):
    from attribute_assignment import assign_attributes_v2

    stats = assign_attributes_v2(
        venue_manager=venue_manager,
        config_path="yaml/attribute_assignment_v2.yaml",
        geo_units={'E00000001', 'E00000002'}  # Optional
    )
"""

# V2 imports
from attribute_assignment.assignment_config_v2 import AttributeAssignmentConfigV2
from attribute_assignment.strategies_v2 import StrategyFactoryV2
from attribute_assignment.assigner_v2 import AttributeAssignerV2, assign_attributes_v2

__all__ = [
    # V2
    'AttributeAssignmentConfigV2',
    'StrategyFactoryV2',
    'AttributeAssignerV2',
    'assign_attributes_v2',
]
