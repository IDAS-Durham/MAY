import logging
import csv
import os
from typing import List, Dict, Any
from collections import defaultdict

logger = logging.getLogger(__name__)

class ReportingManager:
    """
    Handles logging, statistics, and export functionality for the distributor.
    """

    def __init__(self, distributor):
        self.distributor = distributor
        self.config = distributor.config
        self.verbose = distributor.verbose

    def log_allocation_summary(self, world, eligible_count: int = None):
        """Log summary statistics of allocation."""
        total_people = len(world.people)
        allocated = self.distributor.allocated_this_run
        
        logger.info(f"Allocation summary for {self.distributor.venue_type}:")
        logger.debug(f"  - Total people in world: {total_people}")
        if eligible_count is not None:
            logger.info(f"  - Eligible people identified: {eligible_count} ({eligible_count/total_people*100:.1f}%)")
            logger.info(f"  - Allocated this run: {allocated} ({allocated/eligible_count*100:.1f}%)" if eligible_count > 0 else f"  - Allocated this run: {allocated}")
        else:
            logger.info(f"  - Allocated this run: {allocated}")

    def export_venue_summary(self, world, output_path: str):
        """
        Export per-venue summary statistics to CSV.
        
        For each venue of the distributor's type, outputs:
        - Venue ID, name, type, geo unit, coordinates
        - Student count, average age, min age, max age
        - Capacity, remaining capacity
        """
        venue_type = self.distributor.venue_type
        activity_key = self.distributor.activity_map_key
        # activity_type is the nested key in activity_map (e.g., 'education'), falls back to venue_type
        activity_type_key = self.distributor.activity_type or venue_type
        venues = world.venues_by_type(venue_type)
        
        if not venues:
            logger.warning(f"No venues of type '{venue_type}' to export")
            return
        
        # Build venue -> people mapping using the distributor's subset_key
        # This ensures we only count people assigned by THIS distributor,
        # not people placed by other distributors (e.g., students vs teachers)
        subset_key = self.distributor.subset_key
        venue_people = defaultdict(list)
        for venue in venues:
            if subset_key:
                # Only count members from this distributor's subset
                if subset_key in venue.subsets:
                    venue_people[id(venue)] = list(venue.subsets[subset_key].members)
                # else: venue has 0 people from this distributor (don't count other subsets)
            else:
                # No specific subset_key — count all subset members
                for sk, subset in venue.subsets.items():
                    venue_people[id(venue)].extend(subset.members)
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            subset_label = self.distributor.subset_key or 'person'
            writer.writerow([
                'venue_id', 'venue_name', 'BTCode', 'geo_unit', 'latitude', 'longitude',
                f'{subset_label}_count', 'avg_age', 'min_age', 'max_age',
                'capacity', 'remaining_capacity'
            ])
            
            total_allocated = 0
            empty_venues = 0
            
            for venue in sorted(venues, key=lambda v: v.name):
                people = venue_people.get(id(venue), [])
                count = len(people)
                total_allocated += count
                
                if count == 0:
                    empty_venues += 1
                    avg_age = min_age = max_age = ''
                else:
                    ages = [p.age for p in people]
                    avg_age = f"{sum(ages) / len(ages):.1f}"
                    min_age = min(ages)
                    max_age = max(ages)
                
                geo_name = venue.geographical_unit.name if venue.geographical_unit else 'unknown'
                lat, lon = '', ''
                if venue.geographical_unit and venue.geographical_unit.coordinates:
                    coords = venue.geographical_unit.coordinates
                    if len(coords) == 2:
                        lat, lon = coords[0], coords[1]
                
                capacity = self.distributor._get_venue_capacity(venue)
                remaining = self.distributor._get_remaining_capacity(venue)
                
                btcode = venue.properties.get('BTCode', '') if hasattr(venue, 'properties') else ''
                
                writer.writerow([
                    venue.id, venue.name, btcode, geo_name, lat, lon,
                    count, avg_age, min_age, max_age,
                    capacity, remaining
                ])
        
        subset_label = self.distributor.subset_key or 'person'
        logger.info(f"Exported venue summary to {output_path}")
        logger.info(f"  - Venues with {subset_label}s: {len(venues) - empty_venues}")
        logger.info(f"  - Empty venues: {empty_venues}")
        logger.info(f"  - Total {subset_label}s allocated: {total_allocated}")
        
        # Diagnostic: compare counting methods
        people_with_activity = 0
        people_unique_venues = set()
        for person in world.people:
            if activity_key not in person.activity_map:
                continue
            subsets = person.activity_map[activity_key].get(activity_type_key)
            if subsets:
                people_with_activity += 1
                for s in subsets:
                    people_unique_venues.add(id(s.venue))
        
        tracker_total = sum(self.distributor.venue_capacity_tracker.values()) if hasattr(self.distributor, 'venue_capacity_tracker') else 0
        allocated_counter = self.distributor.allocated_this_run
        
        logger.debug(f"  [DIAGNOSTIC] People with '{activity_key}.{activity_type_key}' in activity_map: {people_with_activity}")
        logger.debug(f"  [DIAGNOSTIC] Unique venue IDs from people's activity_maps: {len(people_unique_venues)}")
        logger.debug(f"  [DIAGNOSTIC] Venue IDs in venues list: {len(set(id(v) for v in venues))}")
        logger.debug(f"  [DIAGNOSTIC] Venue IDs matched (intersection): {len(people_unique_venues & set(id(v) for v in venues))}")
        logger.debug(f"  [DIAGNOSTIC] Venue IDs NOT matched: {len(people_unique_venues - set(id(v) for v in venues))}")
        logger.debug(f"  [DIAGNOSTIC] capacity_tracker sum: {tracker_total}")
        logger.debug(f"  [DIAGNOSTIC] allocated_this_run counter: {allocated_counter}")

    def export_unallocated_report(self, world, output_path: str):
        """
        Export details of eligible but unallocated people to CSV.
        
        Helps diagnose why 100% allocation was not achieved.
        Includes person details and their nearest venue distances.
        """
        venue_type = self.distributor.venue_type
        activity_key = self.distributor.activity_map_key
        # activity_type is the nested key in activity_map (e.g., 'education'), falls back to venue_type
        activity_type_key = self.distributor.activity_type or venue_type
        
        # Find eligible people who are NOT allocated
        unallocated = []
        for person in world.people:
            # Check if person is eligible (matches global filters)
            if not self.distributor.filtering.person_matches_filters(
                person, self.distributor._pre_processed_filters
            ):
                continue
            
            # Check if already allocated
            if activity_key in person.activity_map and person.activity_map[activity_key].get(activity_type_key):
                continue
            
            unallocated.append(person)
        
        if not unallocated:
            logger.info("All eligible people were allocated - no unallocated report needed")
            return
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
        
        # Write individual unallocated people
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['person_id', 'age', 'sex', 'geo_unit', 'Occode'])
            
            for person in unallocated:
                geo = person.geographical_unit.name if person.geographical_unit else 'unknown'
                occode = person.properties.get('Occode', '')
                writer.writerow([person.id, person.age, person.sex, geo, occode])
        
        logger.info(f"Exported unallocated report to {output_path}")
        logger.info(f"  - Total unallocated: {len(unallocated)}")
        
        # Log summary breakdown
        by_geo = defaultdict(int)
        by_age = defaultdict(int)
        for p in unallocated:
            geo = p.geographical_unit.name if p.geographical_unit else 'unknown'
            by_geo[geo] += 1
            by_age[p.age] += 1
        
        # Top geo units with most unallocated
        top_geos = sorted(by_geo.items(), key=lambda x: -x[1])[:10]
        logger.info(f"  - Top geo units with unallocated:")
        for geo, count in top_geos:
            logger.info(f"      {geo}: {count}")
        
        # Age distribution
        age_ranges = {'0-4': 0, '5-10': 0, '11-14': 0, '15-18': 0, '19-24': 0, '25+': 0}
        for age, count in by_age.items():
            if age < 5: age_ranges['0-4'] += count
            elif age <= 10: age_ranges['5-10'] += count
            elif age <= 14: age_ranges['11-14'] += count
            elif age <= 18: age_ranges['15-18'] += count
            elif age <= 24: age_ranges['19-24'] += count
            else: age_ranges['25+'] += count
        
        logger.info(f"  - Age distribution of unallocated: {dict(age_ranges)}")

    def export_allocations(self, world, output_path: str):
        """Export allocations to CSV file."""
        logger.info(f"Exporting allocations to {output_path}")
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            sample_venues = world.venues_by_type(self.distributor.venue_type)
            prop_cols = sorted(sample_venues[0].properties.keys()) if sample_venues else []
            header = ['person_id', 'person_sex', 'person_age', 'residence_type', 'residence_pattern', 'residence_geo_unit', 'venue_name', 'venue_type'] + prop_cols
            writer.writerow(header)

            count = 0
            for person in world.people:
                if self.distributor.activity_map_key not in person.activity_map: continue
                subsets = person.activity_map[self.distributor.activity_map_key].get(self.distributor.venue_type)
                if not subsets: continue

                venue = subsets[0].venue
                res_type = getattr(person, 'residence_type', 'unknown') or 'unknown'
                res_pat = person.get_residence_property('original_pattern', '')
                geo = person.geographical_unit.name if person.geographical_unit else 'unknown'

                row = [person.id, person.sex, person.age, res_type, res_pat, geo, venue.name, venue.type]
                row.extend([venue.properties.get(c, '') for c in prop_cols])
                writer.writerow(row)
                count += 1
        logger.info(f"Exported {count} allocations.")

    def check_priority_coverage(self, world):
        """Check that all priority groups with overflow enabled are fully allocated."""
        priority_cfg = self.config.get('eligibility', {}).get('priority_allocation', {})
        if not priority_cfg.get('enabled', False): return

        for group in priority_cfg.get('groups', []):
            if not group.get('allow_overflow', False): continue
            
            group_name = group.get('name', 'unnamed')
            filters = self.distributor._pre_process_filters(group.get('filters', []))
            unallocated = [p for p in world.people if self.distributor.activity_map_key not in p.activity_map and self.distributor.filtering.person_matches_filters(p, filters)]

            if unallocated:
                logger.warning(f"PRIORITY GROUP '{group_name}': {len(unallocated)} NOT allocated!")
                # breakdowns
                ages = defaultdict(int)
                for p in unallocated[:20]: ages[p.age] += 1
                logger.warning(f"  Ages: {dict(sorted(ages.items()))}")
            else:
                logger.info(f"✓ PRIORITY GROUP '{group_name}': All allocated")

