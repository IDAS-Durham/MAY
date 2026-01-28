import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)

class AllocationEngine:
    """
    Orchestrates the distribution process, including batching and individual allocation.
    """

    def __init__(self, distributor):
        self.distributor = distributor
        self.config = distributor.config
        self.verbose = distributor.verbose

        # Pre-process attribute metadata for fast lookups (Global for this distributor)
        eligibility = self.config.get('eligibility', {})
        self.attribute_names = [rule.get('name') for rule in eligibility.get('attributes', [])]
        
        self.attr_getters = []
        for name in self.attribute_names:
            if name == 'age':
                self.attr_getters.append(lambda p: p.age)
            elif name == 'sex':
                self.attr_getters.append(lambda p: p.sex)
            elif name == 'residence.type':
                self.attr_getters.append(lambda p: p.residence_type)
            else:
                # General nested path
                parts = name.split('.')
                self.attr_getters.append(self.distributor._create_path_getter(parts))

    def allocate_group(self, people: List, venues: List, allow_overflow: bool = False, group_search_limits=None) -> int:
        """Allocate a specific group of people with geo-unit level caching and attribute batching."""
        allocated_count = 0
        total_people = len(people)
        people_processed = 0
        progress_interval = max(1, total_people // 10)

        selection_config = self.config.get('venue_selection', {})
        target_count = selection_config.get('count', 5)

        # STRICT LIMITS: Follow baseline behavior. Default to target_count * 4 if no limits provided.
        # This avoid expensive None (all venues) searches.
        search_limits = group_search_limits if group_search_limits is not None else selection_config.get('search_limits', [target_count * 4])
        if not search_limits: search_limits = [target_count * 4]
        
        # Clean search limits and remove None/unlimited cases
        clean_limits = []
        for l in search_limits:
            if l is None: continue
            clean_limits.append(min(l, 100)) # Absolute cap at 100 venues for performance
        if not clean_limits: clean_limits = [20]
        
        search_attempts = sorted(set(clean_limits))

        people_by_geo = defaultdict(list)
        for person in people:
            geo = self.distributor._get_geo_unit_at_level(person, self.distributor.world, target_level=self.distributor.batch_geo_level)
            if geo: people_by_geo[geo].append(person)

        for geo_unit, geo_people in people_by_geo.items():
            if not (geo_unit.coordinates and len(geo_unit.coordinates) == 2): continue
            lat, lon = geo_unit.coordinates

            # Find nearby venues once per geo unit
            geo_nearby = self.distributor._find_closest_venues((lat, lon), self.distributor.venue_type, search_attempts[0], allowed_venue_ids=getattr(self.distributor, 'venue_ids', None))
            
            if not allow_overflow and not self.distributor._filter_venues_by_capacity(geo_nearby):
                people_processed += len(geo_people)
                self._log_progress(people_processed, total_people, progress_interval, allocated_count)
                continue

            people_by_attrs = defaultdict(list)
            for person in geo_people:
                vals = tuple(getter(person) for getter in self.attr_getters)
                people_by_attrs[vals].append(person)

            for attr_vals, people_group in people_by_attrs.items():
                person_attrs = dict(zip(self.attribute_names, attr_vals))
                eligible_venues = self.distributor.matcher.filter_venues_with_expansion(
                    person=people_group[0], venues=venues, initial_pool=geo_nearby,
                    location=(lat, lon), search_limits=search_attempts, person_attrs=person_attrs
                )

                if eligible_venues:
                    pool = eligible_venues[:target_count]
                    for person in people_group:
                        venue = None
                        with_cap = self.distributor._filter_venues_by_capacity(pool)
                        if with_cap:
                            venue = self.distributor.matcher.select_venue(person, with_cap, (lat, lon))
                        elif allow_overflow:
                            venue = self.distributor.matcher.select_venue(person, pool, (lat, lon))
                        
                        if venue:
                            venue.add_to_subset(person, subset_key=self.distributor.subset_key, 
                                               activity_name=self.distributor.activity_map_key, activity_type=self.distributor.activity_type)
                            self.distributor._increment_venue_count(venue)
                            allocated_count += 1
                        
                        people_processed += 1
                        self._log_progress(people_processed, total_people, progress_interval, allocated_count)
                else:
                    people_processed += len(people_group)
                    self._log_progress(people_processed, total_people, progress_interval, allocated_count)

        return allocated_count

    def allocate_by_geo_unit(self, people: List, venues: List) -> List:
        """Batch allocation by geo_unit for performance."""
        people_by_geo = defaultdict(list)
        for person in people:
            geo = self.distributor._get_geo_unit_at_level(person, self.distributor.world, target_level=self.distributor.batch_geo_level)
            if geo: people_by_geo[geo].append(person)

        venues_by_geo = defaultdict(list)
        v_level = self.distributor.venue_geo_level
        for v in venues:
            if not v.geographical_unit:
                continue
            
            # Use the ancestor at the correct venue_geo_level for matching
            target_unit = v.geographical_unit
            if target_unit.level != v_level:
                target_unit = target_unit.get_ancestor_by_level(v_level)
            
            if target_unit:
                venues_by_geo[target_unit.name].append(v)
        
        total = len(people)
        processed = 0
        interval = max(1, total // 10)
        allocated = 0
        unallocated = []

        # Cache for venues by (search_unit, attribute_values) to avoid repeated attribute filtering
        # This keeps it correct even if different people in the same SGU have different eligibility
        pool_cache = {}
        
        # Determine strategy once
        strategy = self.config.get('allocation', {}).get('strategy', 'random')
        respect_capacity = self.config.get('venue_selection', {}).get('respect_capacity', True)

        for geo_unit, geo_people in people_by_geo.items():
            venue_search_unit = geo_unit if self.distributor.batch_geo_level == self.distributor.venue_geo_level else geo_unit.get_ancestor_by_level(self.distributor.venue_geo_level)
            if not venue_search_unit:
                unallocated.extend(geo_people)
                processed += len(geo_people)
                self._log_progress(processed, total, interval, allocated, prefix="  ")
                continue

            lat, lon = geo_unit.coordinates if (geo_unit.coordinates and len(geo_unit.coordinates) == 2) else (None, None)
            
            # Group by attributes within the SGU to ensure correctness for cases like schools/multisectors
            people_by_attrs = defaultdict(list)
            for person in geo_people:
                vals = tuple(getter(person) for getter in self.attr_getters)
                people_by_attrs[vals].append(person)

            for attr_vals, group in people_by_attrs.items():
                cache_key = (venue_search_unit.name, attr_vals)
                
                # 1. Get/Cache the pool of venues for this (LGU, attributes) combination
                if cache_key not in pool_cache:
                    eligible_pool = venues_by_geo.get(venue_search_unit.name, []) if self.config.get('venue_selection', {}).get('consider_by') == 'geo_unit' else self.distributor.matcher.find_eligible_venues_for_location((lat, lon), venues)
                    
                    if eligible_pool:
                        p_attrs = dict(zip(self.attribute_names, attr_vals))
                        pool_cache[cache_key] = self.distributor.matcher.filter_venues_by_person(
                            group[0], eligible_pool, person_attrs=p_attrs
                        )
                    else:
                        pool_cache[cache_key] = []
                
                p_venues = pool_cache[cache_key]

                if not p_venues:
                    unallocated.extend(group)
                    processed += len(group)
                    self._log_progress(processed, total, interval, allocated, prefix="  ")
                    continue

                # 2. Optimization: Efficient capacity iteration
                
                # Local available pool for this attribute group in this SGU
                if respect_capacity:
                    available_venues = [v for v in p_venues if self.distributor._get_venue_capacity(v) > 0]
                else:
                    available_venues = list(p_venues)

                if not available_venues:
                    unallocated.extend(group)
                    processed += len(group)
                    self._log_progress(processed, total, interval, allocated, prefix="  ")
                    continue

                if strategy == 'random' and lat is not None:
                    np.random.shuffle(available_venues)
                    venue_ptr = 0
                    
                    for person in group:
                        assigned = False
                        while venue_ptr < len(available_venues):
                            v = available_venues[venue_ptr]
                            if not respect_capacity or self.distributor._get_venue_capacity(v) > 0:
                                v.add_to_subset(person, subset_key=self.distributor.subset_key, 
                                              activity_name=self.distributor.activity_map_key, activity_type=self.distributor.activity_type)
                                self.distributor._increment_venue_count(v)
                                allocated += 1
                                assigned = True
                                if respect_capacity and self.distributor._get_venue_capacity(v) <= 0:
                                    venue_ptr += 1
                                break
                            else:
                                venue_ptr += 1
                                
                        if not assigned:
                            unallocated.append(person)
                            
                elif strategy == 'closest' and lat is not None:
                    available_venues.sort(key=lambda v: self.distributor._haversine_distance((lat, lon), v.coordinates))
                    venue_ptr = 0
                    
                    for person in group:
                        assigned = False
                        while venue_ptr < len(available_venues):
                            v = available_venues[venue_ptr]
                            if not respect_capacity or self.distributor._get_venue_capacity(v) > 0:
                                v.add_to_subset(person, subset_key=self.distributor.subset_key, 
                                              activity_name=self.distributor.activity_map_key, activity_type=self.distributor.activity_type)
                                self.distributor._increment_venue_count(v)
                                allocated += 1
                                assigned = True
                                if respect_capacity and self.distributor._get_venue_capacity(v) <= 0:
                                    venue_ptr += 1
                                break
                            else:
                                venue_ptr += 1
                        if not assigned:
                            unallocated.append(person)
                else:
                    # Fallback for complex strategies or missing coordinates
                    for person in group:
                        with_cap = [v for v in available_venues if not respect_capacity or self.distributor._get_venue_capacity(v) > 0]
                        if with_cap:
                            venue = self.distributor.matcher.select_venue(person, with_cap, (lat, lon) if lat is not None else None)
                            if venue:
                                venue.add_to_subset(person, subset_key=self.distributor.subset_key, 
                                                  activity_name=self.distributor.activity_map_key, activity_type=self.distributor.activity_type)
                                self.distributor._increment_venue_count(venue)
                                allocated += 1
                                continue
                        unallocated.append(person)

                processed += len(group)
                self._log_progress(processed, total, interval, allocated, prefix="  ")

        self.distributor.allocated_this_run += allocated
        return unallocated

    def allocate_individual(self, people: List, venues: List) -> List:
        """Allocate people individually."""
        allocated = 0
        unallocated = []
        total = len(people)
        interval = max(1, total // 10)

        for i, person in enumerate(people, 1):
            loc = self.distributor._get_person_location(person)
            if not loc:
                unallocated.append(person)
                continue

            pool = self.distributor.matcher.find_eligible_venues_for_location(loc, venues)
            # STRICT DEFAULT: Only use first limit or small pool
            search_limits = self.config.get('venue_selection', {}).get('search_limits', [20])
            p_venues = self.distributor.matcher.filter_venues_with_expansion(person, venues, pool, loc, search_limits)

            if p_venues:
                with_cap = self.distributor._filter_venues_by_capacity(p_venues)
                if with_cap:
                    venue = self.distributor.matcher.select_venue(person, with_cap, loc)
                    if venue:
                        venue.add_to_subset(person, subset_key=self.distributor.subset_key, 
                                          activity_name=self.distributor.activity_map_key, activity_type=self.distributor.activity_type)
                        self.distributor._increment_venue_count(venue)
                        allocated += 1
                        continue
            unallocated.append(person)
            self._log_progress(i, total, interval, allocated, prefix="  ")

        self.distributor.allocated_this_run += allocated
        return unallocated

    def _log_progress(self, current, total, interval, count, prefix="    "):
        if interval <= 0:
            return
        
        # Calculate which interval threshold was reached/crossed
        prev_threshold = (current - 1) // interval if current > 0 else -1
        curr_threshold = current // interval
        
        if curr_threshold > prev_threshold or current >= total:
            logger.info(f"{prefix}Progress: {current}/{total} people processed ({min(100, current/total*100):.1f}%) - {count} allocated")
