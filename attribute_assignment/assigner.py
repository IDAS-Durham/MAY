"""
Main orchestrator for attribute assignment.

This module coordinates the entire attribute assignment process:
- Classifying household structures
- Determining person roles
- Applying assignment rules and strategies
- Tracking assignment progress
"""

import logging
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from attribute_assignment.assignment_config import AttributeAssignmentConfig
from attribute_assignment.data_sources import DataSourceManager
from attribute_assignment.strategies import StrategyFactory

logger = logging.getLogger("attribute_assignment.assigner")


class AttributeAssigner:
    """
    Main orchestrator for attribute assignment.

    Assigns attribute values to all people in a population based on
    YAML configuration, demographic data, and household composition.
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

        # Statistics
        self.stats = {
            'total_people': 0,
            'people_in_households': 0,
            'people_in_venues': 0,
            'households_processed': 0,
            'venues_processed': 0,
            'assignments_by_rule': defaultdict(int),
            'attribute_distribution': defaultdict(int),
            'unassigned_people': 0,
        }

    def assign_all(self, venue_manager) -> Dict[str, Any]:
        """
        Assign attribute to all people in the population.

        Args:
            venue_manager: VenueManager with households and venues

        Returns:
            Dictionary with assignment statistics
        """
        logger.info(f"Starting attribute assignment for '{self.attribute_name}'...")
        logger.info("="*80)

        # Get all venues
        all_venues = venue_manager.get_all_venues_list()
        logger.info(f"Found {len(all_venues)} total venues")

        # Separate households from other venues
        households = [v for v in all_venues if v.type == "household"]
        other_venues = [v for v in all_venues if v.type != "household"]

        logger.info(f"  Households: {len(households)}")
        logger.info(f"  Other venues: {len(other_venues)}")
        logger.info("")

        # Assign households first
        logger.info("Processing households...")
        for household in households:
            self._assign_household(household)

        logger.info(f"✓ Processed {self.stats['households_processed']} households")
        logger.info("")

        # Assign other venues
        if other_venues:
            logger.info("Processing other venues...")
            for venue in other_venues:
                self._assign_venue(venue)

            logger.info(f"✓ Processed {self.stats['venues_processed']} venues")
            logger.info("")

        # Report statistics
        self._report_statistics()

        return self.stats

    def _assign_household(self, household):
        """
        Assign attribute to all people in a household.

        Args:
            household: Venue object (type="household")
        """
        # Get all members
        members = household.get_all_members()
        if not members:
            return

        # Classify household structure
        structure = self.config.get_household_structure(household)
        if not structure:
            logger.debug(f"Could not classify household {household.id}, using independent assignment")
            structure = "unknown"

        # Store structure in household properties
        household.properties['_structure'] = structure

        # Initialize assignment context
        context = {
            'attribute_name': self.attribute_name,
            'household_structure': structure,
            'assigned_people': set(),
            'people_by_role': {},
        }

        logger.debug(f"Household {household.id}: structure={structure}, members={len(members)}")

        # Assign in priority order (rules are already sorted by priority)
        for person in members:
            if person.id in context['assigned_people']:
                continue

            # Determine person's role
            role = self.config.get_person_role(person, household, context)
            if not role:
                logger.debug(f"  Could not determine role for {person}, using fallback")
                role = "independent_person"

            # Store person by role
            role_key = f"{role}_person"
            if role_key not in context:
                context[role_key] = person

            # Find applicable rule
            context['person_role'] = role
            rule = self.config.get_applicable_rule(person, household, context)

            if not rule:
                logger.warning(f"  No rule found for {person} (role={role})")
                self.stats['unassigned_people'] += 1
                continue

            # Create and execute strategy
            strategy = StrategyFactory.create_strategy(rule.assignment, self.data_manager)
            value = strategy.assign(person, household, context)

            if value is not None:
                # Assign attribute to person's properties dict
                person.properties[self.attribute_name] = value
                context['assigned_people'].add(person.id)

                # Update statistics
                self.stats['assignments_by_rule'][rule.name] += 1
                self.stats['attribute_distribution'][value] += 1

                logger.debug(f"  {person}: {self.attribute_name}={value} (rule={rule.name})")
            else:
                logger.warning(f"  Failed to assign {self.attribute_name} to {person}")
                self.stats['unassigned_people'] += 1

        self.stats['households_processed'] += 1
        self.stats['people_in_households'] += len(members)
        self.stats['total_people'] += len(members)

    def _assign_venue(self, venue):
        """
        Assign attribute to all people in a non-household venue.

        Args:
            venue: Venue object (not type="household")
        """
        # Get all members
        members = venue.get_all_members()
        if not members:
            return

        # Find applicable venue rule
        venue_rule = self.config.get_venue_rule(venue.type)
        if not venue_rule:
            logger.warning(f"No venue rule found for type '{venue.type}', skipping venue {venue.id}")
            return

        logger.debug(f"Venue {venue.id} (type={venue.type}): members={len(members)}")

        # Create strategy
        strategy = StrategyFactory.create_strategy(venue_rule.assignment, self.data_manager)

        # Assign to all members
        context = {'attribute_name': self.attribute_name}

        for person in members:
            value = strategy.assign(person, venue, context)

            if value is not None:
                # Assign attribute to person's properties dict
                person.properties[self.attribute_name] = value
                self.stats['attribute_distribution'][value] += 1
                logger.debug(f"  {person}: {self.attribute_name}={value}")
            else:
                logger.warning(f"  Failed to assign {self.attribute_name} to {person}")
                self.stats['unassigned_people'] += 1

        self.stats['venues_processed'] += 1
        self.stats['people_in_venues'] += len(members)
        self.stats['total_people'] += len(members)

    def _report_statistics(self):
        """Report assignment statistics."""
        logger.info("="*80)
        logger.info("Assignment Statistics")
        logger.info("="*80)

        logger.info(f"\nTotal people processed: {self.stats['total_people']:,}")
        logger.info(f"  In households: {self.stats['people_in_households']:,}")
        logger.info(f"  In other venues: {self.stats['people_in_venues']:,}")

        logger.info(f"\nVenues processed:")
        logger.info(f"  Households: {self.stats['households_processed']:,}")
        logger.info(f"  Other venues: {self.stats['venues_processed']:,}")

        if self.stats['unassigned_people'] > 0:
            logger.warning(f"\nUnassigned people: {self.stats['unassigned_people']:,}")

        # Assignments by rule
        if self.stats['assignments_by_rule']:
            logger.info(f"\nAssignments by rule:")
            for rule_name, count in sorted(self.stats['assignments_by_rule'].items(),
                                          key=lambda x: x[1], reverse=True):
                pct = 100 * count / max(self.stats['total_people'], 1)
                logger.info(f"  {rule_name}: {count:,} ({pct:.1f}%)")

        # Attribute distribution
        if self.stats['attribute_distribution']:
            logger.info(f"\n{self.attribute_name.title()} distribution:")
            total_assigned = sum(self.stats['attribute_distribution'].values())
            for value, count in sorted(self.stats['attribute_distribution'].items(),
                                      key=lambda x: x[1], reverse=True):
                pct = 100 * count / max(total_assigned, 1)
                logger.info(f"  {value}: {count:,} ({pct:.1f}%)")

        logger.info("\n" + "="*80)
        logger.info(f"✓ Attribute assignment complete for '{self.attribute_name}'")
        logger.info("="*80 + "\n")


def assign_attributes(venue_manager, config_path: str, geo_units: Optional[Set[str]] = None) -> Dict[str, Any]:
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
