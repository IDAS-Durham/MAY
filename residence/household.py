"""
Household module for distributing people into households.

This module handles:
- Loading household composition data from CSV
- Parsing household composition patterns (e.g., ">=2 >=0 2 0")
- Matching people to households based on age categories
- Handling census data obfuscation through composition demotion
"""

import os
import logging
import yaml
import random
import pandas as pd
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

from geography.geography import GeographicalUnit, Geography
from population.person import Person
from population.population import PopulationManager

logger = logging.getLogger("household")


@dataclass
class AgeCategory:
    """Represents an age category for household composition."""
    name: str
    symbol: str
    min_age: int
    max_age: Optional[int]

    def matches(self, age: int) -> bool:
        """Check if an age falls within this category."""
        if self.max_age is None:
            return age >= self.min_age
        return self.min_age <= age <= self.max_age

    def __repr__(self):
        max_str = f"{self.max_age}" if self.max_age is not None else "∞"
        return f"{self.name}({self.min_age}-{max_str})"


@dataclass
class CompositionPattern:
    """
    Represents a household composition pattern.

    Example: ">=2 >=0 2 0" means:
    - 2 or more people in category 0 (Kids)
    - 0 or more people in category 1 (Young Adults)
    - exactly 2 people in category 2 (Adults)
    - exactly 0 people in category 3 (Old Adults)
    """
    original_pattern: str
    requirements: List[Tuple[str, int]]  # List of (operator, count) for each category
    # operator can be "exact" or "gte" (greater than or equal)

    @classmethod
    def from_string(cls, pattern: str) -> 'CompositionPattern':
        """
        Parse a composition pattern string.

        Args:
            pattern: Pattern string like ">=2 >=0 2 0"

        Returns:
            CompositionPattern object
        """
        parts = pattern.strip().split()
        requirements = []

        for part in parts:
            if part.startswith(">="):
                # Greater-than-or-equal requirement
                count = int(part[2:])
                requirements.append(("gte", count))
            else:
                # Exact requirement
                count = int(part)
                requirements.append(("exact", count))

        return cls(original_pattern=pattern, requirements=requirements)

    def get_min_count(self, category_idx: int) -> int:
        """Get minimum required count for a category."""
        if category_idx >= len(self.requirements):
            return 0
        operator, count = self.requirements[category_idx]
        return count

    def get_max_count(self, category_idx: int) -> Optional[int]:
        """Get maximum allowed count for a category (None if unlimited)."""
        if category_idx >= len(self.requirements):
            return None
        operator, count = self.requirements[category_idx]
        if operator == "exact":
            return count
        else:  # gte
            return None  # No upper limit

    def is_flexible(self, category_idx: int) -> bool:
        """Check if a category has flexible (>=) requirement."""
        if category_idx >= len(self.requirements):
            return True
        operator, _ = self.requirements[category_idx]
        return operator == "gte"

    def min_household_size(self) -> int:
        """Calculate minimum household size required."""
        return sum(self.get_min_count(i) for i in range(len(self.requirements)))

    def demote_once(self, priority_order: List[int]) -> Optional['CompositionPattern']:
        """
        Attempt to demote this pattern by reducing requirements.

        Args:
            priority_order: List of category indices in order of demotion priority

        Returns:
            New CompositionPattern with reduced requirements, or None if can't demote
        """
        new_requirements = list(self.requirements)

        # Try to demote in priority order
        for cat_idx in priority_order:
            if cat_idx >= len(new_requirements):
                continue

            operator, count = new_requirements[cat_idx]

            # Try to reduce the count
            if operator == "gte" and count > 0:
                # Reduce >=N to >=(N-1)
                new_requirements[cat_idx] = ("gte", count - 1)
                new_pattern = self._requirements_to_string(new_requirements)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )
            elif operator == "exact" and count > 0:
                # Reduce exact N to (N-1)
                new_requirements[cat_idx] = ("exact", count - 1)
                new_pattern = self._requirements_to_string(new_requirements)
                return CompositionPattern(
                    original_pattern=self.original_pattern,
                    requirements=new_requirements
                )

        # Couldn't demote further
        return None

    def _requirements_to_string(self, requirements: List[Tuple[str, int]]) -> str:
        """Convert requirements back to pattern string."""
        parts = []
        for operator, count in requirements:
            if operator == "gte":
                parts.append(f">={count}")
            else:
                parts.append(str(count))
        return " ".join(parts)

    def __repr__(self):
        return f"Pattern({self._requirements_to_string(self.requirements)})"

    def to_string(self) -> str:
        """Get current pattern as string."""
        return self._requirements_to_string(self.requirements)


@dataclass
class Household:
    """Represents a household with residents."""
    id: int
    geographical_unit: GeographicalUnit
    residents: List['Person'] = field(default_factory=list)
    properties: Dict = field(default_factory=dict)

    def add_resident(self, person: 'Person'):
        """Add a person to this household."""
        self.residents.append(person)
        person.residence = self

    def size(self) -> int:
        """Get household size."""
        return len(self.residents)

    def get_composition(self) -> Dict[str, int]:
        """Get household composition by age category."""
        if not hasattr(self, '_age_categories'):
            return {}

        composition = {cat.name: 0 for cat in self._age_categories}
        for person in self.residents:
            for cat in self._age_categories:
                if cat.matches(person.age):
                    composition[cat.name] += 1
                    break
        return composition

    def __repr__(self):
        return f"Household(id={self.id}, unit={self.geographical_unit.name}, size={self.size()})"


class HouseholdDistributor:
    """
    Manages household distribution and people allocation.

    This class:
    - Loads household composition data from CSV
    - Loads configuration from YAML
    - Distributes people into households based on composition patterns
    - Handles census obfuscation through pattern demotion
    """

    def __init__(self, geography: Geography, population: PopulationManager,
                 data_dir: str = "data/households", config_file: str = "households_config.yaml"):
        """
        Initialize the household distributor.

        Args:
            geography: Geography object with loaded geographical units
            population: PopulationManager with generated population
            data_dir: Directory containing household data files
            config_file: Path to YAML configuration file (relative to data_dir)
        """
        self.geography = geography
        self.population = population
        self.data_dir = data_dir

        # Load configuration
        config_path = os.path.join(data_dir, config_file)
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Parse age categories from config
        self.age_categories = self._parse_age_categories()

        # Household data
        self.households: List[Household] = []
        self.household_counts_by_area: Dict[str, Dict[str, int]] = {}
        self.allocated_people: Set[int] = set()  # Person IDs that have been allocated

        # Pool of available people by area and category
        self.person_pool_by_area: Dict[str, List[List['Person']]] = {}

        # Round tracking
        self.current_round: int = 0
        self.pools_prepared: bool = False

        logger.info(f"Initialized HouseholdDistributor with {len(self.age_categories)} age categories")
        for cat in self.age_categories:
            logger.info(f"  - {cat}")

    def _parse_age_categories(self) -> List[AgeCategory]:
        """Parse age categories from config."""
        categories = []
        for cat_config in self.config['age_categories']:
            cat = AgeCategory(
                name=cat_config['name'],
                symbol=cat_config['symbol'],
                min_age=cat_config['min_age'],
                max_age=cat_config['max_age']
            )
            categories.append(cat)
        return categories

    def load_household_data(self, filename: str = "households.csv"):
        """
        Load household composition data from CSV.

        Args:
            filename: Name of CSV file in data_dir
        """
        filepath = os.path.join(self.data_dir, filename)
        logger.info(f"Loading household data from {filepath}")

        df = pd.read_csv(filepath)

        # First column is the area code, rest are household compositions
        area_col = df.columns[0]
        composition_cols = df.columns[1:]

        logger.info(f"Found {len(df)} areas with {len(composition_cols)} household types")

        # Store household counts by area
        for _, row in df.iterrows():
            area_code = row[area_col]

            # Only include areas that are in our loaded geography
            if area_code not in self.geography.units:
                continue

            counts = {}
            for col in composition_cols:
                count = int(row[col])
                if count > 0:
                    counts[col] = count

            if counts:
                self.household_counts_by_area[area_code] = counts

        logger.info(f"Loaded household data for {len(self.household_counts_by_area)} geographical units")

    def _categorize_person(self, person: Person) -> int:
        """Get the category index for a person based on their age."""
        for idx, cat in enumerate(self.age_categories):
            if cat.matches(person.age):
                return idx
        # Shouldn't happen, but default to last category
        return len(self.age_categories) - 1

    def _prepare_person_pools(self, refresh: bool = False):
        """
        Prepare pools of available people by area and age category.

        Args:
            refresh: If True, refresh pools with currently unallocated people.
                    If False and pools already exist, skip preparation.
        """
        if self.pools_prepared and not refresh:
            logger.debug("Person pools already prepared, skipping...")
            return

        logger.info("Preparing person pools by area and age category...")

        if refresh:
            # Clear existing pools for refresh
            self.person_pool_by_area = {}

        # Get all SGU units
        sgu_units = self.geography.get_units_by_level("SGU")

        for area_code, unit in sgu_units.items():
            # Get all people in this area
            people = self.population.get_people_by_area(area_code)

            if not people:
                continue

            # Initialize category pools
            category_pools = [[] for _ in self.age_categories]

            # Categorize each person (only if not already allocated)
            for person in people:
                if person.id not in self.allocated_people:
                    cat_idx = self._categorize_person(person)
                    category_pools[cat_idx].append(person)

            # Shuffle each pool for randomness
            for pool in category_pools:
                random.shuffle(pool)

            self.person_pool_by_area[area_code] = category_pools

            # Log pool sizes
            pool_sizes = [len(pool) for pool in category_pools]
            logger.debug(f"  {area_code}: {pool_sizes}")

        total_people = sum(sum(len(pool) for pool in pools)
                          for pools in self.person_pool_by_area.values())
        logger.info(f"Prepared person pools for {len(self.person_pool_by_area)} areas ({total_people} total people)")
        self.pools_prepared = True

    def _allocate_household(self, area_code: str, pattern: CompositionPattern) -> Optional[Household]:
        """
        Attempt to allocate a household in an area with the given pattern.

        Args:
            area_code: SGU code
            pattern: Composition pattern to match

        Returns:
            Household object if successful, None otherwise
        """
        if area_code not in self.person_pool_by_area:
            return None

        pools = self.person_pool_by_area[area_code]
        selected_people = []

        # Try to select people for each category
        for cat_idx in range(len(self.age_categories)):
            min_count = pattern.get_min_count(cat_idx)
            max_count = pattern.get_max_count(cat_idx)

            available = len(pools[cat_idx])

            # Check if we have enough people
            if available < min_count:
                # Can't fulfill this household
                return None

            # Decide how many to take
            if max_count is not None:
                count = max_count
            else:
                # Flexible, take minimum required
                count = min_count

            # Take people from pool
            if count > 0:
                selected = pools[cat_idx][:count]
                selected_people.extend(selected)
                pools[cat_idx] = pools[cat_idx][count:]

        if not selected_people:
            return None

        # Create household
        unit = self.geography.get_unit(area_code)
        household = Household(
            id=len(self.households),
            geographical_unit=unit,
            properties={'original_pattern': pattern.original_pattern}
        )
        household._age_categories = self.age_categories

        # Add residents
        for person in selected_people:
            household.add_resident(person)
            self.allocated_people.add(person.id)

        return household

    def _attempt_with_demotion(self, area_code: str, pattern: CompositionPattern,
                               max_attempts: int) -> Optional[Household]:
        """
        Attempt to allocate a household, using demotion if necessary.

        Args:
            area_code: SGU code
            pattern: Initial composition pattern
            max_attempts: Maximum demotion attempts

        Returns:
            Household object if successful, None otherwise
        """
        # Get demotion priority from config
        priority_config = self.config['demotion']['priority']
        priority_order = []
        for cat_idx, cat in enumerate(self.age_categories):
            priority = priority_config.get(cat.name, 999)
            priority_order.append((priority, cat_idx))
        priority_order.sort()  # Sort by priority (lower = demote first)
        priority_indices = [idx for _, idx in priority_order]

        current_pattern = pattern

        for attempt in range(max_attempts + 1):
            # Try to allocate with current pattern
            household = self._allocate_household(area_code, current_pattern)

            if household:
                if attempt > 0:
                    logger.debug(f"    Succeeded after {attempt} demotion(s): {current_pattern.to_string()}")
                return household

            # Check minimum size
            min_size = self.config['demotion']['min_household_size']
            if current_pattern.min_household_size() < min_size:
                logger.debug(f"    Pattern too small after demotion: {current_pattern.to_string()}")
                return None

            # Try to demote
            if attempt < max_attempts:
                new_pattern = current_pattern.demote_once(priority_indices)
                if new_pattern is None:
                    logger.debug(f"    Cannot demote further: {current_pattern.to_string()}")
                    return None
                current_pattern = new_pattern
            else:
                logger.debug(f"    Max demotion attempts reached: {current_pattern.to_string()}")
                return None

        return None

    def distribute_households(self):
        """
        Main method to distribute people into households.

        This method:
        1. Prepares person pools by area
        2. Iterates through household composition data
        3. Attempts to create households with given patterns
        4. Uses demotion when needed to handle census obfuscation
        """
        logger.info("Starting household distribution...")

        # Prepare pools
        self._prepare_person_pools()

        # Get config
        demotion_enabled = self.config['demotion']['enabled']
        max_attempts = self.config['demotion']['max_attempts']

        total_requested = 0
        total_created = 0
        total_demoted = 0

        # Iterate through each area
        for area_code, compositions in self.household_counts_by_area.items():
            logger.debug(f"Processing area {area_code}...")

            # Iterate through each composition type in this area
            for pattern_str, count in compositions.items():
                total_requested += count
                pattern = CompositionPattern.from_string(pattern_str)

                # Try to create 'count' households of this type
                for i in range(count):
                    if demotion_enabled:
                        household = self._attempt_with_demotion(area_code, pattern, max_attempts)
                    else:
                        household = self._allocate_household(area_code, pattern)

                    if household:
                        self.households.append(household)
                        total_created += 1

                        # Check if we used demotion
                        if household.properties.get('original_pattern') != pattern.to_string():
                            total_demoted += 1
                    else:
                        logger.debug(f"  Failed to allocate household {i+1}/{count} of type '{pattern_str}' in {area_code}")

        # Log summary
        logger.info("=" * 60)
        logger.info("Household distribution complete!")
        logger.info(f"  Requested households: {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
        logger.info(f"  Households using demotion: {total_demoted:,} ({100*total_demoted/max(total_created,1):.1f}%)")
        logger.info(f"  People allocated: {len(self.allocated_people):,}")
        logger.info(f"  People unallocated: {len(self.population.get_all_people()) - len(self.allocated_people):,}")
        logger.info("=" * 60)

    def distribute_households_round(self,
                                   pattern_filter: Optional[List[str]] = None,
                                   max_households: Optional[int] = None,
                                   refresh_pools: bool = False,
                                   round_name: Optional[str] = None):
        """
        Distribute households in a single round with optional filtering.

        This method allows for multi-round allocation where you can:
        1. Allocate specific household types in each round
        2. Limit the number of households created
        3. Refresh pools to include only remaining unallocated people
        4. Perform other operations between rounds

        Args:
            pattern_filter: List of patterns to allocate in this round.
                          If None, allocate all patterns.
                          Example: ["0 0 2 0", "0 0 0 2", ">=2 >=0 2 0"]
            max_households: Maximum number of households to create in this round.
                          If None, no limit.
            refresh_pools: If True, refresh person pools to exclude already allocated people.
                         Use this when coming back after other allocation operations.
            round_name: Optional name for this round (for logging)

        Returns:
            dict: Statistics about this round's allocation
        """
        self.current_round += 1
        round_label = round_name or f"Round {self.current_round}"

        logger.info("=" * 60)
        logger.info(f"Starting household allocation: {round_label}")
        logger.info("=" * 60)

        # Prepare or refresh pools
        self._prepare_person_pools(refresh=refresh_pools)

        # Get config
        demotion_enabled = self.config['demotion']['enabled']
        max_attempts = self.config['demotion']['max_attempts']

        # Track round statistics
        round_start_households = len(self.households)
        round_start_allocated = len(self.allocated_people)
        total_requested = 0
        total_created = 0
        total_demoted = 0
        households_created = 0

        # Convert pattern filter to set for fast lookup
        pattern_set = set(pattern_filter) if pattern_filter else None

        # Iterate through each area
        for area_code, compositions in self.household_counts_by_area.items():
            # Iterate through each composition type in this area
            for pattern_str, count in compositions.items():
                # Check if this pattern should be allocated in this round
                if pattern_set is not None and pattern_str not in pattern_set:
                    continue

                total_requested += count
                pattern = CompositionPattern.from_string(pattern_str)

                # Try to create 'count' households of this type
                for i in range(count):
                    # Check if we've hit the household limit
                    if max_households is not None and households_created >= max_households:
                        logger.info(f"Reached maximum household limit ({max_households}) for {round_label}")
                        break

                    if demotion_enabled:
                        household = self._attempt_with_demotion(area_code, pattern, max_attempts)
                    else:
                        household = self._allocate_household(area_code, pattern)

                    if household:
                        self.households.append(household)
                        total_created += 1
                        households_created += 1

                        # Check if we used demotion
                        if household.properties.get('original_pattern') != pattern.to_string():
                            total_demoted += 1
                    else:
                        logger.debug(f"  Failed to allocate household {i+1}/{count} of type '{pattern_str}' in {area_code}")

                # Break outer loop if limit reached
                if max_households is not None and households_created >= max_households:
                    break

            # Break outer loop if limit reached
            if max_households is not None and households_created >= max_households:
                break

        # Calculate round statistics
        round_stats = {
            'round_name': round_label,
            'round_number': self.current_round,
            'households_created': households_created,
            'households_requested': total_requested,
            'households_with_demotion': total_demoted,
            'people_allocated_this_round': len(self.allocated_people) - round_start_allocated,
            'total_households': len(self.households),
            'total_people_allocated': len(self.allocated_people),
            'total_people_remaining': len(self.population.get_all_people()) - len(self.allocated_people)
        }

        # Log summary
        logger.info("=" * 60)
        logger.info(f"{round_label} complete!")
        logger.info(f"  Requested households (filtered): {total_requested:,}")
        logger.info(f"  Created households: {total_created:,} ({100*total_created/max(total_requested,1):.1f}%)")
        logger.info(f"  Households using demotion: {total_demoted:,}")
        logger.info(f"  People allocated this round: {round_stats['people_allocated_this_round']:,}")
        logger.info(f"  Total households so far: {len(self.households):,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  People remaining: {round_stats['total_people_remaining']:,}")
        logger.info("=" * 60)

        return round_stats

    def get_available_people_count(self) -> int:
        """Get the number of people currently available (not allocated)."""
        return len(self.population.get_all_people()) - len(self.allocated_people)

    def get_available_people_by_category(self) -> Dict[str, int]:
        """Get counts of available people by age category."""
        counts = {cat.name: 0 for cat in self.age_categories}

        for person in self.population.get_all_people():
            if person.id not in self.allocated_people:
                for cat in self.age_categories:
                    if cat.matches(person.age):
                        counts[cat.name] += 1
                        break

        return counts

    def mark_people_as_allocated(self, people: List['Person'], venue_type: str = "external"):
        """
        Mark people as allocated (to venues, care homes, etc.) so they won't
        be allocated to households in subsequent rounds.

        This is useful when you're allocating people to venues between household rounds.

        Args:
            people: List of Person objects to mark as allocated
            venue_type: Type of venue (for logging purposes)

        Returns:
            int: Number of people marked as allocated
        """
        count = 0
        for person in people:
            if person.id not in self.allocated_people:
                self.allocated_people.add(person.id)
                count += 1

        logger.info(f"Marked {count} people as allocated to {venue_type}")
        return count

    def reset_allocation(self):
        """
        Reset all household allocations.

        Warning: This will clear all households and reset person allocations.
        Use with caution!
        """
        logger.warning("Resetting all household allocations...")

        # Clear residence from all allocated people
        for person_id in self.allocated_people:
            person = self.population.get_person(person_id)
            if person and hasattr(person, 'residence'):
                person.residence = None

        # Clear all data
        self.households = []
        self.allocated_people = set()
        self.person_pool_by_area = {}
        self.current_round = 0
        self.pools_prepared = False

        logger.info("Allocation reset complete")

    def distribute_households_from_yaml(self, rounds_config_file: str = "allocation_rounds.yaml"):
        """
        Execute multi-round allocation from a YAML configuration file.

        The YAML file should define rounds with patterns, limits, and options.
        See allocation_rounds.yaml for examples.

        Args:
            rounds_config_file: Path to YAML file (relative to data_dir or absolute)

        Returns:
            list: List of statistics dicts, one per round
        """
        # Load rounds configuration
        if not os.path.isabs(rounds_config_file):
            rounds_config_path = os.path.join(self.data_dir, rounds_config_file)
        else:
            rounds_config_path = rounds_config_file

        logger.info(f"Loading allocation rounds configuration from {rounds_config_path}")

        with open(rounds_config_path, 'r') as f:
            rounds_config = yaml.safe_load(f)

        # Check if multi-round is enabled
        if not rounds_config.get('enabled', True):
            logger.info("Multi-round allocation is disabled in config, using single-pass allocation")
            self.distribute_households()
            return []

        # Get rounds
        rounds = rounds_config.get('rounds', [])
        if not rounds:
            logger.warning("No rounds defined in config, using single-pass allocation")
            self.distribute_households()
            return []

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Starting multi-round allocation with {len(rounds)} rounds")
        logger.info("=" * 60)

        # Execute each round
        all_stats = []
        for i, round_config in enumerate(rounds):
            round_name = round_config.get('name', f"Round {i+1}")
            description = round_config.get('description')

            if description:
                logger.info("")
                logger.info(f"Round {i+1}: {round_name}")
                logger.info(f"  Description: {description}")

            # Get round parameters
            patterns = round_config.get('patterns')
            max_households = round_config.get('max_households')
            refresh_pools = round_config.get('refresh_pools', False)
            enable_demotion = round_config.get('enable_demotion')

            # Temporarily override demotion setting if specified
            original_demotion = None
            if enable_demotion is not None:
                original_demotion = self.config['demotion']['enabled']
                self.config['demotion']['enabled'] = enable_demotion

            # Execute round
            try:
                stats = self.distribute_households_round(
                    pattern_filter=patterns,
                    max_households=max_households,
                    refresh_pools=refresh_pools,
                    round_name=round_name
                )
                all_stats.append(stats)
            finally:
                # Restore original demotion setting
                if original_demotion is not None:
                    self.config['demotion']['enabled'] = original_demotion

        # Print overall summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("MULTI-ROUND ALLOCATION SUMMARY")
        logger.info("=" * 60)

        for stats in all_stats:
            logger.info("")
            logger.info(f"{stats['round_name']}:")
            logger.info(f"  Households created: {stats['households_created']:,}")
            logger.info(f"  People allocated: {stats['people_allocated_this_round']:,}")
            if stats['households_with_demotion'] > 0:
                logger.info(f"  Households with demotion: {stats['households_with_demotion']:,}")

        logger.info("")
        logger.info("Overall Totals:")
        logger.info(f"  Total households: {len(self.households):,}")
        logger.info(f"  Total people allocated: {len(self.allocated_people):,}")
        logger.info(f"  Total people remaining: {self.get_available_people_count():,}")
        logger.info("=" * 60)

        return all_stats

    def export_households_to_csv(self, output_file: str = "household_allocations.csv"):
        """
        Export all household data to a CSV file.

        Creates a detailed CSV with:
        - Household ID
        - Geographical unit
        - Original pattern (from census data)
        - Actual composition (by age category)
        - Household size
        - List of residents with age and sex

        Args:
            output_file: Path to output CSV file
        """
        logger.info(f"Exporting household data to {output_file}...")

        rows = []
        for household in self.households:
            # Get composition
            composition = household.get_composition()
            composition_str = ", ".join([f"{cat}: {count}" for cat, count in composition.items()])

            # Get original pattern
            original_pattern = household.properties.get('original_pattern', 'unknown')

            # Get resident details
            resident_details = []
            for person in household.residents:
                resident_details.append(f"Person_{person.id}(age={person.age},sex={person.sex})")
            residents_str = "; ".join(resident_details)

            # Create row
            row = {
                'household_id': household.id,
                'geo_unit': household.geographical_unit.name,
                'original_pattern': original_pattern,
                'actual_composition': composition_str,
                'household_size': household.size(),
                'num_kids': composition.get('Kids', 0),
                'num_young_adults': composition.get('Young Adults', 0),
                'num_adults': composition.get('Adults', 0),
                'num_old_adults': composition.get('Old Adults', 0),
                'residents': residents_str
            }
            rows.append(row)

        # Create DataFrame and export
        df = pd.DataFrame(rows)
        output_path = os.path.join(self.data_dir, output_file)
        df.to_csv(output_path, index=False)

        logger.info(f"Exported {len(rows)} households to {output_path}")
        return output_path
