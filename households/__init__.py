"""
Household distribution module for June Zero.

Generic, atemporal, and aspatial system for distributing people into
households and communal establishments. Handles data inconsistencies
and reconciliation.
"""

from .household import Household
from .communal_establishment import CommunalEstablishment
from .distributor import HouseholdDistributor
from .config_loader import ConfigLoader
from .rule_engine import (
    RoleResolver,
    ConstraintValidator,
    HouseholdCreationRule,
    RuleEngine,
    AllocationExecutor
)

__all__ = [
    'Household',
    'CommunalEstablishment',
    'HouseholdDistributor',
    'ConfigLoader',
    'RoleResolver',
    'ConstraintValidator',
    'HouseholdCreationRule',
    'RuleEngine',
    'AllocationExecutor',
]
