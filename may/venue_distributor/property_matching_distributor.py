import logging
import random
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
            
        self.mapping_key = self.config.get('mapping_key', 'HID') # Person property name
        self.venue_property = self.config.get('venue_property', 'HID') # Venue property name
        
        self.activity_name = self.config.get('activity_name', 'residence')
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

        # 1. Create a lookup map for venues: property_value -> venue
        venue_map = {}
        for venue in all_venues:
            val = venue.properties.get(self.venue_property)
            if val is not None:
                # Store as string for robust matching
                venue_map[str(val).strip()] = venue
        
        logger.info(f"  Created lookup map for {len(venue_map)} venues using property '{self.venue_property}'")

        # 2. Iterate through population and match
        matched_count = 0
        missed_count = 0
        
        people = world.population.people
        
        for person in people:
            val = person.properties.get(self.mapping_key)
            if val is not None:
                venue = venue_map.get(str(val).strip())
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
            
        logger.info(f"  Explicitly matched {matched_count:,} people to venues using {self.mapping_key}")
        if missed_count > 0:
            logger.warning(f"  Failed to find a venue for {missed_count:,} people with a mapping key")
            
        return {"matched_count": matched_count, "missed_count": missed_count}

    def _get_subset_key(self, venue, person):
        """
        Determine the subset key for a person in a venue.
        
        Priority:
        1. 'subset_categories' in venue properties (Dynamic, attribute-based)
        2. 'subset_key' in venue properties (Static override)
        3. self.subset_key from distributor config (Static default / Backward compat)
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
            
            # If categories exist but no match found, fallback or return None?
            # For now, fallback to static key if available, else None
            pass

        # 2. Check venue-specific static key
        if 'subset_key' in venue.properties:
            return venue.properties['subset_key']

        # 3. Fallback to distributor config (backward compatibility)
        return self.subset_key
