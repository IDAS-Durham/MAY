"""
SocialContactVisitDistributor: Assigns visit_social_contact activity based on social contacts' residences.

This distributor creates a derived activity where the venues are the residences
of a person's social contacts. It runs AFTER relationship building so that
social_contacts are already populated.

The activity allows disease modeling to track visits to contacts' homes.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class SocialContactVisitDistributor:
    """
    Distributor that assigns visit_social_contact activity based on social contacts.

    For each person with social contacts:
    1. Look up each contact's residence from their activity_map
    2. Add that residence to this person's activity_map under 'visit_social_contact'

    This creates a derived activity where venues are determined by relationships,
    not by direct venue allocation.
    """

    def __init__(self, config_file: str = None, config_dict: Dict = None):
        """
        Initialize SocialContactVisitDistributor.

        Args:
            config_file: Path to YAML config file
            config_dict: Dictionary config (alternative to file)
        """
        # Load config
        if config_file:
            self.config = self._load_config(config_file)
            self.config_path = Path(config_file)
        elif config_dict:
            self.config = config_dict
            self.config_path = None
        else:
            raise ValueError("Must provide either config_file or config_dict")

        # Core configuration
        self.activity_map_key = self.config.get('activity_map_key', 'visit_social_contact')
        self.activity_type = self.config.get('activity_type', 'household')

        # Source configuration - where to find social contacts
        source_config = self.config.get('source', {})
        self.source_property_key = source_config.get('property_key', 'social_contacts')

        # Subset configuration - which subset to add visitors to
        self.subset_key = self.config.get('subset_key', 'visitor')

        # Optional limits
        self.max_contacts = self.config.get('max_contacts', None)

        # Eligibility filters
        self.eligibility = self.config.get('eligibility', {})
        self.global_filters = self.eligibility.get('global_filters', [])

        # Statistics
        self.stats = {
            'people_processed': 0,
            'people_with_contacts': 0,
            'total_visits_assigned': 0,
            'contacts_without_residence': 0
        }

        logger.info(f"Initialized SocialContactVisitDistributor: "
                   f"activity_map_key='{self.activity_map_key}', "
                   f"source='{self.source_property_key}', "
                   f"max_contacts={self.max_contacts}")

    def _load_config(self, config_path: str) -> Dict:
        """Load and parse YAML configuration file."""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config

    def _check_eligibility(self, person) -> bool:
        """
        Check if a person is eligible based on global filters.

        Args:
            person: Person object to check

        Returns:
            True if person passes all filters
        """
        for filter_config in self.global_filters:
            attribute = filter_config.get('attribute', '')

            # Get attribute value (support nested attributes)
            if attribute.startswith('properties.'):
                prop_name = attribute.split('.', 1)[1]
                value = person.properties.get(prop_name)
            elif hasattr(person, attribute):
                value = getattr(person, attribute)
            else:
                continue

            # Check filter conditions
            if 'values' in filter_config:
                if value not in filter_config['values']:
                    return False

            if 'min' in filter_config:
                if value is None or value < filter_config['min']:
                    return False

            if 'max' in filter_config:
                if value is None or value > filter_config['max']:
                    return False

        return True

    def allocate(self, world) -> Dict[str, Any]:
        """
        Assign visit_social_contact activity to all eligible people.

        For each person:
        1. Check eligibility
        2. Get their social contacts from properties
        3. For each contact, get their residence
        4. Add the residence to this person's visit_social_contact activity

        Args:
            world: World object containing population and venues

        Returns:
            Statistics dictionary
        """
        logger.info(f"Starting social contact visit allocation...")
        logger.info(f"  Source property: {self.source_property_key}")
        logger.info(f"  Activity key: {self.activity_map_key}")

        all_people = world.population.get_all_people()

        for person in all_people:
            self.stats['people_processed'] += 1

            # Check eligibility
            if not self._check_eligibility(person):
                continue

            # Get social contacts
            contact_ids = person.properties.get(self.source_property_key, [])
            if not contact_ids:
                continue

            self.stats['people_with_contacts'] += 1

            # Limit contacts if configured
            if self.max_contacts and len(contact_ids) > self.max_contacts:
                contact_ids = contact_ids[:self.max_contacts]

            # Initialize activity if needed
            if self.activity_map_key not in person.activities:
                person.add_activity(self.activity_map_key)

            if not isinstance(person.activity_map.get(self.activity_map_key), dict):
                person.activity_map[self.activity_map_key] = {}

            if self.activity_type not in person.activity_map[self.activity_map_key]:
                person.activity_map[self.activity_map_key][self.activity_type] = []

            # Process each contact
            for contact_id in contact_ids:
                contact = world.population.get_person(contact_id)
                if contact is None:
                    continue

                # Get contact's residence
                residence_activity = contact.activity_map.get('residence', {})

                # Try to find household or any residence type
                residence_subsets = None
                for venue_type in ['household', 'farm', 'manor', 'cottage']:
                    if venue_type in residence_activity:
                        residence_subsets = residence_activity[venue_type]
                        break

                # Fallback: try any key in residence activity
                if residence_subsets is None and residence_activity:
                    first_key = next(iter(residence_activity.keys()), None)
                    if first_key:
                        residence_subsets = residence_activity[first_key]

                if not residence_subsets:
                    self.stats['contacts_without_residence'] += 1
                    continue

                # Add contact's residence to this person's visit activity
                for subset in residence_subsets:
                    # Avoid duplicates (check by venue ID)
                    already_added = any(
                        s.venue.id == subset.venue.id
                        for s in person.activity_map[self.activity_map_key][self.activity_type]
                    )
                    if not already_added:
                        person.activity_map[self.activity_map_key][self.activity_type].append(subset)
                        self.stats['total_visits_assigned'] += 1

        # Log results
        logger.info(f"Social contact visit allocation complete:")
        logger.info(f"  People processed: {self.stats['people_processed']:,}")
        logger.info(f"  People with contacts: {self.stats['people_with_contacts']:,}")
        logger.info(f"  Total visit venues assigned: {self.stats['total_visits_assigned']:,}")
        if self.stats['contacts_without_residence'] > 0:
            logger.warning(f"  Contacts without residence: {self.stats['contacts_without_residence']:,}")

        return self.stats

    @classmethod
    def from_yaml(cls, yaml_path: str):
        """
        Factory method to create distributor from YAML file.

        Args:
            yaml_path: Path to YAML config file

        Returns:
            SocialContactVisitDistributor instance
        """
        return cls(config_file=yaml_path)
