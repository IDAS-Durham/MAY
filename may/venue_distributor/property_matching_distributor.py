import logging
import random
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from .base_distributor import BaseDistributor
from .reporting import ReportingManager

logger = logging.getLogger("property_matching_distributor")

class PropertyMatchingDistributor(BaseDistributor):
    """
    Generic distributor that links people to venues based on matching property values.
    
    Example usage:
    - Link people to households using a shared 'HID' property.
    - Link people to specific workplaces using a 'company_id' property.
    """

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        super().__init__(config_file, config_dict)
        
        # Configuration
        target_type = self.config.get('target_venue_type', 'household')
        if isinstance(target_type, str):
            self.target_venue_types = [target_type]
        else:
            self.target_venue_types = list(target_type)
            
        # Required configuration; fail loud on missing keys
        required_keys = ['mapping_key', 'venue_property', 'activity_name']
        missing_keys = [key for key in required_keys if key not in self.config]
        if missing_keys:
            raise ValueError(f"PropertyMatchingDistributor missing required config keys: {missing_keys}")

        self.mapping_key = self.config['mapping_key']
        self.venue_property = self.config['venue_property']
        self.activity_name = self.config['activity_name']
        
        # Optional configuration
        self.subset_key = self.config.get('subset_key', 'resident')
        self.activity_type_override = self.config.get('activity_type', None)
        
        # Component managers
        self.reporting = ReportingManager(self)
        
        logger.info(f"Initialized PropertyMatchingDistributor for types: {self.target_venue_types}")
        logger.info(f"  Matching '{self.mapping_key}' (person) to '{self.venue_property}' (venue)")

    def allocate(self, world):
        """
        Main allocation logic: Matches people to venues using properties.
        """
        logger.info("=" * 60)
        logger.info(f"Starting PropertyMatchingDistributor: {', '.join(self.target_venue_types)}")
        logger.info("=" * 60)
        
        # Collect all candidate venues
        all_venues = []
        for v_type in self.target_venue_types:
            venues = world.venues_by_type(v_type)
            if venues:
                all_venues.extend(venues)
                
        if not all_venues:
            logger.warning(f"No venues of types {self.target_venue_types} found")
            return {"matched_count": 0}

        # Helper to normalize numeric strings (e.g. '123.0' -> '123')
        def normalize_key(val):
            if val is None:
                return None
            s = str(val).strip()
            if s.endswith('.0'):
                s = s[:-2]
            return s

        # 1. Create a lookup map for venues: property_value -> venue
        venue_map = {}
        for venue in all_venues:
            val = venue.properties.get(self.venue_property)
            norm_val = normalize_key(val)
            if norm_val is not None:
                venue_map[norm_val] = venue
        
        logger.info(f"  Created lookup map for {len(venue_map)} venues using property '{self.venue_property}'")

        # 2. Iterate through population and match
        matched_count = 0
        missed_count = 0
        missed_keys = set()
        unassigned_people = []
        
        people = world.population.people
        
        for person in people:
            val = person.properties.get(self.mapping_key)
            norm_val = normalize_key(val)
            if norm_val is not None:
                venue = venue_map.get(norm_val)
                if venue:
                    # Determine subset key (dynamic or static)
                    subset_key = self._get_subset_key(venue, person)
                    
                    if subset_key:
                        # Use override or venue's own type
                        actual_activity_type = self.activity_type_override or venue.type
                        
                        venue.add_to_subset(
                            person, 
                            subset_key=subset_key, 
                            activity_name=self.activity_name,
                            activity_type=actual_activity_type
                        )
                        matched_count += 1
                    else:
                        # Should rarely happen given fallback logic, but good for safety
                        logger.warning(f"Could not determine subset for person {person.id} in venue {venue.id}")
                        missed_count += 1
                else:
                    missed_count += 1
                    missed_keys.add(norm_val)
                    unassigned_people.append({
                        "person_id": person.id,
                        "mapping_key": norm_val
                    })
            
        if missed_count > 0:
            logger.warning(f"  Failed to find a venue for {missed_count:,} people with a mapping key")
            sample_keys = list(missed_keys)[:10]
            logger.warning(f"  Sample of missing keys ({len(missed_keys)} unique): {sample_keys}")

            # Export unassigned people to CSV
            try:
                # Try to infer output directory
                output_dir = "output/1911"
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir, exist_ok=True)
                
                export_file = os.path.join(output_dir, "unassigned_residences.csv")
                df = pd.DataFrame(unassigned_people)
                df.to_csv(export_file, index=False)
                logger.info(f"  Exported {len(unassigned_people)} unassigned people to {export_file}")
            except Exception as e:
                logger.error(f"  Failed to export unassigned people: {e}")
            
        return {"matched_count": matched_count, "missed_count": missed_count}

    def _get_subset_key(self, venue, person):
        """
        Determine the subset key for a person in a venue.
        
        Priority:
        1. 'subset_categories' in venue properties (Dynamic, attribute-based)
        2. 'subset_key' in venue properties (Static override)
        3. self.subset_key from distributor config (Static default)
        """
        
        # 1. Check for dynamic categories (e.g., age-based for households)
        categories = venue.properties.get('subset_categories')
        
        if categories:
            for cat in categories:
                # Check attributes
                attr_name = cat.get('attribute')
                if attr_name:
                    val = getattr(person, attr_name, None)
                    if val is None: 
                        val = person.properties.get(attr_name)
                    
                    if val is not None:
                        # Numerical check
                        if cat.get('type') == 'numerical':
                            limits = cat.get('numerical', {})
                            min_val = limits.get('min')
                            max_val = limits.get('max')
                            
                            if min_val is not None and val < min_val:
                                continue
                            if max_val is not None and val > max_val:
                                continue
                                
                            return cat['name']
                            
                        # Categorical check (if needed in future)
                        # elif cat.get('type') == 'categorical': ...
            
            pass

        # 2. Check venue-specific static key
        if 'subset_key' in venue.properties:
            return venue.properties['subset_key']

        # 3. Distributor config default
        return self.subset_key
