import logging
import numpy as np
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class FilteringManager:
    """
    Manages person-to-venue matching and filtering logic.
    Decouples filtering rules from the main distributor.
    """

    def __init__(self, distributor):
        self.distributor = distributor
        self.config = distributor.config
        self.verbose = distributor.verbose

    def apply_global_filters(self, people: List) -> List:
        """
        Apply global filters and exclusions to a list of people.
        Vectorized where possible if people list is large.
        """
        # vectorized path
        if (hasattr(self.distributor, 'population_arrays') and 
            self.distributor.population_arrays and 
            len(people) > 1000 and 
            self.distributor._can_vectorize_filters(self.distributor._pre_processed_filters)):
            
            indices = []
            pid_to_idx = self.distributor.person_id_to_index
            for p in people:
                idx = pid_to_idx.get(p.id)
                if idx is not None:
                    indices.append(idx)
            
            if len(indices) == len(people):
                indices_arr = np.array(indices, dtype=np.int32)
                filtered_indices = self.distributor._apply_filters_vectorized(
                    indices_arr, self.distributor._pre_processed_filters
                )
                return self.distributor.population_arrays['people'][filtered_indices].tolist()
        
        # Scalar fallback
        eligible = []
        filtered_by_global = 0
        filtered_by_exclusions = 0

        pre_processed_filters = getattr(self.distributor, '_pre_processed_filters', [])
        pre_processed_exclude = getattr(self.distributor, '_pre_processed_exclude', {})
        
        # Pre-cache getters for performance
        if pre_processed_filters and 'getter' not in pre_processed_filters[0]:
            for f in pre_processed_filters:
                f['getter'] = self.distributor._create_path_getter(f['path_parts'])

        for person in people:
            match = True
            for f in pre_processed_filters:
                val = f['getter'](person)
                if val is None or not self._check_condition(val, f):
                    match = False
                    break
            
            if not match:
                filtered_by_global += 1
                continue
            
            if pre_processed_exclude and self.person_excluded(person, pre_processed_exclude):
                filtered_by_exclusions += 1
                continue
            
            eligible.append(person)

        if self.verbose:
            logger.info(f"Global filters: {filtered_by_global} filtered by global rules, "
                        f"{filtered_by_exclusions} filtered by exclusions, {len(eligible)} eligible")

        return eligible

    def person_matches_filters(self, person, filters: List[Dict]) -> bool:
        """Check if person matches all filters in a group."""
        if not filters:
            return True

        is_pre_processed = 'is_nested' in filters[0]
        
        if is_pre_processed:
            for filter_rule in filters:
                person_value = self._get_person_value_optimized(person, filter_rule)
                if person_value is None: return False

                if not self._check_condition(person_value, filter_rule):
                    return False
            return True
        else:
            # Fallback for raw filters
            for filter_rule in filters:
                attr_name = filter_rule.get('attribute')
                person_value = self._get_person_value_raw(person, attr_name)
                if person_value is None: return False

                if not self._check_condition(person_value, filter_rule):
                    return False
            return True

    def _get_person_value_optimized(self, person, filter_rule: Dict) -> Any:
        """Get value using pre-processed filter rule information."""
        if filter_rule.get('is_residence'):
            res = person.residence
            if res is None: return None
            return self.distributor._get_nested_value_with_dict_support(res, filter_rule['residence_parts'])
        
        # Check for direct attributes for speed
        attr = filter_rule['attribute']
        if attr == 'age': return person.age
        if attr == 'sex': return person.sex
        
        return self.distributor._get_nested_value_with_dict_support(person, filter_rule['path_parts'])

    def _get_person_value_raw(self, person, attr_name: str) -> Any:
        """Fallback for raw filters without pre-processing."""
        return self.distributor._get_person_attribute(attr_name, person)

    def _check_condition(self, person_value, filter_rule: Dict) -> bool:
        filter_type = filter_rule.get('type', 'numerical')
        if filter_type == 'numerical':
            min_val = filter_rule.get('min')
            max_val = filter_rule.get('max')
            if min_val is not None and person_value < min_val: return False
            if max_val is not None and person_value > max_val: return False
        elif filter_type == 'categorical':
            val = filter_rule.get('value')
            vals = filter_rule.get('values')
            if val is not None and person_value != val: return False
            if vals is not None and person_value not in vals: return False
        return True

    def person_excluded(self, person, exclude_config: dict) -> bool:
        """Check if person should be excluded based on exclusion rules."""
        household_exclusions = exclude_config.get('households', {})
        if household_exclusions:
            res_venue = person.residence
            if res_venue is None or res_venue.type != 'household':
                return False

            for property_name, exclude_value in household_exclusions.items():
                if hasattr(res_venue, 'properties') and isinstance(res_venue.properties, dict):
                    actual_value = res_venue.properties.get(property_name)
                    if actual_value == exclude_value:
                        if self.verbose:
                            logger.debug(f"Person {person.id} excluded: household.{property_name} == '{actual_value}'")
                        return True
        return False

    def apply_probability_filter(self, people: List, prob_config, group_name: str) -> List:
        """Apply probability filtering to a list of people."""
        if not prob_config:
            return people

        if isinstance(prob_config, (int, float)):
            probability = float(prob_config)
            return [p for p in people if np.random.random() < probability]

        if prob_config.get('type') == 'file':
            file_path = prob_config.get('file_path')
            prob_col = prob_config.get('probability_column')
            lookup_attr = prob_config.get('lookup_attribute', 'geographical_unit.name')
            
            cache_key = (file_path, prob_col)
            cached_data = getattr(self.distributor, 'probability_cache', {}).get(cache_key)

            if not cached_data:
                logger.warning(f"Group '{group_name}': No cached probabilities for {cache_key}")
                default_prob = prob_config.get('default', 0.0)
                return [p for p in people if np.random.random() < default_prob]

            prob_lookup = cached_data['lookup']
            default_prob = cached_data['default']

            selected = []
            for person in people:
                lookup_value = self.distributor._get_person_attribute(lookup_attr, person)
                probability = prob_lookup.get(lookup_value, default_prob) if lookup_value is not None else default_prob
                if np.random.random() < probability:
                    selected.append(person)
            return selected

        return people
