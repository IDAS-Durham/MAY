"""
V2 Configuration system for attribute assignment.

Simplified from v1:
- Roles are mapped to household subsets (Kids, Young Adults, Adults, Old Adults)
- Household structures use flexible pattern matching with actual/original conditions
- Assignment rules are organized by household structure type
- Cleaner, more user-friendly configuration format
"""

import yaml
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
from may.residence.composition_pattern import CompositionPattern

logger = logging.getLogger("attribute_assignment.v2")


@dataclass
class MatchingRule:
    """
    A rule for matching household patterns.

    Can match based on:
    - actual pattern only
    - original pattern only
    - both actual AND original patterns (conditional matching)
    """
    actual_patterns: List[str] = field(default_factory=list)
    original_patterns: List[str] = field(default_factory=list)
    description: str = ""

    def matches(self, household, verbose: bool = False) -> bool:
        """
        Check if a household matches this rule.

        Args:
            household: Venue object with original_pattern and actual_pattern properties
            verbose: If True, log matching details

        Returns:
            True if household matches this rule
        """
        original_pattern = household.properties.get('original_pattern', '')
        actual_pattern = household.properties.get('actual_pattern', '')

        if verbose:
            logger.debug(f"      Testing matching rule:")
            logger.debug(f"        Description: {self.description}")
            logger.debug(f"        Household: original='{original_pattern}', actual='{actual_pattern}'")

        # If both actual and original are specified, BOTH must match
        if self.actual_patterns and self.original_patterns:
            actual_match = self._matches_any_pattern(actual_pattern, self.actual_patterns)
            original_match = original_pattern in self.original_patterns

            if verbose:
                logger.debug(f"        Actual match: {actual_match}")
                logger.debug(f"        Original match: {original_match}")

            return actual_match and original_match

        # If only actual patterns specified
        if self.actual_patterns:
            match = self._matches_any_pattern(actual_pattern, self.actual_patterns)
            if verbose:
                logger.debug(f"        Actual match: {match}")
            return match

        # If only original patterns specified
        if self.original_patterns:
            match = original_pattern in self.original_patterns
            if verbose:
                logger.debug(f"        Original match: {match}")
            return match

        # No patterns specified - always matches
        return True

    def _matches_any_pattern(self, actual_pattern: str, template_patterns: List[str]) -> bool:
        """
        Check if actual pattern matches any of the template patterns.
        Uses CompositionPattern for flexible matching with >=, <=, etc.
        """
        for template in template_patterns:
            if self._pattern_matches(actual_pattern, template):
                return True
        return False

    def _pattern_matches(self, actual: str, template: str) -> bool:
        """
        Check if an actual pattern matches a template pattern.

        Examples:
            actual="2 0 2 0", template=">=1 >=0 2 0" -> True
            actual="0 1 2 0", template=">=1 >=0 2 0" -> False
            actual="2 1 2 0", template="0 >=1 1 <=2" -> False (has kids)
            actual="0 1 1 1", template="0 >=1 1 <=2" -> True
        """
        # Parse actual pattern into counts
        actual_counts = [int(x) for x in actual.split()]

        # Parse template pattern using CompositionPattern
        template_pattern = CompositionPattern.from_string(template)

        # Check each category
        if len(actual_counts) != len(template_pattern.requirements):
            return False

        for i, actual_count in enumerate(actual_counts):
            operator, required_count = template_pattern.requirements[i]

            if operator == "exact":
                if actual_count != required_count:
                    return False
            elif operator == "gte":
                if actual_count < required_count:
                    return False
            elif operator == "lte":
                if actual_count > required_count:
                    return False

        return True


@dataclass
class HouseholdStructureV2:
    """
    V2 household structure with flexible matching rules.
    """
    name: str
    description: str
    inheritance: bool  # Whether this structure uses inheritance
    matching_rules: List[MatchingRule] = field(default_factory=list)

    def matches(self, household, verbose: bool = False) -> bool:
        """
        Check if household matches this structure.
        Returns True if ANY matching rule matches.
        """
        if verbose:
            logger.debug(f"    Testing structure '{self.name}':")
            logger.debug(f"      {len(self.matching_rules)} matching rule(s)")

        for rule in self.matching_rules:
            if rule.matches(household, verbose=verbose):
                if verbose:
                    logger.debug(f"    ✓ MATCHED structure '{self.name}'")
                return True

        if verbose:
            logger.debug(f"    ✗ No match for structure '{self.name}'")
        return False


@dataclass
class RoleV2:
    """
    V2 role definition - maps to household subsets instead of conditions.
    """
    name: str
    description: str
    subsets: List[str]  # List of subset names this role applies to

    def matches(self, person, verbose: bool = False) -> bool:
        """
        Check if person's subset matches this role.
        """
        # Get person's subset from household allocation
        if "household" not in person.activity_map or not person.activity_map["household"]:
            return False

        person_subset = person.activity_map["household"][0].subset_name

        if verbose:
            logger.debug(f"        Testing role '{self.name}': person_subset='{person_subset}', role_subsets={self.subsets}")

        return person_subset in self.subsets


@dataclass
class AssignmentRuleV2:
    """
    V2 assignment rule - simpler than v1.
    """
    role: str  # Can also be list of roles (parsed from config)
    priority: int
    description: str
    assignment: Dict[str, Any]

    def applies_to_role(self, role_name: str) -> bool:
        """Check if this rule applies to a role."""
        if isinstance(self.role, list):
            return role_name in self.role
        return role_name == self.role


@dataclass
class StructureAssignmentRulesV2:
    """
    Assignment rules for a specific household structure.
    """
    structure_name: str
    description: str
    rules: List[AssignmentRuleV2] = field(default_factory=list)


class AttributeAssignmentConfigV2:
    """
    V2 configuration loader for attribute assignment.

    Much simpler than v1:
    - Roles map to subsets
    - Structures use matching_rules
    - Assignment rules organized by structure
    """

    def __init__(self, config_path: Path):
        """Load v2 configuration from YAML."""
        self.config_path = Path(config_path)

        with open(self.config_path, 'r') as f:
            self.raw_config = yaml.safe_load(f)

        # Parse sections
        self.attribute_name = self._parse_attribute()
        self.roles = self._parse_roles()
        self.household_structures = self._parse_household_structures()
        self.data_sources = self._parse_data_sources()
        self.assignment_rules = self._parse_assignment_rules()
        self.venue_assignment_rules = self._parse_venue_assignment_rules()
        self.settings = self._parse_settings()

        logger.info(f"Loaded v2 config for '{self.attribute_name}' from {self.config_path}")
        logger.info(f"  Roles: {len(self.roles)}")
        logger.info(f"  Household structures: {len(self.household_structures)}")
        logger.info(f"  Structure-based assignment rules: {len(self.assignment_rules)}")

    def _parse_attribute(self) -> str:
        """Parse attribute name."""
        return self.raw_config.get('attribute', {}).get('name', 'unknown')

    def _parse_roles(self) -> Dict[str, RoleV2]:
        """Parse role definitions."""
        roles = {}
        roles_config = self.raw_config.get('roles', {})

        for role_name, role_data in roles_config.items():
            if not isinstance(role_data, dict):
                continue

            roles[role_name] = RoleV2(
                name=role_name,
                description=role_data.get('description', ''),
                subsets=role_data.get('subsets', [])
            )

        return roles

    def _parse_household_structures(self) -> Dict[str, HouseholdStructureV2]:
        """Parse household structure definitions."""
        structures = {}
        structures_config = self.raw_config.get('household_structures', {})

        for struct_name, struct_data in structures_config.items():
            if not isinstance(struct_data, dict):
                continue

            # Parse matching rules
            matching_rules = []
            for rule_data in struct_data.get('matching_rules', []):
                matching_rules.append(MatchingRule(
                    actual_patterns=rule_data.get('actual', []),
                    original_patterns=rule_data.get('original', []),
                    description=rule_data.get('description', '')
                ))

            structures[struct_name] = HouseholdStructureV2(
                name=struct_name,
                description=struct_data.get('description', ''),
                inheritance=struct_data.get('inheritance', False),
                matching_rules=matching_rules
            )

        return structures

    def _parse_data_sources(self) -> Dict[str, Dict[str, Any]]:
        """Parse data sources (same as v1)."""
        return self.raw_config.get('data_sources', {})

    def _parse_assignment_rules(self) -> Dict[str, StructureAssignmentRulesV2]:
        """Parse structure-based assignment rules."""
        structure_rules = {}
        rules_config = self.raw_config.get('assignment_rules', {})

        for structure_name, struct_rules_data in rules_config.items():
            if not isinstance(struct_rules_data, dict):
                continue

            rules = []
            for rule_data in struct_rules_data.get('rules', []):
                rules.append(AssignmentRuleV2(
                    role=rule_data.get('role'),  # Can be string or list
                    priority=rule_data.get('priority', 999),
                    description=rule_data.get('description', ''),
                    assignment=rule_data.get('assignment', {})
                ))

            # Sort rules by priority
            rules.sort(key=lambda r: r.priority)

            structure_rules[structure_name] = StructureAssignmentRulesV2(
                structure_name=structure_name,
                description=struct_rules_data.get('description', ''),
                rules=rules
            )

        return structure_rules

    def _parse_venue_assignment_rules(self) -> List[Dict[str, Any]]:
        """Parse venue assignment rules."""
        return self.raw_config.get('venue_assignment_rules', [])

    def _parse_settings(self) -> Dict[str, Any]:
        """Parse settings."""
        return self.raw_config.get('settings', {})

    def get_household_structure(self, household, verbose: bool = False) -> Optional[str]:
        """
        Classify household structure.
        Returns first matching structure.
        """
        if verbose:
            logger.debug(f"  Classifying household {household.id}:")

        for struct_name, structure in self.household_structures.items():
            if structure.matches(household, verbose=verbose):
                return struct_name

        if verbose:
            logger.debug(f"  ✗ No structure matched")
        return None

    def get_person_role(self, person, household_structure: str,
                       assigned_roles: List[str], verbose: bool = False) -> Optional[str]:
        """
        Determine person's role based on their subset and household structure.

        Args:
            person: Person object
            household_structure: Name of household structure
            assigned_roles: List of roles already assigned in this household
            verbose: If True, log matching details

        Returns:
            Role name or None
        """
        if verbose:
            logger.debug(f"    Determining role for {person}:")

        # Get assignment rules for this structure
        if household_structure not in self.assignment_rules:
            if verbose:
                logger.debug(f"      No assignment rules for structure '{household_structure}'")
            return None

        struct_rules = self.assignment_rules[household_structure]

        # Try each role in order until we find a matching one
        for role_name, role in self.roles.items():
            if verbose:
                logger.debug(f"      Testing role '{role_name}':")

            # Check if person's subset matches this role
            if not role.matches(person, verbose=verbose):
                if verbose:
                    logger.debug(f"        ✗ Subset doesn't match")
                continue

            # Check if this role has been assigned already (for primary/secondary distinction)
            role_count = assigned_roles.count(role_name)

            # Determine if we should assign this role based on count and naming
            # primary_* -> first occurrence
            # secondary_* -> second occurrence
            # extra_* -> third+ occurrences
            if role_name.startswith('primary_') and role_count == 0:
                if verbose:
                    logger.debug(f"      ✓ Assigned role '{role_name}' (primary)")
                return role_name
            elif role_name.startswith('secondary_') and role_count == 0:
                # Check if primary was assigned
                primary_role = role_name.replace('secondary_', 'primary_')
                if primary_role in assigned_roles:
                    if verbose:
                        logger.debug(f"      ✓ Assigned role '{role_name}' (secondary)")
                    return role_name
            elif role_name.startswith('extra_'):
                # Check if both primary and secondary were assigned
                primary_role = role_name.replace('extra_', 'primary_')
                secondary_role = role_name.replace('extra_', 'secondary_')
                if primary_role in assigned_roles and secondary_role in assigned_roles:
                    if verbose:
                        logger.debug(f"      ✓ Assigned role '{role_name}' (extra)")
                    return role_name
            elif not role_name.startswith(('primary_', 'secondary_', 'extra_')):
                # For non-primary/secondary/extra roles (like 'children', 'independent_young')
                if verbose:
                    logger.debug(f"      ✓ Assigned role '{role_name}'")
                return role_name

        if verbose:
            logger.debug(f"      ✗ No role matched")
        return None

    def get_assignment_rule(self, household_structure: str, role: str,
                           verbose: bool = False) -> Optional[AssignmentRuleV2]:
        """
        Get assignment rule for a role within a structure.
        """
        if household_structure not in self.assignment_rules:
            return None

        struct_rules = self.assignment_rules[household_structure]

        for rule in struct_rules.rules:
            if rule.applies_to_role(role):
                if verbose:
                    logger.debug(f"    ✓ Found rule for role '{role}'")
                return rule

        if verbose:
            logger.debug(f"    ✗ No rule for role '{role}'")
        return None

    @classmethod
    def from_yaml(cls, config_path: Path) -> 'AttributeAssignmentConfigV2':
        """Load configuration from YAML file."""
        return cls(config_path)
