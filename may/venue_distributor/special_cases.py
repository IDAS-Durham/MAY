import logging
import numpy as np
from typing import List, Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)

class SpecialCaseManager:
    """
    Handles special case allocations (e.g., boarding schools).
    These are processed before normal allocation.
    """

    def __init__(self, distributor):
        self.distributor = distributor
        self.config = distributor.config
        self.verbose = distributor.verbose

    def handle_special_cases(self, people: List, venues: List, world) -> Tuple[List, List]:
        """
        Handle special case allocations.
        Returns Tuple of (remaining_people, unallocated_special_case_people).
        """
        special_cases = self.config.get('special_cases', [])
        if not special_cases:
            return people, []

        # Build venue index for fast lookup
        venue_index = {}
        for venue in venues:
            if hasattr(venue, 'name') and hasattr(venue, 'geographical_unit') and venue.geographical_unit:
                key = (venue.name, venue.geographical_unit.name)
                venue_index[key] = venue

        if venue_index and self.verbose:
            logger.debug(f"Built special case venue index with {len(venue_index)} entries")

        remaining_people = []
        unallocated_special_case_people = []
        allocated_count = 0

        for person in people:
            matched_any = False
            allocated = False

            for case in special_cases:
                if self.matches_special_case(person, case):
                    matched_any = True
                    if self.allocate_special_case(person, case, venues, venue_index):
                        allocated = True
                        allocated_count += 1
                        break

            if not matched_any:
                remaining_people.append(person)
            elif not allocated:
                unallocated_special_case_people.append(person)

        if allocated_count > 0:
            logger.info(f"Allocated {allocated_count} people via special cases")
            self.distributor.allocated_this_run += allocated_count

        return remaining_people, unallocated_special_case_people

    def matches_special_case(self, person, case: Dict) -> bool:
        """Check if person matches special case condition."""
        condition = case.get('condition', {})

        if 'person_residence_type' in condition:
            required_type = condition['person_residence_type']
            res_venue = person.residence
            if res_venue is None or not hasattr(res_venue, 'type') or res_venue.type != required_type:
                return False

        if 'filters' in condition:
            filters = condition['filters']
            if not self.distributor.filtering.person_matches_filters(person, filters):
                return False

        return True

    def allocate_special_case(self, person, case: Dict, venues: List, venue_index: Dict = None) -> bool:
        """Allocate person according to special case rule."""
        rule = case.get('allocation_rule', {})
        strategy = rule.get('strategy')
        match_by = rule.get('match_by', [])

        selected_venue = None

        if strategy:
            geo_unit = self.distributor._get_geo_unit_at_level(person, self.distributor.world)
            if geo_unit and geo_unit.coordinates:
                loc = geo_unit.coordinates
                if strategy == 'closest':
                    min_dist = float('inf')
                    for venue in venues:
                        if venue.coordinates and len(venue.coordinates) == 2:
                            dist = self.distributor._haversine_distance(loc, venue.coordinates)
                            if dist < min_dist:
                                min_dist = dist
                                selected_venue = venue
                elif strategy == 'random' and venues:
                    selected_venue = np.random.choice(venues)

        elif match_by and venue_index:
            lookup_key = self._extract_lookup_key(person, match_by)
            if lookup_key:
                selected_venue = venue_index.get(lookup_key)
            
            if not selected_venue:
                selected_venue = self._fallback_search(person, venues, match_by)

        elif match_by:
            selected_venue = self._fallback_search(person, venues, match_by)

        if selected_venue:
            selected_venue.add_to_subset(
                person, 
                subset_key=self.distributor.subset_key, 
                activity_name=self.distributor.activity_map_key, 
                activity_type=self.distributor.activity_type
            )
            self.distributor._increment_venue_count(selected_venue)
            return True

        res_name = self.distributor._get_person_attribute('residence.name', person)
        if_no_match = rule.get('if_no_match', 'error')
        if if_no_match == 'error':
            raise ValueError(f"Special case allocation failed for person {person.id} with residence '{res_name}'")
        elif if_no_match == 'warn':
            logger.warning(f"Special case: No match found for person {person.id} with residence '{res_name}'")

        return False

    def _extract_lookup_key(self, person, match_by: List[Dict]) -> Optional[Tuple]:
        try:
            parts = []
            for criterion in match_by:
                source = criterion.get('source', '')
                if source.startswith('person.'):
                    val = self.distributor._get_person_attribute(source.replace('person.', ''), person)
                    if val is None: return None
                    parts.append(val)
            return tuple(parts) if parts else None
        except Exception:
            return None

    def _fallback_search(self, person, venues: List, match_by: List[Dict]):
        for venue in venues:
            if self._venue_matches_criteria(person, venue, match_by):
                return venue
        return None

    def _venue_matches_criteria(self, person, venue, match_by: List[Dict]) -> bool:
        for criterion in match_by:
            source = criterion.get('source')
            target = criterion.get('target')
            match_type = criterion.get('match_type', 'exact')

            src_val = self.distributor._get_person_attribute(source.replace('person.', ''), person)
            tgt_val = self.distributor._get_nested_value(venue, target.replace('venue.', ''))

            if match_type == 'exact' and src_val != tgt_val:
                return False
        return True
