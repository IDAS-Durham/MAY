"""
Main orchestrator for attribute assignment.

Simplified attribute assignment system:
- Cleaner structure classification (Family/Couple/Independents)
- Simple role assignment (primary/secondary/extra based on naming)
- No complex condition evaluation
- Structure-based rule lookup
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional
from collections import defaultdict

from .assignment_config import AttributeAssignmentConfig
from .data_sources import DataSourceManager
from .strategies import StrategyFactory

logger = logging.getLogger("may.attribute_assignment.assigner")


class AttributeAssigner:
    """
    Main orchestrator for attribute assignment.

    Uses structure-based assignment with straightforward role logic.
    """

    def __init__(self, config: AttributeAssignmentConfig, data_manager: DataSourceManager):
        """
        Initialize attribute assigner.

        Args:
            config: Attribute assignment configuration
            data_manager: Data source manager with loaded data
        """
        self.config = config
        self.data_manager = data_manager
        self.attribute_name = config.attribute_name

        # Logging settings
        self.verbose = config.settings.get('logging', {}).get('detailed_assignment_logging', False)

        # Statistics
        self.stats = {
            'total_people': 0,
            'people_in_households': 0,
            'households_processed': 0,
            'assignments_by_rule': defaultdict(int),
            'assignments_by_role': defaultdict(int),
            'assignments_by_strategy': defaultdict(int),
            'attribute_distribution': defaultdict(int),
            'household_structure_counts': defaultdict(int),
            'unassigned_people': 0,
        }

    def assign_all(self, venue_manager) -> Dict[str, Any]:
        """
        Assign attribute based on assignment level (household or person).

        Args:
            venue_manager: VenueManager with households and people

        Returns:
            Dictionary with assignment statistics
        """
        logger.info(f"Starting attribute assignment for '{self.attribute_name}'...")
        logger.info(f"Assignment level: {self.config.assignment_level}")
        logger.info("=" * 80)

        # Branch based on assignment level
        if self.config.assignment_level == "person":
            self._assign_all_people(venue_manager)
        else:  # household (default)
            self._assign_all_households(venue_manager)

        # Report statistics
        self._report_statistics()

        return self.stats

    def _assign_all_households(self, venue_manager):
        """Assign attributes at household level (existing logic)."""
        # Get all venues
        all_venues = venue_manager.get_all_venues_list()
        logger.info(f"Found {len(all_venues)} total venues")

        # Get households only
        households = [v for v in all_venues if v.type == "household"]
        logger.info(f"  Households: {len(households)}")
        logger.info("")

        # Assign households with progress tracking
        logger.info("Processing households...")
        total = len(households)
        progress_interval = max(1, total // 20)  # Report every 5%

        for i, household in enumerate(households):
            self._assign_household(household)

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == total:
                progress = ((i + 1) / total) * 100
                logger.info(f"  Progress: {i+1:,}/{total:,} ({progress:.1f}%)")

        logger.info(f"\n✓ Processed {self.stats['households_processed']} households")
        logger.info("")

    def _assign_all_people(self, venue_manager):
        """Assign attributes at person level (new logic)."""
        # Get all people from venue manager
        all_people = []
        for venue in venue_manager.get_all_venues_list():
            all_people.extend(venue.get_all_members())

        logger.info(f"Found {len(all_people)} total people")
        logger.info("")

        # Check required attributes
        self._check_required_attributes(all_people)

        # Assign each person
        logger.info("Processing people...")
        total = len(all_people)

        # Progress tracking
        progress_interval = max(1, total // 20)  # Report every 5%

        # Sample tracking for debugging
        sample_size = min(10, total)
        sample_indices = set(np.random.choice(total, sample_size, replace=False))
        samples_logged = []

        for i, person in enumerate(all_people):
            # Track if this is a sample person
            is_sample = i in sample_indices

            if is_sample:
                logger.debug(f"\n  [SAMPLE {len(samples_logged)+1}] Person {person.id}:")
                logger.debug(f"    Age: {person.age}, Sex: {person.sex}")
                logger.debug(f"    Geo Unit: {person.geographical_unit.name if person.geographical_unit else 'None'}")
                logger.debug(f"    Existing attributes: {list(person.properties.keys())}")

            self._assign_person(person, debug=is_sample)

            if is_sample:
                result = person.properties.get(self.attribute_name, "NOT_ASSIGNED")
                logger.debug(f"    Result: {self.attribute_name} = {result}")
                samples_logged.append((person.id, result))

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == total:
                progress = ((i + 1) / total) * 100
                logger.info(f"  Progress: {i+1:,}/{total:,} ({progress:.1f}%)")

        logger.info(f"\n✓ Processed {len(all_people)} people")
        logger.info(f"✓ Assigned {self.stats['total_people'] - self.stats['unassigned_people']} people")
        logger.info(f"✓ Fallback used: {self.stats.get('fallback_count', 0)} times")
        logger.info("")

    def _assign_household(self, household):
        """
        Assign attribute to all people in a household.

        Main assignment flow:
        1. Classify household structure
        2. Sort people by configured assignment order
        3. For each person:
           a. Determine role based on subset + already assigned roles
           b. Get assignment rule for (structure, role)
           c. Execute strategy
           d. Track assigned roles

        Args:
            household: Venue object (type="household")
        """
        # Get all members
        members = household.get_all_members()
        if not members:
            return

        if self.verbose:
            logger.debug(f"\n{'=' * 80}")
            logger.debug(f"Processing Household {household.id} "
                        f"(geo_unit={household.geographical_unit.name if household.geographical_unit else 'None'})")
            logger.debug(f"  Members: {len(members)}")
            logger.debug(f"  Original pattern: {household.properties.get('original_pattern', 'N/A')}")
            logger.debug(f"  Actual pattern: {household.properties.get('actual_pattern', 'N/A')}")

        # 1. Classify household structure
        structure = self.config.get_household_structure(household, verbose=self.verbose)
        if not structure:
            if self.verbose:
                logger.debug(f"  Could not classify household {household.id}, skipping")
            else:
                logger.warning(f"Could not classify household {household.id}, skipping")
            self.stats['unassigned_people'] += len(members)
            return

        # Store structure in household properties
        household.properties['_structure'] = structure
        self.stats['household_structure_counts'][structure] += 1

        if not self.verbose:
            logger.debug(f"Household {household.id}: structure={structure}, members={len(members)}")

        # Initialize assignment context
        context = {
            'attribute_name': self.attribute_name,
            'household_structure': structure,
        }

        # Track assigned roles (as a list to maintain order and count)
        assigned_roles: List[str] = []

        # 2. Sort people based on configured assignment order
        sorted_members = self._sort_members_by_assignment_order(
            members, household, structure
        )

        # 3. Assign each person in order
        for person in sorted_members:
            if self.verbose:
                category = self._get_person_category(person)
                logger.debug(f"\n  Assigning {person} (category={category}):")

            # 3a. Determine role
            role = self.config.get_person_role(
                person, structure, assigned_roles, verbose=self.verbose
            )

            if not role:
                if self.verbose:
                    logger.debug(f"    Could not determine role, skipping")
                else:
                    logger.warning(f"  Could not determine role for {person} in {household.id}")
                self.stats['unassigned_people'] += 1
                continue

            # Track assigned roles
            assigned_roles.append(role)

            # Store person by role in context (for strategies to reference)
            person_key = f"{role}_person"
            context[person_key] = person

            # 3b. Get assignment rule
            rule = self.config.get_assignment_rule(structure, role, verbose=self.verbose)

            if not rule:
                if self.verbose:
                    logger.debug(f"    No rule found for role '{role}', skipping")
                else:
                    logger.warning(f"  No rule for role '{role}' in structure '{structure}' for {person}")
                self.stats['unassigned_people'] += 1
                continue

            # 3c. Create and execute strategy
            try:
                strategy = StrategyFactory.create_strategy(rule.assignment, self.data_manager)
                value = strategy.assign(person, household, context)

                if value is not None:
                    # Assign attribute to person's properties dict
                    person.properties[self.attribute_name] = value

                    # Update statistics
                    self.stats['assignments_by_role'][role] += 1
                    self.stats['assignments_by_strategy'][strategy.strategy_type] += 1
                    self.stats['attribute_distribution'][value] += 1

                    if self.verbose:
                        logger.debug(f"    ✓ Assigned: {self.attribute_name}={value} "
                                   f"(role={role}, strategy={strategy.strategy_type})")
                    else:
                        logger.debug(f"  {person}: {self.attribute_name}={value} (role={role})")
                else:
                    logger.warning(f"  Strategy returned None for {person} (role={role})")
                    self.stats['unassigned_people'] += 1

            except Exception as e:
                logger.error(f"  Error assigning to {person}: {e}")
                self.stats['unassigned_people'] += 1

        if self.verbose:
            logger.debug(f"{'=' * 80}\n")

        self.stats['households_processed'] += 1
        self.stats['people_in_households'] += len(members)
        self.stats['total_people'] += len(members)

    def _sort_members_by_assignment_order(self, members, household, structure: str):
        """
        Sort household members by configured assignment order.

        Args:
            members: List of Person objects
            household: Household venue
            structure: Household structure name

        Returns:
            Sorted list of Person objects
        """
        def get_sort_key(person):
            """Get sort key for person based on configured assignment order."""
            if "household" not in person.activity_map or not person.activity_map["household"]:
                return (999, person.id)  # Fallback

            category = person.activity_map["household"][0].subset_name

            # Get assignment order configuration
            assignment_order = self.config.settings.get('assignment_order', {})

            # Check for structure-specific overrides first
            structure_overrides = assignment_order.get('structure_overrides', {})
            if structure in structure_overrides:
                priorities = structure_overrides[structure]
            else:
                # Use default category priorities
                priorities = assignment_order.get('category_priorities', {})

            # Get priority for this category (default 999 if not specified)
            priority = priorities.get(category, 999)
            return (priority, person.id)  # Use person ID as tiebreaker

        return sorted(members, key=get_sort_key)

    def _get_person_category(self, person) -> str:
        """
        Get person's category (subset name) from their household activity.

        Args:
            person: Person object

        Returns:
            Category name or "unknown"
        """
        if "household" in person.activity_map and person.activity_map["household"]:
            return person.activity_map["household"][0].subset_name
        return "unknown"

    def _assign_person(self, person, debug=False):
        """
        Assign attribute to a single person (person-level assignment).

        Args:
            person: Person object
            debug: If True, log detailed debug information
        """
        # Check dependencies
        for attr_name, attr_config in self.config.required_attributes.items():
            if attr_config.get('required', False):
                if attr_name not in person.properties:
                    if attr_config.get('error_if_missing', False):
                        if debug:
                            logger.debug(f"    ⚠️  Missing required attribute '{attr_name}', skipping")
                        self.stats['unassigned_people'] += 1
                        self.stats['total_people'] += 1
                        return

        # Get household (if person is in one)
        household = self._get_person_household(person)
        if debug:
            logger.debug(f"    Household: {household.id if household else 'None'}")

        # Get assignment rule for person-level
        rule = self.config.get_person_assignment_rule()
        if not rule:
            logger.warning(f"No assignment rule for person-level attribute '{self.attribute_name}'")
            self.stats['unassigned_people'] += 1
            self.stats['total_people'] += 1
            return

        # Create context
        context = {
            'attribute_name': self.attribute_name,
            'debug': debug,  # Pass debug flag through
        }

        # Create and execute strategy
        try:
            strategy = StrategyFactory.create_strategy(rule.assignment, self.data_manager)
            if debug:
                logger.debug(f"    Strategy: {strategy.strategy_type}")
                logger.debug(f"    Data source: {rule.assignment.get('data_source', 'N/A')}")

            value = strategy.assign(person, household, context)

            if value is not None:
                person.properties[self.attribute_name] = value
                self.stats['assignments_by_strategy'][strategy.strategy_type] += 1
                self.stats['attribute_distribution'][str(value)] += 1
                self.stats['total_people'] += 1

                if debug:
                    logger.debug(f"    ✓ Assigned: {value}")
            else:
                if debug:
                    logger.debug(f"    ⚠️  Strategy returned None")
                self.stats['unassigned_people'] += 1
                self.stats['total_people'] += 1

        except Exception as e:
            if debug:
                logger.error(f"    ❌ Error: {e}")
            else:
                logger.error(f"Error assigning to {person}: {e}")
            self.stats['unassigned_people'] += 1
            self.stats['total_people'] += 1

    def _get_person_household(self, person):
        """Get household venue for a person, if any."""
        if "household" in person.activity_map and person.activity_map["household"]:
            return person.activity_map["household"][0].venue
        return None

    def _check_required_attributes(self, people):
        """Check and log required attribute availability."""
        if not self.config.required_attributes:
            return

        logger.info("Checking required attributes...")
        for attr_name, attr_config in self.config.required_attributes.items():
            if not attr_config.get('required', False):
                continue

            missing_count = sum(1 for p in people if attr_name not in p.properties)
            total_count = len(people)
            present_count = total_count - missing_count

            logger.info(f"  '{attr_name}': {present_count}/{total_count} people have this attribute")

            if missing_count > 0:
                logger.warning(f"    {missing_count} people missing required attribute '{attr_name}'")

        logger.info("")

    def _report_statistics(self):
        """Report assignment statistics."""
        logger.info("=" * 80)
        logger.info("ASSIGNMENT STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Total people: {self.stats['total_people']}")
        if self.stats['people_in_households'] > 0:
            logger.info(f"  In households: {self.stats['people_in_households']}")
        if self.stats['households_processed'] > 0:
            logger.info(f"Households processed: {self.stats['households_processed']}")
        logger.info(f"Unassigned people: {self.stats['unassigned_people']}")
        logger.info("")

        # Household structure distribution (only if household-level)
        if self.stats['household_structure_counts']:
            logger.info("Household structures:")
            for structure, count in sorted(self.stats['household_structure_counts'].items()):
                logger.info(f"  {structure}: {count}")
            logger.info("")

        # Role distribution (only if household-level)
        if self.stats['assignments_by_role']:
            logger.info("Assignments by role:")
            for role, count in sorted(self.stats['assignments_by_role'].items()):
                logger.info(f"  {role}: {count}")
            logger.info("")

        # Strategy distribution
        if self.stats['assignments_by_strategy']:
            logger.info("Assignments by strategy:")
            for strategy, count in sorted(self.stats['assignments_by_strategy'].items()):
                logger.info(f"  {strategy}: {count}")
            logger.info("")

        # Attribute distribution
        logger.info(f"{self.attribute_name.capitalize()} distribution:")
        total_assigned = sum(self.stats['attribute_distribution'].values())
        for value, count in sorted(self.stats['attribute_distribution'].items()):
            percentage = (count / total_assigned * 100) if total_assigned > 0 else 0
            logger.info(f"  {value}: {count:6d} ({percentage:5.2f}%)")
        logger.info("")
        logger.info("=" * 80)


def assign_attributes(venue_manager, config_path: str, geo_units: Optional[set] = None) -> Dict[str, Any]:
    """
    Convenience function to assign attributes to a population.

    Args:
        venue_manager: VenueManager with households and venues
        config_path: Path to YAML configuration file
        geo_units: Optional set of geo unit codes to preload data for

    Returns:
        Assignment statistics dictionary
    """
    # Load configuration
    config = AttributeAssignmentConfig.from_yaml(config_path)

    # Initialize data manager
    data_manager = DataSourceManager(config)

    # Load data
    if geo_units:
        logger.info(f"Preloading data for {len(geo_units)} geographical units...")
        data_manager.load_all(geo_units)
    else:
        logger.info("Loading all data sources...")
        data_manager.load_all()

    # Create assigner and run
    assigner = AttributeAssigner(config, data_manager)
    stats = assigner.assign_all(venue_manager)

    return stats
