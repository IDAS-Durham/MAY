import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class VenueMatcher:
    """
    Manages venue-side matching logic, including attribute checks,
    spatial expansion, and selection strategies.
    """

    def __init__(self, distributor):
        self.distributor = distributor
        self.config = distributor.config
        self.verbose = distributor.verbose
        
        # Attribute caches and indices
        self.venue_attribute_cache = {}
        self.categorical_index = {}
        self.num_constraints = {}
        self.numerical_match_rules = []
        self.categorical_match_rules = []
        self.attribute_index_built = False

    def build_attribute_index(self, venues: List):
        """
        Pre-process venue attributes for fast filtering (Optimized).
        """
        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        # Reset and initialize basic indices
        self.venue_attribute_cache = {}
        self.categorical_index = {}
        self.num_constraints = {}
        self.venue_id_to_idx = {id(v): i for i, v in enumerate(venues)}

        if not attributes:
            self.attribute_index_built = True
            return

        # Pre-filter rules to those that actually have venue components
        active_rules = []
        for rule in attributes:
            attr_name = rule.get('name')
            attr_type = rule.get('type')
            
            if attr_type == 'numerical' and rule.get('venue_constraints'):
                v_con = rule.get('venue_constraints')
                active_rules.append({
                    'name': attr_name,
                    'type': 'numerical',
                    'min_col': v_con.get('min_column'),
                    'max_col': v_con.get('max_column')
                })
                # Initialize arrays for this numerical attribute
                self.num_constraints[attr_name] = {
                    'min': np.full(len(venues), -1000, dtype=np.int16),
                    'max': np.full(len(venues), 1000, dtype=np.int16)
                }
            elif attr_type == 'categorical' and rule.get('venue_column'):
                active_rules.append({
                    'name': attr_name,
                    'type': 'categorical',
                    'col': rule.get('venue_column'),
                    'assume': rule.get('assume_if_missing', 'Mixed'),
                    'case_sensitive': rule.get('case_sensitive', False),
                    'rules': rule.get('matching_rules', {})
                })

        if not active_rules:
            self.attribute_index_built = True
            return

        # Pre-process matching rules for categorical (avoiding repeated work)
        for rule in active_rules:
            if rule['type'] == 'categorical' and not rule['case_sensitive']:
                rule['rules'] = {k.lower(): [v.lower() for v in vals] for k, vals in rule['rules'].items()}

        # Single pass over venues
        for i, venue in enumerate(venues):
            v_props = venue.properties
            v_id = id(venue)
            
            for rule in active_rules:
                attr_name = rule['name']
                
                if rule['type'] == 'numerical':
                    min_val = v_props.get(rule['min_col']) if rule['min_col'] else None
                    max_val = v_props.get(rule['max_col']) if rule['max_col'] else None
                    
                    if min_val is not None and min_val != '':
                        self.num_constraints[attr_name]['min'][i] = int(float(min_val))
                    if max_val is not None and max_val != '':
                        self.num_constraints[attr_name]['max'][i] = int(float(max_val))

                else: # categorical
                    v_val = v_props.get(rule['col'])
                    if v_val is None or v_val == '':
                        v_val = rule['assume']
                    
                    if not rule['case_sensitive']:
                        v_val = str(v_val).lower() if v_val else ''
                    
                    allowed = rule['rules'].get(v_val)
                    if allowed:
                        for p_val in allowed:
                            index_key = (attr_name, p_val)
                            if index_key not in self.categorical_index:
                                self.categorical_index[index_key] = set()
                            self.categorical_index[index_key].add(v_id)

        self.numerical_match_rules = [r for r in active_rules if r['type'] == 'numerical']
        self.categorical_match_rules = [r for r in active_rules if r['type'] == 'categorical' and not r.get('venue_column')]
        
        self.attribute_index_built = True
        
        if self.verbose:
            logger.info(f"Built attribute index for {len(venues)} venues with {len(attributes)} attributes")
            if self.categorical_index:
                logger.info(f"Built categorical index: {len(self.categorical_index)} unique value combinations")

    def filter_venues_with_expansion(self, person, venues: List, initial_pool: List, 
                                   location: Tuple[float, float], search_limits: List[int], 
                                   person_attrs: Optional[Dict] = None) -> List:
        """
        Filter venues for a person. Restores 'strict' behavior from baseline.
        """
        # Tier 1: Try the initial pool (Fast path - matches old strict behavior)
        eligible = self.filter_venues_by_person(person, initial_pool, person_attrs=person_attrs)
        if eligible:
            return eligible
            
        # Expansion Tiers: Only triggered if explicitly configured and initial failed
        # Performance Trade-off: We prefer skipping people over massive spatial searches.
        if self.config.get('venue_selection', {}).get('consider_by') == 'count':
            # Strict mode: If only one search limit or no limits, don't expand
            if len(search_limits) <= 1:
                return []

            for search_count in search_limits:
                # Skip if already tried this many or fewer
                if search_count <= len(initial_pool):
                    continue
                
                # RESTRAIN EXPANSION: Max 100 venues for performance
                # The old code queried max 50-100. Checking 10,000 is too slow.
                limit = min(search_count, 100) 
                
                if self.verbose:
                    logger.debug(f"Expanding search for person {person.id} to k={limit}")
                
                expanded_pool = self.distributor._find_closest_venues(
                    location, self.distributor.venue_type, limit, 
                    allowed_venue_ids=getattr(self.distributor, 'venue_ids', None)
                )
                eligible = self.filter_venues_by_person(person, expanded_pool, person_attrs=person_attrs)
                
                if eligible:
                    return eligible
                    
                # If we've reached the safety cap, stop expanding
                if limit >= 100:
                    break
                    
        return []

    def filter_venues_by_person(self, person, venues: List, person_attrs: Optional[Dict] = None) -> List:
        """Filter venues based on person's attributes (age, gender, etc.)."""
        match_attrs = getattr(self.distributor, '_pre_processed_match_attrs', [])
        
        # Pre-fetch attributes for this person to avoid repeated slow lookups
        if person_attrs is None:
            person_attrs = {}
            for rule in match_attrs:
                attr = rule['attribute']
                if attr not in person_attrs:
                    if rule.get('is_residence'):
                        res = person.residence
                        val = self.distributor._get_nested_value_with_dict_support(res, rule['residence_parts']) if res else None
                    elif rule.get('is_nested'):
                        val = self.distributor._get_nested_value_with_dict_support(person, rule['path_parts'])
                    else:
                        # Direct attribute
                        val = getattr(person, attr, None)
                    person_attrs[attr] = val

        # Step 1: Pre-filter using categorical index
        venues = self.prefilter_venues_by_categorical(person, venues, person_attrs=person_attrs)
        if not venues:
            return []

        # Step 2: Filter remaining venues by other attributes
        eligible_venues = []
        for venue in venues:
            if self.venue_accepts_person(person, venue, match_attrs, person_attrs=person_attrs):
                eligible_venues.append(venue)

        return eligible_venues

    def venue_accepts_person(self, person, venue, attribute_rules: List[Dict], person_attrs: Optional[Dict] = None) -> bool:
        """Check if venue accepts person based on attribute rules using pre-computed arrays (Optimized)."""
        v_id = id(venue)
        v_idx = self.venue_id_to_idx.get(v_id)
        
        if v_idx is None:
            return self.venue_accepts_person_slow(person, venue, attribute_rules)

        # Optimization: Separate loops and pre-defined lists avoid dictionary lookups on 'rule'
        for rule in self.numerical_match_rules:
            attr_name = rule['name']
            if attr_name in self.num_constraints:
                person_value = self._get_person_attr(person, attr_name, person_attrs)
                if person_value is None:
                    return False
                
                constraints = self.num_constraints[attr_name]
                # Direct array access is much faster than dict lookup
                v_min = constraints['min'][v_idx]
                if v_min != -1000 and person_value < v_min:
                    return False
                    
                v_max = constraints['max'][v_idx]
                if v_max != 1000 and person_value > v_max:
                    return False

        # Categorical rules with venue_column are handled via prefilter_venues_by_categorical
        # We only check those without a venue_column (rare but possible)
        for rule in self.categorical_match_rules:
            # Implement categorical check here if needed (not common in hot path)
            pass
                
        return True

    def venue_accepts_person_slow(self, person, venue, attribute_rules: List[Dict]) -> bool:
        """Fallback for venues without cache."""
        for rule in attribute_rules:
            attr_name = rule.get('name')
            person_value = self.distributor._get_person_attribute(attr_name, person)
            if person_value is None: return False

            if rule.get('type') == 'numerical':
                if not self._check_numerical_constraint(person_value, venue, rule): return False
            elif rule.get('type') == 'categorical':
                if not self._check_categorical_constraint(person_value, venue, rule): return False
        return True

    def prefilter_venues_by_categorical(self, person, venues: List, person_attrs: Optional[Dict] = None) -> List:
        """Pre-filter venues using categorical index for massive speedup."""
        if not self.categorical_index:
            return venues

        eligibility = self.config.get('eligibility', {})
        attributes = eligibility.get('attributes', [])

        categorical_filters = []
        for rule in attributes:
            if rule.get('type') == 'categorical' and rule.get('venue_column'):
                attr_name = rule.get('name')
                val = self._get_person_attr(person, attr_name, person_attrs)
                if val is not None:
                    if not rule.get('case_sensitive', False):
                        val = str(val).lower() if val else ''
                    categorical_filters.append((attr_name, val))

        if not categorical_filters:
            return venues

        attr_name, val = categorical_filters[0]
        filtered_ids = self.categorical_index.get((attr_name, val), set())

        if len(categorical_filters) > 1:
            filtered_ids = filtered_ids.copy()
            for attr_name, val in categorical_filters[1:]:
                filtered_ids &= self.categorical_index.get((attr_name, val), set())

        return [v for v in venues if id(v) in filtered_ids]

    def select_venue(self, person, venues: List, person_location: Tuple[float, float]) -> Optional[Any]:
        """Select final venue from eligible list based on strategy."""
        if not venues: return None

        strategy = self.config.get('allocation', {}).get('strategy', 'random')
        if strategy == 'random':
            return np.random.choice(venues)
        elif strategy == 'closest':
            valid_venues = [v for v in venues if v.coordinates]
            if not valid_venues: return venues[0]
            
            # Optimization: Use scalar math for small sets, vectorized for large sets
            if len(valid_venues) < 50:
                return min(valid_venues, key=lambda v: self.distributor._haversine_distance(person_location, v.coordinates))
            else:
                coords = np.array([v.coordinates for v in valid_venues])
                dists = self.distributor._haversine_distance_vectorized(person_location, coords)
                return valid_venues[np.argmin(dists)]
        elif strategy == 'proportional':
            valid = [v for v in venues if v.coordinates]
            if not valid: return venues[0]
            
            # Optimization: Use scalar math for small sets, vectorized for large sets
            if len(valid) < 50:
                dists = [self.distributor._haversine_distance(person_location, v.coordinates) for v in valid]
            else:
                coords = np.array([v.coordinates for v in valid])
                dists = self.distributor._haversine_distance_vectorized(person_location, coords)
                
            weights = np.array([1.0 / (d + 0.1) for d in dists])
            return np.random.choice(valid, p=weights / weights.sum())
        elif strategy == 'largest_capacity':
            return max(venues, key=lambda v: self.distributor._get_venue_capacity(v))

        return venues[0]

    def find_eligible_venues_for_location(self, location: Tuple[float, float], venues: List) -> List:
        """Find candidate venues based on distance/count config."""
        selection = self.config.get('venue_selection', {})
        consider_by = selection.get('consider_by', 'count')

        if consider_by == 'count':
            count = selection.get('count', 5)
            if selection.get('criteria') == 'largest_capacity':
                # Query a larger pool first to find large ones nearby
                closest_pool = self.distributor._find_closest_venues(location, self.distributor.venue_type, max(count * 5, 20), allowed_venue_ids=getattr(self.distributor, 'venue_ids', None))
                return sorted(closest_pool, key=lambda v: self.distributor._get_venue_capacity(v), reverse=True)[:count]
            return self.distributor._find_closest_venues(location, self.distributor.venue_type, count, allowed_venue_ids=getattr(self.distributor, 'venue_ids', None))

        elif consider_by == 'distance':
            max_dist = selection.get('max_distance', 10)
            unit = selection.get('max_distance_unit', 'km')
            if unit == 'miles': max_dist *= 1.60934
            elif unit == 'meters': max_dist /= 1000

            eligible = []
            valid = [v for v in venues if v.coordinates]
            if valid:
                coords = np.array([v.coordinates for v in valid])
                dists = self.distributor._haversine_distance_vectorized(location, coords)
                eligible = [v for v, d in zip(valid, dists) if d <= max_dist]
            else:
                eligible = []
            
            if selection.get('criteria') == 'largest_capacity':
                eligible.sort(key=lambda v: self.distributor._get_venue_capacity(v), reverse=True)
            return eligible

        return venues

    def _get_person_attr(self, person, attr_name: str, person_attrs: Optional[Dict]) -> Any:
        """
        Get person attribute using the distributor's lookup method.
        """
        if person_attrs and attr_name in person_attrs:
            return person_attrs[attr_name]

        return self.distributor._get_person_attribute(attr_name, person)

    def _check_numerical_constraint(self, val, venue, rule: Dict) -> bool:
        constraints = rule.get('venue_constraints', {})
        min_v = venue.properties.get(constraints.get('min_column')) if constraints.get('min_column') else None
        max_v = venue.properties.get(constraints.get('max_column')) if constraints.get('max_column') else None
        if min_v is not None and val < min_v: return False
        if max_v is not None and val > max_v: return False
        return True

    def _check_categorical_constraint(self, val, venue, rule: Dict) -> bool:
        col = rule.get('venue_column')
        if not col: return True
        v_val = venue.properties.get(col, rule.get('assume_if_missing', 'Mixed'))
        matching = rule.get('matching_rules', {})
        if not rule.get('case_sensitive', False):
            v_val = str(v_val).lower()
            val = str(val).lower()
            matching = {k.lower(): [v.lower() for v in vals] for k, vals in matching.items()}
        return val in matching.get(v_val, []) if v_val in matching else True
