import logging
import csv
from typing import List, Dict, Any

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
        
        logger.info(f"Allocation Summary:")
        logger.info(f"  - Total people in world: {total_people}")
        if eligible_count is not None:
            logger.info(f"  - Eligible people identified: {eligible_count} ({eligible_count/total_people*100:.1f}%)")
            logger.info(f"  - Allocated this run: {allocated} ({allocated/eligible_count*100:.1f}%)" if eligible_count > 0 else f"  - Allocated this run: {allocated}")
        else:
            logger.info(f"  - Allocated this run: {allocated}")

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
