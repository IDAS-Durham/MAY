"""
Configuration system for attribute assignment.

Simplified attribute assignment configuration:
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
from functools import lru_cache
from may.residence.composition_pattern import CompositionPattern
from may.attribute_assignment.strategies import validate_assignment_config
from may.utils import path_resolver as pr

logger = logging.getLogger("may.attribute_assignment.config")


@lru_cache(maxsize=4096)
def _pattern_matches_cached(actual: str, template: str) -> bool:
    """
    Cached pattern matching function.

    Check if an actual pattern matches a template pattern.

    Examples:
        actual="2 0 2 0", template=">=1 >=0 2 0" -> True
        actual="0 1 2 0", template=">=1 >=0 2 0" -> False
    """
    # Handle empty patterns
    if not actual or not template:
        return False

    # Parse actual pattern into counts
    try:
        actual_counts = [int(x) for x in actual.split()]
    except ValueError:
        return False

    # Parse template pattern using CompositionPattern (which is now cached)
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
class DataSourceConfig:
    """
    Configuration for a data source.

    Data sources provide probability distributions for attribute values
    based on context (e.g., geographical unit code, first person's ethnicity, etc.).
    """
    name: str
    type: str
    description: str
    files: List[Dict[str, Any]] = field(default_factory=list)
    fallbacks: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


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

        # Compute actual pattern from household members
        actual_pattern = self._compute_actual_pattern(household)

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

    def _compute_actual_pattern(self, household) -> str:
        """
        Compute the actual composition pattern from household members.

        Args:
            household: Venue object with members

        Returns:
            Pattern string like "2 0 2 0" (counts per category)
        """
        # Check if pattern is already cached on the household
        cached_pattern = household.properties.get('_cached_actual_pattern')
        if cached_pattern is not None:
            return cached_pattern

        # Get age categories from household properties
        age_categories = household.properties.get('_age_categories', [])
        if not age_categories:
            # Try to get from config if available
            # For now, return empty string
            return ''

        # Build category name → index mapping
        category_indices = {cat.name: i for i, cat in enumerate(age_categories)}

        # Count members in each category
        counts = [0] * len(age_categories)

        members = household.get_all_members()
        for person in members:
            # Get person's household category from activity_map
            # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
            if "residence" in person.activity_map and "household" in person.activity_map["residence"] and person.activity_map["residence"]["household"]:
                subset_name = person.activity_map["residence"]["household"][0].subset_name

                if subset_name in category_indices:
                    counts[category_indices[subset_name]] += 1

        # Return as space-separated string
        pattern = ' '.join(str(c) for c in counts)

        # Cache the pattern on the household for future lookups
        household.properties['_cached_actual_pattern'] = pattern

        return pattern

    def _pattern_matches(self, actual: str, template: str) -> bool:
        """
        Check if an actual pattern matches a template pattern.

        Examples:
            actual="2 0 2 0", template=">=1 >=0 2 0" -> True
            actual="0 1 2 0", template=">=1 >=0 2 0" -> False
            actual="2 1 2 0", template="0 >=1 1 <=2" -> False (has kids)
            actual="0 1 1 1", template="0 >=1 1 <=2" -> True
        """
        # Use cached function for pattern matching
        return _pattern_matches_cached(actual, template)


@dataclass
class HouseholdStructure:
    """
    Household structure with flexible matching rules.
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
class Role:
    """
    Role definition - maps to household subsets instead of conditions.
    """
    name: str
    description: str
    subsets: List[str]  # List of subset names this role applies to
    role_type: str = "general" # primary, secondary, extra, or general

    def matches(self, person, verbose: bool = False) -> bool:
        """
        Check if person's subset matches this role.
        """
        # Get person's subset from residence allocation
        # UNIFIED STRUCTURE: activity_map['residence'][venue_type] = [subsets]
        if "residence" not in person.activity_map:
            return False

        if not person.activity_map["residence"]:
            return False

        # Get the residence subset from any residence type (household, care_home, etc.)
        residence_dict = person.activity_map["residence"]
        residence_subset = None

        for venue_type, subsets in residence_dict.items():
            if subsets and isinstance(subsets, list) and len(subsets) > 0:
                residence_subset = subsets[0]
                break

        if residence_subset is None:  # Check for None explicitly, not truthiness (Subset has __len__)
            return False

        person_subset = residence_subset.subset_name

        if verbose:
            logger.debug(f"        Testing role '{self.name}': person_subset='{person_subset}', role_subsets={self.subsets}")

        return person_subset in self.subsets


@dataclass
class AssignmentRule:
    """
    Simplified assignment rule.
    """
    role: str  # Can also be list of roles (parsed from config)
    priority: int
    description: str
    assignment: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list) # Roles this rule depends on

    def applies_to_role(self, role_name: str) -> bool:
        """Check if this rule applies to a role."""
        if isinstance(self.role, list):
            return role_name in self.role
        return role_name == self.role


@dataclass
class StructureAssignmentRules:
    """
    Assignment rules for a specific household structure.
    """
    structure_name: str
    description: str
    rules: List[AssignmentRule] = field(default_factory=list)


class AttributeAssignmentConfig:
    """
    Configuration loader for attribute assignment.

    Simplified configuration system:
    - Roles map to subsets
    - Structures use matching_rules
    - Assignment rules organized by structure
    """

    def __init__(self, config_path: Path):
        """Load configuration from YAML."""
        self.config_path = Path(pr.resolve(str(config_path)))

        with open(self.config_path, 'r') as f:
            self.raw_config = yaml.safe_load(f)

        # Parse sections
        self.attribute_name = self._parse_attribute()
        self.assignment_level = self._parse_assignment_level()
        self.residence_venue_types = self._parse_residence_venue_types()
        self.filters = self._parse_filters()
        self.required_attributes = self._parse_required_attributes()
        self.region_mapping = self.raw_config.get('region_mapping', {})
        self.categories = self._parse_categories()
        self.roles = self._parse_roles()
        self.household_structures = self._parse_household_structures()
        self.data_sources = self._parse_data_sources()
        self.assignment_rules = self._parse_assignment_rules()
        self.venue_assignment_rules = self._parse_venue_assignment_rules()
        self.settings = self._parse_settings()

        # Cache valid roles per structure
        self._valid_roles_cache = {}

        # Cache category lookups
        self._category_lookup_cache = {}
        self._build_category_lookup_structures()

        logger.info(f"Loaded config for '{self.attribute_name}' from {self.config_path}")
        logger.info(f"  Assignment level: {self.assignment_level}")
        if self.required_attributes:
            logger.info(f"  Required attributes: {list(self.required_attributes.keys())}")
        if self.categories:
            logger.info(f"  Categories: {len(self.categories)}")
        logger.info(f"  Roles: {len(self.roles)}")
        logger.info(f"  Household structures: {len(self.household_structures)}")
        logger.info(f"  Assignment rules: {len(self.assignment_rules)}")

    def _parse_attribute(self) -> str:
        """Parse attribute name."""
        return self.raw_config.get('attribute', {}).get('name', 'unknown')

    def _parse_assignment_level(self) -> str:
        """Parse assignment level: 'person' or 'person_by_residence'."""
        return self.raw_config.get('attribute', {}).get('assignment_level', 'person_by_residence')

    def _parse_residence_venue_types(self) -> List[str]:
        """Residence venue types assigned by household structure (default ['household']).

        Other residence types fall through to venue_assignment_rules.
        """
        return self.raw_config.get('attribute', {}).get('residence_venue_types', ['household'])

    def _parse_filters(self) -> Dict[str, Any]:
        """Parse filters (e.g., activity-based filtering)."""
        return self.raw_config.get('filters', {})

    def _parse_required_attributes(self) -> Dict[str, Any]:
        """Parse required attributes (dependencies).

        Supports two formats:
        1. Dict format: {attr_name: {description: "...", required: true, ...}}
        2. List format: [{name: "attr_name", description: "...", required: true, ...}]

        Returns a dict format for backward compatibility.
        """
        raw_attrs = self.raw_config.get('required_attributes', {})

        # If it's already a dict, return it
        if isinstance(raw_attrs, dict):
            return raw_attrs

        # If it's a list, convert to dict using 'name' field as key
        if isinstance(raw_attrs, list):
            result = {}
            for attr in raw_attrs:
                if 'name' not in attr:
                    raise ValueError(f"Required attribute entry missing 'name' field: {attr}")
                name = attr['name']
                # Copy all fields except 'name' into the config
                config = {k: v for k, v in attr.items() if k != 'name'}
                result[name] = config
            return result

        return {}

    def _parse_categories(self) -> List[Dict[str, Any]]:
        """Parse categories (e.g., age bands)."""
        return self.raw_config.get('categories', [])

    def _parse_roles(self) -> Dict[str, Role]:
        """Parse role definitions."""
        roles = {}
        roles_config = self.raw_config.get('roles', {})

        for role_name, role_data in roles_config.items():
            if not isinstance(role_data, dict):
                continue

            # Use explicit 'type' if provided, otherwise infer from name prefix.
            # The config builder writes the type AS the name prefix
            # (primary_/secondary_/extra_) and omits the explicit key, but
            # hand-authored configs may still use arbitrary names + explicit type.
            role_type = role_data.get('type')
            if not role_type:
                if role_name.startswith('primary_'):
                    role_type = 'primary'
                elif role_name.startswith('secondary_'):
                    role_type = 'secondary'
                elif role_name.startswith('extra_'):
                    role_type = 'extra'
                else:
                    role_type = 'general'

            roles[role_name] = Role(
                name=role_name,
                description=role_data.get('description', ''),
                subsets=role_data.get('subsets', []),
                role_type=role_type
            )

        return roles

    def _parse_household_structures(self) -> Dict[str, HouseholdStructure]:
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

            structures[struct_name] = HouseholdStructure(
                name=struct_name,
                description=struct_data.get('description', ''),
                inheritance=struct_data.get('inheritance', False),
                matching_rules=matching_rules
            )

        return structures

    def _parse_data_sources(self) -> Dict[str, DataSourceConfig]:
        """Parse data sources (wrapped in DataSourceConfig for compatibility with v1)."""
        sources = {}
        sources_config = self.raw_config.get('data_sources', {})

        for source_name, source_data in sources_config.items():
            sources[source_name] = DataSourceConfig(
                name=source_name,
                type=source_data.get('type', 'csv_lookup'),
                description=source_data.get('description', ''),
                files=source_data.get('files', []),
                fallbacks=[source_data.get('fallback', {})],  # YAML uses 'fallback' key
                config=source_data
            )

        return sources

    def _parse_assignment_rules(self) -> Dict[str, StructureAssignmentRules]:
        """Parse structure-based assignment rules."""
        structure_rules = {}
        rules_config = self.raw_config.get('assignment_rules', {})

        for structure_name, struct_rules_data in rules_config.items():
            if not isinstance(struct_rules_data, dict):
                continue

            rules = []
            for i, rule_data in enumerate(struct_rules_data.get('rules', [])):
                assignment_data = rule_data.get('assignment', {})
                # Fail loudly on keys no strategy reads (dead config / typos).
                validate_assignment_config(
                    assignment_data,
                    where=f"{self.config_path.name}: assignment_rules."
                          f"{structure_name}.rules[{i}]",
                )

                # Extract dependencies from inheritance strategies
                dependencies = []
                inherit_from = assignment_data.get('inherit_from', {})
                if inherit_from:
                    # Forward inheritance uses 'roles' (list)
                    if 'roles' in inherit_from:
                        dependencies.extend(inherit_from['roles'])
                    # Reverse inheritance uses 'role' (string)
                    elif 'role' in inherit_from:
                        dependencies.append(inherit_from['role'])

                rules.append(AssignmentRule(
                    role=rule_data.get('role'),  # Can be string or list
                    priority=rule_data.get('priority', 999),
                    description=rule_data.get('description', ''),
                    assignment=assignment_data,
                    dependencies=list(set(dependencies)) # Unique dependencies
                ))

            # Sort rules by priority
            rules.sort(key=lambda r: r.priority)

            structure_rules[structure_name] = StructureAssignmentRules(
                structure_name=structure_name,
                description=struct_rules_data.get('description', ''),
                rules=rules
            )

        return structure_rules

    def _parse_venue_assignment_rules(self) -> List[Dict[str, Any]]:
        """Parse venue assignment rules."""
        rules = self.raw_config.get('venue_assignment_rules', [])
        for i, rule in enumerate(rules):
            validate_assignment_config(
                (rule or {}).get('assignment', {}),
                where=f"{self.config_path.name}: venue_assignment_rules[{i}]",
            )
        return rules

    def _parse_settings(self) -> Dict[str, Any]:
        """Parse settings."""
        return self.raw_config.get('settings', {})

    def get_household_structure(self, household, verbose: bool = False) -> Optional[str]:
        """
        Classify household structure.
        Returns first matching structure.
        """
        # Check if structure is already cached (only when not verbose)
        if not verbose:
            cached_structure = household.properties.get('_cached_household_structure')
            if cached_structure is not None:
                return cached_structure

        if verbose:
            logger.debug(f"  Classifying household {household.id}:")

        for struct_name, structure in self.household_structures.items():
            if structure.matches(household, verbose=verbose):
                # Cache the result (only when not verbose to avoid caching debug runs)
                if not verbose:
                    household.properties['_cached_household_structure'] = struct_name
                return struct_name

        if verbose:
            logger.debug(f"  ✗ No structure matched")

        # Cache None result as well
        if not verbose:
            household.properties['_cached_household_structure'] = None

        return None

    def get_person_role(self, person, household_structure: str,
                       assigned_roles: List[str], verbose: bool = False,
                       person_category: str = None) -> Optional[str]:
        """
        Determine person's role based on their subset and household structure.

        Args:
            person: Person object
            household_structure: Name of household structure
            assigned_roles: List of roles already assigned in this household
            verbose: If True, log matching details
            person_category: Optional pre-calculated person category (subset name)

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

        # Get valid roles for this structure (cached to avoid rebuilding for every person)
        if household_structure not in self._valid_roles_cache:
            valid_roles_for_structure = set()
            for rule in struct_rules.rules:
                if isinstance(rule.role, list):
                    valid_roles_for_structure.update(rule.role)
                else:
                    valid_roles_for_structure.add(rule.role)
            self._valid_roles_cache[household_structure] = valid_roles_for_structure
        else:
            valid_roles_for_structure = self._valid_roles_cache[household_structure]

        # Try each role in order until we find a matching one
        for role_name, role in self.roles.items():
            # Skip roles that don't have rules for this structure
            if role_name not in valid_roles_for_structure:
                continue

            if verbose:
                logger.debug(f"      Testing role '{role_name}':")

            # Check if person's subset matches this role
            # Use pre-calculated category if valid
            matched = False
            if person_category and person_category != "unknown":
                if person_category in role.subsets:
                    matched = True
                elif verbose:
                    logger.debug(f"        ✗ Category '{person_category}' not in role subsets {role.subsets}")
            else:
                # Fallback to internal lookup only if needed
                if role.matches(person, verbose=verbose):
                    matched = True

            if not matched:
                continue

            # Check if this role has been assigned already
            role_count = assigned_roles.count(role_name)

            # Determine if we should assign this role based on count and explicit type
            if role.role_type == 'primary' and role_count == 0:
                if verbose:
                    logger.debug(f"      ✓ Assigned role '{role_name}' (primary)")
                return role_name
                
            elif role.role_type == 'secondary' and role_count == 0:
                # Check if a primary role for the same subset was already assigned
                has_primary = False
                for assigned_name in assigned_roles:
                    assigned_role = self.roles.get(assigned_name)
                    if assigned_role and assigned_role.role_type == 'primary':
                        # Check if subsets overlap (e.g., both apply to 'Adults')
                        if set(assigned_role.subsets) & set(role.subsets):
                            has_primary = True
                            break
                            
                if has_primary:
                    if verbose:
                        logger.debug(f"      ✓ Assigned role '{role_name}' (secondary)")
                    return role_name
                    
            elif role.role_type == 'extra':
                # Check if both primary and secondary for the same subset were assigned
                has_primary = False
                has_secondary = False
                for assigned_name in assigned_roles:
                    assigned_role = self.roles.get(assigned_name)
                    if assigned_role:
                        if assigned_role.role_type == 'primary' and (set(assigned_role.subsets) & set(role.subsets)):
                            has_primary = True
                        if assigned_role.role_type == 'secondary' and (set(assigned_role.subsets) & set(role.subsets)):
                            has_secondary = True
                            
                if has_primary and has_secondary:
                    if verbose:
                        logger.debug(f"      ✓ Assigned role '{role_name}' (extra)")
                    return role_name
                    
            elif role.role_type == 'general':
                if verbose:
                    logger.debug(f"      ✓ Assigned role '{role_name}'")
                return role_name

        if verbose:
            logger.debug(f"      ✗ No role matched")
        return None

    def get_assignment_rule(self, household_structure: str, role: str,
                           verbose: bool = False) -> Optional[AssignmentRule]:
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

    def _build_category_lookup_structures(self):
        """
        Build lookup structures for categories.
        Called once during __init__ to avoid repeated iterations.
        """
        # Group categories by attribute name for faster filtering
        categories_by_attr = {}
        for category in self.categories:
            attr = category.get('attribute')
            if attr not in categories_by_attr:
                categories_by_attr[attr] = []
            categories_by_attr[attr].append(category)

        # For numerical categories (like age), sort by min value for binary search
        for attr, cats in list(categories_by_attr.items()):
            numerical_cats = [c for c in cats if c.get('type') == 'numerical']
            if numerical_cats:
                # Sort by min value
                numerical_cats.sort(key=lambda c: c['numerical']['min'])
                categories_by_attr[attr + '_numerical'] = numerical_cats

        self._categories_by_attr = categories_by_attr

    def get_category_for_value(self, value: Any, attribute_name: str = "age") -> Optional[Dict[str, Any]]:
        """
        Find which category a value falls into.

        Args:
            value: The value to categorize (e.g., age=25)
            attribute_name: The attribute name to match against (default: "age")

        Returns:
            Category dict with 'csv_value' or None if no match
        """
        # Check cache first (87% hit rate based on profiling patterns)
        cache_key = (attribute_name, value)
        if cache_key in self._category_lookup_cache:
            return self._category_lookup_cache[cache_key]

        result = None

        # Use pre-filtered categories instead of iterating all
        numerical_cats = self._categories_by_attr.get(attribute_name + '_numerical', [])
        if numerical_cats and isinstance(value, (int, float)):
            # For numerical, iterate through sorted categories (typically just 4-5)
            for category in numerical_cats:
                min_val = category['numerical']['min']
                max_val = category['numerical'].get('max')

                if max_val is None:
                    # No upper limit
                    if value >= min_val:
                        result = category
                        break
                elif min_val <= value <= max_val:
                    result = category
                    break
        else:
            # For categorical or fallback, check all categories for this attribute
            cats = self._categories_by_attr.get(attribute_name, [])
            for category in cats:
                if category.get('type') == 'categorical':
                    allowed = category.get('categorical', {}).get('allowed_values', [])
                    if value in allowed:
                        result = category
                        break

        # Cache the result
        self._category_lookup_cache[cache_key] = result
        return result

    def get_person_assignment_rule(self) -> Optional[AssignmentRule]:
        """
        Get assignment rule for person-level assignment.

        Returns:
            First assignment rule from 'person' structure or None
        """
        if 'person' not in self.assignment_rules:
            return None

        person_rules = self.assignment_rules['person']
        if not person_rules.rules:
            return None

        return person_rules.rules[0]

    def get_required_attribute_mapping(self, attr_name: str) -> Dict[str, str]:
        """
        Get mapping for a required attribute.

        Args:
            attr_name: Name of required attribute

        Returns:
            Mapping dict or empty dict
        """
        if attr_name in self.required_attributes:
            return self.required_attributes[attr_name].get('mapping', {})
        return {}

    @classmethod
    def from_yaml(cls, config_path: Path) -> 'AttributeAssignmentConfig':
        """Load configuration from YAML file."""
        return cls(config_path)
