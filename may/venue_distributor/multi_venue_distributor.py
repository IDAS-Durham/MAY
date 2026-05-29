"""
MultiVenueDistributor: Generic distributor for assigning multiple venue options

This is a distributor that works with any set of venue types.

Structure:
    person.activity_map[activity_map_key] = {
        venue_type_1: [subset1, subset2, subset3],
        venue_type_2: [subset1, subset2],
        venue_type_3: [subset1, subset2, subset3, subset4],
    }

Example use cases:
    - Leisure activities: cinema, gym, pub, grocery
    - Social venues: cafe, park, community_center
    - Service locations: bank, post_office, library
    - Any other scenario requiring multiple venue options
"""

import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .base_distributor import BaseDistributor
from may.population import Subset
from may.utils import path_resolver as pr

logger = logging.getLogger(__name__)


class MultiVenueDistributor(BaseDistributor):
    """
    Distributor for assigning multiple venue options to people.

    Features:
    - Handles any number of venue types
    - Assigns N closest venues per type to each person
    - Stores in nested dict: activity_map[key][venue_type] = [subsets]
    - Configurable age filtering
    - Distance-based venue selection with spatial indexing
    """

    def __init__(self, config_path: str = None, config_dict: dict = None):
        """
        Initialize MultiVenueDistributor from YAML configuration.

        Args:
            config_path: Path to distributor YAML file
            config_dict: Dictionary config (alternative to file)
        """
        super().__init__(config_file=config_path, config_dict=config_dict)

        # Extract configuration
        self.distributor_name = self.config.get('distributor_name', 'multi_venue_distributor')
        self.activity_map_key = self.config.get('activity_map_key')
        self.subset_key = self.config.get('subset_key', 'default')
        self.venue_types = self.config.get('venue_types', [])

        # Validation
        if not self.activity_map_key:
            raise ValueError("activity_map_key must be specified in configuration")
        if not self.venue_types:
            raise ValueError("venue_types must be specified in configuration")

        # Venue selection config
        venue_selection = self.config.get('venue_selection', {})
        self.default_venue_count = venue_selection.get('count', 5)
        self.distance_metric = venue_selection.get('distance_metric', 'haversine')

        # Per-venue-type configuration
        self.venue_type_config = self.config.get('venue_type_config', {})

        # Load participation data for venue types that have it
        self.participation_data = {}  # venue_type -> {data, row_filters, probability_column}
        for venue_type, type_config in self.venue_type_config.items():
            if 'participation_filter' in type_config:
                self._load_participation_data(venue_type, type_config['participation_filter'])

        # Eligibility config
        eligibility = self.config.get('eligibility', {})
        self.min_age = None
        self.max_age = None
        self.require_residence = eligibility.get('require_residence', True)

        # Extract age filters from global filters
        global_filters = eligibility.get('global_filters', [])
        for filter_rule in global_filters:
            if filter_rule.get('attribute') == 'age' and filter_rule.get('type') == 'numerical':
                self.min_age = filter_rule.get('min')
                self.max_age = filter_rule.get('max')
                break

        logger.info(f"Initialized {self.distributor_name}")
        logger.info(f"  activity_map_key: '{self.activity_map_key}'")
        logger.info(f"  venue_types: {self.venue_types}")
        logger.info(f"  subset_key: '{self.subset_key}'")
        logger.info(f"  default_venue_count: {self.default_venue_count}")

        # Log per-venue-type overrides
        for venue_type in self.venue_types:
            count = self._get_venue_count_for_type(venue_type)
            if count != self.default_venue_count:
                logger.info(f"    {venue_type}: {count} venues (override)")
            if venue_type in self.participation_data:
                logger.info(f"    {venue_type}: has participation filtering")

        if self.min_age is not None or self.max_age is not None:
            logger.info(f"  age_filter: [{self.min_age}, {self.max_age}]")

    def _get_venue_count_for_type(self, venue_type: str) -> int:
        """Get the number of venues to assign for a specific type, including overrides."""
        return self.venue_type_config.get(venue_type, {}).get('count', self.default_venue_count)

    def _load_participation_data(self, venue_type: str, filter_config: Dict):
        """
        Load participation data for a venue type and build lookup index.

        Args:
            venue_type: Type of venue
            filter_config: Participation filter configuration from YAML
        """
        data_file = pr.resolve(filter_config.get('data_file', '')) or None
        if not data_file:
            logger.warning(f"No data_file specified for {venue_type} participation filter")
            return

        try:
            # Load CSV
            df = pd.read_csv(data_file)
            logger.info(f"Loaded participation data for '{venue_type}': {len(df)} rows from {data_file}")

            row_filters = filter_config.get('row_filters', [])
            prob_config = filter_config.get('probability_column', {})

            # Build lookup index
            # Index structure: {(filter_val1, filter_val2, ...): {sex: prob}}
            lookup_index = {}

            for _, row in df.iterrows():
                # Extract filter keys from this row
                filter_keys = []
                for filter_cfg in row_filters:
                    csv_column = filter_cfg.get('csv_column')
                    value = row.get(csv_column)
                    filter_keys.append(str(value))

                # Build probability dict for this row
                # If using column_template, we need all possible values
                if 'column_template' in prob_config:
                    # Extract all probability columns (e.g., pct_male, pct_female)
                    prob_dict = {}
                    template = prob_config['column_template']
                    person_attr = prob_config.get('person_attribute')

                    # Try to infer possible values from columns
                    # For "pct_{value}", extract all columns matching pattern
                    prefix = template.split('{')[0]  # e.g., "pct_"
                    for col in row.index:
                        if col.startswith(prefix):
                            # Extract the value part: "pct_male" -> "male"
                            attr_value = col[len(prefix):]
                            prob_dict[attr_value] = float(row[col])

                    lookup_index[tuple(filter_keys)] = prob_dict

                elif 'column_name' in prob_config:
                    # Fixed column - single probability value
                    column_name = prob_config['column_name']
                    lookup_index[tuple(filter_keys)] = float(row[column_name])

            logger.info(f"Built participation lookup index for '{venue_type}': {len(lookup_index)} entries")

            # Store the lookup index and configuration
            self.participation_data[venue_type] = {
                'lookup_index': lookup_index,
                'row_filters': row_filters,
                'probability_column': prob_config
            }

        except Exception as e:
            logger.error(f"Failed to load participation data for '{venue_type}': {e}")
            # Mark as failed so _should_allocate_venue_type returns False (fail-closed)
            self.participation_data[venue_type] = {
                'lookup_index': {},
                'row_filters': filter_config.get('row_filters', []),
                'probability_column': filter_config.get('probability_column', {}),
            }

    def _match_row_filters(self, person, row, row_filters: List[Dict]) -> bool:
        """
        Check if a person matches a CSV row based on configured filters.

        Supports multiple match types:
        - age_range: Parses "16-24" format from CSV
        - exact: Exact match between person attribute and CSV value
        - numerical_range: Parses numerical ranges like "0-1000"

        Args:
            person: Person object
            row: Pandas Series (CSV row)
            row_filters: List of filter configurations

        Returns:
            True if all filters match, False otherwise
        """
        for filter_config in row_filters:
            person_attr = filter_config.get('person_attribute')
            csv_column = filter_config.get('csv_column')
            match_type = filter_config.get('match_type', 'exact')

            # Get person attribute value
            person_value = self._get_person_attribute(person_attr, person)
            if person_value is None:
                return False

            # Get CSV value
            csv_value = row.get(csv_column)
            if pd.isna(csv_value):
                return False

            # Apply match type
            if match_type == 'age_range':
                # Parse "16-24", "65-+", or "65+" formats
                try:
                    csv_str = str(csv_value)
                    if csv_str.endswith('+') and '-' not in csv_str:
                        # Standalone "65+" format
                        min_val = int(csv_str[:-1])
                        max_val = 200  # Arbitrary high value
                        if not (min_val <= person_value <= max_val):
                            return False
                    else:
                        parts = csv_str.split('-')
                        if len(parts) == 2:
                            min_val = int(parts[0])
                            # Handle "65-+" format
                            if parts[1].endswith('+'):
                                max_val = 200  # Arbitrary high value
                            else:
                                max_val = int(parts[1])

                            if not (min_val <= person_value <= max_val):
                                return False
                        else:
                            return False
                except (ValueError, AttributeError):
                    return False

            elif match_type == 'numerical_range':
                # Parse numerical ranges "0-1000"
                try:
                    parts = str(csv_value).split('-')
                    if len(parts) == 2:
                        min_val = float(parts[0])
                        max_val = float(parts[1])
                        if not (min_val <= person_value <= max_val):
                            return False
                    else:
                        return False
                except (ValueError, AttributeError):
                    return False

            elif match_type == 'exact':
                # Exact match
                if str(person_value).lower() != str(csv_value).lower():
                    return False

            else:
                logger.warning(f"Unknown match_type: {match_type}")
                return False

        return True

    def _get_probability_for_person(self, person, row, prob_config: Dict) -> Optional[float]:
        """
        Get participation probability for a person from a CSV row.

        Supports:
        - column_template: Dynamic column based on person attribute
        - column_name: Fixed column name

        Args:
            person: Person object
            row: Pandas Series (CSV row)
            prob_config: Probability column configuration

        Returns:
            Probability value (0.0 to 1.0) or None if not found
        """
        # Option 1: Column template (e.g., "pct_{sex}")
        if 'column_template' in prob_config:
            template = prob_config['column_template']
            person_attr = prob_config.get('person_attribute')

            if person_attr:
                person_value = self._get_person_attribute(person_attr, person)
                if person_value is None:
                    return None

                # Replace {value} or {attribute_name} in template
                lower_value = str(person_value).lower()
                if '{value}' in template:
                    column_name = template.replace('{value}', lower_value)
                elif f'{{{person_attr}}}' in template:
                    column_name = template.replace(f'{{{person_attr}}}', lower_value)
                else:
                    column_name = template

                if column_name in row:
                    return float(row[column_name])
                else:
                    logger.debug(f"Column '{column_name}' not found in CSV row")
                    return None

        # Option 2: Fixed column name
        elif 'column_name' in prob_config:
            column_name = prob_config['column_name']
            if column_name in row:
                return float(row[column_name])
            else:
                logger.debug(f"Column '{column_name}' not found in CSV row")
                return None

        return None

    def _should_allocate_venue_type(self, person, venue_type: str) -> bool:
        """
        Check if a person should be allocated to a specific venue type.

        Uses participation data if configured, otherwise returns True.

        Args:
            person: Person object
            venue_type: Type of venue

        Returns:
            True if person should be allocated, False otherwise
        """
        # No participation filter = allocate to everyone
        if venue_type not in self.participation_data:
            return True

        participation_config = self.participation_data[venue_type]
        lookup_index = participation_config['lookup_index']
        row_filters = participation_config['row_filters']
        prob_config = participation_config['probability_column']

        # Build lookup key from person attributes
        lookup_keys = []
        for filter_idx, filter_cfg in enumerate(row_filters):
            person_attr = filter_cfg.get('person_attribute')
            match_type = filter_cfg.get('match_type', 'exact')

            # Get person attribute value
            person_value = self._get_person_attribute(person_attr, person)
            if person_value is None:
                return False

            # Find matching CSV value based on match_type
            csv_value = None

            if match_type == 'age_range':
                # Find which age range this person falls into
                # Try all possible age ranges in the lookup index
                for key_tuple in lookup_index.keys():
                    if filter_idx < len(key_tuple):
                        age_band = key_tuple[filter_idx]
                        # Parse "16-24", "65-+", or "65+" formats
                        try:
                            if age_band.endswith('+') and '-' not in age_band:
                                # Standalone "65+" format
                                min_val = int(age_band[:-1])
                                max_val = 200
                            else:
                                parts = age_band.split('-')
                                if len(parts) != 2:
                                    continue
                                min_val = int(parts[0])
                                if parts[1].endswith('+'):
                                    max_val = 200
                                else:
                                    max_val = int(parts[1])

                            if min_val <= person_value <= max_val:
                                csv_value = age_band
                                break
                        except (ValueError, AttributeError):
                            continue

            elif match_type == 'exact':
                csv_value = str(person_value)

            elif match_type == 'numerical_range':
                # Similar to age_range but for numerical ranges
                for key_tuple in lookup_index.keys():
                    if filter_idx < len(key_tuple):
                        range_val = key_tuple[filter_idx]
                        try:
                            parts = range_val.split('-')
                            if len(parts) == 2:
                                min_val = float(parts[0])
                                max_val = float(parts[1])
                                if min_val <= person_value <= max_val:
                                    csv_value = range_val
                                    break
                        except (ValueError, AttributeError):
                            continue

            if csv_value is None:
                return False

            lookup_keys.append(csv_value)

        # Look up probability in index
        lookup_tuple = tuple(lookup_keys)
        if lookup_tuple not in lookup_index:
            return False

        prob_value = lookup_index[lookup_tuple]

        # Get probability based on configuration
        probability = None

        if isinstance(prob_value, dict):
            # Template-based: select probability by person attribute
            person_attr = prob_config.get('person_attribute')
            attr_value = self._get_person_attribute(person_attr, person)
            if attr_value is not None:
                probability = prob_value.get(str(attr_value).lower())
        else:
            # Fixed column: probability is a single value
            probability = prob_value

        if probability is None:
            return False

        # Probabilistic allocation
        return np.random.random() < probability

    def allocate(self, world):
        """
        Main entry point: Allocate venues to people.

        Args:
            world: World object containing people, venues, geography
        """
        logger.info(f"Starting {self.distributor_name} allocation")
        logger.info(f"Processing venue types: {self.venue_types}")

        # Build spatial indices for each venue type using base class method
        self._build_spatial_indices({vt: world.venues_by_type(vt) for vt in self.venue_types})

        # Get eligible people
        eligible_people = self._get_eligible_people(world)
        logger.info(f"Found {len(eligible_people)} eligible people")

        if not eligible_people:
            logger.info("No eligible people for allocation")
            return

        # Allocate venues to each person
        self._allocate_venues(eligible_people, world)

        # Log summary
        if self.config.get('settings', {}).get('log_summary', True):
            self._log_summary(world)


    def _get_eligible_people(self, world) -> List:
        """
        Get people eligible for allocation based on configured criteria.

        Args:
            world: World object

        Returns:
            List of eligible people
        """
        eligible = []

        for person in world.people:
            # Check age filters
            if self.min_age is not None and person.age < self.min_age:
                continue
            if self.max_age is not None and person.age > self.max_age:
                continue

            # Check residence if required
            if self.require_residence and not person.has_residence():
                continue

            # Check geographical unit
            if person.geographical_unit is None:
                continue

            eligible.append(person)

        return eligible

    def _allocate_venues(self, people: List, world):
        """
        Allocate venues to each person using geo_unit batching for performance.

        Groups people by their geographical_unit coordinates.

        Args:
            people: List of eligible people
            world: World object
        """
        # Step 1: Group people by geographical_unit
        people_by_geo_unit = {}
        for person in people:
            geo_unit = person.geographical_unit
            if geo_unit is None:
                continue
            if geo_unit not in people_by_geo_unit:
                people_by_geo_unit[geo_unit] = []
            people_by_geo_unit[geo_unit].append(person)

        logger.info(f"Batching {len(people)} people into {len(people_by_geo_unit)} unique geo_units")

        # Step 2: For each unique geo_unit, query spatial index once per venue_type
        geo_unit_venue_cache = {}  # (geo_unit, venue_type) -> [venues]

        for geo_unit in people_by_geo_unit.keys():
            # Get geo_unit coordinates
            if geo_unit.coordinates is None or len(geo_unit.coordinates) != 2:
                logger.warning(f"Geo unit {geo_unit.name} has invalid coordinates ({getattr(geo_unit, 'coordinates', None)}), "
                               f"skipping {len(people_by_geo_unit[geo_unit])} people")
                continue

            coords = list(geo_unit.coordinates)

            # Query once per venue type for this geo_unit
            for venue_type in self.venue_types:
                cache_key = (geo_unit, venue_type)
                geo_unit_venue_cache[cache_key] = self._find_closest_venues(
                    coords, venue_type, self._get_venue_count_for_type(venue_type)
                )

        # Step 3: Assign cached venue results to all people in each geo_unit
        allocated_count = 0

        # Progress tracking
        total_people = len(people)
        people_processed = 0
        progress_interval = max(1, total_people // 10)  # Update every 10%

        for geo_unit, geo_unit_people in people_by_geo_unit.items():
            for person in geo_unit_people:
                venue_dict = {}

                # Get cached venues for each venue type
                for venue_type in self.venue_types:
                    # Check if person should get this venue type (participation filtering)
                    if not self._should_allocate_venue_type(person, venue_type):
                        continue

                    cache_key = (geo_unit, venue_type)
                    venues = geo_unit_venue_cache.get(cache_key, [])

                    if venues:
                        # Create subsets and add person to each
                        subsets = []
                        for venue in venues:
                            subset = self._get_or_create_subset(venue)
                            subset.add_member(person)
                            subsets.append(subset)

                        venue_dict[venue_type] = subsets

                # Store in activity_map if we found any venues
                if venue_dict:
                    person.activity_map[self.activity_map_key] = venue_dict

                    # Add activity to person's activities list
                    if self.activity_map_key not in person.activities:
                        person.add_activity(self.activity_map_key)

                    allocated_count += 1

                # Update progress tracking
                people_processed += 1
                if people_processed % progress_interval == 0 or people_processed == total_people:
                    percent_complete = (people_processed / total_people) * 100
                    logger.info(f"  Progress: {people_processed}/{total_people} people processed ({percent_complete:.1f}%) - {allocated_count} allocated")

        logger.info(f"Allocated venues to {allocated_count} people")

    def _get_or_create_subset(self, venue):
        """
        Get or create a subset with the configured subset_key.

        Args:
            venue: Venue object

        Returns:
            Subset object
        """
        # Check if subset already exists
        if self.subset_key in venue.subsets:
            return venue.subsets[self.subset_key]

        # Create new subset — use max existing index + 1 to avoid collisions after deletions
        subset_index = (max(s.subset_index for s in venue.subsets.values()) + 1) if venue.subsets else 0
        subset = Subset(
            venue=venue,
            subset_index=subset_index,
            subset_name=self.subset_key
        )
        venue.subsets[self.subset_key] = subset

        return subset

    def _log_summary(self, world):
        """Log summary statistics of allocation."""
        total_allocated = 0
        type_counts = {vtype: 0 for vtype in self.venue_types}
        venue_count_stats = {vtype: [] for vtype in self.venue_types}

        for person in world.people:
            if self.activity_map_key in person.activity_map:
                total_allocated += 1

                venue_dict = person.activity_map[self.activity_map_key]
                for vtype in self.venue_types:
                    if vtype in venue_dict and venue_dict[vtype]:
                        type_counts[vtype] += 1
                        venue_count_stats[vtype].append(len(venue_dict[vtype]))

        logger.info(f"=== {self.distributor_name} Summary ===")
        logger.info(f"Total people allocated: {total_allocated}")
        logger.info(f"Breakdown by venue type:")
        for vtype, count in type_counts.items():
            if venue_count_stats[vtype]:
                avg_venues = sum(venue_count_stats[vtype]) / len(venue_count_stats[vtype])
                logger.info(f"  - {vtype}: {count} people (avg {avg_venues:.1f} venues/person)")
            else:
                logger.info(f"  - {vtype}: {count} people")

    @property
    def venue_type(self):
        """
        Return activity_map_key as venue_type for compatibility with export code.

        This allows the export code to use distributor.venue_type consistently.
        """
        return self.activity_map_key

    def export_allocations(self, world, output_path: str):
        """
        Export multi-venue allocations to CSV.

        Creates a CSV with columns:
        - person_id, person_sex, person_age, person_geo_unit
        - venue_type, venue_id, venue_name, venue_geo_unit
        - venue_lat, venue_lon

        Args:
            world: World object
            output_path: Path to output CSV file
        """
        import csv

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                'person_id',
                'person_sex',
                'person_age',
                'person_geo_unit',
                'venue_type',
                'venue_id',
                'venue_name',
                'venue_geo_unit',
                'venue_lat',
                'venue_lon'
            ])

            # Write data
            allocated_count = 0
            for person in world.people:
                if self.activity_map_key not in person.activity_map:
                    continue

                venue_dict = person.activity_map[self.activity_map_key]

                # For each venue type, export all venues
                for venue_type, subsets in venue_dict.items():
                    for subset in subsets:
                        venue = subset.venue

                        # Get venue coordinates
                        lat, lon = None, None
                        if venue.coordinates:
                            lat, lon = venue.coordinates

                        writer.writerow([
                            person.id,
                            person.sex,
                            person.age,
                            person.geographical_unit.name if person.geographical_unit else '',
                            venue_type,
                            venue.id,
                            venue.name,
                            venue.geographical_unit.name if venue.geographical_unit else '',
                            lat,
                            lon
                        ])
                        allocated_count += 1

        logger.info(f"Exported {allocated_count} venue allocations to {output_path}")