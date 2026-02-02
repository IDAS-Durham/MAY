#!/usr/bin/env python3
"""
Event Loader for World Map Visualization

Loads simulation events from HDF5 files and aggregates them by geographical unit
for display on the interactive map with time-based filtering.
"""

import h5py
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class EventLoader:
    """
    Loads and aggregates simulation events from HDF5 files.

    Supports:
    - Infections
    - Deaths
    - Hospital admissions
    - ICU admissions
    - Hospital discharges
    - Symptom changes
    """

    def __init__(self, events_path: str, world_state_path: Optional[str] = None):
        """
        Initialize the event loader.

        Args:
            events_path: Path to simulation_events.h5
            world_state_path: Optional path to world_state.h5 for venue->geo_unit mapping
        """
        self.events_path = Path(events_path)
        self.world_state_path = Path(world_state_path) if world_state_path else None

        # Data containers
        self.events = {}
        self.venue_to_geo_unit = {}
        self.person_to_geo_unit = {}
        self.geo_unit_coords = {}
        self.geo_unit_population = {}

        # Time range
        self.time_min = 0.0
        self.time_max = 0.0

        # Load data
        self._load_events()
        self._load_lookups()

    def _load_events(self):
        """Load all event types from HDF5 file."""
        logger.info(f"Loading events from {self.events_path}")

        if not self.events_path.exists():
            logger.warning(f"Events file not found: {self.events_path}")
            return

        with h5py.File(self.events_path, 'r') as f:
            # Load each event type
            event_types = [
                ('infections', ['person_id', 'infector_id', 'venue_id', 'time']),
                ('deaths', ['person_id', 'venue_id', 'time']),
                ('hospital_admissions', ['person_id', 'hospital_id', 'time', 'reason']),
                ('icu_admissions', ['person_id', 'hospital_id', 'time']),
                ('hospital_discharges', ['person_id', 'hospital_id', 'time', 'outcome']),
                ('symptom_changes', ['person_id', 'venue_id', 'time', 'old_symptom', 'new_symptom']),
            ]

            all_times = []

            for event_type, columns in event_types:
                path = f'events/{event_type}'
                if path in f:
                    data = f[path][:]
                    self.events[event_type] = data
                    logger.info(f"  Loaded {len(data)} {event_type}")

                    # Collect times for range calculation
                    if 'time' in data.dtype.names and len(data) > 0:
                        all_times.extend(data['time'])
                else:
                    self.events[event_type] = np.array([])
                    logger.info(f"  {event_type} not found in file")

            # Calculate time range
            if all_times:
                self.time_min = float(min(all_times))
                self.time_max = float(max(all_times))
                logger.info(f"  Time range: {self.time_min:.1f} - {self.time_max:.1f}")

    def _load_lookups(self):
        """Load venue and person lookup tables for geo_unit mapping."""
        if not self.events_path.exists():
            return

        with h5py.File(self.events_path, 'r') as f:
            # Load venue lookup (venue_id -> geo_unit_id)
            if 'lookups/venues' in f:
                venues = f['lookups/venues'][:]
                for venue in venues:
                    venue_id = int(venue['venue_id'])
                    geo_unit_id = int(venue['geo_unit_id'])
                    self.venue_to_geo_unit[venue_id] = geo_unit_id
                logger.info(f"  Loaded {len(self.venue_to_geo_unit)} venue mappings")

            # Load person lookup (person_id -> geo_unit_id)
            if 'lookups/people' in f:
                people = f['lookups/people'][:]
                for person in people:
                    person_id = int(person['person_id'])
                    geo_unit_id = int(person['geo_unit_id'])
                    self.person_to_geo_unit[person_id] = geo_unit_id
                logger.info(f"  Loaded {len(self.person_to_geo_unit)} person mappings")

            # Try population summary for population counts
            if 'lookups/population_summary' in f:
                pop_summary = f['lookups/population_summary'][:]
                geo_counts = defaultdict(int)
                for person in pop_summary:
                    geo_counts[int(person['geo_unit_id'])] += 1
                self.geo_unit_population = dict(geo_counts)

    def set_geo_unit_coords(self, coords: Dict[int, Tuple[float, float]]):
        """Set geo unit coordinates for map display."""
        self.geo_unit_coords = coords

    def set_geo_unit_population(self, population: Dict[int, int]):
        """Set geo unit population for rate calculations."""
        self.geo_unit_population = population

    def get_time_range(self) -> Tuple[float, float]:
        """Get the time range of all events."""
        return self.time_min, self.time_max

    def get_available_event_types(self) -> List[str]:
        """Get list of event types that have data."""
        return [k for k, v in self.events.items() if len(v) > 0]

    def get_event_summary(self) -> Dict[str, int]:
        """Get summary counts of all event types."""
        return {k: len(v) for k, v in self.events.items()}

    def aggregate_events_by_geo_unit(
        self,
        event_type: str,
        time_start: float,
        time_end: float,
        method: str = 'count'
    ) -> Dict[int, Dict[str, Any]]:
        """
        Aggregate events by geographical unit within a time window.

        Args:
            event_type: Type of event ('infections', 'deaths', etc.)
            time_start: Start of time window (inclusive)
            time_end: End of time window (inclusive)
            method: Aggregation method ('count' or 'rate')

        Returns:
            Dict mapping geo_unit_id to aggregation result:
            {
                geo_unit_id: {
                    'count': int,
                    'rate': float (per 100k if method='rate'),
                    'coords': [lat, lon] if available
                }
            }
        """
        if event_type not in self.events:
            return {}

        events = self.events[event_type]
        if len(events) == 0:
            return {}

        # Filter by time window
        time_mask = (events['time'] >= time_start) & (events['time'] <= time_end)
        filtered_events = events[time_mask]

        if len(filtered_events) == 0:
            return {}

        # Get geo_unit_id for each event
        geo_unit_counts = defaultdict(int)

        # Determine which field to use for venue/location
        if 'venue_id' in filtered_events.dtype.names:
            venue_field = 'venue_id'
        elif 'hospital_id' in filtered_events.dtype.names:
            venue_field = 'hospital_id'
        else:
            venue_field = None

        for event in filtered_events:
            geo_unit_id = None

            # Try to get geo_unit from venue
            if venue_field:
                venue_id = int(event[venue_field])
                geo_unit_id = self.venue_to_geo_unit.get(venue_id)

            # Fallback to person's geo_unit
            if geo_unit_id is None and 'person_id' in event.dtype.names:
                person_id = int(event['person_id'])
                geo_unit_id = self.person_to_geo_unit.get(person_id)

            if geo_unit_id is not None:
                geo_unit_counts[geo_unit_id] += 1

        # Build result
        result = {}
        for geo_unit_id, count in geo_unit_counts.items():
            entry = {'count': count}

            # Calculate rate if requested
            if method == 'rate':
                population = self.geo_unit_population.get(geo_unit_id, 0)
                if population > 0:
                    entry['rate'] = (count / population) * 100000
                else:
                    entry['rate'] = 0.0

            # Add coordinates if available
            if geo_unit_id in self.geo_unit_coords:
                entry['coords'] = self.geo_unit_coords[geo_unit_id]

            result[geo_unit_id] = entry

        return result

    def get_cumulative_events_by_geo_unit(
        self,
        event_type: str,
        up_to_time: float,
        method: str = 'count'
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get cumulative events by geographical unit up to a given time.

        Args:
            event_type: Type of event
            up_to_time: Include all events up to this time
            method: Aggregation method ('count' or 'rate')

        Returns:
            Same format as aggregate_events_by_geo_unit
        """
        return self.aggregate_events_by_geo_unit(
            event_type,
            self.time_min,
            up_to_time,
            method
        )

    def get_daily_events_timeseries(
        self,
        event_type: str
    ) -> pd.DataFrame:
        """
        Get daily event counts as a timeseries.

        Returns:
            DataFrame with 'day' and 'count' columns
        """
        if event_type not in self.events or len(self.events[event_type]) == 0:
            return pd.DataFrame(columns=['day', 'count'])

        events = self.events[event_type]
        times = events['time']

        # Bin by day
        days = np.floor(times).astype(int)
        unique, counts = np.unique(days, return_counts=True)

        return pd.DataFrame({'day': unique, 'count': counts})

    def get_events_geojson(
        self,
        event_type: str,
        time_start: float,
        time_end: float,
        method: str = 'count',
        cumulative: bool = False
    ) -> Dict:
        """
        Get events as GeoJSON FeatureCollection for map display.

        Args:
            event_type: Type of event
            time_start: Start of time window
            time_end: End of time window
            method: Aggregation method
            cumulative: If True, include all events up to time_end

        Returns:
            GeoJSON FeatureCollection
        """
        if cumulative:
            aggregated = self.get_cumulative_events_by_geo_unit(
                event_type, time_end, method
            )
        else:
            aggregated = self.aggregate_events_by_geo_unit(
                event_type, time_start, time_end, method
            )

        features = []
        for geo_unit_id, data in aggregated.items():
            if 'coords' not in data:
                continue

            lat, lon = data['coords']

            feature = {
                'type': 'Feature',
                'properties': {
                    'geo_unit_id': geo_unit_id,
                    'count': data['count'],
                    'rate': data.get('rate', 0.0)
                },
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(lon), float(lat)]
                }
            }
            features.append(feature)

        return {
            'type': 'FeatureCollection',
            'features': features,
            'properties': {
                'event_type': event_type,
                'time_start': time_start,
                'time_end': time_end,
                'method': method,
                'cumulative': cumulative,
                'total_count': sum(d['count'] for d in aggregated.values())
            }
        }


def load_events_with_world(
    events_path: str,
    world=None
) -> EventLoader:
    """
    Create an EventLoader and populate geo_unit coordinates from a World instance.

    Args:
        events_path: Path to simulation_events.h5
        world: World instance with geography data

    Returns:
        Configured EventLoader instance
    """
    loader = EventLoader(events_path)

    if world and world.geography:
        # Extract coordinates from all geo units
        coords = {}
        population = {}

        for level in world.geography.levels:
            units = world.geography.get_units_by_level(level)
            for unit in units.values():
                if unit.coordinates:
                    coords[unit.id] = unit.coordinates
                if unit.people:
                    population[unit.id] = len(unit.get_people())

        loader.set_geo_unit_coords(coords)
        loader.set_geo_unit_population(population)
        logger.info(f"Set {len(coords)} geo_unit coordinates from world")

    return loader
