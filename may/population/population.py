"""
Population manager for June Zero.

Handles population generation and distribution across geographical units.
"""

import os
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from .person import Person

logger = logging.getLogger("population")


class PopulationManager:
    """
    Manages population generation and distribution.

    This class loads demographic data and creates Person objects distributed
    across geographical units according to specified distributions.
    """

    def __init__(self, geography, data_dir):
        """
        Initialize the PopulationManager.

        Args:
            geography (Geography): Geography object containing geographical units
            data_dir (str): Directory containing population data files
        """
        self.geography = geography
        self.data_dir = data_dir
        self.people = []
        self.people_by_id = {}

        # Precise demographics: geo_unit -> age -> sex -> count
        self.precise_demographics = {}

    def __len__(self):
        return len(self.people)

    @staticmethod
    def _create_nested_defaultdict():
        """
        Create a nested defaultdict for demographics storage.

        This is a separate function (not a lambda) to make the object pickle-compatible.
        Returns a defaultdict(dict) for storing age -> sex -> count mappings.
        """
        return defaultdict(dict)

    def load_demographics_from_csv(self, male_file="demographics_male.csv",
                                     female_file="demographics_female.csv"):
        """
        Load precise population demographics from matrix-style CSV files.

        Expected format (separate files for male/female):
            geo_unit,0,1,2,3,...,100
            E00004320,2,2,1,3,...,0
            E00004321,1,3,2,2,...,1
            ...

        Rows = geo units
        Columns = ages (1-year bins from 0 to 100)

        Args:
            male_file (str): Filename for male demographics
            female_file (str): Filename for female demographics
        
        """
        male_path = os.path.join(self.data_dir, male_file)
        female_path = os.path.join(self.data_dir, female_file)

        if not os.path.exists(male_path) or not os.path.exists(female_path):
            logger.error(f"Demographics files not found: {male_path} or {female_path}")
            logger.info("Cannot generate population without demographics data")
            return

        # Get the smallest geographical level from the loaded geography
        # to filter demographics to only relevant geo units
        smallest_level = self.geography.levels[0]
        smallest_units_dict = self.geography.get_units_by_level(smallest_level)

        if not smallest_units_dict:
            logger.warning(f"No {smallest_level} units found in geography. Cannot load demographics.")
            return

        # Create a set of geo unit names that exist in our geography for fast lookup
        valid_geo_units = set(smallest_units_dict.keys())
        logger.info(f"Filtering demographics to {len(valid_geo_units)} {smallest_level}s in loaded geography")

        logger.info(f"Loading male demographics from {male_path}")
        male_df = pd.read_csv(male_path)

        logger.info(f"Loading female demographics from {female_path}")
        female_df = pd.read_csv(female_path)

        # Validate structure
        if 'geo_unit' not in male_df.columns or 'geo_unit' not in female_df.columns:
            raise ValueError("Demographics files must have 'geo_unit' column")


        # Ignore index column if it exists
        for _df in [male_df, female_df]:
            if 'index' in _df.columns:
                _df.drop(columns=['index'], inplace=True)
        

        # Filter to only geo units in our geography BEFORE processing
        male_df = male_df[male_df['geo_unit'].isin(valid_geo_units)]
        female_df = female_df[female_df['geo_unit'].isin(valid_geo_units)]

        logger.info(f"Filtered to {len(male_df)} male geo units and {len(female_df)} female geo units")


        # Load into nested dict structure: geo_unit -> age -> sex -> count
        # Note: Using a regular function instead of lambda for pickle compatibility
        self.precise_demographics = defaultdict(self._create_nested_defaultdict)
        total_people = 0

        logger.info("Processing male demographics...")
        # Convert male dataframe to long format for efficient processing
        male_melted = male_df.melt(id_vars=['geo_unit'], var_name='age', value_name='count')
        male_melted['age'] = male_melted['age'].astype(int)
        male_melted['count'] = male_melted['count'].fillna(0).astype(int)
        # Filter out zero counts for efficiency
        male_melted = male_melted[male_melted['count'] > 0]

        logger.info("Processing female demographics...")
        # Convert female dataframe to long format
        female_melted = female_df.melt(id_vars=['geo_unit'], var_name='age', value_name='count')
        female_melted['age'] = female_melted['age'].astype(int)
        female_melted['count'] = female_melted['count'].fillna(0).astype(int)
        # Filter out zero counts for efficiency
        female_melted = female_melted[female_melted['count'] > 0]

        logger.info("Building demographic dictionary...")
        # Convert to numpy arrays for much faster iteration
        male_values = male_melted.values  # [[geo_unit, age, count], ...]
        female_values = female_melted.values

        # Build nested dictionary
        for row in male_values:
            geo_unit = str(row[0])
            age = int(row[1])
            count = int(row[2])

            self.precise_demographics[geo_unit][age]['male'] = count
            total_people += count

        for row in female_values:
            geo_unit = str(row[0])
            age = int(row[1])
            count = int(row[2])

            self.precise_demographics[geo_unit][age]['female'] = count
            total_people += count

        logger.info(f"Loaded precise demographics for {len(self.precise_demographics)} geographical units")
        logger.info(f"Total people in demographics: {total_people:,}")

    def generate_population(self, **kwargs):
        """
        Generate population from precise demographics data.

        Creates exact number of people per age/sex/geo_unit as specified
        in the demographics file. People are created in age order globally
        (person 0 is the youngest person across all smallest geographical units).

        Assumes demographics are provided for the smallest geographical level
        (first level in the hierarchy, e.g., SGU, village, census block, etc.).

        Args:
          **kwargs:
            Arbitrary keyword arguments to be passed to the creation of Person.
            Supported keys include:
              * activities (list[str], optional): list of activity names for each Person.
              * properties (dict, optional): a dict of properties of the Person, e.g. 'ethnicity', 'compliance', 'taste'.
              * activity_map (DefaultDict[str,list[Subset]], optional):
                a dict mapping an activity (same string as in activities) to a list of potential Subsets the Person would
                join to fulfil that activity. 
                    
        """
        if not self.precise_demographics:
            logger.error("No demographics data loaded. Cannot generate population.")
            return

        logger.info("Generating population from precise demographics...")
        Person.reset_counter()

        # Get the smallest geographical level (first in the hierarchy)
        smallest_level = self.geography.levels[0]
        smallest_units_dict = self.geography.get_units_by_level(smallest_level)

        if not smallest_units_dict:
            logger.warning(f"No {smallest_level} units found in geography. Cannot generate population.")
            return

        # Collect all (age, sex, geo_unit, count) tuples and sort by age
        all_age_sex_geo = []

        for unit in smallest_units_dict.values():
            if unit.name not in self.precise_demographics:
                logger.debug(f"No demographic data for {unit.name}, skipping")
                continue

            age_sex_data = self.precise_demographics[unit.name]

            for age, sex_counts in age_sex_data.items():
                for sex, count in sex_counts.items():
                    all_age_sex_geo.append((age, sex, unit, count))

        # Sort by age first, then sex (for consistent ordering)
        all_age_sex_geo.sort(key=lambda x: (x[0], x[1]))

        # Now create people in age order across all smallest units
        total_people = 0
        geo_units_with_data = len(set(item[2] for item in all_age_sex_geo))

        for age, sex, unit, count in all_age_sex_geo:
            for _ in range(count):
                person = Person(age=age, sex=sex, geographical_unit=unit, **kwargs)
                self.add_person(person)
                # Add person to their geographical unit's people list
                unit.add_person(person)
                total_people += 1

        logger.info(f"Generated {total_people:,} people across {geo_units_with_data} {smallest_level}s")
        if geo_units_with_data > 0:
            logger.info(f"Average: {total_people / geo_units_with_data:.1f} people per {smallest_level}")

    def add_person(self, person: Person):
        self.people.append(person)
        self.people_by_id[person.id] = person

    def add_people(self, people: list[Person]):
        for person in people:
            self.add_person(person)

    def get_person(self, person_id):
        """
        Get a person by their ID.

        Args:
            person_id (int): ID of the person

        Returns:
            Person: The person object, or None if not found
        """
        return self.people_by_id.get(person_id)

    def get_all_people(self):
        """
        Get all people as a list.

        Returns:
            list: List of all Person objects
        """
        return self.people

    def get_people_by_age_range(self, min_age, max_age):
        """
        Get all people within an age range.

        Args:
            min_age (int): Minimum age (inclusive)
            max_age (int): Maximum age (inclusive)

        Returns:
            list: List of Person objects in age range
        """
        return [p for p in self.people if min_age <= p.age <= max_age]

    def get_people_by_sex(self, sex):
        """
        Get all people of a specific sex.

        Args:
            sex (str): Sex category

        Returns:
            list: List of Person objects
        """
        return [p for p in self.people if p.sex == sex]

    def get_people_by_activity(self, activity):
        """
        Get all people with a specific activity.

        Args:
            activity (str): Activity name

        Returns:
            list: List of Person objects with this activity
        """
        return [p for p in self.people if p.has_activity(activity)]

    def get_people_by_geo_unit(self, geo_unit_code):
        """
        Get all people in a specific geographical unit.

        Args:
            geo_unit_code (str): Name/code of the geographical unit

        Returns:
            list: List of Person objects in this geo_unit
        """
        unit = self.geography.get_unit(geo_unit_code)
        if unit is None:
            return []
        return unit.people if hasattr(unit, 'people') else []

    def get_statistics(self):
        """
        Get basic statistics about the population.

        Returns:
            dict: Dictionary of statistics
        """
        if not self.people:
            return {}

        ages = [p.age for p in self.people]
        sexes = [p.sex for p in self.people]

        # Count sex categories
        sex_counts = {}
        for sex in sexes:
            sex_counts[sex] = sex_counts.get(sex, 0) + 1

        # Collect all activities
        all_activities = set()
        for p in self.people:
            all_activities.update(p.activities)

        activity_counts = {}
        for activity in all_activities:
            activity_counts[activity] = len(self.get_people_by_activity(activity))

        return {
            'total_population': len(self.people),
            'mean_age': np.mean(ages),
            'median_age': np.median(ages),
            'min_age': np.min(ages),
            'max_age': np.max(ages),
            'sex_distribution': sex_counts,
            'activity_counts': activity_counts
        }
