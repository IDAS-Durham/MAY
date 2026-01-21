import logging
import numpy as np
from typing import Dict, List, Any, Optional
from collections import defaultdict

from .assignment_config import AttributeAssignmentConfig
from .data_sources import DataSourceManager
from .strategies import StrategyFactory

logger = logging.getLogger("may.attribute_assignment.assigner")

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

        # Cache strategy objects to avoid repeated creation
        self._strategy_cache = {}  # Maps strategy config hash to strategy instance

        # Pre-compute filter configuration (called 35M times in profiling!)
        self._has_filters = hasattr(config, 'filters') and config.filters
        self._filter_list = list(config.filters.items()) if self._has_filters else []
        self._activity_filters = config.filters.get('activities', {}) if self._has_filters else {}
        self._include_activities = self._activity_filters.get('include', [])
        self._exclude_activities = self._activity_filters.get('exclude', [])
        self._required_attrs = list(config.required_attributes.items()) if config.required_attributes else []

        # Statistics
        self.stats = {
            'total_people': 0,
            'people_in_households': 0,
            'people_in_other_residences': 0,
            'households_processed': 0,
            'other_residences_processed': 0,
            'assignments_by_venue_type': defaultdict(int),
            'assignments_by_rule': defaultdict(int),
            'assignments_by_role': defaultdict(int),
            'assignments_by_strategy': defaultdict(int),
            'attribute_distribution': defaultdict(int),
            'household_structure_counts': defaultdict(int),
            'unassigned_people': 0,
            'filtered_people': 0,  # People filtered out by age/activity filters
            'assigned_people': 0,  # People successfully assigned
        }

    def _get_or_create_strategy(self, assignment_config):
        """
        Get cached strategy or create new one.

        Args:
            assignment_config: Strategy configuration dict (from AttributeAssignmentRule)

        Returns:
            Strategy instance
        """
        # Use object id as cache key

        config_key = id(assignment_config)

        # Check cache
        if config_key not in self._strategy_cache:
            # Create new strategy
            self._strategy_cache[config_key] = StrategyFactory.create_strategy(
                assignment_config, self.data_manager
            )

        return self._strategy_cache[config_key]

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
        elif self.config.assignment_level in ["person_by_household", "person_by_residence"]:
            self._assign_all_residences(venue_manager)
        else:
            raise ValueError(f"Unknown assignment_level: '{self.config.assignment_level}'. "
                           f"Expected 'person', 'person_by_household', or 'person_by_residence'.")

        # Report statistics
        self._report_statistics()

        return self.stats

    def _assign_all_residences(self, venue_manager):
        """Assign attributes at residence level (households and communal establishments)."""
        # Get all venues
        all_venues = venue_manager.get_all_venues_list()
        logger.info(f"Found {len(all_venues)} total venues")

        # Count total people across ALL venues for accurate statistics
        total_people_in_simulation = sum(venue.size() for venue in all_venues)

        # Get household venue types from config (defaults to ["household"])
        household_venue_types = self.config.household_venue_types or ["household"]

        # Separate households from other residence venues based on config
        households = [v for v in all_venues if v.type in household_venue_types]
        other_residences = [v for v in all_venues if v.type not in household_venue_types]
        people_in_other_residences = sum(venue.size() for venue in other_residences)

        logger.info(f"  Households: {len(households)}")
        if other_residences:
            logger.info(f"  Other residences: {len(other_residences)} (containing {people_in_other_residences} people)")
        logger.info("")

        # Process households with structure-based logic
        logger.info("Processing households...")
        total = len(households)
        progress_interval = max(1, total // 20)  # Report every 5%

        for i, household in enumerate(households):
            self._assign_household(household)

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == total:
                progress = ((i + 1) / total) * 100
                logger.info(f"  Progress: {i+1:,}/{total:,} ({progress:.1f}%)")

        logger.info(f"✓ Processed {self.stats['households_processed']} households")
        logger.info("")

        # Process other residences (care homes, dorms, etc.) with simpler logic
        people_assigned_in_other_residences = 0
        if other_residences:
            logger.info(f"Processing {len(other_residences)} other residences (care homes, dorms, etc.)...")
            people_assigned_in_other_residences = self._assign_other_residences(other_residences)
            logger.info(f"✓ Assigned {people_assigned_in_other_residences} people in other residences")
            logger.info("")

        # Update total_people stat to reflect actual total
        self.stats['total_people'] = total_people_in_simulation
        self.stats['unassigned_people'] = total_people_in_simulation - self.stats['people_in_households'] - people_assigned_in_other_residences

    def _assign_other_residences(self, venues):
        """
        Assign attributes to people in non-household residences (care homes, dorms, etc.).
        Uses rules defined in venue_assignment_rules section of config.

        Args:
            venues: List of non-household residence venues

        Returns:
            Number of people assigned
        """
        people_assigned = 0
        venues_processed = 0

        for venue in venues:
            members = venue.get_all_members()
            if not members:
                continue

            # Find the assignment rule for this venue type
            venue_rule = None
            for rule in self.config.venue_assignment_rules:
                if venue.type in rule.get('venue_types', []):
                    venue_rule = rule
                    break

            if not venue_rule:
                logger.warning(f"No assignment rule found for venue type '{venue.type}', skipping")
                continue

            # Get the assignment strategy from the rule
            assignment_config = venue_rule.get('assignment', {})

            try:
                strategy = self._get_or_create_strategy(assignment_config)
                venue_assigned = 0

                # Assign each person
                for person in members:
                    # Skip if already assigned
                    if self.attribute_name in person.properties:
                        continue

                    # Create context for strategy
                    context = {
                        'attribute_name': self.attribute_name,
                        'venue_type': venue.type
                    }

                    value = strategy.assign(person, venue, context)

                    if value is not None:
                        person.properties[self.attribute_name] = value
                        self.stats['attribute_distribution'][value] += 1
                        self.stats['assignments_by_strategy'][f'venue_{venue.type}'] += 1
                        self.stats['assignments_by_venue_type'][venue.type] += 1
                        people_assigned += 1
                        venue_assigned += 1
                    else:
                        self.stats['unassigned_people'] += 1
                        logger.warning(f"Failed to assign {self.attribute_name} to person {person.id} in {venue.type}")

                if venue_assigned > 0:
                    venues_processed += 1

            except Exception as e:
                logger.error(f"Error assigning attributes to venue {venue.id} ({venue.type}): {e}")
                continue

        # Update stats
        self.stats['people_in_other_residences'] = people_assigned
        self.stats['other_residences_processed'] = venues_processed

        return people_assigned

    def _passes_filters(self, person):
        """
        Check if person passes all configured filters (optimized - called 35M times!).

        Args:
            person: Person object

        Returns:
            bool: True if person passes all filters
        """
        if not self._has_filters:
            # Check required attributes even if no filters
            for attr_name, attr_config in self._required_attrs:
                if attr_config.get('required', False):
                    if attr_name not in person.properties:
                        if attr_config.get('error_if_missing', False):
                            return False
            return True

        # 1. Attribute filters
        # Use pre-computed filter list instead of repeated hasattr/dict lookups
        for _, filter_config in self._filter_list:
            attr_name = filter_config.get('attribute')
            if not attr_name:
                continue

            # Optimized lookup: check properties first as it's common
            # Avoid hasattr(person, 'properties') if we can assume it exists or use getattr
            person_value = person.properties.get(attr_name)
            if person_value is None:
                # Direct attribute access optimization
                try:
                    person_value = getattr(person, attr_name)
                except AttributeError:
                    person_value = None

            if person_value is None:
                continue

            filter_type = filter_config.get('type')
            if filter_type == 'numerical':
                numerical_config = filter_config.get('numerical', {})
                min_value = numerical_config.get('min')
                if min_value is not None and person_value < min_value:
                    return False
                max_value = numerical_config.get('max')
                if max_value is not None and person_value > max_value:
                    return False
            elif filter_type == 'categorical':
                # Add categorical filter support if needed in the future
                pass

        # 2. Activity filters (Fast set intersection check)
        if self._include_activities or self._exclude_activities:
            # Optimize: use direct attribute access for activities (it's a slot)
            person_activities = person.activities
            
            if self._include_activities:
                # Optimize: simple loop is faster than generator for small lists
                has_activity = False
                for a in self._include_activities:
                    if a in person_activities:
                        has_activity = True
                        break
                if not has_activity:
                    return False

            if self._exclude_activities:
                for a in self._exclude_activities:
                    if a in person_activities:
                        return False

        # 3. Required attributes
        for attr_name, attr_config in self._required_attrs:
            if attr_config.get('required', False):
                if attr_name not in person.properties:
                    if attr_config.get('error_if_missing', False):
                        return False

        return True

    def _assign_all_people(self, venue_manager):
        """
        Assign attributes at person level.

        """
        # Get all people from venue manager
        all_people = []
        for venue in venue_manager.get_all_venues_list():
            all_people.extend(venue.get_all_members())

        logger.info(f"Found {len(all_people)} total people")
        logger.info("")

        # Check required attributes
        self._check_required_attributes(all_people)

        # Pre-filter all people once
        logger.info("Pre-filtering people by age/activity filters...")
        eligible_people = []
        for person in all_people:
            if self._passes_filters(person):
                eligible_people.append(person)
            else:
                self.stats['filtered_people'] += 1

        self.stats['total_people'] = len(all_people)
        logger.info(f"  ✓ Eligible for assignment: {len(eligible_people)} / {len(all_people)} people")
        logger.info(f"  ✓ Filtered out: {self.stats['filtered_people']} people")
        logger.info("")

        # Get assignment rule and strategy
        rule = self.config.get_person_assignment_rule()
        if not rule:
            logger.warning(f"No assignment rule for person-level attribute '{self.attribute_name}'")
            self.stats['unassigned_people'] = len(eligible_people)
            logger.info("")
            return

        strategy = self._get_or_create_strategy(rule.assignment)

        # Check if strategy supports batch assignment
        if hasattr(strategy, 'assign_batch') and callable(getattr(strategy, 'assign_batch')):
            logger.info("Using BATCH assignment mode for better performance...")
            self._assign_all_people_batch(eligible_people, strategy)
        else:
            logger.info("Using standard assignment mode...")
            self._assign_all_people_sequential(eligible_people, strategy)

        logger.info(f"✓ Processed {len(all_people)} people")
        logger.info(f"✓ Filtered {self.stats['filtered_people']} people (age/activity filters)")
        logger.info(f"✓ Assigned {self.stats['assigned_people']} people")
        logger.info(f"✓ Unassigned {self.stats['unassigned_people']} people (failed assignment)")
        logger.info(f"✓ Fallback used: {self.stats.get('fallback_count', 0)} times")
        logger.info("")

    def _assign_all_people_batch(self, eligible_people, strategy):
        """
        Batch assignment mode.

        Uses strategy's assign_batch method to process all people together.

        Args:
            eligible_people: List of pre-filtered people
            strategy: Assignment strategy with assign_batch method
        """
        logger.info("Processing people in batch mode...")
        total = len(eligible_people)

        # Progress tracking
        progress_interval = max(1, total // 20)  # Report every 5%

        # Prepare batch data
        logger.info(f"  Preparing batch data for {total:,} people...")
        households = [self._get_person_household(p) for p in eligible_people]
        contexts = [{'attribute_name': self.attribute_name} for _ in eligible_people]

        # Call batch assignment
        logger.info(f"  Running batch assignment...")
        results = strategy.assign_batch(eligible_people, households, contexts)

        # Assign results to people
        logger.info(f"  Applying results to people...")
        for i, (person, value) in enumerate(zip(eligible_people, results)):
            if value is not None:
                # Handle single value or multiple values (dict)
                if isinstance(value, dict):
                    # Multiple attributes returned
                    for attr_name, attr_value in value.items():
                        person.properties[attr_name] = attr_value
                        if attr_name == self.attribute_name:
                            self.stats['attribute_distribution'][str(attr_value)] += 1
                else:
                    # Single attribute
                    person.properties[self.attribute_name] = value
                    self.stats['attribute_distribution'][str(value)] += 1

                self.stats['assignments_by_strategy'][strategy.strategy_type] += 1
                self.stats['assigned_people'] += 1
            else:
                self.stats['unassigned_people'] += 1

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == total:
                progress = ((i + 1) / total) * 100
                logger.info(f"    Progress: {i+1:,}/{total:,} ({progress:.1f}%)")

        logger.info(f"✓ Batch processed {total:,} people")

    def _assign_all_people_sequential(self, eligible_people, strategy):
        """
        Standard sequential assignment mode.

        Args:
            eligible_people: List of pre-filtered people
            strategy: Assignment strategy (already created, reuse it!)
        """
        logger.info("Processing people sequentially...")
        total = len(eligible_people)

        # Progress tracking
        progress_interval = max(1, total // 20)  # Report every 5%

        # Sample tracking for debugging
        sample_size = min(10, total) if total > 0 else 0
        sample_indices = set(np.random.choice(total, sample_size, replace=False)) if total > 0 else set()
        samples_logged = []

        # Process each person with the pre-created strategy
        for i, person in enumerate(eligible_people):
            # Track if this is a sample person
            is_sample = i in sample_indices

            if is_sample:
                logger.debug(f"\n  [SAMPLE {len(samples_logged)+1}] Person {person.id}:")
                logger.debug(f"    Age: {person.age}, Sex: {person.sex}")
                logger.debug(f"    Geo Unit: {person.geographical_unit.name if person.geographical_unit else 'None'}")
                logger.debug(f"    Existing attributes: {list(person.properties.keys())}")

            # Pass strategy directly instead of looking it up again
            household = self._get_person_household(person)
            context = {'attribute_name': self.attribute_name, 'debug': is_sample}

            try:
                value = strategy.assign(person, household, context)

                if value is not None:
                    # Handle single value or multiple values (dict)
                    if isinstance(value, dict):
                        for attr_name, attr_value in value.items():
                            person.properties[attr_name] = attr_value
                            if attr_name == self.attribute_name:
                                self.stats['attribute_distribution'][str(attr_value)] += 1
                    else:
                        person.properties[self.attribute_name] = value
                        self.stats['attribute_distribution'][str(value)] += 1

                    self.stats['assignments_by_strategy'][strategy.strategy_type] += 1
                    self.stats['assigned_people'] += 1
                else:
                    self.stats['unassigned_people'] += 1
            except Exception as e:
                logger.error(f"Exception assigning {self.attribute_name} to person {person.id}: {e}")
                self.stats['unassigned_people'] += 1

            if is_sample:
                result = person.properties.get(self.attribute_name, "NOT_ASSIGNED")
                logger.debug(f"    Result: {self.attribute_name} = {result}")
                samples_logged.append((person.id, result))

            # Log progress
            if (i + 1) % progress_interval == 0 or (i + 1) == total:
                progress = ((i + 1) / total) * 100
                logger.info(f"  Progress: {i+1:,}/{total:,} ({progress:.1f}%)")

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

        # OPTIMIZATION: Pre-calculate person categories (subsets) to avoid repeated lookups
        # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
        person_categories = {}
        for person in members:
            category = "unknown"
            if "residence" in person.activity_map and "household" in person.activity_map["residence"]:
                res_subsets = person.activity_map["residence"]["household"]
                if res_subsets:
                    category = res_subsets[0].subset_name
            person_categories[person.id] = category

        # 1. Classify household structure
        # Pass pre-calculated categories if possible, but get_household_structure currently uses internal logic
        # For now, just optimize the call itself
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
            members, structure, person_categories
        )

        # 3. Assign each person in order
        for person in sorted_members:
            category = person_categories.get(person.id, "unknown")
            
            if self.verbose:
                logger.debug(f"\n  Assigning {person} (category={category}):")

            # 3a. Determine role
            # OPTIMIZATION: Pass pre-calculated category
            role = self.config.get_person_role(
                person, structure, assigned_roles, verbose=self.verbose,
                person_category=category
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
            # OPTIMIZATION: get_assignment_rule is already fairly fast, but could be memoized in config
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
                strategy = self._get_or_create_strategy(rule.assignment)
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

    def _sort_members_by_assignment_order(self, members, structure: str, person_categories: Dict[int, str] = None):
        """
        Sort household members by configured assignment order.

        Args:
            members: List of Person objects
            structure: Household structure name
            person_categories: Optional dict of pre-calculated categories
        """
        def get_sort_key(person):
            """Get sort key for person based on configured assignment order."""
            # Use pre-calculated category if available
            if person_categories:
                category = person_categories.get(person.id, "unknown")
            else:
                # Fallback to recalculating
                # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
                if "residence" not in person.activity_map or "household" not in person.activity_map["residence"] or not person.activity_map["residence"]["household"]:
                     category = "unknown"
                else:
                     category = person.activity_map["residence"]["household"][0].subset_name

            if category == "unknown":
                 return (999, person.id)

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
        # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
        if "residence" in person.activity_map and "household" in person.activity_map["residence"] and person.activity_map["residence"]["household"]:
            return person.activity_map["residence"]["household"][0].subset_name
        return "unknown"


    def _assign_person_without_filter_check(self, person, debug=False):
        """
        Assign attribute to a single person (person-level assignment).
        Assumes filtering has already been done.

        Skips filter checks for pre-filtered people.

        Args:
            person: Person object
            debug: If True, log detailed debug information
        """
        # Get household (if person is in one)
        household = self._get_person_household(person)
        if debug:
            logger.debug(f"    Household: {household.id if household else 'None'}")

        # Get assignment rule for person-level
        rule = self.config.get_person_assignment_rule()
        if not rule:
            logger.warning(f"No assignment rule for person-level attribute '{self.attribute_name}'")
            self.stats['unassigned_people'] += 1
            return

        # Create context
        context = {
            'attribute_name': self.attribute_name,
            'debug': debug,  # Pass debug flag through
        }

        # Create and execute strategy
        try:
            strategy = self._get_or_create_strategy(rule.assignment)
            if debug:
                logger.debug(f"    Strategy: {strategy.strategy_type}")
                logger.debug(f"    Data source: {rule.assignment.get('data_source', 'N/A')}")

            value = strategy.assign(person, household, context)

            if value is not None:
                # Handle single value or multiple values (dict)
                if isinstance(value, dict):
                    # Multiple attributes returned (e.g., workplace_location and work_mode)
                    for attr_name, attr_value in value.items():
                        person.properties[attr_name] = attr_value
                        if attr_name == self.attribute_name:
                            self.stats['attribute_distribution'][str(attr_value)] += 1
                    if debug:
                        logger.debug(f"    ✓ Assigned: {value}")
                else:
                    # Single attribute
                    person.properties[self.attribute_name] = value
                    self.stats['attribute_distribution'][str(value)] += 1
                    if debug:
                        logger.debug(f"    ✓ Assigned: {value}")

                self.stats['assignments_by_strategy'][strategy.strategy_type] += 1
                self.stats['assigned_people'] += 1
            else:
                # Strategy returned None - log detailed failure info
                logger.warning(f"Failed to assign {self.attribute_name} to person {person.id}")
                logger.warning(f"  Person details: age={person.age}, sex={person.sex}, geo_unit={person.geographical_unit.name if person.geographical_unit else 'None'}")

                # Show residence information
                if household:
                    logger.warning(f"  Residence: Household {household.id} in {household.geographical_unit.name if household.geographical_unit else 'None'}")
                else:
                    # Check activity_map for other residence types
                    # UNIFIED STRUCTURE: activity_map['residence'][venue_type] = [subsets]
                    if 'residence' in person.activity_map:
                        residence_types = [res_type for res_type in person.activity_map['residence'].keys() if res_type in ['care_home', 'student_dorms', 'boarding_school']]
                        if residence_types:
                            res_type = residence_types[0]
                            res_venue = person.activity_map['residence'][res_type][0].venue if person.activity_map['residence'][res_type] else None
                            logger.warning(f"  Residence: {res_type} {res_venue.id if res_venue else 'unknown'} (type={res_venue.type if res_venue else 'unknown'})")
                        else:
                            logger.warning(f"  Residence: None (no household or care facility)")
                    else:
                        logger.warning(f"  Residence: None (no household or care facility)")

                logger.warning(f"  Existing attributes: {list(person.properties.keys())}")
                logger.warning(f"  Strategy: {strategy.strategy_type}, Data source: {rule.assignment.get('data_source', 'N/A')}")
                if debug:
                    logger.debug(f"    ⚠️  Strategy returned None")
                self.stats['unassigned_people'] += 1

        except Exception as e:
            # Exception during assignment - log detailed error info
            logger.error(f"Exception assigning {self.attribute_name} to person {person.id}: {e}")
            logger.error(f"  Person details: age={person.age}, sex={person.sex}, geo_unit={person.geographical_unit.name if person.geographical_unit else 'None'}")
            logger.error(f"  Existing attributes: {list(person.properties.keys())}")
            logger.error(f"  Strategy: {strategy.strategy_type if 'strategy' in locals() else 'unknown'}")
            if debug:
                import traceback
                logger.error(f"    Traceback:\n{traceback.format_exc()}")
            self.stats['unassigned_people'] += 1

    def _get_person_household(self, person):
        """Get household venue for a person, if any."""
        # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
        if "residence" in person.activity_map and "household" in person.activity_map["residence"] and person.activity_map["residence"]["household"]:
            return person.activity_map["residence"]["household"][0].venue
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

        # Show filtered/assigned/unassigned breakdown
        if self.stats.get('filtered_people', 0) > 0:
            logger.info(f"Filtered people (age/activity): {self.stats['filtered_people']}")
        if self.stats.get('assigned_people', 0) > 0:
            logger.info(f"Assigned people: {self.stats['assigned_people']}")
        if self.stats['unassigned_people'] > 0:
            logger.info(f"Unassigned people (failures): {self.stats['unassigned_people']}")

        # Household-specific stats
        if self.stats['people_in_households'] > 0:
            logger.info(f"  In households: {self.stats['people_in_households']}")
        if self.stats['people_in_other_residences'] > 0:
            logger.info(f"  In other residences: {self.stats['people_in_other_residences']}")
        if self.stats['households_processed'] > 0:
            logger.info(f"Households processed: {self.stats['households_processed']}")
        if self.stats['other_residences_processed'] > 0:
            logger.info(f"Other residences processed: {self.stats['other_residences_processed']}")
        logger.info("")

        # Show breakdown by venue type if applicable
        if self.stats['assignments_by_venue_type']:
            logger.info("Assignments by venue type:")
            for venue_type, count in sorted(self.stats['assignments_by_venue_type'].items()):
                logger.info(f"  {venue_type}: {count}")
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

        # Attribute distribution (can be disabled via settings)
        show_distribution = self.config.settings.get('logging', {}).get('show_attribute_distribution', True)

        if show_distribution:
            logger.info(f"{self.attribute_name.capitalize()} distribution:")
            total_assigned = sum(self.stats['attribute_distribution'].values())
            for value, count in sorted(self.stats['attribute_distribution'].items()):
                percentage = (count / total_assigned * 100) if total_assigned > 0 else 0
                logger.info(f"  {value}: {count:6d} ({percentage:5.2f}%)")
            logger.info("")
        else:
            # Still show summary count even when distribution is hidden
            unique_values = len(self.stats['attribute_distribution'])
            total_assigned = sum(self.stats['attribute_distribution'].values())
            logger.info(f"{self.attribute_name.capitalize()} distribution: {unique_values} unique values, {total_assigned} total assignments")
            logger.info("")

        logger.info("=" * 80)