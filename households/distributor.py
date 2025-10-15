"""
HouseholdDistributor for June Zero.

Allocates people into households using a 3-stage process:
- Stage 1: Exact private households (families with kids prioritized)
- Stage 2: Communal establishments
- Stage 3: Flexible/expandable households + emergency households

Handles messy census data with demotion/promotion strategies.
"""

import logging
import csv
import yaml
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import defaultdict, Counter

from .household import Household
from .config_loader import ConfigLoader
from .rule_engine import RoleResolver, ConstraintValidator, RuleEngine, AllocationExecutor

logger = logging.getLogger("distributor")


class HouseholdDistributor:
    """
    Distributes people into households across geographical units.

    Design principles:
    - Generic: Works with any person categorization (age, social class, etc.)
    - Realistic: Handles incomplete/noisy census data
    - Prioritized: Families with kids get allocated first
    - Flexible: Falls back to simpler patterns when needed
    """

    def __init__(
        self,
        geography,
        config_dir: str = "data/households/config",
        household_data_file: str = "data/households/households.csv"
    ):
        """
        Initialize the household distributor.

        Args:
            geography: Geography object with all S.G.Us
            config_dir: Path to configuration directory
            household_data_file: Path to household composition CSV
        """
        self.geography = geography
        self.config_dir = Path(config_dir)
        self.household_data_file = Path(household_data_file)

        # Load configuration
        self.config_loader = ConfigLoader(str(self.config_dir))
        self.config = self.config_loader.load_all()

        # Extract key configs
        self.categories = [c['name'] for c in self.config['age_brackets']['person_categories']]
        self.reconciliation = self.config['reconciliation']
        self.composition_assumptions = self.config.get('composition_assumptions', {'assumptions': [], 'config': {}})

        # Household data (loaded from CSV)
        self.household_patterns = {}  # {pattern: column_index}
        self.area_compositions = {}   # {area_code: {pattern: count}}

        # Created households and tracking
        self.households = []
        self.person_pool_by_area = defaultdict(list)  # {area_code: [Person]}
        self.allocated_people = set()  # Set of person IDs

        # Statistics
        self.stats = {
            'stage1': {
                'households_created': 0,
                'people_allocated': 0,
                'patterns_demoted': 0,
                'patterns_failed': 0
            }
        }

        # Initialize rule engine
        logger.info("Initializing rule engine...")
        self._init_rule_engine()

        logger.info("HouseholdDistributor initialized")

    def load_household_data(self):
        """
        Load household composition data from CSV.

        CSV format:
        area,pattern1,pattern2,...,patternN
        E00004320,14,19,12,...

        Pattern format: "{kid} {young_adult} {adult} {elder}"
        Example: "2 0 2 0" = 2 kids, 0 young adults, 2 adults, 0 elders
        """
        logger.info(f"Loading household data from {self.household_data_file}")

        with open(self.household_data_file, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)

            # Parse patterns from header (skip first column "area")
            patterns = header[1:]
            self.household_patterns = {pattern: idx for idx, pattern in enumerate(patterns)}

            logger.info(f"Found {len(patterns)} household patterns: {', '.join(patterns[:5])}...")

            # Validate patterns
            for pattern in patterns:
                is_valid, error = self.config_loader.validate_composition_pattern(pattern)
                if not is_valid:
                    raise ValueError(f"Invalid pattern in CSV header: {pattern}. {error}")

            # Load area data
            for row in reader:
                area_code = row[0]
                counts = [int(x) for x in row[1:]]

                # Store as {pattern: count} dict
                self.area_compositions[area_code] = {
                    pattern: count for pattern, count in zip(patterns, counts)
                }

        logger.info(f"Loaded household data for {len(self.area_compositions)} areas")

    def _init_rule_engine(self):
        """
        Initialize the rule engine for constraint-based household creation.
        """
        # Load household creation rules from YAML
        rules_file = self.config_dir / "household_creation_rules.yaml"

        with open(rules_file, 'r') as f:
            rules_config = yaml.safe_load(f)

        # Initialize components
        self.role_resolver = RoleResolver(self.config['age_brackets']['person_categories'])
        self.constraint_validator = ConstraintValidator(self.config['relationship_constraints'])
        self.rule_engine = RuleEngine(
            rules_config['household_creation_rules'],
            self.role_resolver,
            self.constraint_validator
        )
        self.allocation_executor = AllocationExecutor(
            self.role_resolver,
            self.constraint_validator,
            self  # Pass distributor reference
        )

        logger.info(f"Rule engine initialized with {len(self.rule_engine.rules)} rules")

    def add_person_to_pool(self, person, area_code: str):
        """
        Add a person to the allocation pool for their area.

        Args:
            person: Person object
            area_code: S.G.U code where person lives
        """
        self.person_pool_by_area[area_code].append(person)

    def get_person_category(self, person) -> str:
        """
        Determine which category a person belongs to.

        Works for both age-based and property-based categories.

        Args:
            person: Person object

        Returns:
            Category name (e.g., 'kid', 'adult', 'noble', etc.)
        """
        cat_type = self.config['age_brackets'].get('categorization_type', 'age')

        for category in self.config['age_brackets']['person_categories']:
            if cat_type == 'age':
                # Age-based categorization
                if category['min_age'] <= person.age <= category['max_age']:
                    return category['name']
            elif cat_type == 'property':
                # Property-based categorization
                property_key = category['property_key']
                property_value = category['property_value']
                if hasattr(person, 'properties') and person.properties.get(property_key) == property_value:
                    return category['name']

        logger.warning(f"Person {person.id} (age {person.age}) doesn't fit any category!")
        return None

    def parse_pattern(self, pattern: str) -> Dict:
        """
        Parse a composition pattern string into structured data.

        Args:
            pattern: Pattern string (e.g., "2 0 2 0" or ">=2 >=0 2 0")

        Returns:
            Dict with keys:
            - 'requirements': {category_index: count} for exact counts
            - 'minimums': {category_index: count} for >= counts
            - 'requirements_by_name': {category_name: count} for exact counts
            - 'minimums_by_name': {category_name: count} for >= counts
            - 'total_exact': Total exact people needed
            - 'is_expandable': True if has any >= patterns
            - 'pattern': Original pattern string
        """
        parts = pattern.strip().split()

        if len(parts) != len(self.categories):
            raise ValueError(f"Pattern '{pattern}' has {len(parts)} values, expected {len(self.categories)}")

        requirements = {}  # By index
        minimums = {}      # By index
        requirements_by_name = {}  # By name (for backward compatibility)
        minimums_by_name = {}      # By name (for backward compatibility)
        total_exact = 0
        is_expandable = False

        for idx, (category, value_str) in enumerate(zip(self.categories, parts)):
            if value_str.startswith('>='):
                # Expandable (minimum)
                count = int(value_str[2:])
                minimums[idx] = count
                minimums_by_name[category] = count
                is_expandable = True
            else:
                # Exact count
                count = int(value_str)
                requirements[idx] = count
                requirements_by_name[category] = count
                total_exact += count

        return {
            'requirements': requirements,
            'minimums': minimums,
            'requirements_by_name': requirements_by_name,
            'minimums_by_name': minimums_by_name,
            'total_exact': total_exact,
            'is_expandable': is_expandable,
            'pattern': pattern
        }

    def get_sgu(self, area_code: str):
        """
        Get S.G.U by area code.

        Args:
            area_code: S.G.U name/code

        Returns:
            GeographicalUnit or None
        """
        return self.geography.get_unit(area_code)

    def get_pool_composition(self, area_code: str) -> Dict[str, int]:
        """
        Get current composition of unallocated people in area's pool.

        Args:
            area_code: S.G.U code

        Returns:
            Dict mapping category to count
        """
        composition = {cat: 0 for cat in self.categories}

        for person in self.person_pool_by_area[area_code]:
            if person.id not in self.allocated_people:
                category = self.get_person_category(person)
                if category:
                    composition[category] += 1

        return composition

    def can_create_household(self, area_code: str, parsed_pattern: Dict) -> bool:
        """
        Check if we have enough people to create this household.

        Args:
            area_code: S.G.U code
            parsed_pattern: Parsed pattern from parse_pattern()

        Returns:
            True if we can create the household
        """
        pool_composition = self.get_pool_composition(area_code)

        # Check exact requirements (use _by_name for compatibility)
        for category, needed in parsed_pattern.get('requirements_by_name', {}).items():
            if pool_composition[category] < needed:
                return False

        # Check minimums (for expandable patterns)
        for category, needed in parsed_pattern.get('minimums_by_name', {}).items():
            if pool_composition[category] < needed:
                return False

        return True

    def allocate_people_to_household(
        self,
        household: Household,
        area_code: str,
        parsed_pattern: Dict
    ) -> bool:
        """
        Allocate people from pool to a household based on pattern.

        Uses the rule engine to apply constraint-based allocation with
        relationship validation (age gaps, sex preferences, etc.)

        Args:
            household: Household to add people to
            area_code: S.G.U code
            parsed_pattern: Parsed pattern

        Returns:
            True if successful
        """
        # Find matching rule
        rule = self.rule_engine.find_rule(parsed_pattern)

        if not rule:
            logger.debug(
                f"No rule matched pattern '{parsed_pattern['pattern']}', "
                f"falling back to simple allocation"
            )
            household.properties['rule_name'] = 'simple_fallback'
            return self._simple_allocate(household, area_code, parsed_pattern)

        # Check if rule has empty allocation sequence (signals fallback)
        if not rule.allocation_sequence:
            logger.debug(
                f"Rule '{rule.name}' has empty allocation sequence, "
                f"falling back to simple allocation"
            )
            household.properties['rule_name'] = rule.name
            return self._simple_allocate(household, area_code, parsed_pattern)

        # Store rule name in household properties
        household.properties['rule_name'] = rule.name

        # Execute rule with constraint-based allocation
        initial_resident_count = len(household.residents)

        try:
            success = self.allocation_executor.execute_rule(
                rule,
                parsed_pattern,
                area_code,
                household
            )

            if success:
                # Mark allocated people
                for person in household.residents[initial_resident_count:]:
                    self.allocated_people.add(person.id)
                return True
            else:
                # Rule execution failed, rollback
                logger.debug(f"Rule execution failed for pattern '{parsed_pattern['pattern']}'")
                household.residents = household.residents[:initial_resident_count]
                return False

        except Exception as e:
            logger.error(f"Error executing rule: {e}", exc_info=True)
            # Rollback
            household.residents = household.residents[:initial_resident_count]
            return False

    def _simple_allocate(
        self,
        household: Household,
        area_code: str,
        parsed_pattern: Dict
    ) -> bool:
        """
        Simple allocation without constraint checking (fallback).

        Used when no rule matches the pattern.

        Args:
            household: Household to add people to
            area_code: S.G.U code
            parsed_pattern: Parsed pattern

        Returns:
            True if successful
        """
        allocated_in_household = []

        try:
            # Allocate exact requirements first (use _by_name)
            for category, needed in parsed_pattern.get('requirements_by_name', {}).items():
                allocated = 0

                for person in self.person_pool_by_area[area_code]:
                    if person.id in self.allocated_people:
                        continue

                    if self.get_person_category(person) == category:
                        household.add_resident(person)
                        self.allocated_people.add(person.id)
                        allocated_in_household.append(person.id)
                        allocated += 1

                        if allocated >= needed:
                            break

                if allocated < needed:
                    raise ValueError(f"Could not allocate {needed} {category} (only got {allocated})")

            # For now, don't expand beyond minimums (that's Stage 3)
            # Just allocate the minimum for expandable patterns
            for category, needed in parsed_pattern.get('minimums_by_name', {}).items():
                allocated = 0

                for person in self.person_pool_by_area[area_code]:
                    if person.id in self.allocated_people:
                        continue

                    if self.get_person_category(person) == category:
                        household.add_resident(person)
                        self.allocated_people.add(person.id)
                        allocated_in_household.append(person.id)
                        allocated += 1

                        if allocated >= needed:
                            break

                if allocated < needed:
                    raise ValueError(f"Could not allocate {needed} {category} (only got {allocated})")

            return True

        except Exception as e:
            # Rollback allocations
            logger.debug(f"Simple allocation failed: {e}. Rolling back.")
            for person_id in allocated_in_household:
                self.allocated_people.discard(person_id)
            household.residents.clear()
            return False

    def demote_pattern(self, pattern: str, area_code: str) -> Optional[str]:
        """
        Demote a household pattern by removing the scarcest resource.

        This is the "resource-aware" demotion strategy from config.

        Args:
            pattern: Current pattern (e.g., "2 0 2 0")
            area_code: S.G.U code (for checking resource availability)

        Returns:
            Demoted pattern string, or None if can't demote further
        """
        parsed = self.parse_pattern(pattern)
        pool_composition = self.get_pool_composition(area_code)

        # Find which category is scarcest (highest demand/supply ratio)
        scarcity_scores = {}

        # Use requirements_by_name for compatibility
        for category, needed in parsed.get('requirements_by_name', {}).items():
            if needed > 0:
                available = pool_composition.get(category, 0)
                # Scarcity = how many we need / how many available
                # Higher = scarcer
                scarcity = needed / max(available, 0.1)
                scarcity_scores[category] = scarcity

        if not scarcity_scores:
            logger.debug(f"Cannot demote pattern '{pattern}' - no exact requirements")
            return None

        # Remove scarcest category
        scarcest_category = max(scarcity_scores.keys(), key=lambda k: scarcity_scores[k])

        logger.debug(
            f"Demoting pattern '{pattern}': removing 1 {scarcest_category} "
            f"(scarcity score: {scarcity_scores[scarcest_category]:.2f})"
        )

        # Build new pattern by DECREMENTING scarcest category by 1 (not zeroing it out)
        parts = pattern.split()
        category_index = self.categories.index(scarcest_category)
        current_value = int(parts[category_index])
        new_value = current_value - 1
        parts[category_index] = str(new_value)

        new_pattern = ' '.join(parts)

        # Check if new pattern is valid (at least one non-zero)
        if all(p == '0' or p == '>=0' for p in parts):
            logger.debug(f"Demoted pattern '{new_pattern}' is empty - cannot use")
            return None

        return new_pattern

    def apply_composition_assumption(self, pattern: str) -> Optional[str]:
        """
        Apply composition assumptions to a pattern if applicable.

        Checks if pattern needs assumptions (e.g., lacks supervision, not unique)
        and applies minimum additions to make it valid.

        Args:
            pattern: Original pattern (e.g., ">=2 >=0 >=0 >=0")

        Returns:
            Transformed pattern with assumptions applied, or None if should skip,
            or original pattern if no assumption needed
        """
        assumptions = self.composition_assumptions.get('assumptions', [])
        assumptions_config = self.composition_assumptions.get('config', {})

        # Find matching assumption
        matching_assumption = None
        for assumption in assumptions:
            if assumption.get('pattern') == pattern:
                matching_assumption = assumption
                break

        # No assumption found - process pattern as-is (unless config says otherwise)
        if not matching_assumption:
            if assumptions_config.get('skip_if_no_assumption', False):
                logger.debug(f"No assumption found for pattern '{pattern}' and skip_if_no_assumption=True")
                return None
            return pattern

        # Check if pattern should be skipped (e.g., ">=0 >=0 >=0 >=0")
        resulting_minimum = matching_assumption.get('resulting_minimum')
        if resulting_minimum is None:
            if assumptions_config.get('log_skipped_patterns', True):
                logger.info(f"Skipping pattern '{pattern}' in Stage 1 (will process in Stage 3)")
                logger.info(f"  Reason: {matching_assumption.get('assumption', 'No guaranteed members')}")
            return None

        # Apply minimum additions
        minimum_additions = matching_assumption.get('minimum_additions', {})

        if not minimum_additions:
            # No additions needed - pattern is valid as-is
            if assumptions_config.get('log_assumptions_applied', True):
                logger.info(f"Pattern '{pattern}' valid as-is (no additions needed)")
            return pattern

        # Build new pattern with minimum additions
        # Parse original pattern to get current values
        parts = pattern.split()
        new_parts = []

        for category, original_part in zip(self.categories, parts):
            addition = minimum_additions.get(category, 0)

            if original_part.startswith('>='):
                # For >= patterns, if we're adding a minimum, convert to exact count
                # Example: ">=0" + add 1 → "1" (not ">=0")
                #          ">=2" + add 0 → ">=2" (keep as-is)
                current_min = int(original_part[2:])
                new_min = current_min + addition

                if addition > 0:
                    # Adding a minimum requirement makes it exact for Stage 1
                    new_parts.append(str(new_min))
                else:
                    # No addition, keep >= prefix
                    new_parts.append(original_part)
            else:
                # Exact value - add the minimum addition
                current_value = int(original_part)
                new_value = current_value + addition
                new_parts.append(str(new_value))

        new_pattern = ' '.join(new_parts)

        # Validate uniqueness if configured
        if assumptions_config.get('validate_uniqueness', True):
            # Check if new pattern conflicts with other patterns in area_compositions
            # (We'll do this during Stage 1 allocation when we have area context)
            pass

        # Log transformation
        if assumptions_config.get('log_assumptions_applied', True):
            logger.info(f"Applied assumption to pattern '{pattern}':")
            logger.info(f"  Assumption: {matching_assumption.get('assumption', '').split(chr(10))[0]}...")
            logger.info(f"  Minimum additions: {minimum_additions}")
            logger.info(f"  Resulting pattern: {new_pattern}")
            logger.info(f"  Reasoning: {matching_assumption.get('reasoning', 'N/A')}")

        return new_pattern

    def stage1_allocate(self):
        """
        STAGE 1: Allocate exact private households.

        Strategy:
        1. Process patterns where priority category has minimum > 0
        2. Prioritize by priority category count (more = higher priority)
        3. Try to create each household with exact composition
        4. If fails, demote pattern (remove scarcest resource) and retry
        5. Track statistics

        Note: Priority category is determined from allocation_rounds config
        (typically 'kid' but configurable for different societies/time periods)
        """
        logger.info("=" * 70)
        logger.info("STAGE 1: Allocating exact private households (priority category first)")
        logger.info("=" * 70)

        stage1_config = self.reconciliation['allocation_stages']['stage1_private']

        # Get priority category from config (the one with allocation_order: 1)
        allocation_rounds = self.reconciliation['allocation_rounds']['rounds']
        priority_round = min(allocation_rounds, key=lambda r: r['allocation_order'])
        priority_category = priority_round['category']
        priority_category_index = self.categories.index(priority_category)

        logger.info(f"Priority category: '{priority_category}' (index {priority_category_index})")

        # Build priority queue of (area, pattern, count) sorted by priority
        allocation_queue = []

        # TEMPORARY: Only process specific patterns for testing
        allowed_patterns = [">=2 >=0 2 0", ">=2 >=0 1 0", "1 >=0 2 0", "1 >=0 1 0"]

        for area_code, composition in self.area_compositions.items():
            for pattern, count in composition.items():
                if count == 0:
                    continue

                # TEMPORARY FILTER: Only process allowed patterns
                if pattern not in allowed_patterns:
                    continue

                # Apply composition assumptions BEFORE processing
                transformed_pattern = self.apply_composition_assumption(pattern)

                # Skip patterns that assumptions mark as "skip in Stage 1"
                if transformed_pattern is None:
                    continue

                # Use transformed pattern for all subsequent operations
                working_pattern = transformed_pattern

                # Calculate priority score
                parsed = self.parse_pattern(working_pattern)
                pattern_parts = working_pattern.split()

                # Get kid count (handle >= prefix)
                kid_str = pattern_parts[0]
                kid_count = int(kid_str.replace('>=', ''))

                # For priority, use minimum required people (not total_exact which is 0 for expandables)
                min_people = sum(parsed['minimums'].values()) + parsed['total_exact']

                # Priority: (has_kids, kid_count, min_people)
                # Higher values = higher priority
                priority = (
                    1 if kid_count > 0 else 0,  # Families with kids first
                    kid_count,                   # More kids = higher priority
                    min_people                   # More people = tiebreaker
                )

                allocation_queue.append({
                    'area_code': area_code,
                    'pattern': pattern,  # Original pattern from census
                    'working_pattern': working_pattern,  # Transformed pattern with assumptions
                    'count': count,
                    'priority': priority,
                    'assumption_applied': pattern != working_pattern  # Track if assumption was applied
                })

        # Sort by priority (descending)
        allocation_queue.sort(key=lambda x: x['priority'], reverse=True)

        total_households = sum(x['count'] for x in allocation_queue)
        expandable_count = sum(1 for x in allocation_queue if '>=' in x['pattern'])

        logger.info(
            f"Stage 1 queue: {len(allocation_queue)} pattern-area combinations, "
            f"{total_households} households to create"
        )
        logger.info(f"  - Including {expandable_count} expandable patterns (will allocate minimums)")
        logger.info(f"  - Skipped only '0 >=0 >=0 >=0' (fully flexible, Stage 3)")

        # Process queue
        for item in allocation_queue:
            area_code = item['area_code']
            pattern = item['pattern']  # Original
            working_pattern = item['working_pattern']  # With assumptions applied
            count = item['count']
            assumption_applied = item.get('assumption_applied', False)

            # Get the geographical unit
            geographical_unit = self.get_sgu(area_code)
            if not geographical_unit:
                logger.warning(f"Area {area_code} not found in geography - skipping")
                continue

            created = 0
            current_pattern = working_pattern  # Start with transformed pattern

            for i in range(count):
                # Try to create household with current pattern
                parsed = self.parse_pattern(current_pattern)

                # Check if we can create it
                if not self.can_create_household(area_code, parsed):
                    logger.debug(
                        f"Cannot create household with pattern '{current_pattern}' - "
                        f"insufficient people"
                    )

                    # Try demotion if enabled
                    if stage1_config.get('demotion_on_failure', True):
                        demoted = self.demote_pattern(current_pattern, area_code)
                        if demoted:
                            logger.info(f"  Demoting: '{current_pattern}' → '{demoted}'")
                            current_pattern = demoted
                            parsed = self.parse_pattern(current_pattern)
                            self.stats['stage1']['patterns_demoted'] += 1

                            # Retry with demoted pattern
                            if not self.can_create_household(area_code, parsed):
                                logger.debug("  Still can't create - skipping this household")
                                self.stats['stage1']['patterns_failed'] += 1
                                continue
                        else:
                            logger.debug("  Cannot demote further - skipping")
                            self.stats['stage1']['patterns_failed'] += 1
                            continue
                    else:
                        self.stats['stage1']['patterns_failed'] += 1
                        continue

                # Create household
                household = Household(geographical_unit, self.config['age_brackets']['person_categories'])
                household.properties['stage'] = 'stage1'
                household.properties['original_pattern'] = pattern
                household.properties['actual_pattern'] = current_pattern

                # Allocate people
                success = self.allocate_people_to_household(household, area_code, parsed)

                if success:
                    self.households.append(household)
                    created += 1
                    self.stats['stage1']['households_created'] += 1
                    self.stats['stage1']['people_allocated'] += household.size()

                    if (i + 1) % 10 == 0 or (i + 1) == count:
                        logger.debug(f"  Progress: {i + 1}/{count} households created")
                else:
                    logger.warning(f"  Failed to allocate people for pattern '{current_pattern}'")
                    self.stats['stage1']['patterns_failed'] += 1

        logger.info("\n" + "=" * 70)
        logger.info("STAGE 1 COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Households created: {self.stats['stage1']['households_created']}")
        logger.info(f"People allocated: {self.stats['stage1']['people_allocated']}")
        logger.info(f"Patterns demoted: {self.stats['stage1']['patterns_demoted']}")
        logger.info(f"Patterns failed: {self.stats['stage1']['patterns_failed']}")

        # Log pool status
        total_remaining = sum(
            len([p for p in people if p.id not in self.allocated_people])
            for people in self.person_pool_by_area.values()
        )
        logger.info(f"Remaining unallocated: {total_remaining} people")
        logger.info("=" * 70)

    def print_detailed_sgu_households(self, sgu_code: str):
        """
        Print detailed information about all households in a specific SGU.

        Shows every household created in the SGU, including:
        - Original pattern requested
        - Actual pattern created (after any demotions)
        - Rule used for allocation
        - Every member with full details
        - Allocation stage

        Args:
            sgu_code: S.G.U code to inspect
        """
        # Get households in this SGU
        sgu_households = [h for h in self.households if h.geographical_unit.name == sgu_code]

        if not sgu_households:
            logger.info(f"\nNo households found in SGU '{sgu_code}'")
            return

        sgu = self.get_sgu(sgu_code)

        logger.info("\n" + "=" * 80)
        logger.info(f"DETAILED HOUSEHOLD INSPECTION: {sgu_code}")
        logger.info("=" * 80)
        logger.info(f"SGU: {sgu.name}")
        logger.info(f"Total households in this SGU: {len(sgu_households)}")
        logger.info(f"Total residents: {sum(h.size() for h in sgu_households)}")
        logger.info("=" * 80)

        for i, household in enumerate(sgu_households, 1):
            logger.info("")
            logger.info("─" * 80)
            logger.info(f"HOUSEHOLD #{i} (ID: {household.id})")
            logger.info("─" * 80)

            # Basic info
            logger.info(f"Location: {household.geographical_unit.name}")
            logger.info(f"Size: {household.size()} people")

            # Pattern information
            original_pattern = household.properties.get('original_pattern', 'unknown')
            actual_pattern = household.properties.get('actual_pattern', 'unknown')
            stage = household.properties.get('stage', 'unknown')
            rule_name = household.properties.get('rule_name', 'unknown')

            logger.info(f"Allocation Stage: {stage}")
            logger.info(f"Original Pattern Requested: {original_pattern}")

            if original_pattern != actual_pattern:
                logger.info(f"Actual Pattern Created: {actual_pattern} (DEMOTED)")
            else:
                logger.info(f"Actual Pattern Created: {actual_pattern} (no demotion)")

            # Current composition
            composition = household.get_composition()
            composition_str = household.get_composition_string()
            logger.info(f"Final Composition: {composition_str}")
            logger.info(f"  Breakdown: {', '.join([f'{k}={v}' for k, v in composition.items()])}")

            # Rule information
            logger.info(f"Rule Used: {rule_name}")

            # Get the rule object for more details if available
            if rule_name != 'unknown' and rule_name != 'simple_fallback':
                parsed = self.parse_pattern(actual_pattern)
                rule = self.rule_engine.find_rule(parsed)
                if rule:
                    logger.info(f"  Rule Description: {rule.description}")
                    if rule.allocation_sequence:
                        logger.info(f"  Allocation Sequence: {len(rule.allocation_sequence)} steps")
                        for idx, step in enumerate(rule.allocation_sequence, 1):
                            step_num = step.get('step', idx)
                            description = step.get('description', 'No description')
                            category_name = step.get('category_name', 'unknown')
                            count = step.get('count', 'unknown')
                            selection_method = step.get('selection_method', 'unknown')
                            constraints = step.get('constraints', [])

                            logger.info(f"    Step {step_num}: {description}")
                            logger.info(f"      Category: {category_name}")
                            logger.info(f"      Count: {count}")
                            logger.info(f"      Selection: {selection_method}")

                            if constraints:
                                logger.info(f"      Constraints:")
                                for constraint in constraints:
                                    if isinstance(constraint, dict):
                                        constraint_type = constraint.get('type', 'unknown')
                                        constraint_desc = constraint.get('description', '')
                                        config_key = constraint.get('config_key', '')
                                        required = constraint.get('required', False)

                                        logger.info(f"        - Type: {constraint_type}")
                                        if constraint_desc:
                                            logger.info(f"          Desc: {constraint_desc}")
                                        if config_key:
                                            logger.info(f"          Config: {config_key}")
                                        logger.info(f"          Required: {required}")
            elif rule_name == 'simple_fallback':
                logger.info(f"  (Simple allocation - no rule matched, allocated by category only)")

            # Member details
            logger.info("")
            logger.info(f"RESIDENTS ({household.size()} people):")
            logger.info("")

            for resident_idx, person in enumerate(household.residents, 1):
                category = self.get_person_category(person)
                logger.info(f"  [{resident_idx}] Person ID: {person.id}")
                logger.info(f"      Age: {person.age}")
                logger.info(f"      Sex: {person.sex}")
                logger.info(f"      Category: {category}")
                logger.info(f"      Activities: {', '.join(person.activities) if person.activities else 'none'}")

                # Show household role if stored in properties
                if hasattr(person, 'properties') and 'household_role' in person.properties:
                    logger.info(f"      Household Role: {person.properties['household_role']}")

                # Show any other relevant properties
                if hasattr(person, 'properties') and person.properties:
                    other_props = {k: v for k, v in person.properties.items() if k != 'household_role'}
                    if other_props:
                        logger.info(f"      Other Properties: {other_props}")

                logger.info("")

        logger.info("=" * 80)
        logger.info(f"END OF DETAILED INSPECTION FOR {sgu_code}")
        logger.info("=" * 80)

    def print_summary(self):
        """Print overall allocation summary."""
        logger.info("\n" + "=" * 70)
        logger.info("HOUSEHOLD DISTRIBUTION SUMMARY")
        logger.info("=" * 70)

        total_people = sum(len(people) for people in self.person_pool_by_area.values())
        allocated_count = len(self.allocated_people)
        unallocated_count = total_people - allocated_count

        logger.info(f"Total people: {total_people}")
        logger.info(f"Allocated: {allocated_count} ({allocated_count/max(total_people, 1)*100:.1f}%)")
        logger.info(f"Unallocated: {unallocated_count} ({unallocated_count/max(total_people, 1)*100:.1f}%)")
        logger.info(f"Total households: {len(self.households)}")

        if self.households:
            avg_size = sum(h.size() for h in self.households) / len(self.households)
            logger.info(f"Average household size: {avg_size:.2f}")

        logger.info("=" * 70)
