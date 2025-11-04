"""
YAML configuration parser for attribute assignment system.

This module parses YAML configuration files that define how to assign attributes
to people based on household structure, person roles, and assignment rules.
"""

import yaml
import logging
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("attribute_assignment")


@dataclass
class HouseholdStructure:
    """
    Defines a household structure classification.

    Household structures are identified by comparing original and actual patterns.
    This allows distinguishing between intended structure (e.g., family) and
    actual composition (e.g., couple without kids).

    Attributes:
        name: Identifier for this structure (e.g., "family_with_kids")
        description: Human-readable description
        patterns: Dict with 'original' and 'actual' pattern lists
        conditions: Additional conditions to check (list of condition strings)
    """
    name: str
    description: str
    patterns: Dict[str, List[str]] = field(default_factory=dict)
    conditions: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Pre-compile condition expressions for performance."""
        # Compile each condition string once for faster evaluation
        self._compiled_conditions = []
        for condition_str in self.conditions:
            try:
                compiled_code = compile(condition_str, '<string>', 'eval')
                self._compiled_conditions.append((condition_str, compiled_code))
            except SyntaxError as e:
                logger.warning(f"Failed to compile condition '{condition_str}': {e}")
                self._compiled_conditions.append((condition_str, None))

    def matches(self, household) -> bool:
        """
        Check if a household matches this structure.

        Args:
            household: Venue object (with type="household")

        Returns:
            True if household matches this structure's criteria
        """
        # Get patterns from household properties
        original_pattern = household.properties.get('original_pattern', '')
        actual_pattern = household.properties.get('actual_pattern', '')

        # Check original patterns (highest priority)
        if 'original' in self.patterns:
            if original_pattern in self.patterns['original']:
                # Original pattern match - check conditions
                if self._evaluate_conditions(household):
                    return True

        # Check actual patterns with conditions
        if 'actual' in self.patterns:
            if actual_pattern in self.patterns['actual']:
                # Actual pattern match - must also satisfy conditions
                if self._evaluate_conditions(household):
                    return True

        return False

    def _evaluate_conditions(self, household) -> bool:
        """
        Evaluate all conditions for this household.

        Args:
            household: Venue object

        Returns:
            True if all conditions are satisfied
        """
        if not self._compiled_conditions:
            return True

        # Create safe evaluation context once for all conditions
        context = {
            'household': household,
            'not': lambda x: not x,
            'len': len,
        }

        for condition_str, compiled_code in self._compiled_conditions:
            if not self._evaluate_single_condition(household, condition_str, compiled_code, context):
                return False

        return True

    def _evaluate_single_condition(self, household, condition_str: str, compiled_code, context: Dict) -> bool:
        """
        Evaluate a single condition string using pre-compiled code.

        Examples of condition strings:
            - "household.size == 1"
            - "not household.original_pattern.startswith('0 >=0')"
            - "household.has_category('Adults')"

        Args:
            household: Venue object
            condition_str: Condition expression as string (for error messages)
            compiled_code: Pre-compiled code object or None if compilation failed
            context: Evaluation context dict

        Returns:
            True if condition is satisfied
        """
        try:
            # Skip if compilation failed
            if compiled_code is None:
                return False

            # Evaluate the pre-compiled condition
            result = eval(compiled_code, {"__builtins__": {}}, context)
            return bool(result)
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition_str}': {e}")
            return False

    def __repr__(self):
        return f"HouseholdStructure({self.name})"


@dataclass
class PersonRole:
    """
    Defines a person's role within a household.

    Roles determine which assignment rule applies to a person.
    Examples: "primary_adult", "dependent_child", "elderly_in_family"

    Attributes:
        name: Identifier for this role
        description: Human-readable description
        conditions: List of condition strings to check
    """
    name: str
    description: str
    conditions: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Pre-compile condition expressions for performance."""
        # Compile each condition string once for faster evaluation
        self._compiled_conditions = []
        for condition_str in self.conditions:
            try:
                compiled_code = compile(condition_str, '<string>', 'eval')
                self._compiled_conditions.append((condition_str, compiled_code))
            except SyntaxError as e:
                logger.warning(f"Failed to compile condition '{condition_str}': {e}")
                self._compiled_conditions.append((condition_str, None))

    def matches(self, person, household, assignment_context: Optional[Dict] = None) -> bool:
        """
        Check if a person matches this role.

        Args:
            person: Person object
            household: Venue object (with type="household")
            assignment_context: Dict with assignment progress info (e.g., has_assigned_adult)

        Returns:
            True if person matches this role's criteria
        """
        if not self._compiled_conditions:
            return True

        # Prepare context for evaluation
        if assignment_context is None:
            assignment_context = {}

        # Create evaluation context once for all conditions
        eval_context = {
            'person': person,
            'household': household,
            'not': lambda x: not x,
            'len': len,
            **assignment_context  # Include assignment context (has_assigned_adult, etc.)
        }

        for condition_str, compiled_code in self._compiled_conditions:
            if not self._evaluate_condition(person, household, eval_context, condition_str, compiled_code):
                return False

        return True

    def _evaluate_condition(self, person, household, eval_context: Dict, condition_str: str, compiled_code) -> bool:
        """
        Evaluate a condition string for person role matching using pre-compiled code.

        Examples:
            - "person.category in ['Adults', 'Young Adults']"
            - "household.has_assigned_adult"
            - "household.structure == 'family_with_kids'"

        Args:
            person: Person object
            household: Venue object
            eval_context: Pre-built evaluation context dict
            condition_str: Condition expression as string (for error messages)
            compiled_code: Pre-compiled code object or None if compilation failed

        Returns:
            True if condition is satisfied
        """
        try:
            # Skip if compilation failed
            if compiled_code is None:
                return False

            # Evaluate the pre-compiled condition
            result = eval(compiled_code, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            logger.debug(f"Error evaluating role condition '{condition_str}': {e}")
            return False

    def __repr__(self):
        return f"PersonRole({self.name})"


@dataclass
class AssignmentRule:
    """
    Defines a rule for assigning attribute values.

    Rules are evaluated in priority order. Each rule specifies:
    - Which person roles it applies to
    - What assignment strategy to use
    - Any additional parameters for the strategy

    Attributes:
        name: Identifier for this rule
        priority: Execution priority (lower = earlier)
        description: Human-readable description
        applies_to: Dict specifying which roles/structures this applies to
        assignment: Dict with assignment strategy specification
    """
    name: str
    priority: int
    description: str
    applies_to: Dict[str, Any]
    assignment: Dict[str, Any]

    def applies_to_person(self, person, household, assignment_context: Optional[Dict] = None) -> bool:
        """
        Check if this rule applies to a person.

        Args:
            person: Person object
            household: Venue object
            assignment_context: Dict with assignment progress

        Returns:
            True if this rule should be applied to this person
        """
        if assignment_context is None:
            assignment_context = {}

        # Check person_role criteria
        if 'person_role' in self.applies_to:
            person_role_criteria = self.applies_to['person_role']
            person_role = assignment_context.get('person_role')

            # Handle list or single value
            if isinstance(person_role_criteria, list):
                if person_role not in person_role_criteria:
                    return False
            else:
                if person_role != person_role_criteria:
                    return False

        # Check household_structure criteria
        if 'household_structure' in self.applies_to:
            structure_criteria = self.applies_to['household_structure']
            household_structure = household.properties.get('_structure')

            # Handle list or single value
            if isinstance(structure_criteria, list):
                if household_structure not in structure_criteria:
                    return False
            else:
                if household_structure != structure_criteria:
                    return False

        return True

    def __repr__(self):
        return f"AssignmentRule({self.name}, priority={self.priority})"


@dataclass
class DataSourceConfig:
    """
    Configuration for a data source.

    Data sources provide probability distributions for attribute values
    based on context (e.g., area code, first person's ethnicity, etc.).

    Attributes:
        name: Identifier for this data source
        type: Type of data source (e.g., "csv_lookup")
        description: Human-readable description
        files: List of file configurations
        fallbacks: Fallback probability distributions
        config: Additional configuration dict
    """
    name: str
    type: str
    description: str
    files: List[Dict[str, Any]] = field(default_factory=list)
    fallbacks: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        return f"DataSourceConfig({self.name}, type={self.type})"


@dataclass
class VenueAssignmentRule:
    """
    Assignment rule for people in venues (not households).

    Simpler than household rules - typically just area-based probabilistic assignment.

    Attributes:
        venue_types: List of venue types this applies to
        description: Human-readable description
        assignment: Assignment strategy specification
    """
    venue_types: List[str]
    description: str
    assignment: Dict[str, Any]

    def applies_to_venue(self, venue_type: str) -> bool:
        """Check if this rule applies to a venue type."""
        return venue_type in self.venue_types

    def __repr__(self):
        return f"VenueAssignmentRule({self.venue_types})"


class AttributeAssignmentConfig:
    """
    Main configuration class for attribute assignment.

    Parses and holds all configuration from a YAML file:
    - Attribute metadata
    - Household structure definitions
    - Person role definitions
    - Data source configurations
    - Assignment rules
    - Venue assignment rules
    - Settings
    """

    def __init__(self, config_path: Union[str, Path]):
        """
        Initialize configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = Path(config_path)

        # Load YAML
        with open(self.config_path, 'r') as f:
            self.raw_config = yaml.safe_load(f)

        # Parse sections
        self.attribute_name = self._parse_attribute()
        self.household_structures = self._parse_household_structures()
        self.person_roles = self._parse_person_roles()
        self.data_sources = self._parse_data_sources()
        self.assignment_rules = self._parse_assignment_rules()
        self.venue_assignment_rules = self._parse_venue_assignment_rules()
        self.category_adjustments = self._parse_category_adjustments()
        self.settings = self._parse_settings()
        self.ethnicity_codes = self._parse_ethnicity_codes()

        logger.info(f"Loaded attribute assignment config for '{self.attribute_name}' from {self.config_path}")
        logger.info(f"  Household structures: {len(self.household_structures)}")
        logger.info(f"  Person roles: {len(self.person_roles)}")
        logger.info(f"  Data sources: {len(self.data_sources)}")
        logger.info(f"  Assignment rules: {len(self.assignment_rules)}")
        logger.info(f"  Venue assignment rules: {len(self.venue_assignment_rules)}")

    @classmethod
    def from_yaml(cls, config_path: Union[str, Path]) -> 'AttributeAssignmentConfig':
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            AttributeAssignmentConfig instance
        """
        return cls(config_path)

    def _parse_attribute(self) -> str:
        """Parse attribute metadata section."""
        attribute_config = self.raw_config.get('attribute', {})
        return attribute_config.get('name', 'unknown')

    def _parse_household_structures(self) -> Dict[str, HouseholdStructure]:
        """Parse household structure definitions."""
        structures = {}
        structures_config = self.raw_config.get('household_structures', {})

        for structure_name, structure_data in structures_config.items():
            # Skip non-dict entries (like notes)
            if not isinstance(structure_data, dict):
                continue

            structures[structure_name] = HouseholdStructure(
                name=structure_name,
                description=structure_data.get('description', ''),
                patterns=structure_data.get('patterns', {}),
                conditions=structure_data.get('conditions', [])
            )

        return structures

    def _parse_person_roles(self) -> Dict[str, PersonRole]:
        """Parse person role definitions."""
        roles = {}
        roles_config = self.raw_config.get('person_roles', {})

        for role_name, role_data in roles_config.items():
            # Skip non-dict entries
            if not isinstance(role_data, dict):
                continue

            roles[role_name] = PersonRole(
                name=role_name,
                description=role_data.get('description', ''),
                conditions=role_data.get('conditions', [])
            )

        return roles

    def _parse_data_sources(self) -> Dict[str, DataSourceConfig]:
        """Parse data source configurations."""
        sources = {}
        sources_config = self.raw_config.get('data_sources', {})

        for source_name, source_data in sources_config.items():
            sources[source_name] = DataSourceConfig(
                name=source_name,
                type=source_data.get('type', 'csv_lookup'),
                description=source_data.get('description', ''),
                files=source_data.get('files', []),
                fallbacks=source_data.get('fallbacks', []),
                config=source_data
            )

        return sources

    def _parse_assignment_rules(self) -> List[AssignmentRule]:
        """Parse assignment rules."""
        rules = []
        rules_config = self.raw_config.get('assignment_rules', [])

        for rule_data in rules_config:
            rules.append(AssignmentRule(
                name=rule_data.get('name', 'unnamed'),
                priority=rule_data.get('priority', 999),
                description=rule_data.get('description', ''),
                applies_to=rule_data.get('applies_to', {}),
                assignment=rule_data.get('assignment', {})
            ))

        # Sort by priority (lower = earlier)
        rules.sort(key=lambda r: r.priority)

        return rules

    def _parse_venue_assignment_rules(self) -> List[VenueAssignmentRule]:
        """Parse venue assignment rules."""
        rules = []
        rules_config = self.raw_config.get('venue_assignment_rules', [])

        for rule_data in rules_config:
            rules.append(VenueAssignmentRule(
                venue_types=rule_data.get('venue_types', []),
                description=rule_data.get('description', ''),
                assignment=rule_data.get('assignment', {})
            ))

        return rules

    def _parse_category_adjustments(self) -> Dict[str, Any]:
        """Parse category adjustments section."""
        return self.raw_config.get('category_adjustments', {})

    def _parse_settings(self) -> Dict[str, Any]:
        """Parse settings section."""
        return self.raw_config.get('settings', {})

    def _parse_ethnicity_codes(self) -> Dict[str, str]:
        """Parse ethnicity codes reference."""
        return self.raw_config.get('ethnicity_codes', {})

    def get_household_structure(self, household) -> Optional[str]:
        """
        Classify a household's structure.

        Args:
            household: Venue object (type="household")

        Returns:
            Structure name (str) or None if no match
        """
        for structure_name, structure in self.household_structures.items():
            if structure.matches(household):
                return structure_name

        return None

    def get_person_role(self, person, household, assignment_context: Optional[Dict] = None) -> Optional[str]:
        """
        Classify a person's role within a household.

        Args:
            person: Person object
            household: Venue object
            assignment_context: Dict with assignment progress

        Returns:
            Role name (str) or None if no match
        """
        for role_name, role in self.person_roles.items():
            if role.matches(person, household, assignment_context):
                return role_name

        return None

    def get_applicable_rule(self, person, household, assignment_context: Optional[Dict] = None) -> Optional[AssignmentRule]:
        """
        Find the first applicable assignment rule for a person.

        Rules are already sorted by priority, so return the first match.

        Args:
            person: Person object
            household: Venue object
            assignment_context: Dict with assignment progress

        Returns:
            AssignmentRule or None if no match
        """
        for rule in self.assignment_rules:
            if rule.applies_to_person(person, household, assignment_context):
                return rule

        return None

    def get_venue_rule(self, venue_type: str) -> Optional[VenueAssignmentRule]:
        """
        Find the assignment rule for a venue type.

        Args:
            venue_type: Type of venue (e.g., "care_home")

        Returns:
            VenueAssignmentRule or None if no match
        """
        for rule in self.venue_assignment_rules:
            if rule.applies_to_venue(venue_type):
                return rule

        return None

    def __repr__(self):
        return f"AttributeAssignmentConfig(attribute='{self.attribute_name}', rules={len(self.assignment_rules)})"
