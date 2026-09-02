import logging
import numpy as np
from typing import List, Dict, Any
from .probability import ProbabilityConfigError, probability_cache_key
from may.utils.attribute_access import _compile_attribute, get_attribute

logger = logging.getLogger(__name__)


class _FilteringMixin:
    def apply_global_filters(self, people: List) -> List:
        """
        Apply global filters and exclusions to a list of people.
        Vectorized where possible if people list is large.
        """
        # vectorized path
        if (
            hasattr(self.owner, "population_arrays")
            and self.owner.population_arrays
            and len(people) > 1000
            and self.owner._can_vectorize_filters(self.owner._pre_processed_filters)
        ):

            indices = []
            pid_to_idx = self.owner.person_id_to_index
            for p in people:
                idx = pid_to_idx.get(p.id)
                if idx is not None:
                    indices.append(idx)

            if len(indices) == len(people):
                indices_arr = np.array(indices, dtype=np.int32)
                filtered_indices = self.owner._apply_filters_vectorized(
                    indices_arr, self.owner._pre_processed_filters
                )
                survivors = self.owner.population_arrays["people"][
                    filtered_indices
                ].tolist()

                # Exclusions depend on residence.properties (e.g. household
                # original_pattern), so apply them scalar-ly to the
                # already-filtered survivors.
                pre_processed_exclude = getattr(
                    self.owner, "_pre_processed_exclude", {}
                )
                if pre_processed_exclude:
                    survivors = [
                        p
                        for p in survivors
                        if not self.person_excluded(p, pre_processed_exclude)
                    ]
                return survivors

        # Scalar fallback
        eligible = []
        filtered_by_global = 0
        filtered_by_exclusions = 0

        pre_processed_filters = getattr(self.owner, "_pre_processed_filters", [])
        pre_processed_exclude = getattr(self.owner, "_pre_processed_exclude", {})

        # Pre-cache getters for performance
        if pre_processed_filters and "getter" not in pre_processed_filters[0]:
            for f in pre_processed_filters:
                f["getter"] = _compile_attribute(f["attribute"])

        for person in people:
            match = True
            for f in pre_processed_filters:
                val = f["getter"](person)
                if val is None or not self._check_condition(val, f):
                    match = False
                    break

            if not match:
                filtered_by_global += 1
                continue

            if pre_processed_exclude and self.person_excluded(
                person, pre_processed_exclude
            ):
                filtered_by_exclusions += 1
                continue

            eligible.append(person)

        if self.verbose:
            logger.info(
                f"Global filters: {filtered_by_global} filtered by global rules, "
                f"{filtered_by_exclusions} filtered by exclusions, {len(eligible)} eligible"
            )

        return eligible

    def person_matches_filters(self, person, filters: List[Dict]) -> bool:
        """Check if person matches all filters in a group."""
        if not filters:
            return True

        is_pre_processed = "is_nested" in filters[0]

        if is_pre_processed:
            for filter_rule in filters:
                person_value = self._get_person_value_preprocessed(person, filter_rule)
                if person_value is None:
                    return False

                if not self._check_condition(person_value, filter_rule):
                    return False
            return True
        else:
            # Fallback for raw filters
            for filter_rule in filters:
                attr_name = filter_rule.get("attribute")
                person_value = self._get_person_value_raw(person, attr_name)
                if person_value is None:
                    return False

                if not self._check_condition(person_value, filter_rule):
                    return False
            return True

    def _get_person_value_preprocessed(self, person, filter_rule: Dict) -> Any:
        """Get value using pre-processed filter rule information."""
        # Check for direct attributes for speed
        attr = filter_rule["attribute"]
        if attr == "age":
            return person.age
        if attr == "sex":
            return person.sex
        return get_attribute(person, attr)

    def _get_person_value_raw(self, person, attr_name: str) -> Any:
        """Fallback for raw filters without pre-processing."""
        return get_attribute(person, attr_name)

    def _check_condition(self, person_value, filter_rule: Dict) -> bool:
        filter_type = filter_rule.get("type", "numerical")
        if filter_type == "numerical":
            min_val = filter_rule.get("min")
            max_val = filter_rule.get("max")
            if min_val is not None and person_value < min_val:
                return False
            if max_val is not None and person_value > max_val:
                return False
        elif filter_type == "categorical":
            val = filter_rule.get("value")
            vals = filter_rule.get("values")
            if val is not None and person_value != val:
                return False
            if vals is not None and person_value not in vals:
                return False
        return True

    def person_excluded(self, person, exclude_config: dict) -> bool:
        """Check if person should be excluded based on exclusion rules."""
        household_exclusions = exclude_config.get("households", {})
        if household_exclusions:
            res_venue = person.residence
            if res_venue is None or res_venue.type != "household":
                return False

            for property_name, exclude_value in household_exclusions.items():
                if hasattr(res_venue, "properties") and isinstance(
                    res_venue.properties, dict
                ):
                    actual_value = res_venue.properties.get(property_name)
                    if actual_value == exclude_value:
                        if self.verbose:
                            logger.debug(
                                f"Person {person.id} excluded: household.{property_name} == '{actual_value}'"
                            )
                        return True
        return False

    def apply_probability_filter(
        self, people: List, prob_config, group_name: str
    ) -> List:
        """Apply probability filtering to a list of people."""
        if not prob_config:
            return people

        if isinstance(prob_config, (int, float)):
            probability = float(prob_config)
            return [p for p in people if np.random.random() < probability]

        if prob_config.get("type") == "file":
            lookup_attr = prob_config.get("lookup_attribute", "geographical_unit.name")

            cache_key = probability_cache_key(prob_config)
            cached_data = getattr(self.owner, "probability_cache", {}).get(cache_key)

            if not cached_data:
                raise ProbabilityConfigError(
                    f"Group '{group_name}': no probabilities cached for {cache_key}. "
                    f"The file was never loaded — check probability_config."
                )

            prob_lookup = cached_data["lookup"]

            selected = []
            for person in people:
                lookup_value = get_attribute(
                    person, lookup_attr, nested_properties=False
                )
                if lookup_value not in prob_lookup:
                    raise ProbabilityConfigError(
                        f"Group '{group_name}': no probability for "
                        f"{lookup_attr}={lookup_value!r}."
                    )
                if np.random.random() < prob_lookup[lookup_value]:
                    selected.append(person)
            return selected

        return people
