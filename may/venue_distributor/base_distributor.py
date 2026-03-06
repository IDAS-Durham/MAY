import yaml
import math
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
    
    def _get_venue_location(self, venue) -> Optional[Tuple[float, float]]:
        """Get venue's coordinates with fallback to geographical unit."""
        if hasattr(venue, 'coordinates') and venue.coordinates:
            if len(venue.coordinates) == 2:
                return tuple(venue.coordinates)
        
        # Fallback to geographical unit coordinates
        geo = getattr(venue, 'geographical_unit', None)
        if geo and hasattr(geo, 'coordinates') and geo.coordinates:
            return tuple(geo.coordinates)
        
        return None

    def _haversine_distance(self, loc1: Tuple[float, float], loc2: Tuple[float, float]) -> float:
        """Calculate distance between two lat/lon points in km."""
        lat1, lon1 = loc1
        lat2, lon2 = loc2
        
        # Convert degrees to radians - math.radians is much faster than np.radians for scalars
        r_lat1 = math.radians(lat1)
        r_lon1 = math.radians(lon1)
        r_lat2 = math.radians(lat2)
        r_lon2 = math.radians(lon2)

        dlat = r_lat2 - r_lat1
        dlon = r_lon2 - r_lon1

        a = math.sin(dlat/2)**2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return c * 6371  # Earth radius in km

    def _haversine_distance_vectorized(self, loc1: Tuple[float, float], locs2: np.ndarray) -> np.ndarray:
        """Calculate distance between one point and many points in km (Vectorized)."""
        lat1, lon1 = np.radians(loc1)
        lats2, lons2 = np.radians(locs2[:, 0]), np.radians(locs2[:, 1])

        dlat = lats2 - lat1
        dlon = lons2 - lon1

        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lats2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return c * 6371

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
                v_coords = self._get_venue_location(v)
                
                if v_coords:
                    coords.append(v_coords)
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

    def _build_population_arrays(self, people: List, attributes: Optional[List[str]] = None, **kwargs):
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

        # Pre-calculate path parts to avoid repeated splitting
        attr_metadata = {}
        numerical_attrs = set(kwargs.get('numerical_attributes', []))
        
        for attr in attrs_to_vectorize:
            if attr == 'age':
                attr_metadata[attr] = {'parts': ['age'], 'type': 'direct', 'is_numerical': True}
            elif attr == 'sex':
                attr_metadata[attr] = {'parts': ['sex'], 'type': 'direct', 'is_numerical': False}
            elif attr == 'residence.type':
                attr_metadata[attr] = {'parts': ['residence_type'], 'type': 'property', 'is_numerical': False}
            elif attr == 'residence.id':
                attr_metadata[attr] = {'parts': ['residence_id'], 'type': 'property', 'is_numerical': True}
            else:
                attr_metadata[attr] = {
                    'parts': attr.split('.'), 
                    'type': 'nested', 
                    'is_numerical': attr in numerical_attrs
                }

        # First pass: Identify all unique values for categorical attributes to build mappings
        categorical_vals = defaultdict(set)
        
        for person in people:
            for attr, meta in attr_metadata.items():
                if meta['is_numerical']: continue
                
                val = self._get_person_attribute(attr, person)
                if val is not None and not (isinstance(val, (float, np.floating)) and np.isnan(val)):
                    categorical_vals[attr].add(val)

        # Build mappings: val -> index (starting from 1, 0 is reserved for 'missing/other')
        for attr, vals in categorical_vals.items():
            self.attribute_mappings[attr] = {val: i+1 for i, val in enumerate(sorted(list(vals)))}

        # Second pass: Fill arrays
        for attr, meta in attr_metadata.items():
            if meta['is_numerical']:
                if attr == 'age':
                    self.population_arrays['age'] = np.array([getattr(p, 'age', 0) for p in people], dtype=np.int32)
                elif attr == 'residence.id':
                    self.population_arrays[attr] = np.array([p.residence.id if p.residence else -1 for p in people], dtype=np.int32)
                else:
                    self.population_arrays[attr] = np.array([
                        self._safe_int(self._get_person_attribute(attr, p))
                        for p in people
                    ], dtype=np.int32)
            else:
                mapping = self.attribute_mappings.get(attr, {})
                parts = meta['parts']
                # Fast-path for common attributes
                if attr == 'sex':
                    self.population_arrays[attr] = np.array([mapping.get(p.sex, 0) for p in people], dtype=np.int32)
                elif attr == 'residence.type':
                    self.population_arrays[attr] = np.array([mapping.get(p.residence_type, 0) for p in people], dtype=np.int32)
                elif attr == 'residence.id':
                    # Directly use residence.id if it's an integer, otherwise use mapping
                    self.population_arrays[attr] = np.array([p.residence.id if p.residence else -1 for p in people], dtype=np.int32)
                else:
                    # General path (properties, nested, etc.)
                    # Must use _get_person_attribute to check person.properties
                    self.population_arrays[attr] = np.array([
                        mapping.get(self._get_person_attribute(attr, p), 0) 
                        for p in people
                    ], dtype=np.int32)

    def _get_person_attribute(self, path: str, person: Any):
        """
        Get value from person with special handling for residence.

        For paths like 'residence.name' or 'residence.geographical_unit.name',
        this looks at the person.residence property.
        """
        if path.startswith('residence.'):
            residence = getattr(person, 'residence', None)
            if residence is None:
                return None
            attr_path = path.replace('residence.', '')
            return self._get_nested_value_with_dict_support(residence, attr_path)

        # Check properties first for common attributes not in slots
        if hasattr(person, 'properties') and path in person.properties:
            return person.properties[path]

        return self._get_nested_value_with_dict_support(person, path)

    def _get_nested_value(self, obj, path: str):
        """Get value from nested object path (e.g., 'name' or 'geo_unit')."""
        if not path: return obj
        parts = path.split('.')
        value = obj
        for part in parts:
            if value is None: return None
            if hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
        return value

    def _create_path_getter(self, path: List[str]):
        """Create a getter function for a specific nested path."""
        if not path:
            return lambda obj: obj
            
        if len(path) == 1:
            part = path[0]
            def single_getter(obj):
                if obj is None: return None
                if isinstance(obj, dict): return obj.get(part)
                return getattr(obj, part, None)
            return single_getter
        
        # Nested path: pre-bind the parts to avoid loops
        def nested_getter(obj):
            val = obj
            for part in path:
                if val is None: return None
                if isinstance(val, dict): val = val.get(part)
                else: val = getattr(val, part, None)
            return val
        return nested_getter

    def _normalize_value(self, val: Any) -> str:
        """
        Normalize value to a clean string for matching.
        Handles float-to-string conversion issues (e.g., 787.0 -> "787").
        """
        if val is None or val == '':
            return ""
        
        # If it's a float that's actually an integer, convert to int string
        if isinstance(val, (float, np.floating)):
            if val.is_integer():
                return str(int(val))
            return str(val)
        
        # If it's already a string that looks like a whole number float, clean it
        s_val = str(val).strip()
        if s_val.endswith('.0'):
            return s_val[:-2]
            
        return s_val

    def _safe_int(self, val: Any) -> int:
        """Safe conversion to integer, handling None, empty strings, and NaN."""
        if val is None or val == '':
            return 0
        try:
            # Handle numpy types and floats (including NaN)
            f_val = float(val)
            if np.isnan(f_val):
                return 0
            return int(f_val)
        except (ValueError, TypeError, OverflowError):
            return 0

    def _get_nested_value_with_dict_support(self, obj, path: Any):
        """
        Get value from nested path supporting both object attributes and dictionaries.
        """
        if not path: return obj
        
        # skip split/isinstance if we already have a list/tuple
        if isinstance(path, (list, tuple)):
            parts = path
        else:
            parts = path.split('.')
        
        value = obj
        for part in parts:
            if value is None:
                return None

            # Try dict access first if value is actually a dict
            # This is significantly faster than try/except getattr for dicts
            if type(value) is dict:
                value = value.get(part)
            else:
                value = getattr(value, part, None)
                
        return value

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
            
            filter_type = rule.get('type', 'numerical')
            if filter_type == 'numerical':
                min_val, max_val = rule.get('min'), rule.get('max')
                if min_val is not None: mask &= (current_vals >= min_val)
                if max_val is not None: mask &= (current_vals <= max_val)
            else:
                # Categorical filter using dynamic mapping
                mapping = self.attribute_mappings.get(attr, {})
                
                # Single value filter
                val = rule.get('value')
                if val is not None:
                    # Try direct lookup, then normalized lookup
                    target_code = mapping.get(val)
                    if target_code is None:
                        # Normalize both search value and mapping keys if needed
                        norm_val = self._normalize_value(val)
                        for m_val, m_code in mapping.items():
                            if self._normalize_value(m_val) == norm_val:
                                target_code = m_code
                                break
                    
                    if target_code is not None:
                        mask &= (current_vals == target_code)
                    else:
                        mask &= False
                
                # Multi-value filter
                vals = rule.get('values', [])
                if vals:
                    allowed_codes = []
                    for v in vals:
                        code = mapping.get(v)
                        if code is None:
                            norm_v = self._normalize_value(v)
                            for m_val, m_code in mapping.items():
                                if self._normalize_value(m_val) == norm_v:
                                    code = m_code
                                    break
                        if code is not None:
                            allowed_codes.append(code)
                            
                    if allowed_codes:
                        val_mask = np.zeros(len(indices), dtype=bool)
                        for code in allowed_codes:
                            val_mask |= (current_vals == code)
                        mask &= val_mask
                    else:
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
            for attr in ["SchoolCapacity", "Noofroomscode", "number_staff", "capacity", "max_capacity"]:
                if hasattr(venue, attr):
                    capacity = getattr(venue, attr)
                elif hasattr(venue, 'properties') and attr in venue.properties:
                    capacity = venue.properties[attr]
                
                if capacity is not None and not pd.isna(capacity):
                    # Heuristic: if it's rooms, multiply by a reasonable factor
                    if attr == "Noofroomscode":
                        capacity = int(float(capacity)) * 30 
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

    def _get_remaining_capacity(self, venue) -> int:
        """Get the remaining capacity of a venue."""
        v_id = id(venue)
        current = self.venue_capacity_tracker.get(v_id, 0) if hasattr(self, 'venue_capacity_tracker') else 0
        capacity = self._get_venue_capacity(venue)
        return max(0, capacity - current)

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
            if self._get_remaining_capacity(v) > 0:
                available.append(v)
        return available
