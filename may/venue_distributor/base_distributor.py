import math
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from scipy.spatial import cKDTree
import logging
from may.utils import path_resolver as pr
from may.utils.attribute_access import _compile_attribute, get_attribute
from may.utils.yaml_loader import load_yaml

logger = logging.getLogger(__name__)

# Of those, the ones whose values are already integers and go into an array
# without a categorical mapping.
_INTEGER_SLOT_ATTRIBUTES = frozenset({"age", "residence.id"})


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
            config_file = pr.resolve(str(config_file))
            self.config = load_yaml(config_file)
            self.config_path = Path(config_file)
        elif config_dict:
            self.config = config_dict
            self.config_path = None
        else:
            raise ValueError("Must provide either config_file or config_dict")

        self.verbose = self.config.get("settings", {}).get("verbose", False)

        # Statistics and tracking
        self.stats = {}
        self.allocated_this_run = 0

        # Geographical level configuration. Required at the point of use, so
        # distributors that skip geo venue search (e.g. route) can leave it unset.
        self.venue_geo_level = self.config.get("venue_selection", {}).get(
            "venue_geo_level"
        )
        self.batch_geo_level = self.config.get("venue_selection", {}).get(
            "batch_geo_level", self.venue_geo_level
        )

        # Spatial indexing (supports multiple venue types)
        self.spatial_indices = {}  # venue_type -> cKDTree
        self.venue_lists = {}  # venue_type -> List[Venue]

        # Vectorized population arrays
        self.population_arrays = {}
        self.person_id_to_index = {}
        self.attribute_mappings = {}  # attr_name -> {value: int_index}

    def _pre_process_filters(self, filters: List[Dict]) -> List[Dict]:
        """Pre-process filters to avoid repeated path parsing."""
        processed = []
        for f in filters:
            p_filter = f.copy()
            attr_name = f.get("attribute")
            if attr_name:
                parts = attr_name.split(".")
                p_filter["path_parts"] = parts
                p_filter["is_nested"] = len(parts) > 1
                p_filter["is_residence"] = parts[0] == "residence"
                if p_filter["is_residence"]:
                    p_filter["residence_parts"] = parts[1:]
            else:
                p_filter["is_nested"] = False
            processed.append(p_filter)
        return processed

    def _get_person_location(self, person) -> Optional[Tuple[float, float]]:
        """Get a person's coordinates from the configured location source."""
        source = self.config.get("venue_selection", {}).get(
            "locate_person_by", "geographical_unit.coordinates"
        )
        location = get_attribute(person, source, nested_properties=False)
        if source.startswith("properties.") and isinstance(location, str):
            world = getattr(self, "world", None)
            geography = getattr(world, "geography", None)
            location = geography.get_unit(location) if geography else None
        if location is not None and hasattr(location, "coordinates"):
            location = location.coordinates
        if location is not None and not isinstance(location, str):
            try:
                if len(location) == 2:
                    return tuple(location)
            except TypeError:
                pass
        if source.startswith("properties."):
            return None

        residence = get_attribute(person, "residence")
        lat, lon = get_attribute(residence, "lat"), get_attribute(residence, "lon")
        if lat is not None and lon is not None:
            return (lat, lon)
        return None

    def _get_venue_location(self, venue) -> Optional[Tuple[float, float]]:
        """Get venue's coordinates with fallback to geographical unit."""
        coordinates = get_attribute(venue, "coordinates")
        if coordinates and len(coordinates) == 2:
            return tuple(coordinates)
        coordinates = get_attribute(venue, "geographical_unit.coordinates")
        if coordinates:
            return tuple(coordinates)
        return None

    def _haversine_distance(
        self, loc1: Tuple[float, float], loc2: Tuple[float, float]
    ) -> float:
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

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))
        return c * 6371  # Earth radius in km

    def _haversine_distance_vectorized(
        self, loc1: Tuple[float, float], locs2: np.ndarray
    ) -> np.ndarray:
        """Calculate distance between one point and many points in km (Vectorized)."""
        lat1, lon1 = np.radians(loc1)
        lats2, lons2 = np.radians(locs2[:, 0]), np.radians(locs2[:, 1])

        dlat = lats2 - lat1
        dlon = lons2 - lon1

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lats2) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))
        return c * 6371

    def _require_venue_geo_level(self):
        """The configured venue geography level, or fail loud."""
        if self.venue_geo_level is None:
            raise ValueError(
                f"{type(self).__name__}: 'venue_selection.venue_geo_level' is required "
                f"for geo-based venue allocation; there is no default."
            )
        return self.venue_geo_level

    def _get_geo_unit_at_level(self, person, world, target_level=None):
        """
        Get the person's geographical unit at a specified level.
        Enables traversal up the hierarchy (e.g. SGU -> MSOA).
        Supports custom location attributes via 'locate_person_by' config.
        """
        if target_level is None:
            target_level = self._require_venue_geo_level()

        # Get the locate_person_by config (default to 'geographical_unit')
        loc_source = self.config.get("venue_selection", {}).get(
            "locate_person_by", "geographical_unit"
        )

        person_geo_unit = None

        # Handle common formats: 'geographical_unit', 'geographical_unit.coordinates', 'properties.workplace_sgu'
        person_geo_unit = (
            get_attribute(person, "geographical_unit")
            if loc_source.startswith("geographical_unit")
            else get_attribute(person, loc_source, nested_properties=False)
        )
        if loc_source.startswith("properties.") and person_geo_unit is not None:
            person_geo_unit = world.geography.get_unit(person_geo_unit)

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
                    logger.info(
                        f"Built spatial index for {venue_type} with {len(coords)} venues"
                    )
            else:
                logger.warning(
                    f"No venues with coordinates found for {venue_type} spatial index"
                )

    def _find_closest_venues(
        self,
        location: Tuple[float, float],
        venue_type: str,
        count: int,
        k: Optional[int] = None,
        allowed_venue_ids: Optional[set] = None,
    ) -> List:
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
        if fetch_k <= 0:
            return []

        try:
            distances, indices = index.query(location, k=fetch_k)
        except Exception as e:
            logger.debug(
                f"Failed to query spatial index for {venue_type} at {location}: {e}"
            )
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

    def _build_population_arrays(
        self, people: List, attributes: Optional[List[str]] = None, **kwargs
    ):
        """
        Extract key attributes into NumPy arrays for vectorized filtering.
        Dynamically builds mappings for categorical attributes.

        Args:
            people: List of Person objects
            attributes: Optional list of attribute names to vectorize (e.g., ['age', 'sex', 'residence.type'])
        """
        n = len(people)
        if n == 0:
            return

        # Default attributes that are always vectorized if available
        attrs_to_vectorize = set(["age", "sex"])
        if attributes:
            attrs_to_vectorize.update(attributes)

        self.population_arrays = {
            "indices": np.arange(n, dtype=np.int32),
            "people": np.array(people, dtype=object),
        }
        self.person_id_to_index = {person.id: i for i, person in enumerate(people)}
        self.attribute_mappings = {}

        numerical_attrs = set(kwargs.get("numerical_attributes", []))

        # Each attribute is resolved once per person. The values feed both the
        # categorical mapping and the array, so a second walk is not needed.
        for attr in attrs_to_vectorize:
            getter = _compile_attribute(attr, False)
            if attr == "age":
                values = [
                    get_attribute(p, attr, 0, nested_properties=False) for p in people
                ]
            elif attr == "residence.id":
                values = [
                    get_attribute(
                        get_attribute(p, "residence"), "id", -1, nested_properties=False
                    )
                    for p in people
                ]
            else:
                values = [getter(p) for p in people]

            if attr in _INTEGER_SLOT_ATTRIBUTES:
                self.population_arrays[attr] = np.array(values, dtype=np.int32)
            elif attr in numerical_attrs:
                self.population_arrays[attr] = np.array(
                    [self._safe_int(v) for v in values], dtype=np.int32
                )
            else:
                # Index 0 is reserved for missing values, so mapping starts at 1
                present = {
                    v
                    for v in values
                    if v is not None
                    and not (isinstance(v, (float, np.floating)) and np.isnan(v))
                }
                mapping = {val: i + 1 for i, val in enumerate(sorted(present))}
                self.attribute_mappings[attr] = mapping
                self.population_arrays[attr] = np.array(
                    [mapping.get(v, 0) for v in values], dtype=np.int32
                )

    def _normalize_value(self, val: Any) -> str:
        """
        Normalize value to a clean string for matching.
        Handles float-to-string conversion issues (e.g., 787.0 -> "787").
        """
        if val is None or val == "":
            return ""

        # If it's a float that's actually an integer, convert to int string
        if isinstance(val, (float, np.floating)):
            if val.is_integer():
                return str(int(val))
            return str(val)

        # If it's already a string that looks like a whole number float, clean it
        s_val = str(val).strip()
        if s_val.endswith(".0"):
            return s_val[:-2]

        return s_val

    def _safe_int(self, val: Any) -> int:
        """Safe conversion to integer, handling None, empty strings, and NaN."""
        if val is None or val == "":
            return 0
        try:
            # Handle numpy types and floats (including NaN)
            f_val = float(val)
            if np.isnan(f_val):
                return 0
            return int(f_val)
        except (ValueError, TypeError, OverflowError):
            return 0

    def _can_vectorize_filters(self, filters: List[Dict]) -> bool:
        """Check if all filters in the list are supported by the current vectorized arrays."""
        if not self.population_arrays:
            return False

        for rule in filters:
            attr = rule.get("attribute")
            if attr not in self.population_arrays:
                return False
        return True

    def _apply_filters_vectorized(
        self, indices: np.ndarray, filters: List[Dict]
    ) -> np.ndarray:
        """Apply filters using vectorized boolean masks and dynamic mappings."""
        if len(indices) == 0:
            return indices

        mask = np.ones(len(indices), dtype=bool)

        for rule in filters:
            attr = rule.get("attribute")
            if attr not in self.population_arrays:
                continue

            current_vals = self.population_arrays[attr][indices]

            filter_type = rule.get("type", "numerical")
            if filter_type == "numerical":
                min_val, max_val = rule.get("min"), rule.get("max")
                if min_val is not None:
                    mask &= current_vals >= min_val
                if max_val is not None:
                    mask &= current_vals <= max_val
            else:
                # Categorical filter using dynamic mapping
                mapping = self.attribute_mappings.get(attr, {})

                # Single value filter
                val = rule.get("value")
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
                        mask &= current_vals == target_code
                    else:
                        mask &= False

                # Multi-value filter
                vals = rule.get("values", [])
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
                            val_mask |= current_vals == code
                        mask &= val_mask
                    else:
                        mask &= False

        return indices[mask]

    def _increment_venue_count(self, venue):
        """Track how many people are assigned to this venue."""
        if not hasattr(self, "venue_capacity_tracker"):
            self.venue_capacity_tracker = {}
        v_id = id(venue)
        self.venue_capacity_tracker[v_id] = self.venue_capacity_tracker.get(v_id, 0) + 1

    def _get_venue_capacity(self, venue) -> int:
        """Get the total capacity of a venue from configuration or default attributes."""
        # fixed_capacity overrides everything
        allocation_config = self.config.get("allocation", {})
        fixed = allocation_config.get("fixed_capacity")
        if fixed is not None:
            return fixed

        # Check for specific capacity column in venue object (attributes or properties)
        col = allocation_config.get("capacity_column")
        capacity = None

        if col:
            if hasattr(venue, col):
                capacity = getattr(venue, col)
            elif hasattr(venue, "properties") and col in venue.properties:
                capacity = venue.properties[col]

        # Handle missing capacity based on config
        capacity_handling = allocation_config.get("capacity_handling", {})
        if capacity is None or pd.isna(capacity):
            if_missing = capacity_handling.get("if_missing", "ignore")
            if if_missing == "ignore":
                return 1_000_000  # Effective unlimited
            elif if_missing == "default":
                return capacity_handling.get("default_capacity", 1000)
            return 0

        # Handle zero capacity based on config
        if int(capacity) == 0:
            if_zero = capacity_handling.get("if_zero", "skip")
            if if_zero == "ignore":
                return 1_000_000  # Effective unlimited
            return 0

        return int(capacity)

    def _get_remaining_capacity(self, venue) -> int:
        """Get the remaining capacity of a venue."""
        v_id = id(venue)
        current = (
            self.venue_capacity_tracker.get(v_id, 0)
            if hasattr(self, "venue_capacity_tracker")
            else 0
        )
        capacity = self._get_venue_capacity(venue)
        return max(0, capacity - current)

    def _filter_venues_by_capacity(self, venues: List) -> List:
        """Filter venues that still have remaining capacity."""
        allocation_config = self.config.get("allocation", {})

        # Check if capacity tracking is actually enabled
        if not allocation_config.get("track_capacity", True):
            return venues

        when_full = allocation_config.get("when_full", "exclude")
        if when_full == "overflow":
            return venues

        available = []
        for v in venues:
            if self._get_remaining_capacity(v) > 0:
                available.append(v)
        return available
