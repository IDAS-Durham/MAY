import logging
import pandas as pd
import os
from collections import defaultdict

logger = logging.getLogger("HouseholdCreator")

from may.geography import VenueManager, Venue


class HouseholdManager(VenueManager):
    """Designed to read and interpret the household composition document. 
    
    """

    def initialise_venue(self,
                         venue_type: str,
                         composition: str,
                         geo_unit,
                         **kwargs):
        """Does the job of a CompositionManager
        
        Args:
          composition (str): The column label for the household composition.
        
        """
        name=str(self._generate_id())
        newvenue = Venue(
            name,
            venue_type = venue_type,
            geographical_unit=geo_unit,
            **kwargs
        )
        newvenue.properties['venue_subtype'] = composition
        return newvenue
    
    def load_venue_type_from_df(self, venue_type, df):
        # Required columns
        required_cols = ['geo_unit']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column '{col}' in households file")

        # Optional coordinate columns
        has_coords = 'latitude' in df.columns and 'longitude' in venue_df.columns

        # Get additional property columns
        reserved_cols = {'geo_unit', 'latitude', 'longitude'}
        household_composition_cols = [col for col in df.columns if col not in reserved_cols]

        logger.info("Detected {} households in the dataframe...".format(df.sum(numeric_only=True).sum()))
        
        # Create households
        venues_created = 0
        venues_skipped = 0
        for i, row in df.iterrows():
            geo_unit_name = row['geo_unit']

            # Check if geo unit is in loaded geography
            if self.filter_by_geography and geo_unit_name not in self._loaded_geo_units:
                venues_skipped += 1
                continue

            # Get geographical unit
            geo_unit = self.geography.get_unit(geo_unit_name)
            if not geo_unit:
                logger.warning(f"Geographical unit '{geo_unit_name}' not found for venue in line {i}'. Skipping.")
                venues_skipped += 1
                continue

            # Get coordinates if provided
            coordinates = None
            if has_coords and pd.notna(row['latitude']) and pd.notna(row['longitude']):
                coordinates = (row['latitude'], row['longitude'])

            for composition in household_composition_cols:
                if pd.notna(row[composition]):
                    for i in range(row[composition]):
                        venue = self.initialise_venue(venue_type, composition, geo_unit)
                        self.add_venue(venue, geo_unit)
                        venues_created += 1

        if venues_skipped > 0:
            logger.info(f"Created {venues_created} {venue_type} venues ({venues_skipped} skipped due to geography filter)")
        else:
            logger.info(f"Created {venues_created} {venue_type} venues")
        

        
    

    

    
