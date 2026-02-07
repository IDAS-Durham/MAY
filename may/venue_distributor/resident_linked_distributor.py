import logging
import random
import numpy as np
import time
from typing import Dict, List, Optional, Any
from .base_distributor import BaseDistributor
from .filtering import FilteringManager
from .reporting import ReportingManager

logger = logging.getLogger("resident_linked_distributor")

class ResidentLinkedDistributor(BaseDistributor):
    """
    Generic distributor that links 'visitors' to 'venues' based on the residents 
    already present in those venues. Matches residents to visitor units 
    (individuals or households) geographically.
    
    This replicates the JUNE 1 care home linking behavior while remaining generic.
    """

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        super().__init__(config_file, config_dict)
        
        # Configuration
        self.target_venue_type = self.config.get('target_venue_type', 'care_home')
        self.resident_subset = self.config.get('resident_subset', 'resident')
        self.activity_map_key = self.config.get('activity_map_key', 'leisure')
        self.link_level = self.config.get('link_level', 'household') # 'person' or 'household'
        self.multiplier = self.config.get('multiplier', 1) # Visitors per resident
        
        # Component managers
        self.filtering = FilteringManager(self)
        self.reporting = ReportingManager(self)
        
        self.visitor_filters = self.config.get('visitor_eligibility', {}).get('global_filters', [])
        self._pre_processed_filters = self._pre_process_filters(self.visitor_filters)
        self._pre_processed_exclude = self.config.get('visitor_eligibility', {}).get('exclude', {})
        
        logger.info(f"Initialized ResidentLinkedDistributor for '{self.target_venue_type}'")
        logger.info(f"  Link level: {self.link_level}, Multiplier: {self.multiplier}")

    def _pre_process_filters(self, filters: List[Dict]) -> List[Dict]:
        """Pre-process filters to avoid repeated path parsing."""
        processed = []
        for f in filters:
            p_filter = f.copy()
            attr_name = f.get('attribute')
            if attr_name:
                parts = attr_name.split('.')
                p_filter['path_parts'] = parts
                p_filter['is_nested'] = len(parts) > 1
                p_filter['is_residence'] = parts[0] == 'residence'
                if p_filter['is_residence']:
                    p_filter['residence_parts'] = parts[1:]
            else:
                p_filter['is_nested'] = False
            processed.append(p_filter)
        return processed

    def allocate(self, world):
        """
        Main allocation logic optimized for large-scale populations.
        """
        start_time = time.time()
        logger.info("=" * 60)
        logger.info(f"Starting ResidentLinkedDistributor: {self.target_venue_type}")
        logger.info("=" * 60)
        
        venues = world.venues_by_type(self.target_venue_type)
        if not venues:
            return {"total_links": 0}

        # 1. Prepare vectorized population data
        logger.info(f"  Preparing population data...")
        self._prepare_vectorized_data(world)

        # 2. Setup filtering manager
        logger.info(f"  Setting up filtering manager...")
        from may.venue_distributor.filtering import FilteringManager
        self.filtering_manager = FilteringManager(self)

        # 3. Batch processing by geography level
        geo_level = self.config.get('geography_level', self.batch_geo_level)
        geo_units = list(world.geography.get_units_by_level(geo_level).values())
        
        logger.info(f"  Building '{self.target_venue_type}' links for {len(geo_units)} {geo_level}s")
        
        # Calculate total residents for summary stats
        total_residents = 0
        for venue in venues:
            res_subset = venue.subsets.get(self.resident_subset)
            if res_subset:
                total_residents += len(res_subset.members)
        
        logger.info(f"  Found {len(venues)} target venues with {total_residents:,} total residents")
        
        total_links = 0
        total_venues_processed = 0
        unit_count = len(geo_units)
        report_interval = max(1, unit_count // 10)
        
        for i, geo_unit in enumerate(geo_units):
            people_in_unit = list(geo_unit.get_people())
            if not people_in_unit:
                continue
                
            # B. Filter by eligibility
            eligible_people = self.filtering_manager.apply_global_filters(people_in_unit)
            
            if not eligible_people:
                continue
                
            # C. Group by household units if configured
            visitor_units = self._group_visitors_optimized(eligible_people)
            
            if not visitor_units:
                continue
                
            # C. Get venues in this geo unit
            unit_venues = [v for v in venues if self._venue_matches_geo_unit(v, geo_unit)]
            if not unit_venues:
                continue
                
            links_created = self._allocate_batch_optimized(visitor_units, unit_venues)
            total_links += links_created
            total_venues_processed += len(unit_venues)

            # Progress reporting
            if (i + 1) % report_interval == 0 or (i + 1) == unit_count:
                percent = ((i + 1) / unit_count) * 100
                logger.info(f"    Progress: {i+1:,}/{unit_count:,} {geo_level}s processed ({percent:.1f}%)")

        elapsed = time.time() - start_time
        avg_links = total_links / total_residents if total_residents > 0 else 0
        logger.info(f"Built {total_links:,} total links (avg {avg_links:.1f} per resident) in {elapsed:.2f}s")
        return {"total_links": total_links}

    def _prepare_vectorized_data(self, world):
        """Build population arrays needed for vectorized filtering/grouping."""
        if self.population_arrays:
            return

        needed_attrs = ['age', 'sex', 'residence.id']
        # Add attributes from filters
        for f in self._pre_processed_filters:
            if f.get('attribute'):
                needed_attrs.append(f['attribute'])
        
        needed_attrs = list(set(needed_attrs))
        self._build_population_arrays(world.people, needed_attrs)

    def _allocate_batch_optimized(self, visitor_units: List[List], venues: List) -> int:
        """
        Fast pairing logic for a batch of venues and visitors.
        """
        link_data = [] # List of (visitor_unit, venue)
        
        # 1. Flatten residents from all venues in batch
        # We just need to know how many visits are available across all venues
        venue_capacities = []
        for venue in venues:
            res_subset = venue.subsets.get(self.resident_subset)
            if not res_subset: continue
            
            num_residents = len(res_subset.members)
            if num_residents == 0: continue
            
            venue_capacities.append((venue, num_residents))
            
        logger.debug(f"      Batch matching: {len(visitor_units)} visitor units, {len(venue_capacities)} eligible venues")
        if not venue_capacities: return 0

        # 2. Match with visitor units using multiplier
        multiplier = self.multiplier
        v_idx = 0
        
        logger.debug(f"      Multiplier: {multiplier}")
        
        for venue, num_residents in venue_capacities:
            # For each resident, we link 'multiplier' units
            for _ in range(num_residents):
                num_to_link = int(multiplier)
                if multiplier % 1 > 0 and random.random() < (multiplier % 1):
                    num_to_link += 1
                    
                for _ in range(num_to_link):
                    if v_idx >= len(visitor_units):
                        break
                    link_data.append((visitor_units[v_idx], venue))
                    v_idx += 1
                
                if v_idx >= len(visitor_units):
                    break
            if v_idx >= len(visitor_units):
                break
            
        # 3. Bulk apply links
        if link_data:
            self._bulk_link_units_to_venues(link_data)
        
        return len(link_data)

    def _bulk_link_units_to_venues(self, link_data: List):
        """
        Apply links in bulk to subsets and activity maps.
        """
        from may.population import Subset
        
        venue_subset_to_people = {} # (venue, subset_key) -> [list of people]
        
        subset_key = self.config.get('subset_key', 'visitor')
        activity_key = self.activity_map_key
        venue_type = self.target_venue_type
        
        for unit, venue in link_data:
            key = (venue, subset_key)
            if key not in venue_subset_to_people:
                venue_subset_to_people[key] = []
            venue_subset_to_people[key].extend(unit)

        # Apply in bulk
        for (venue, subset_key), people in venue_subset_to_people.items():
            # Get or create subset
            if subset_key not in venue.subsets:
                subset = Subset(venue=venue, subset_index=len(venue.subsets), subset_name=subset_key)
                venue.subsets[subset_key] = subset
            else:
                subset = venue.subsets[subset_key]
                
            # Bulk add members
            subset.members.update(people)
            
            # Bulk update people
            for p in people:
                if activity_key not in p.activity_map:
                    p.activity_map[activity_key] = {}
                if venue_type not in p.activity_map[activity_key]:
                    p.activity_map[activity_key][venue_type] = []
                
                # IMPORTANT: Use a list of unique subsets per (activity, venue_type)
                if subset not in p.activity_map[activity_key][venue_type]:
                    p.activity_map[activity_key][venue_type].append(subset)
                
                if activity_key not in p.activities:
                    p.add_activity(activity_key)

    def _venue_matches_geo_unit(self, venue, geo_unit) -> bool:
        """Efficiently check if venue belongs to geo_unit."""
        v_geo = venue.geographical_unit
        while v_geo:
            if v_geo.id == geo_unit.id:
                return True
            if v_geo.level == geo_unit.level: # Reached same level, no match
                return False
            v_geo = v_geo.parent
        return False

    def _group_visitors_optimized(self, people: List) -> List[List]:
        """Vectorized grouping of people into units."""
        if self.link_level != 'household':
            return [[p] for p in people]

        # Group by household ID using the vectorized array
        # This is much faster than Python dictionary iteration for large lists
        p_indices = [self.person_id_to_index[p.id] for p in people]
        hh_ids = self.population_arrays['residence.id'][p_indices]
        
        # Dictionary approach is still fine for LGU-sized batches
        # but we use hh_ids array for O(1) attribute access
        hh_to_members = {}
        for i, person in enumerate(people):
            hh_id = hh_ids[i]
            if hh_id == -1: continue
            if hh_id not in hh_to_members:
                hh_to_members[hh_id] = []
            hh_to_members[hh_id].append(person)
            
        return list(hh_to_members.values())

    def _get_venue_geo_match(self, venue, geo_unit_name: str) -> bool:
        """
        Check if venue belongs to the target geographical unit.
        """
        geo_level = self.config.get('geography_level', self.batch_geo_level)
        v_geo = venue.geographical_unit
        if not v_geo: return False
        
        # Traversal to target level
        unit = v_geo
        while unit and unit.level != geo_level:
            unit = unit.parent
            
        return unit.name == geo_unit_name if unit else False

    def _link_unit_to_venue(self, members: List, venue, resident_id: Optional[int] = None):
        """
        Link all members of a unit to a venue in their activity map.
        
        Args:
            members: List of Person objects in the visitor unit
            venue: Target Venue
            resident_id: Optional ID of the resident being visited
        """
        activity_key = self.activity_map_key
        venue_type = self.target_venue_type
        
        # Get or create subset in venue for visiting
        # We include the resident_id in the subset name for tracking/debugging
        base_subset_key = self.config.get('subset_key', 'visitor')
        subset_key = f"{base_subset_key}_for_{resident_id}" if resident_id is not None else base_subset_key
        
        from may.population import Subset
        
        if subset_key not in venue.subsets:
            subset = Subset(
                venue=venue,
                subset_index=len(venue.subsets),
                subset_name=subset_key
            )
            venue.subsets[subset_key] = subset
        else:
            subset = venue.subsets[subset_key]

        for p in members:
            # Initialize leisure dict if not exists
            if activity_key not in p.activity_map:
                p.activity_map[activity_key] = {}
            
            # Add venue to the list for this type
            if venue_type not in p.activity_map[activity_key]:
                p.activity_map[activity_key][venue_type] = []
            
            # Use JuneZero structure: list of subsets
            if subset not in p.activity_map[activity_key][venue_type]:
                p.activity_map[activity_key][venue_type].append(subset)
                subset.add_member(p)
                
            # Ensure activity is in p.activities
            if activity_key not in p.activities:
                p.add_activity(activity_key)

    def export_links(self, world, output_path: str):
        """
        Export resident-linked connections to CSV.
        
        Args:
            world: World object (or proxy)
            output_path: Path to output CSV file
        """
        import csv
        logger.info(f"Exporting resident-linked connections to {output_path}")
        
        # Get all relevant people (those who might have leisure links)
        people = world.people
        
        # Collect links
        data = []
        for person in people:
            if self.activity_map_key not in person.activity_map:
                continue
            
            links = person.activity_map[self.activity_map_key].get(self.target_venue_type, [])
            for subset_link in links:
                venue = subset_link.venue
                
                # Get person details
                residence = person.residence
                household_id = residence.id if residence and residence.type == 'household' else 'none'
                
                data.append({
                    'person_id': person.id,
                    'age': person.age,
                    'sex': person.sex,
                    'household_id': household_id,
                    'geo_unit': person.geographical_unit.name if person.geographical_unit else 'none',
                    'linked_venue_id': venue.id,
                    'linked_venue_name': venue.name,
                    'linked_venue_type': venue.type,
                    'linked_venue_geo': venue.geographical_unit.name if venue.geographical_unit else 'none'
                })
        
        if not data:
            logger.warning("No links found to export.")
            return

        # Write to CSV
        with open(output_path, 'w', newline='') as f:
            fieldnames = ['person_id', 'age', 'sex', 'household_id', 'geo_unit', 
                         'linked_venue_id', 'linked_venue_name', 'linked_venue_type', 'linked_venue_geo']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
            
        logger.info(f"Successfully exported {len(data)} links.")
