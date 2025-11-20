"""
MultiVenueDistributor: Generic distributor for assigning multiple venue options

This is a GENERIC distributor that works with any set of venue types.
All configuration is driven by YAML - no hardcoded venue types or activity names.

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

import yaml
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from scipy.spatial import cKDTree
import logging

from may.population import Subset

logger = logging.getLogger(__name__)


class MultiVenueDistributor:
    """
    Generic distributor for assigning multiple venue options to people.

    Features:
    - Completely generic - all configuration from YAML
    - Handles any number of venue types
    - Assigns N closest venues per type to each person
    - Stores in nested dict: activity_map[key][venue_type] = [subsets]
    - Configurable age filtering
    - Distance-based venue selection with spatial indexing
    """

    def __init__(self, config_path: str):
        """
        Initialize MultiVenueDistributor from YAML configuration.

        Args:
            config_path: Path to distributor YAML file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # Extract configuration (all from YAML, nothing hardcoded)
        self.distributor_name = self.config.get('distributor_name', 'multi_venue_distributor')
        self.activity_map_key = self.config.get('activity_map_key')
        self.subset_key = self.config.get('subset_key', 'default')
        self.venue_types = self.config.get('venue_types', [])
        self.verbose = self.config.get('settings', {}).get('verbose', False)

        # Validation
        if not self.activity_map_key:
            raise ValueError("activity_map_key must be specified in configuration")
        if not self.venue_types:
            raise ValueError("venue_types must be specified in configuration")

        # Venue selection config
        venue_selection = self.config.get('venue_selection', {})
        self.max_venues_per_type = venue_selection.get('count', 5)
        self.venue_geo_level = venue_selection.get('venue_geo_level', 'SGU')
        self.distance_metric = venue_selection.get('distance_metric', 'haversine')

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

        # Spatial indices (one per venue type)
        self.spatial_indices = {}  # venue_type -> cKDTree
        self.venue_lists = {}  # venue_type -> list of venues

        logger.info(f"Initialized {self.distributor_name}")
        logger.info(f"  activity_map_key: '{self.activity_map_key}'")
        logger.info(f"  venue_types: {self.venue_types}")
        logger.info(f"  subset_key: '{self.subset_key}'")
        logger.info(f"  max_venues_per_type: {self.max_venues_per_type}")
        if self.min_age is not None or self.max_age is not None:
            logger.info(f"  age_filter: [{self.min_age}, {self.max_age}]")

    def _load_config(self) -> Dict:
        """Load and parse YAML configuration file."""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config

    def allocate(self, world):
        """
        Main entry point: Allocate venues to people.

        Args:
            world: World object containing people, venues, geography
        """
        logger.info(f"Starting {self.distributor_name} allocation")
        logger.info(f"Processing venue types: {self.venue_types}")

        # Build spatial indices for each venue type
        self._build_spatial_indices(world)

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

    def _build_spatial_indices(self, world):
        """
        Build KDTree spatial indices for each venue type.

        Args:
            world: World object
        """
        for venue_type in self.venue_types:
            venues = world.venues_by_type(venue_type)

            if not venues:
                logger.warning(f"No venues found for type '{venue_type}'")
                self.spatial_indices[venue_type] = None
                self.venue_lists[venue_type] = []
                continue

            coords = []
            venue_list = []

            for venue in venues:
                if venue.coordinates is not None and len(venue.coordinates) == 2:
                    lat, lon = venue.coordinates
                    if lat is not None and lon is not None:
                        coords.append([lat, lon])
                        venue_list.append(venue)

            if coords:
                self.spatial_indices[venue_type] = cKDTree(np.array(coords))
                self.venue_lists[venue_type] = venue_list
                logger.info(f"Built spatial index for '{venue_type}': {len(coords)} venues")
            else:
                logger.warning(f"No venues with coordinates found for type '{venue_type}'")
                self.spatial_indices[venue_type] = None
                self.venue_lists[venue_type] = []

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
        Allocate venues to each person.

        For each person, finds N closest venues of each configured venue type
        and stores them in person.activity_map[activity_map_key][venue_type].

        Args:
            people: List of eligible people
            world: World object
        """
        allocated_count = 0

        for person in people:
            # Initialize nested dict for this person
            venue_dict = {}

            # For each venue type, find N closest venues
            for venue_type in self.venue_types:
                subsets = self._find_closest_venues(person, venue_type, world)

                if subsets:
                    venue_dict[venue_type] = subsets

            # Store in activity_map if we found any venues
            if venue_dict:
                person.activity_map[self.activity_map_key] = venue_dict

                # Add activity to person's activities list
                if self.activity_map_key not in person.activities:
                    person.add_activity(self.activity_map_key)

                allocated_count += 1

        logger.info(f"Allocated venues to {allocated_count} people")

    def _find_closest_venues(self, person, venue_type: str, world) -> List:
        """
        Find the N closest venues of a specific type for a person.

        Args:
            person: Person object
            venue_type: Type of venue
            world: World object

        Returns:
            List of Subset objects for the closest venues
        """
        # Get spatial index for this venue type
        spatial_index = self.spatial_indices.get(venue_type)
        venue_list = self.venue_lists.get(venue_type)

        if spatial_index is None or not venue_list:
            return []

        # Get person's location
        person_coords = self._get_person_coordinates(person, world)
        if person_coords is None:
            return []

        # Query spatial index for N closest venues
        n_venues = min(self.max_venues_per_type, len(venue_list))

        try:
            distances, indices = spatial_index.query(person_coords, k=n_venues)
        except Exception as e:
            logger.debug(f"Failed to query spatial index for person {person.id}: {e}")
            return []

        # Handle single result (not in array)
        if n_venues == 1:
            indices = [indices]

        # Get venues and create subsets
        subsets = []
        for idx in indices:
            if idx < len(venue_list):
                venue = venue_list[idx]

                # Get or create subset for this venue
                subset = self._get_or_create_subset(venue)

                # Add person to subset
                subset.add_member(person)

                subsets.append(subset)

        return subsets

    def _get_person_coordinates(self, person, world) -> Optional[List[float]]:
        """
        Get coordinates for a person.

        Args:
            person: Person object
            world: World object

        Returns:
            [lat, lon] or None if not available
        """
        # Use geographical_unit coordinates
        if person.geographical_unit and person.geographical_unit.coordinates:
            lat, lon = person.geographical_unit.coordinates
            if lat is not None and lon is not None:
                return [lat, lon]

        return None

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

        # Create new subset
        subset_index = len(venue.subsets)
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
