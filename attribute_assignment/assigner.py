"""
Main orchestrator for attribute assignment.

Simplified attribute assignment system:
- Cleaner structure classification (Family/Couple/Independents)
- Simple role assignment (primary/secondary/extra based on naming)
- No complex condition evaluation
- Structure-based rule lookup
"""

import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict

from attribute_assignment.assignment_config import AttributeAssignmentConfig
from attribute_assignment.data_sources import DataSourceManager
from attribute_assignment.strategies import StrategyFactory

logger = logging.getLogger("attribute_assignment.assigner")


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
        Assign attribute to all people in households.

        Args:
            venue_manager: VenueManager with households

        Returns:
            Dictionary with assignment statistics
        """
        logger.info(f"Starting attribute assignment for '{self.attribute_name}'...")
        logger.info("=" * 80)

        # Get all venues
        all_venues = venue_manager.get_all_venues_list()
        logger.info(f"Found {len(all_venues)} total venues")

        # Get households only
        households = [v for v in all_venues if v.type == "household"]
        logger.info(f"  Households: {len(households)}")
        logger.info("")

        # Assign households
        logger.info("Processing households...")
        for household in households:
            self._assign_household(household)

        logger.info(f"✓ Processed {self.stats['households_processed']} households")
        logger.info("")

        # Report statistics
        self._report_statistics()

        return self.stats

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

    def _report_statistics(self):
        """Report assignment statistics."""
        logger.info("=" * 80)
        logger.info("ASSIGNMENT STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Total people: {self.stats['total_people']}")
        logger.info(f"  In households: {self.stats['people_in_households']}")
        logger.info(f"Households processed: {self.stats['households_processed']}")
        logger.info(f"Unassigned people: {self.stats['unassigned_people']}")
        logger.info("")

        # Household structure distribution
        logger.info("Household structures:")
        for structure, count in sorted(self.stats['household_structure_counts'].items()):
            logger.info(f"  {structure}: {count}")
        logger.info("")

        # Role distribution
        logger.info("Assignments by role:")
        for role, count in sorted(self.stats['assignments_by_role'].items()):
            logger.info(f"  {role}: {count}")
        logger.info("")

        # Strategy distribution
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
