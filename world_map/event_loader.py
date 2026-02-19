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

# ---------------------------------------------------------------------------
# Optional Numba JIT compilation for the inner aggregation loop.
# Falls back to pure Python if numba is not installed.
# ---------------------------------------------------------------------------
try:
    from numba import njit
    _NUMBA_AVAILABLE = True
except ImportError:
    _NUMBA_AVAILABLE = False
    # No-op decorator so the functions below are still importable
    def njit(*args, **kwargs):
        def decorator(f):
            return f
        return decorator if (args and callable(args[0])) else decorator


@njit(cache=True)
def _count_venue_and_person(venue_ids, person_ids, venue_geo, person_geo, n_geo):
    """
    JIT-compiled aggregation: count events per geo_unit.

    Uses venue_id as the primary location, person_id as fallback.

    Args:
        venue_ids:  int32 array of venue IDs for each event
        person_ids: int32 array of person IDs for each event
        venue_geo:  int32 array mapping venue_id -> geo_unit_id (-1 = unknown)
        person_geo: int32 array mapping person_id -> geo_unit_id (-1 = unknown)
        n_geo:      size of the output counts array

    Returns:
        int32 array of length n_geo; counts[i] = events in geo_unit i
    """
    counts = np.zeros(n_geo, dtype=np.int32)
    for i in range(len(venue_ids)):
        geo_id = np.int32(-1)
        vid = venue_ids[i]
        if 0 <= vid < len(venue_geo):
            geo_id = venue_geo[vid]
        if geo_id < 0:
            pid = person_ids[i]
            if 0 <= pid < len(person_geo):
                geo_id = person_geo[pid]
        if 0 <= geo_id < n_geo:
            counts[geo_id] += 1
    return counts


@njit(cache=True)
def _count_person_only(person_ids, person_geo, n_geo):
    """
    JIT-compiled aggregation: count events per geo_unit using only person_id.

    Args:
        person_ids: int32 array of person IDs for each event
        person_geo: int32 array mapping person_id -> geo_unit_id (-1 = unknown)
        n_geo:      size of the output counts array

    Returns:
        int32 array of length n_geo; counts[i] = events in geo_unit i
    """
    counts = np.zeros(n_geo, dtype=np.int32)
    for i in range(len(person_ids)):
        pid = person_ids[i]
        if 0 <= pid < len(person_geo):
            geo_id = person_geo[pid]
            if 0 <= geo_id < n_geo:
                counts[geo_id] += 1
    return counts


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

        # --- Fast-path structures (built after load) ---
        # Events sorted by time for binary-search window filtering
        self.events_sorted = {}   # {event_type: structured array sorted by time}
        self.events_times = {}    # {event_type: float32 times array (sorted)}

        # Dense numpy arrays for O(1) venue/person → geo_unit lookup
        self.venue_geo_array = None   # int32[venue_id]  = geo_unit_id (-1 = missing)
        self.person_geo_array = None  # int32[person_id] = geo_unit_id (-1 = missing)
        self._n_geo = 1               # length of per-tick counts array

        # Simple result cache keyed by (event_type, time_start, time_end, method)
        self._result_cache: Dict = {}

        # Load data
        self._load_events()
        self._load_lookups()

        # Build fast-path structures
        self._preprocess_events()
        self._build_lookup_arrays()

        if _NUMBA_AVAILABLE:
            logger.info("Numba JIT available — event aggregation will use compiled kernels")
        else:
            logger.warning("Numba not available — falling back to Python loop for aggregation")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Fast-path preprocessing (called once after load)
    # ------------------------------------------------------------------

    def _preprocess_events(self):
        """
        Sort each event array by time so that time-window queries can use
        binary search (O(log n)) instead of a full boolean mask (O(n)).
        """
        for event_type, events in self.events.items():
            if len(events) == 0:
                self.events_sorted[event_type] = events
                self.events_times[event_type] = np.array([], dtype=np.float32)
                continue

            sort_idx = np.argsort(events['time'], kind='stable')
            sorted_arr = events[sort_idx]
            self.events_sorted[event_type] = sorted_arr
            self.events_times[event_type] = sorted_arr['time'].astype(np.float32)

        logger.info("  Events pre-sorted by time for fast window queries")

    def _build_lookup_arrays(self):
        """
        Convert venue/person → geo_unit dicts into dense numpy arrays.
        Indexed directly by ID, giving O(1) vectorised lookup vs. O(1) per-item
        Python dict lookup (with lower constant factor and JIT-friendly memory layout).
        """
        _MAX_ID = 50_000_000  # Safety cap (~200 MB for int32 array)

        if self.venue_to_geo_unit:
            vids  = np.array(list(self.venue_to_geo_unit.keys()),   dtype=np.int32)
            vgeos = np.array(list(self.venue_to_geo_unit.values()), dtype=np.int32)
            max_vid = int(vids.max())
            if max_vid < _MAX_ID:
                self.venue_geo_array = np.full(max_vid + 1, -1, dtype=np.int32)
                self.venue_geo_array[vids] = vgeos
                logger.info(f"  Built venue lookup array (size {max_vid + 1:,})")

        if self.person_to_geo_unit:
            pids  = np.array(list(self.person_to_geo_unit.keys()),   dtype=np.int32)
            pgeos = np.array(list(self.person_to_geo_unit.values()), dtype=np.int32)
            max_pid = int(pids.max())
            if max_pid < _MAX_ID:
                self.person_geo_array = np.full(max_pid + 1, -1, dtype=np.int32)
                self.person_geo_array[pids] = pgeos
                logger.info(f"  Built person lookup array (size {max_pid + 1:,})")

        all_geos: set = set(self.venue_to_geo_unit.values()) | set(self.person_to_geo_unit.values())
        self._n_geo = int(max(all_geos)) + 1 if all_geos else 1

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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

        Uses binary search for O(log n) time filtering and Numba-JIT compiled
        kernels for the inner counting loop.

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

        # --- Cache check ---
        cache_key = (event_type, round(time_start, 3), round(time_end, 3), method)
        if cache_key in self._result_cache:
            return self._result_cache[cache_key]

        # --- O(log n) time filtering via binary search on pre-sorted array ---
        times      = self.events_times.get(event_type)
        sorted_arr = self.events_sorted.get(event_type)

        if times is None or sorted_arr is None or len(times) == 0:
            return {}

        start_idx = int(np.searchsorted(times, time_start, side='left'))
        end_idx   = int(np.searchsorted(times, time_end,   side='right'))

        if start_idx >= end_idx:
            return {}

        filtered = sorted_arr[start_idx:end_idx]  # numpy view — O(1)

        # --- Determine which field holds the venue/location ID ---
        if 'venue_id' in filtered.dtype.names:
            venue_field = 'venue_id'
        elif 'hospital_id' in filtered.dtype.names:
            venue_field = 'hospital_id'
        else:
            venue_field = None

        # --- Count events per geo_unit (JIT path or Python fallback) ---
        counts_arr = None

        if (venue_field is not None
                and self.venue_geo_array is not None
                and 'person_id' in filtered.dtype.names
                and self.person_geo_array is not None):
            # Primary path: venue with person fallback
            venue_ids  = np.ascontiguousarray(filtered[venue_field],  dtype=np.int32)
            person_ids = np.ascontiguousarray(filtered['person_id'], dtype=np.int32)
            counts_arr = _count_venue_and_person(
                venue_ids, person_ids,
                self.venue_geo_array, self.person_geo_array,
                self._n_geo)

        elif ('person_id' in filtered.dtype.names
              and self.person_geo_array is not None):
            # Person-only path
            person_ids = np.ascontiguousarray(filtered['person_id'], dtype=np.int32)
            counts_arr = _count_person_only(
                person_ids, self.person_geo_array, self._n_geo)

        else:
            # Fallback: original Python loop (when lookup arrays are unavailable)
            geo_unit_counts: Dict[int, int] = defaultdict(int)
            for event in filtered:
                geo_unit_id = None
                if venue_field:
                    vid = int(event[venue_field])
                    geo_unit_id = self.venue_to_geo_unit.get(vid)
                if geo_unit_id is None and 'person_id' in event.dtype.names:
                    pid = int(event['person_id'])
                    geo_unit_id = self.person_to_geo_unit.get(pid)
                if geo_unit_id is not None:
                    geo_unit_counts[geo_unit_id] += 1

            result = self._build_result_from_dict(geo_unit_counts, method)
            self._cache(cache_key, result)
            return result

        # --- Build result dict from counts array ---
        result = self._build_result_from_array(counts_arr, method)
        self._cache(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result_from_array(self, counts_arr: np.ndarray, method: str) -> Dict:
        """Convert a dense counts array (indexed by geo_unit_id) to a result dict."""
        nonzero_geos = np.nonzero(counts_arr)[0]
        result = {}
        for geo_id_np in nonzero_geos:
            geo_id = int(geo_id_np)
            count  = int(counts_arr[geo_id])
            entry: Dict[str, Any] = {'count': count}
            if method == 'rate':
                pop = self.geo_unit_population.get(geo_id, 0)
                entry['rate'] = (count / pop) * 100_000 if pop > 0 else 0.0
            if geo_id in self.geo_unit_coords:
                entry['coords'] = self.geo_unit_coords[geo_id]
            result[geo_id] = entry
        return result

    def _build_result_from_dict(self, geo_unit_counts: Dict[int, int], method: str) -> Dict:
        """Convert a {geo_unit_id: count} dict to a result dict."""
        result = {}
        for geo_unit_id, count in geo_unit_counts.items():
            entry: Dict[str, Any] = {'count': count}
            if method == 'rate':
                pop = self.geo_unit_population.get(geo_unit_id, 0)
                entry['rate'] = (count / pop) * 100_000 if pop > 0 else 0.0
            if geo_unit_id in self.geo_unit_coords:
                entry['coords'] = self.geo_unit_coords[geo_unit_id]
            result[geo_unit_id] = entry
        return result

    def _cache(self, key: tuple, result: Dict):
        """Store result in cache, evicting the oldest entry if full."""
        if len(self._result_cache) >= 256:
            self._result_cache.pop(next(iter(self._result_cache)))
        self._result_cache[key] = result

    # ------------------------------------------------------------------
    # Remaining public API (unchanged logic)
    # ------------------------------------------------------------------

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
