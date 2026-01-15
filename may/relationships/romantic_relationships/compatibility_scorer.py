"""
Compatibility scoring for romantic partner matching.

Provides scoring and filtering for finding compatible romantic partners
based on ethnicity, geography, age, orientation, and shared activities.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Set

logger = logging.getLogger("romantic_relationships")


class CompatibilityScorer:
    """
    Scores and filters potential romantic partners for compatibility.

    Factors considered:
    - Sexual orientation compatibility
    - Age difference constraints
    - Ethnicity partnership probabilities
    - Geographical proximity
    - Shared activity venues (workplace, school)
    - Household exclusion (siblings, parents cannot date)
    """

    def __init__(
        self,
        config: dict,
        ethnicity_probs: Optional[Dict] = None,
        residence_cache: Optional[Dict[int, int]] = None,
        orientation_key: str = 'sexual_orientation',
        partners_key: str = 'romantic_partners'
    ):
        """
        Initialize the compatibility scorer.

        Args:
            config: Full configuration dict from YAML
            ethnicity_probs: Pre-loaded ethnicity partnership probabilities
            residence_cache: Dict mapping person ID to residence ID
            orientation_key: Key for sexual orientation in person.properties
            partners_key: Key for partners list in person.properties
        """
        self.config = config
        self.ethnicity_probs = ethnicity_probs
        self.residence_cache = residence_cache or {}
        self.orientation_key = orientation_key
        self.partners_key = partners_key

        # Cache config sections for faster access
        self.compat_rules = config.get('compatibility_rules', {})
        self.age_diff_config = config.get('age_differences', {})
        self.scoring_config = config.get('compatibility_scoring', {})
        self.perf_config = config.get('performance', {})

    def get_age_group(self, person) -> str:
        """
        Get age group string for a person.

        Returns strings like "18-25", "26-35", etc. based on age.
        """
        age = person.age

        if age < 26:
            return "18-25"
        elif age < 36:
            return "26-35"
        elif age < 51:
            return "36-50"
        elif age < 65:
            return "51-64"
        else:
            return "65+"

    def is_orientation_compatible(self, person1, person2) -> bool:
        """
        Check if two people have compatible sexual orientations.

        Args:
            person1: First person
            person2: Second person

        Returns:
            True if compatible, False otherwise
        """
        orientation1 = person1.properties.get(self.orientation_key)
        orientation2 = person2.properties.get(self.orientation_key)

        if not orientation1 or not orientation2:
            return False

        # Check if person1's orientation is compatible with person2's sex
        compatible_sexes_1 = self.compat_rules.get(orientation1, {}).get(person1.sex, [])
        if person2.sex not in compatible_sexes_1:
            return False

        # Check if person2's orientation is compatible with person1's sex
        compatible_sexes_2 = self.compat_rules.get(orientation2, {}).get(person2.sex, [])
        if person1.sex not in compatible_sexes_2:
            return False

        return True

    def filter_by_age_difference(self, person, candidates: List) -> List:
        """
        Filter candidates by age difference constraints.

        Args:
            person: Person seeking partner
            candidates: List of potential partners

        Returns:
            Filtered list of age-appropriate candidates
        """
        age_group = self.get_age_group(person)
        age_constraints = self.age_diff_config.get(age_group, {})

        min_diff = age_constraints.get('min', 0)
        max_diff = age_constraints.get('max', 100)

        age_appropriate = []
        for candidate in candidates:
            age_diff = abs(candidate.age - person.age)
            if min_diff <= age_diff <= max_diff:
                age_appropriate.append(candidate)

        return age_appropriate

    def get_ethnicity_probability(self, person1, person2) -> float:
        """
        Get the ethnicity partnership probability between two people.

        Returns the probability from the loaded ethnicity data, or 1.0 if
        ethnicity compatibility is disabled or data unavailable.

        Args:
            person1: First person
            person2: Second person

        Returns:
            Probability (0.0 to 1.0)
        """
        if not self.ethnicity_probs:
            return 1.0

        ethnicity_config = self.scoring_config.get('ethnicity', {})
        ethnicity_attr = ethnicity_config.get('attribute', 'ethnicity')

        eth1 = person1.properties.get(ethnicity_attr)
        eth2 = person2.properties.get(ethnicity_attr)

        if not eth1 or not eth2:
            return 1.0

        return self.ethnicity_probs.get(eth1, {}).get(eth2, 0.0)

    def get_geographical_multiplier(self, person1, person2) -> float:
        """
        Get geographical compatibility multiplier based on proximity.

        Returns higher multipliers for same M.G.U > same L.G.U > different regions.

        Args:
            person1: First person
            person2: Second person

        Returns:
            Multiplier (>= 1.0) based on geographical proximity
        """
        unit1 = person1.geographical_unit
        unit2 = person2.geographical_unit

        if not unit1 or not unit2:
            return 1.0

        # Same S.G.U (neighbors)
        if unit1.name == unit2.name:
            return self.scoring_config.get('same_sgu', 3.0)

        # Same M.G.U
        mgu1 = unit1.parent if unit1.parent else unit1
        mgu2 = unit2.parent if unit2.parent else unit2
        if mgu1 and mgu2 and mgu1.name == mgu2.name:
            return self.scoring_config.get('same_mgu', 2.0)

        # Same L.G.U
        lgu1 = mgu1.parent if mgu1 and mgu1.parent else mgu1
        lgu2 = mgu2.parent if mgu2 and mgu2.parent else mgu2
        if lgu1 and lgu2 and lgu1.name == lgu2.name:
            return self.scoring_config.get('same_lgu', 1.5)

        return 1.0

    def are_same_household(self, person1, person2) -> bool:
        """
        Check if two people live in the same household.

        Uses cached residence IDs for O(1) lookup.

        Args:
            person1: First person
            person2: Second person

        Returns:
            True if they live together, False otherwise
        """
        residence1_id = self.residence_cache.get(person1.id)
        residence2_id = self.residence_cache.get(person2.id)

        if not residence1_id or not residence2_id:
            return False

        return residence1_id == residence2_id

    def is_household_couple(self, person1, person2) -> bool:
        """
        Check if two people are marked as a household couple.

        Args:
            person1: First person
            person2: Second person

        Returns:
            True if they're a household couple, False otherwise
        """
        if 'household_couple' in person1.properties:
            if person1.properties['household_couple'] == person2.id:
                return True

        if 'household_couple' in person2.properties:
            if person2.properties['household_couple'] == person1.id:
                return True

        return False

    def are_already_partners(self, person1, person2) -> bool:
        """
        Check if two people are already romantic partners.

        Args:
            person1: First person
            person2: Second person

        Returns:
            True if already partners, False otherwise
        """
        if self.partners_key not in person1.properties:
            return False

        partners_dict = person1.properties[self.partners_key]

        return (person2.id in partners_dict.get('exclusive', [])) or \
               (person2.id in partners_dict.get('non_exclusive', []))

    def get_activity_venues(self, person) -> Set[int]:
        """
        Get set of venue IDs for person's primary activities.

        Args:
            person: Person to get venues for

        Returns:
            Set of venue IDs
        """
        venues = set()
        if 'primary_activity' in person.activity_map:
            for _, subsets in person.activity_map['primary_activity'].items():
                for subset in subsets:
                    if subset.venue:
                        venues.add(subset.venue.id)
        return venues

    def find_compatible_partner(self, person, candidates: List):
        """
        Find a compatible romantic partner for a person.

        Assumes candidates are already orientation-compatible.
        Scores by activity, geography, and ethnicity.

        Args:
            person: Person seeking a partner
            candidates: List of potential partners (pre-filtered by orientation)

        Returns:
            Selected partner or None if no compatible candidates
        """
        max_candidates = self.perf_config.get('max_candidates_per_search', len(candidates))

        if len(candidates) > max_candidates:
            candidates = list(np.random.choice(candidates, size=max_candidates, replace=False))

        # Filter by household exclusion
        non_household = []
        for candidate in candidates:
            if self.are_same_household(person, candidate):
                if not self.is_household_couple(person, candidate):
                    continue
            non_household.append(candidate)

        if not non_household:
            return None

        # Filter by age
        age_appropriate = self.filter_by_age_difference(person, non_household)
        if not age_appropriate:
            age_appropriate = non_household

        # Score candidates
        scores = []
        person_venues = self.get_activity_venues(person)
        activity_bonus = self.scoring_config.get('same_activity', 2.5)

        for candidate in age_appropriate:
            geo_multiplier = self.get_geographical_multiplier(person, candidate)

            # Check shared activity venue
            share_activity = False
            if person_venues:
                candidate_venues = self.get_activity_venues(candidate)
                share_activity = bool(person_venues & candidate_venues)

            activity_multiplier = activity_bonus if share_activity else 1.0

            ethnicity_prob = self.get_ethnicity_probability(person, candidate)
            if ethnicity_prob == 0:
                continue

            combined_score = ethnicity_prob * geo_multiplier * activity_multiplier
            scores.append((candidate, combined_score))

        if not scores:
            return np.random.choice(age_appropriate) if age_appropriate else None

        compatible_candidates = [c for c, _ in scores]
        weights = np.array([w for _, w in scores])
        weights = weights / weights.sum()

        return np.random.choice(compatible_candidates, p=weights)
