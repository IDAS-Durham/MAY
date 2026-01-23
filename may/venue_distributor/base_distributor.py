import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from scipy.spatial import cKDTree
import logging

logger = logging.getLogger(__name__)

class BaseDistributor:
    """
    Base class for all venue distributors, providing shared infrastructure
    for configuration, spatial queries, and geographic management.
    """

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        """
        Initialize BaseDistributor.

        Args:
            config_file: Path to YAML config file
            config_dict: Dictionary config (alternative to file)
        """
        if config_file:
            self.config = self._load_config(config_file)
            self.config_path = Path(config_file)
        elif config_dict:
            self.config = config_dict
            self.config_path = None
        else:
            raise ValueError("Must provide either config_file or config_dict")

        self.verbose = self.config.get('settings', {}).get('verbose', False)
        
        # Statistics and tracking
        self.stats = {}
        self.allocated_this_run = 0

        # Geographical level configuration
        self.venue_geo_level = self.config.get('venue_selection', {}).get('venue_geo_level', 'SGU')
        self.batch_geo_level = self.config.get('venue_selection', {}).get('batch_geo_level', self.venue_geo_level)

        # Spatial indexing (supports multiple venue types)
        self.spatial_indices = {}  # venue_type -> cKDTree
        self.venue_lists = {}      # venue_type -> List[Venue]

        # Vectorized population arrays
        self.population_arrays = {}
        self.person_id_to_index = {}
        self.attribute_mappings = {}  # attr_name -> {value: int_index}

    def _load_config(self, config_path: str) -> Dict:
        """Load and parse YAML configuration file."""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _get_person_location(self, person) -> Optional[Tuple[float, float]]:
        """Get person's coordinates from their residence or geographical unit."""
        if hasattr(person, 'residence') and person.residence:
            if hasattr(person.residence, 'lat') and hasattr(person.residence, 'lon'):
                if person.residence.lat is not None and person.residence.lon is not None:
                    return (person.residence.lat, person.residence.lon)
        
        # Fallback to geographical unit coordinates
        geo = getattr(person, 'geographical_unit', None)
        if geo and hasattr(geo, 'coordinates') and geo.coordinates:
            return tuple(geo.coordinates)
        
        return None

    def _haversine_distance(self, loc1: Tuple[float, float], loc2: Tuple[float, float]) -> float:
        """Calculate distance between two lat/lon points in km."""
        lat1, lon1 = np.radians(loc1)
        lat2, lon2 = np.radians(loc2)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return c * 6371  # Earth radius in km

    def _get_geo_unit_at_level(self, person, world, target_level=None):
        """
        Get the person's geographical unit at a specified level.
        Enables traversal up the hierarchy (e.g. SGU -> MSOA).
        Supports custom location attributes via 'person_location_source' config.
        """
        if target_level is None:
            target_level = self.venue_geo_level

        # Get the person_location_source config (default to 'geographical_unit')
        loc_source = self.config.get('venue_selection', {}).get('person_location_source', 'geographical_unit')
        
        person_geo_unit = None

        # Handle common formats: 'geographical_unit', 'geographical_unit.coordinates', 'properties.workplace_sgu'
        if loc_source.startswith('geographical_unit'):
            person_geo_unit = getattr(person, 'geographical_unit', None)
        elif loc_source.startswith('properties.'):
            attr_name = loc_source.split('.')[1]
            if hasattr(person, 'properties'):
                loc_val = person.properties.get(attr_name)
                if loc_val:
                    person_geo_unit = world.geography.get_unit(loc_val)
        else:
            # Direct attribute
            person_geo_unit = getattr(person, loc_source, None)

        if person_geo_unit is None:
            return None

        if person_geo_unit.level == target_level:
            return person_geo_unit

        return person_geo_unit.get_ancestor_by_level(target_level)

    def _build_spatial_indices(self, venues_by_type: Dict[str, List]):
        """Build KDTree spatial indices for each provided venue type."""
        for venue_type, venues in venues_by_type.items():
            coords = []
            valid_venues = []
            for v in venues:
                if v.coordinates and len(v.coordinates) == 2:
                    coords.append(v.coordinates)
                    valid_venues.append(v)
            
            if coords:
                self.spatial_indices[venue_type] = cKDTree(np.array(coords))
                self.venue_lists[venue_type] = valid_venues
                if self.verbose:
                    logger.info(f"Built spatial index for {venue_type} with {len(coords)} venues")
            else:
                logger.warning(f"No venues with coordinates found for {venue_type} spatial index")

    def _find_closest_venues(self, location: Tuple[float, float], venue_type: str, count: int, k: Optional[int] = None, allowed_venue_ids: Optional[set] = None) -> List:
        """
        Find N closest venues of a specific type using spatial index.
        
        Args:
            location: (lat, lon) coordinates
            venue_type: Type of venue to search for
            count: Number of venues to return
            k: Number of candidates to query from KDTree (defaults to count if None)
            allowed_venue_ids: Optional set of venue IDs to restrict search to
        """
        index = self.spatial_indices.get(venue_type)
        venue_list = self.venue_lists.get(venue_type, [])
        
        if not index or not venue_list:
            return []

        # Use provided k or fallback to count
        # If allowed_venue_ids is provided, query more candidates to increase match probability
        fetch_k = k if k is not None else (count * 10 if allowed_venue_ids else count)
        
        fetch_k = min(fetch_k, len(venue_list))
        if fetch_k <= 0: return []

        try:
            distances, indices = index.query(location, k=fetch_k)
        except Exception as e:
            logger.debug(f"Failed to query spatial index for {venue_type} at {location}: {e}")
            return []

        if np.isscalar(indices):
            indices = [indices]
        else:
            indices = indices.tolist()

        closest_venues = []
        for i in indices:
            if 0 <= i < len(venue_list):
                venue = venue_list[i]
                if not allowed_venue_ids or id(venue) in allowed_venue_ids:
                    closest_venues.append(venue)
                    if len(closest_venues) >= count:
                        break

        return closest_venues

    def _build_population_arrays(self, people: List, attributes: Optional[List[str]] = None):
        """
        Extract key attributes into NumPy arrays for vectorized filtering.
        Dynamically builds mappings for categorical attributes.

        Args:
            people: List of Person objects
            attributes: Optional list of attribute names to vectorize (e.g., ['age', 'sex', 'residence.type'])
        """
        n = len(people)
        if n == 0: return

        # Default attributes that are always vectorized if available
        attrs_to_vectorize = set(['age', 'sex'])
        if attributes:
            attrs_to_vectorize.update(attributes)

        self.population_arrays = {
            'indices': np.arange(n, dtype=np.int32),
            'people': np.array(people, dtype=object)
        }
        self.person_id_to_index = {person.id: i for i, person in enumerate(people)}
        self.attribute_mappings = {}

        # First pass: Identify all unique values for categorical attributes to build mappings
        categorical_vals = defaultdict(set)
        
        # We'll determine which attributes are categorical based on person data
        # (Numerical attributes like 'age' are handled directly)
        
        for person in people:
            for attr in attrs_to_vectorize:
                if attr == 'age': continue
                
                val = self._get_person_attribute_for_vectorization(person, attr)
                if val is not None:
                    categorical_vals[attr].add(val)

        # Build mappings: val -> index (starting from 1, 0 is reserved for 'missing/other')
        for attr, vals in categorical_vals.items():
            self.attribute_mappings[attr] = {val: i+1 for i, val in enumerate(sorted(list(vals)))}

        # Second pass: Fill arrays
        for attr in attrs_to_vectorize:
            if attr == 'age':
                self.population_arrays['age'] = np.zeros(n, dtype=np.int16)
                for i, person in enumerate(people):
                    self.population_arrays['age'][i] = getattr(person, 'age', 0)
            else:
                self.population_arrays[attr] = np.zeros(n, dtype=np.int16)
                mapping = self.attribute_mappings.get(attr, {})
                for i, person in enumerate(people):
                    val = self._get_person_attribute_for_vectorization(person, attr)
                    self.population_arrays[attr][i] = mapping.get(val, 0)

    def _get_person_attribute_for_vectorization(self, person, attr_path: str) -> Any:
        """Helper to get attribute value from person including nested/residence paths."""
        if attr_path == 'residence.type':
            return getattr(person, 'residence_type', None)
        elif '.' in attr_path:
            # Simple nested support (e.g. residence.properties.xxx)
            parts = attr_path.split('.')
            curr = person
            for p in parts:
                if curr is None: return None
                if hasattr(curr, p):
                    curr = getattr(curr, p)
                elif hasattr(curr, 'properties') and isinstance(curr.properties, dict) and p in curr.properties:
                    curr = curr.properties[p]
                elif isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                else:
                    return None
            return curr
        else:
            return getattr(person, attr_path, None)

    def _can_vectorize_filters(self, filters: List[Dict]) -> bool:
        """Check if all filters in the list are supported by the current vectorized arrays."""
        if not self.population_arrays:
            return False
            
        for rule in filters:
            attr = rule.get('attribute')
            if attr not in self.population_arrays:
                return False
        return True

    def _apply_filters_vectorized(self, indices: np.ndarray, filters: List[Dict]) -> np.ndarray:
        """Apply filters using vectorized boolean masks and dynamic mappings."""
        if len(indices) == 0: return indices

        mask = np.ones(len(indices), dtype=bool)

        for rule in filters:
            attr = rule.get('attribute')
            if attr not in self.population_arrays:
                continue

            current_vals = self.population_arrays[attr][indices]
            
            if attr == 'age':
                min_val, max_val = rule.get('min'), rule.get('max')
                if min_val is not None: mask &= (current_vals >= min_val)
                if max_val is not None: mask &= (current_vals <= max_val)
            else:
                # Categorical filter using dynamic mapping
                mapping = self.attribute_mappings.get(attr, {})
                
                # Single value filter
                val = rule.get('value')
                if val is not None:
                    target_code = mapping.get(val, -1) # -1 will never match if missing
                    mask &= (current_vals == target_code)
                
                # Multi-value filter
                vals = rule.get('values', [])
                if vals:
                    allowed_codes = [mapping[v] for v in vals if v in mapping]
                    if allowed_codes:
                        val_mask = np.zeros(len(indices), dtype=bool)
                        for code in allowed_codes:
                            val_mask |= (current_vals == code)
                        mask &= val_mask
                    else:
                        # None of the requested values exist in the population
                        mask &= False
                        
        return indices[mask]

    def _increment_venue_count(self, venue):
        """Track how many people are assigned to this venue."""
        if not hasattr(self, 'venue_capacity_tracker'):
            self.venue_capacity_tracker = {}
        v_id = id(venue)
        self.venue_capacity_tracker[v_id] = self.venue_capacity_tracker.get(v_id, 0) + 1

    def _get_venue_capacity(self, venue) -> int:
        """Get the total capacity of a venue from configuration or default attributes."""
        # fixed_capacity overrides everything
        allocation_config = self.config.get('allocation', {})
        fixed = allocation_config.get('fixed_capacity')
        if fixed is not None:
            return fixed

        # Check for specific capacity column in venue object (attributes or properties)
        col = allocation_config.get('capacity_column')
        capacity = None
        
        if col:
            if hasattr(venue, col):
                capacity = getattr(venue, col)
            elif hasattr(venue, 'properties') and col in venue.properties:
                capacity = venue.properties[col]
        
        # Default heuristics for common venue types if no specific col found
        if capacity is None:
            for attr in ["SchoolCapacity", "number_staff", "capacity", "max_capacity"]:
                if hasattr(venue, attr):
                    capacity = getattr(venue, attr)
                    break
                elif hasattr(venue, 'properties') and attr in venue.properties:
                    capacity = venue.properties[attr]
                    break

        # Handle missing capacity based on config
        capacity_handling = allocation_config.get('capacity_handling', {})
        if capacity is None or pd.isna(capacity):
            if_missing = capacity_handling.get('if_missing', 'ignore')
            if if_missing == 'ignore':
                return 1_000_000  # Effective unlimited
            elif if_missing == 'default':
                return capacity_handling.get('default_capacity', 1000)
            return 0

        # Handle zero capacity based on config
        if int(capacity) == 0:
            if_zero = capacity_handling.get('if_zero', 'skip')
            if if_zero == 'ignore':
                return 1_000_000  # Effective unlimited
            return 0

        return int(capacity)

    def _filter_venues_by_capacity(self, venues: List) -> List:
        """Filter venues that still have remaining capacity."""
        allocation_config = self.config.get('allocation', {})
        
        # Check if capacity tracking is actually enabled
        if not allocation_config.get('track_capacity', True):
            return venues

        when_full = allocation_config.get('when_full', 'exclude')
        if when_full == 'overflow':
            return venues

        available = []
        for v in venues:
            # Use venue's id() as key in capacity tracker
            current = self.venue_capacity_tracker.get(id(v), 0) if hasattr(self, 'venue_capacity_tracker') else 0
            capacity = self._get_venue_capacity(v)
            if current < capacity:
                available.append(v)
        return available
