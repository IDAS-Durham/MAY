import logging
from typing import List, Dict

logger = logging.getLogger(__name__)
FALLBACK_STRATEGIES = {'skip', 'relax_distance', 'relax_capacity', 'assign_closest'}

class _FallbackMixin:
        def handle_fallbacks(self, unallocated_people: List, venues: List, world) -> List:
            """Handle people who couldn't be allocated during the normal pass."""
            fallback_config = self.config.get('fallback', {})
            strategy = fallback_config.get('strategy', 'skip')
            
            if strategy == 'skip' or not unallocated_people:
                return unallocated_people
                
            logger.debug(f"Handling fallbacks for {len(unallocated_people)} people using strategy '{strategy}'")
            
            if strategy == 'relax_distance':
                return self._relax_distance(unallocated_people, venues, fallback_config)
            elif strategy == 'relax_capacity':
                return self._relax_capacity(unallocated_people, venues)
            elif strategy == 'assign_closest':
                return self._assign_closest(unallocated_people, venues)
            else:
                raise ValueError(
                    f"Unknown fallback.strategy {strategy!r}; expected one of "
                    f"{sorted(FALLBACK_STRATEGIES)}."
                )

        def _relax_distance(self, people: List, venues: List, config: Dict) -> List:
            """Retry allocation with progressively relaxed distance constraints."""
            relax_params = config.get('relax_params', {})
            multiplier = relax_params.get('distance_multiplier', 2.0)
            max_iters = relax_params.get('max_iterations', 3)
            
            remaining = list(people)
            selection_config = self.config.get('venue_selection', {})
            original_max_dist = selection_config.get('max_distance')
            original_count = selection_config.get('count')
            
            try:
                for i in range(max_iters):
                    if not remaining: break

                    scale = multiplier ** (i + 1)
                    if original_max_dist is not None:
                        selection_config['max_distance'] = original_max_dist * scale
                    if original_count is not None:
                        selection_config['count'] = int(original_count * scale)

                    logger.info(f"  Relaxation iteration {i+1}/{max_iters} (distance x{scale:.1f})...")
                    remaining = self.allocate_individual(remaining, venues)
            finally:
                if original_max_dist is not None:
                    selection_config['max_distance'] = original_max_dist
                if original_count is not None:
                    selection_config['count'] = original_count
                
            return remaining

        def _relax_capacity(self, people: List, venues: List) -> List:
            """Retry allocation while ignoring capacity limits."""
            original_when_full = self.config.get('allocation', {}).get('when_full', 'exclude')
            self.config.setdefault('allocation', {})['when_full'] = 'overflow'
            
            try:
                logger.info("  Relaxing capacity constraints...")
                remaining = self.allocate_individual(people, venues)
            finally:
                self.config['allocation']['when_full'] = original_when_full
                
            return remaining

        def _assign_closest(self, people: List, venues: List) -> List:
            """Assign each person to their absolute closest venue, ignoring ALL other constraints."""
            allocated_count = 0
            remaining = []
            logger.debug("  Assigning to closest venue regardless of eligibility or capacity...")

            for person in people:
                location = self.owner._get_person_location(person)
                if location:
                    closest = self.owner._find_closest_venues(location, self.owner.venue_type, 1)
                    if closest:
                        venue = closest[0]
                        venue.add_to_subset(
                            person,
                            subset_key=self.owner.subset_key,
                            activity_name=self.owner.activity_map_key,
                            activity_type=self.owner.activity_type
                        )
                        self.owner._increment_venue_count(venue)
                        allocated_count += 1
                    else:
                        logger.warning(f"Could not find ANY venue for person {person.id} in assign_closest fallback")
                        remaining.append(person)
                else:
                    remaining.append(person)

            self.owner.allocated_this_run += allocated_count
            logger.info(f"  Fallback (assign_closest): {allocated_count}/{len(people)} placed")

            return remaining
