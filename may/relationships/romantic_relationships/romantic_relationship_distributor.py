"""
Generic romantic/sexual relationship distributor for population building.

This module handles:
- Sexual orientation assignment
- Creating romantic relationships (exclusive and non-exclusive)
- Coordinating with household relationships
- Handling infidelity/cheating

All logic is driven by YAML configuration - no hardcoded assumptions.
"""

import logging
import yaml
import numpy as np
import pandas as pd
from collections import defaultdict
from typing import List, Set, Tuple

from .compatibility_scorer import CompatibilityScorer
from .relationship_exporter import (
    export_relationships_csv,
    export_cheating_network_csv,
    print_statistics
)
from .relationship_utils import (
    group_by_geography,
    get_candidates_by_geography_tier,
    build_residence_cache,
    build_person_index
)

logger = logging.getLogger("romantic_relationships")


class RomanticRelationshipDistributor:
    """
    Distributes romantic/sexual relationships across a population.

    All parameters (orientations, probabilities, age differences, etc.)
    are configured via YAML - no hardcoding.

    Usage:
        distributor = RomanticRelationshipDistributor(
            world=world,
            config="yaml/relationships/romantic_relationships.yaml"
        )
        distributor.distribute_all()
    """

    def __init__(self, world, config: str | dict):
        """
        Initialize the romantic relationship distributor.

        Args:
            world: World object with population and geography
            config: Path to YAML config file or config dict
        """
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']

        # Storage keys (from config)
        storage = self.config.get('storage', {})
        self.orientation_key = storage.get('orientation_key', 'sexual_orientation')
        self.partners_key = storage.get('partners_key', 'romantic_partners')
        self.status_key = storage.get('status_key', 'relationship_status')

        # Tracking
        self.potential_cheaters: Set[int] = set()
        self.stats = defaultdict(int)

        # Load ethnicity partnership probabilities if enabled
        self.ethnicity_probs = None
        if self._is_ethnicity_enabled():
            self._load_ethnicity_probabilities()

        logger.info(f"Initialized {self.name} distributor")

    def _load_config(self, config) -> dict:
        """Load configuration from YAML file or dict."""
        if isinstance(config, str):
            logger.info(f"Loading config from: {config}")
            with open(config, 'r') as f:
                return yaml.safe_load(f)
        return config

    def _is_ethnicity_enabled(self) -> bool:
        """Check if ethnicity compatibility is enabled in config."""
        ethnicity_config = self.config.get('compatibility_scoring', {}).get('ethnicity', {})
        return ethnicity_config.get('enabled', False)

    def _load_ethnicity_probabilities(self):
        """
        Load ethnicity partnership probabilities from CSV.

        Creates a lookup: ethnicity_probs[person_ethnicity][partner_ethnicity] = probability
        Handles mapping M/O (CSV) to M and O (system codes).
        """
        ethnicity_config = self.config['compatibility_scoring']['ethnicity']
        data_file = ethnicity_config['data_file']
        code_mapping = ethnicity_config.get('code_mapping', {})

        logger.info(f"Loading ethnicity partnership probabilities from: {data_file}")

        try:
            df = pd.read_csv(data_file)

            # Build probability lookup
            self.ethnicity_probs = defaultdict(dict)

            for _, row in df.iterrows():
                person_eth = row['person_ethnicity']
                partner_eth = row['partner_ethnicity']
                probability = row['probability']

                # Map CSV codes to system codes
                person_codes = code_mapping.get(person_eth, [person_eth])
                partner_codes = code_mapping.get(partner_eth, [partner_eth])

                # Handle both list and string
                if not isinstance(person_codes, list):
                    person_codes = [person_codes]
                if not isinstance(partner_codes, list):
                    partner_codes = [partner_codes]

                # Apply probability to all code combinations
                for p_code in person_codes:
                    for partner_code in partner_codes:
                        self.ethnicity_probs[p_code][partner_code] = probability

            logger.info(f"Loaded ethnicity probabilities for {len(self.ethnicity_probs)} ethnicities")

        except Exception as e:
            logger.error(f"Failed to load ethnicity probabilities from {data_file}: {e}")
            logger.warning("Ethnicity compatibility will be disabled")
            self.ethnicity_probs = None

    def distribute_all(self):
        """
        Main entry point: Distribute romantic relationships to entire population.

        This runs a 5-pass algorithm:
        0. Assign sexual orientations
        1. Process household couples
        2. Create exclusive relationships for singles
        3. Create non-exclusive relationships
        4. Handle cheating/affairs
        """
        logger.info("=" * 60)
        logger.info("Starting romantic relationship distribution")
        logger.info("=" * 60)

        # Get all adults
        all_adults = [p for p in self.world.population.people if p.age >= 18]
        logger.info(f"Processing {len(all_adults):,} adults")

        # Build indices using utility functions
        self.person_by_id = build_person_index(all_adults)
        logger.info(f"Built person ID index for {len(self.person_by_id):,} adults")

        self.residence_cache = build_residence_cache(all_adults)
        logger.info(f"Cached residence IDs for {len(self.residence_cache):,} adults")

        # Create compatibility scorer with all needed data
        self.scorer = CompatibilityScorer(
            config=self.config,
            ethnicity_probs=self.ethnicity_probs,
            residence_cache=self.residence_cache,
            orientation_key=self.orientation_key,
            partners_key=self.partners_key
        )

        # Pass 0: Assign sexual orientations
        logger.info("\n[Pass 0] Assigning sexual orientations...")
        self._assign_all_orientations(all_adults)

        # Pass 1: Process household couples
        logger.info("\n[Pass 1] Processing household couples...")
        self._process_household_couples(all_adults)

        # Pass 2: Create exclusive relationships for singles
        logger.info("\n[Pass 2] Creating exclusive relationships for singles...")
        self._create_exclusive_relationships(all_adults)

        # Pass 3: Create non-exclusive relationships
        logger.info("\n[Pass 3] Creating non-exclusive relationships...")
        self._create_non_exclusive_relationships(all_adults)

        # Pass 4: Handle cheating/affairs
        logger.info("\n[Pass 4] Processing cheating/affairs...")
        self._process_cheating(all_adults)

        # Print statistics
        logger.info("\n" + "=" * 60)
        logger.info("Romantic relationship distribution complete")
        logger.info("=" * 60)
        print_statistics(all_adults, self.stats, self.status_key)

        # Export detailed CSVs
        export_relationships_csv(
            self.world.population,
            self.person_by_id,
            self.partners_key,
            self.status_key,
            self.orientation_key,
            "romantic_relationships_detailed.csv"
        )
        export_cheating_network_csv(
            self.world.population,
            self.person_by_id,
            self.partners_key,
            self.status_key,
            self.orientation_key,
            "cheating_network_detailed.csv"
        )

    # ========================================================================
    # PASS 0: SEXUAL ORIENTATION ASSIGNMENT
    # ========================================================================

    def _assign_all_orientations(self, all_adults: List):
        """
        Assign sexual orientations to everyone.

        - Singles/non-household people: Independent assignment
        - Household couples: Constrained assignment (must be compatible)
        """
        # Identify household couples
        household_couple_ids = set()
        for person in all_adults:
            if 'household_couple' in person.properties:
                household_couple_ids.add(person.id)

        # Assign to non-household people first
        count = 0
        for person in all_adults:
            if person.id not in household_couple_ids:
                self._assign_sexual_orientation(person)
                count += 1

        logger.info(f"  Assigned orientations to {count:,} non-household adults")
        logger.info(f"  {len(household_couple_ids):,} people in household couples "
                   f"(will be assigned in Pass 1)")

    def _assign_sexual_orientation(self, person):
        """
        Assign sexual orientation to a person based on configured probabilities.

        This is independent assignment - not constrained by any partner.
        Uses configured probabilities by sex, with optional age adjustments.
        """
        sex = person.sex
        orientation_config = self.config['sexual_orientations']

        # Get base probabilities for this sex
        base_probs = orientation_config['probabilities'].get(sex, {})
        if not base_probs:
            logger.warning(f"No orientation probabilities for sex={sex}, using defaults")
            # Fallback to first available sex config
            base_probs = list(orientation_config['probabilities'].values())[0]

        # Apply age adjustments if configured
        age_adjustments = orientation_config.get('age_adjustments', {})
        age_group = self.scorer.get_age_group(person)

        adjusted_probs = {}
        for orientation, base_prob in base_probs.items():
            # Get age multiplier for this orientation and age group
            multiplier = age_adjustments.get(age_group, {}).get(orientation, 1.0)
            adjusted_probs[orientation] = base_prob * multiplier

        # Normalize to sum to 1.0
        total = sum(adjusted_probs.values())
        if total == 0:
            logger.error(f"All orientation probabilities are zero for {person}")
            # Emergency fallback
            adjusted_probs = {list(base_probs.keys())[0]: 1.0}
            total = 1.0

        normalized_probs = {k: v / total for k, v in adjusted_probs.items()}

        # Sample orientation
        orientations = list(normalized_probs.keys())
        probabilities = list(normalized_probs.values())

        orientation = np.random.choice(orientations, p=probabilities)

        # Store in person.properties
        person.properties[self.orientation_key] = orientation

        # Track statistics
        self.stats[f'orientation_{orientation}'] += 1

    # ========================================================================
    # PASS 1: HOUSEHOLD COUPLES
    # ========================================================================

    def _process_household_couples(self, all_adults: List):
        """
        Process people already living together as couples.

        - Assign compatible sexual orientations
        - Decide relationship type (exclusive vs non-exclusive)
        - Create romantic relationship
        - Roll for potential cheating
        """
        household_couples = self._get_household_couples(all_adults)
        logger.info(f"  Found {len(household_couples)} household couples")

        if not household_couples:
            logger.info("  No household couples to process")
            return

        # Progress tracking
        total_couples = len(household_couples)
        progress_interval = max(1, total_couples // 10)  # Log every 10%

        for idx, (person1, person2) in enumerate(household_couples):
            # Progress logging every 10%
            if idx > 0 and idx % progress_interval == 0:
                progress_pct = (idx / total_couples) * 100
                logger.info(f"    Progress: {idx:,} / {total_couples:,} couples processed ({progress_pct:.1f}%)")
            # Assign compatible orientations
            self._assign_compatible_orientations(person1, person2)

            # Sample relationship type (exclusive vs non-exclusive)
            # Note: No "no_partner" option since they're living together!
            rel_type = self._sample_relationship_type_for_couple(person1, person2)

            # Create romantic relationship
            self._create_relationship(person1, person2, rel_type)

            # Roll for potential cheating (only for exclusive relationships)
            if rel_type == "exclusive":
                if np.random.random() < self._get_cheating_probability(person1):
                    self.potential_cheaters.add(person1.id)
                    self.stats['marked_as_potential_cheater'] += 1

                if np.random.random() < self._get_cheating_probability(person2):
                    self.potential_cheaters.add(person2.id)
                    self.stats['marked_as_potential_cheater'] += 1

        logger.info(f"  Processed {len(household_couples)} household couples")
        logger.info(f"  Marked {len(self.potential_cheaters)} potential cheaters")

    def _get_household_couples(self, all_adults: List) -> List[Tuple]:
        """
        Extract household couples from population.

        Returns:
            List of (person1, person2) tuples
        """
        couples = []
        processed = set()

        for person in all_adults:
            if person.id in processed:
                continue

            if 'household_couple' in person.properties:
                partner_id = person.properties['household_couple']

                # Find partner using O(1) index lookup
                partner = self.person_by_id.get(partner_id)

                if partner:
                    # Add couple (only once)
                    couples.append((person, partner))
                    processed.add(person.id)
                    processed.add(partner.id)
                else:
                    logger.warning(f"Person {person.id} has household_couple={partner_id} "
                                 f"but partner not found")

        return couples

    def _assign_compatible_orientations(self, person1, person2):
        """
        Assign sexual orientations to a household couple.

        Orientations must be mutually compatible given their sexes.
        Uses configured probabilities but filters to valid options.

        Args:
            person1: First person in couple
            person2: Second person in couple
        """
        sex1, sex2 = person1.sex, person2.sex
        orientation_config = self.config['sexual_orientations']

        # Get base probabilities for each person's sex
        base_probs1 = orientation_config['probabilities'].get(sex1, {})
        base_probs2 = orientation_config['probabilities'].get(sex2, {})

        # Determine which orientations are valid for this couple
        if sex1 == sex2:
            # Same-sex couple: both must be homosexual or bisexual
            valid_orientations = ['homosexual', 'bisexual']
        else:
            # Different-sex couple: both must be heterosexual or bisexual
            valid_orientations = ['heterosexual', 'bisexual']

        # Filter probabilities to valid orientations
        filtered_probs1 = {k: v for k, v in base_probs1.items() if k in valid_orientations}
        filtered_probs2 = {k: v for k, v in base_probs2.items() if k in valid_orientations}

        # Apply age adjustments if configured
        age_adjustments = orientation_config.get('age_adjustments', {})
        age_group1 = self.scorer.get_age_group(person1)
        age_group2 = self.scorer.get_age_group(person2)

        for orientation in list(filtered_probs1.keys()):
            mult = age_adjustments.get(age_group1, {}).get(orientation, 1.0)
            filtered_probs1[orientation] *= mult

        for orientation in list(filtered_probs2.keys()):
            mult = age_adjustments.get(age_group2, {}).get(orientation, 1.0)
            filtered_probs2[orientation] *= mult

        # Normalize to sum to 1.0
        total1 = sum(filtered_probs1.values())
        total2 = sum(filtered_probs2.values())

        if total1 == 0 or total2 == 0:
            # Emergency fallback - assign first valid orientation
            logger.warning(f"Couple {person1.id}-{person2.id} has zero probability "
                         f"for valid orientations. Using fallback.")
            person1.properties[self.orientation_key] = valid_orientations[0]
            person2.properties[self.orientation_key] = valid_orientations[0]
            self.stats[f'orientation_{valid_orientations[0]}'] += 2
            return

        normalized_probs1 = {k: v / total1 for k, v in filtered_probs1.items()}
        normalized_probs2 = {k: v / total2 for k, v in filtered_probs2.items()}

        # Sample orientations
        orientation1 = np.random.choice(
            list(normalized_probs1.keys()),
            p=list(normalized_probs1.values())
        )
        orientation2 = np.random.choice(
            list(normalized_probs2.keys()),
            p=list(normalized_probs2.values())
        )

        # Store in person.properties
        person1.properties[self.orientation_key] = orientation1
        person2.properties[self.orientation_key] = orientation2

        # Track statistics
        self.stats[f'orientation_{orientation1}'] += 1
        self.stats[f'orientation_{orientation2}'] += 1
        self.stats['household_couples_processed'] += 1

    def _sample_relationship_type_for_couple(self, person1, person2) -> str:
        """
        Sample relationship type for a household couple.

        Since they're living together, only sample between exclusive and non_exclusive
        (no "no_partner" option).

        Uses age-adjusted probabilities averaged between both partners.

        Args:
            person1: First person in couple
            person2: Second person in couple

        Returns:
            "exclusive" or "non_exclusive"
        """
        rel_type_config = self.config['relationship_types']
        base_probs = rel_type_config['base_probabilities']
        age_mults = rel_type_config.get('age_multipliers', {})

        # Get age groups
        age_group1 = self.scorer.get_age_group(person1)
        age_group2 = self.scorer.get_age_group(person2)

        # Get age multipliers for each person
        mult1 = age_mults.get(age_group1, {})
        mult2 = age_mults.get(age_group2, {})

        # Calculate adjusted probabilities (average of both partners)
        exclusive_mult = (mult1.get('exclusive', 1.0) + mult2.get('exclusive', 1.0)) / 2
        non_exclusive_mult = (mult1.get('non_exclusive', 1.0) + mult2.get('non_exclusive', 1.0)) / 2

        # Apply multipliers to base probabilities
        exclusive_prob = base_probs['exclusive'] * exclusive_mult
        non_exclusive_prob = base_probs['non_exclusive'] * non_exclusive_mult

        # Normalize (only these two options for couples)
        total = exclusive_prob + non_exclusive_prob
        exclusive_prob /= total
        non_exclusive_prob /= total

        # Sample
        rel_type = np.random.choice(
            ['exclusive', 'non_exclusive'],
            p=[exclusive_prob, non_exclusive_prob]
        )

        # Track statistics
        self.stats[f'relationship_type_{rel_type}'] += 1

        return rel_type

    def _create_relationship(self, person1, person2, relationship_type: str):
        """
        Create a romantic relationship between two people.

        Stores the relationship in person.properties for both people.

        Args:
            person1: First person
            person2: Second person
            relationship_type: "exclusive" or "non_exclusive"
        """
        # Initialize romantic_partners if not exists
        if self.partners_key not in person1.properties:
            person1.properties[self.partners_key] = {'exclusive': [], 'non_exclusive': []}
        if self.partners_key not in person2.properties:
            person2.properties[self.partners_key] = {'exclusive': [], 'non_exclusive': []}

        # Add each other as partners
        person1.properties[self.partners_key][relationship_type].append(person2.id)
        person2.properties[self.partners_key][relationship_type].append(person1.id)

        # Set relationship status
        person1.properties[self.status_key] = {
            'type': relationship_type,
            'consensual': True
        }
        person2.properties[self.status_key] = {
            'type': relationship_type,
            'consensual': True
        }

        # Track statistics
        self.stats['relationships_created'] += 1
        self.stats[f'{relationship_type}_relationships_created'] += 1

    def _get_cheating_probability(self, person) -> float:
        """
        Get the probability that a person will cheat.

        Uses base probability with age-based multipliers.

        Args:
            person: Person to calculate probability for

        Returns:
            Probability (0.0 to 1.0)
        """
        cheating_config = self.config['cheating']
        base_prob = cheating_config['base_probability']
        age_mults = cheating_config.get('age_multipliers', {})

        age_group = self.scorer.get_age_group(person)
        multiplier = age_mults.get(age_group, 1.0)

        probability = base_prob * multiplier

        # Clamp to [0, 1]
        return max(0.0, min(1.0, probability))

    def _get_singles(self, all_adults: List) -> List:
        """
        Get all singles (people without existing romantic relationships).

        Returns:
            List of people who are single
        """
        singles = []
        for person in all_adults:
            # Check if has household couple
            if 'household_couple' in person.properties:
                continue

            # Check if has existing relationship
            if self.status_key in person.properties:
                status = person.properties[self.status_key]
                if status.get('type') != 'no_partner':
                    continue

            # This person is single
            singles.append(person)

        return singles

    def _wants_exclusive_relationship(self, person) -> bool:
        """
        Sample whether a person wants an exclusive relationship.

        Uses age-adjusted probabilities for exclusive vs no_partner.

        Args:
            person: Person to check

        Returns:
            True if person wants exclusive relationship, False otherwise
        """
        rel_type_config = self.config['relationship_types']
        base_probs = rel_type_config['base_probabilities']
        age_mults = rel_type_config.get('age_multipliers', {})

        age_group = self.scorer.get_age_group(person)
        mult = age_mults.get(age_group, {})

        # Adjust probabilities
        exclusive_prob = base_probs['exclusive'] * mult.get('exclusive', 1.0)
        no_partner_prob = base_probs['no_partner'] * mult.get('no_partner', 1.0)

        # Normalize (only these two options for singles in this pass)
        total = exclusive_prob + no_partner_prob
        exclusive_prob /= total

        # Sample
        return np.random.random() < exclusive_prob

    def _wants_non_exclusive_relationship(self, person) -> bool:
        """
        Sample whether a person wants a non-exclusive relationship.

        Uses age-adjusted probabilities for non_exclusive vs no_partner.

        Args:
            person: Person to check

        Returns:
            True if person wants non-exclusive relationship, False otherwise
        """
        rel_type_config = self.config['relationship_types']
        base_probs = rel_type_config['base_probabilities']
        age_mults = rel_type_config.get('age_multipliers', {})

        age_group = self.scorer.get_age_group(person)
        mult = age_mults.get(age_group, {})

        # Adjust probabilities
        non_exclusive_prob = base_probs['non_exclusive'] * mult.get('non_exclusive', 1.0)
        no_partner_prob = base_probs['no_partner'] * mult.get('no_partner', 1.0)

        # Normalize
        total = non_exclusive_prob + no_partner_prob
        non_exclusive_prob /= total

        # Sample
        return np.random.random() < non_exclusive_prob

    def _get_max_partners(self, person, relationship_context: str) -> int:
        """
        Get maximum number of partners for a person.

        Based on age, sex, and relationship context.

        Args:
            person: Person to check
            relationship_context: "exclusive", "non_exclusive", or "cheating"

        Returns:
            Maximum number of partners
        """
        partner_limits = self.config['partner_limits']

        if relationship_context == 'exclusive':
            return partner_limits['exclusive']['default']

        # For non_exclusive or cheating, look up by age and sex
        context_key = 'non_exclusive' if relationship_context == 'non_exclusive' else 'cheating'
        limits_by_age_sex = partner_limits[context_key].get('by_age_and_sex', {})

        age_group = self.scorer.get_age_group(person)
        sex = person.sex

        # Look up limit
        if age_group in limits_by_age_sex:
            if sex in limits_by_age_sex[age_group]:
                return limits_by_age_sex[age_group][sex]

        # Fallback to default
        return partner_limits[context_key].get('default', 1)

    # ========================================================================
    # PASS 2: EXCLUSIVE RELATIONSHIPS FOR SINGLES
    # ========================================================================

    def _create_exclusive_relationships(self, all_adults: List):
        """
        Create exclusive relationships for singles.

        Uses tiered geographical search:
        1. Match within same M.G.U first (highest priority)
        2. Then within same L.G.U
        3. Finally, wider search if needed

        This dramatically reduces search space for large populations.
        """
        # Get all singles (no household couple, no existing relationship)
        singles = self._get_singles(all_adults)
        logger.info(f"  Found {len(singles)} singles")

        if not singles:
            logger.info("  No singles to process")
            return

        # Shuffle for randomness
        np.random.shuffle(singles)

        # Determine who wants exclusive relationships
        exclusive_seekers = []
        for person in singles:
            # Sample whether this person wants exclusive relationship
            if self._wants_exclusive_relationship(person):
                exclusive_seekers.append(person)

        logger.info(f"  {len(exclusive_seekers)} singles want exclusive relationships")

        # PRE-BUILD orientation-based indices to avoid millions of checks
        # Group by (orientation, sex) for O(1) lookup of compatible candidates
        seekers_by_orientation_sex = defaultdict(list)
        compat_rules = self.config['compatibility_rules']

        for person in exclusive_seekers:
            orientation = person.properties.get(self.orientation_key)
            if not orientation:
                continue
            # Index by what this person is attracted to
            # E.g., heterosexual male goes into group that heterosexual females can match with
            for partner_orientation, sex_rules in compat_rules.items():
                for partner_sex, compatible_sexes in sex_rules.items():
                    if person.sex in compatible_sexes:
                        key = (partner_orientation, partner_sex)
                        seekers_by_orientation_sex[key].append(person)

        logger.info(f"  Built orientation index with {len(seekers_by_orientation_sex)} groups")

        # Group seekers by geography for efficient matching
        seekers_by_mgu, seekers_by_lgu = group_by_geography(exclusive_seekers)
        logger.info(f"  Grouped into {len(seekers_by_mgu)} M.G.U groups and {len(seekers_by_lgu)} L.G.U groups")

        # Track matched people
        matched = set()
        relationships_created = 0

        # Progress tracking
        total_seekers = len(exclusive_seekers)
        progress_interval = max(1, total_seekers // 10)  # Log every 10%

        for idx, person in enumerate(exclusive_seekers):
            # Progress logging every 10%
            if idx > 0 and idx % progress_interval == 0:
                progress_pct = (idx / total_seekers) * 100
                logger.info(f"    Progress: {idx:,} / {total_seekers:,} seekers processed "
                           f"({progress_pct:.1f}%), {relationships_created:,} relationships created")

            if person.id in matched:
                continue  # Already matched

            # Get orientation-compatible candidates FIRST (eliminates millions of checks!)
            person_orientation = person.properties.get(self.orientation_key)
            if not person_orientation:
                continue

            orientation_key = (person_orientation, person.sex)
            orientation_compatible = seekers_by_orientation_sex.get(orientation_key, [])

            if not orientation_compatible:
                continue

            # Get geographical tier from orientation-compatible candidates only
            geo_group = get_candidates_by_geography_tier(
                person, orientation_compatible, seekers_by_mgu, seekers_by_lgu
            )

            # Filter once: unmatched and not self (fast set lookup)
            candidates = [p for p in geo_group if p.id not in matched and p.id != person.id]

            if not candidates:
                continue  # No available candidates

            # Find compatible partner (already orientation-filtered!)
            partner = self.scorer.find_compatible_partner(person, candidates)

            if partner:
                # Create exclusive relationship
                self._create_relationship(person, partner, 'exclusive')
                relationships_created += 1

                # Mark both as matched
                matched.add(person.id)
                matched.add(partner.id)

                # Roll for potential cheating
                if np.random.random() < self._get_cheating_probability(person):
                    self.potential_cheaters.add(person.id)
                    self.stats['marked_as_potential_cheater'] += 1

                if np.random.random() < self._get_cheating_probability(partner):
                    self.potential_cheaters.add(partner.id)
                    self.stats['marked_as_potential_cheater'] += 1

        logger.info(f"  Created {relationships_created} exclusive relationships for singles")
        logger.info(f"  {len(exclusive_seekers) - len(matched)} singles remain unmatched")

    # ========================================================================
    # PASS 3: NON-EXCLUSIVE RELATIONSHIPS
    # ========================================================================

    def _create_non_exclusive_relationships(self, all_adults: List):
        """
        Create non-exclusive (consensual non-monogamous) relationships.

        Uses tiered geographical search for efficiency at scale.
        """
        # Get remaining singles
        singles = self._get_singles(all_adults)
        logger.info(f"  Found {len(singles)} remaining singles")

        if not singles:
            logger.info("  No singles to process")
            return

        # Shuffle for randomness
        np.random.shuffle(singles)

        # Determine who wants non-exclusive relationships
        non_exclusive_seekers = []
        for person in singles:
            if self._wants_non_exclusive_relationship(person):
                # Mark as non-exclusive seeker
                person.properties[self.status_key] = {
                    'type': 'non_exclusive',
                    'consensual': True
                }
                non_exclusive_seekers.append(person)

        logger.info(f"  {len(non_exclusive_seekers)} singles want non-exclusive relationships")

        if not non_exclusive_seekers:
            return

        # Group seekers by geography for efficient matching
        seekers_by_mgu, seekers_by_lgu = group_by_geography(non_exclusive_seekers)
        logger.info(f"  Grouped into {len(seekers_by_mgu)} M.G.U groups and {len(seekers_by_lgu)} L.G.U groups")

        # Track current partner counts
        partner_counts = {p.id: 0 for p in non_exclusive_seekers}

        # Match non-exclusive seekers with each other
        relationships_created = 0

        # Progress tracking
        total_seekers = len(non_exclusive_seekers)
        progress_interval = max(1, total_seekers // 10)  # Log every 10%

        for idx, person in enumerate(non_exclusive_seekers):
            # Progress logging every 10%
            if idx > 0 and idx % progress_interval == 0:
                progress_pct = (idx / total_seekers) * 100
                logger.info(f"    Progress: {idx:,} / {total_seekers:,} seekers processed "
                           f"({progress_pct:.1f}%), {relationships_created:,} relationships created")
            # Check if person has reached their limit
            max_partners = self._get_max_partners(person, 'non_exclusive')
            current_partners = partner_counts[person.id]

            if current_partners >= max_partners:
                continue  # Already at limit

            # Determine how many more partners this person wants
            n_partners_to_add = max_partners - current_partners

            # Sample actual number (might want fewer than max)
            if n_partners_to_add > 1:
                # Probabilistically choose fewer partners
                n_partners_to_add = np.random.randint(1, n_partners_to_add + 1)

            # Get geographical tier (no matched filtering for non-exclusive)
            geo_group = get_candidates_by_geography_tier(
                person, non_exclusive_seekers, seekers_by_mgu, seekers_by_lgu
            )

            # Filter to available candidates (not self, not at limit, not already partnered)
            candidates = []
            for candidate in geo_group:
                if candidate.id == person.id:
                    continue

                # Check if candidate has room for more partners
                candidate_max = self._get_max_partners(candidate, 'non_exclusive')
                candidate_current = partner_counts[candidate.id]

                if candidate_current < candidate_max:
                    # Check if not already partners
                    if not self.scorer.are_already_partners(person, candidate):
                        candidates.append(candidate)

            if not candidates:
                continue

            # Create relationships
            for _ in range(n_partners_to_add):
                if not candidates:
                    break

                # Find compatible partner
                partner = self.scorer.find_compatible_partner(person, candidates)

                if partner:
                    # Create non-exclusive relationship
                    self._create_relationship(person, partner, 'non_exclusive')
                    relationships_created += 1

                    # Update partner counts
                    partner_counts[person.id] += 1
                    partner_counts[partner.id] += 1

                    # Remove partner from candidates
                    candidates.remove(partner)

                    # Check if person reached limit
                    if partner_counts[person.id] >= max_partners:
                        break

        logger.info(f"  Created {relationships_created} non-exclusive relationships")

        # Mark remaining singles as having no partner
        remaining_singles = self._get_singles(all_adults)
        for person in remaining_singles:
            if self.status_key not in person.properties:
                person.properties[self.status_key] = {
                    'type': 'no_partner',
                    'consensual': True
                }
                self.stats['no_partner'] += 1

    # ========================================================================
    # PASS 4: CHEATING/AFFAIRS
    # ========================================================================

    def _process_cheating(self, all_adults: List):
        """
        Process cheating/affairs for people in exclusive relationships.

        Uses geographical partitioning for efficiency.
        """
        logger.info(f"  Processing {len(self.potential_cheaters)} potential cheaters")

        if not self.potential_cheaters:
            logger.info("  No potential cheaters to process")
            return

        # Get people who could be affair partners
        # These are people in non-exclusive relationships or singles willing to be affair partners
        affair_partner_pool = []

        for person in all_adults:
            # Skip if person is in the cheaters set
            if person.id in self.potential_cheaters:
                continue

            # Get status (empty dict if not set)
            status = person.properties.get(self.status_key, {})

            # Include if in non-exclusive relationship
            if status.get('type') == 'non_exclusive':
                affair_partner_pool.append(person)
                continue

            # Include singles if they're open to it (sample based on probability)
            if status.get('type') == 'no_partner':
                # Use non-exclusive probability as proxy for affair willingness
                if self._wants_non_exclusive_relationship(person):
                    affair_partner_pool.append(person)

        logger.info(f"  Found {len(affair_partner_pool)} potential affair partners")

        # Group affair partners by geography for efficient matching
        partners_by_mgu, partners_by_lgu = group_by_geography(affair_partner_pool)
        logger.info(f"  Grouped affair partners into {len(partners_by_mgu)} M.G.U groups")

        # Track removed partners (at capacity) to avoid double-removal errors
        removed_partners = set()
        affairs_created = 0

        # Progress tracking
        total_cheaters = len(self.potential_cheaters)
        progress_interval = max(1, total_cheaters // 10)  # Log every 10%

        for idx, cheater_id in enumerate(self.potential_cheaters):
            # Progress logging every 10%
            if idx > 0 and idx % progress_interval == 0:
                progress_pct = (idx / total_cheaters) * 100
                logger.info(f"    Progress: {idx:,} / {total_cheaters:,} cheaters processed "
                           f"({progress_pct:.1f}%), {affairs_created:,} affairs created")

            # Find the cheater using O(1) index lookup
            cheater = self.person_by_id.get(cheater_id)
            if not cheater:
                continue

            # Get max affairs for this person
            max_affairs = self._get_max_partners(cheater, 'cheating')

            # Count current non-exclusive partners
            current_affairs = 0
            if self.partners_key in cheater.properties:
                current_affairs = len(cheater.properties[self.partners_key].get('non_exclusive', []))

            if current_affairs >= max_affairs:
                continue  # Already has enough affairs

            # Determine how many affairs to create
            n_affairs = max_affairs - current_affairs

            # Sample actual number (might have fewer)
            if n_affairs > 1:
                n_affairs = np.random.randint(1, n_affairs + 1)

            # Find compatible affair partners
            for _ in range(n_affairs):
                if not affair_partner_pool:
                    break

                # Get geographical tier
                geo_group = get_candidates_by_geography_tier(
                    cheater, affair_partner_pool, partners_by_mgu, partners_by_lgu
                )

                # Filter once: not removed, not already partners
                available = [p for p in geo_group
                           if p.id not in removed_partners
                           and not self.scorer.are_already_partners(cheater, p)]

                if not available:
                    break

                # Find compatible partner
                partner = self.scorer.find_compatible_partner(cheater, available)

                if partner:
                    # Create non-exclusive relationship
                    self._create_relationship(cheater, partner, 'non_exclusive')
                    affairs_created += 1

                    # Mark cheater's relationship as non-consensual
                    if self.status_key in cheater.properties:
                        cheater.properties[self.status_key]['consensual'] = False

                    # Remove partner from pool if they're at their limit
                    if partner.id in self.potential_cheaters:
                        # Partner is also a cheater
                        partner_max = self._get_max_partners(partner, 'cheating')
                    else:
                        # Partner is in non-exclusive relationship
                        partner_max = self._get_max_partners(partner, 'non_exclusive')

                    partner_current = len(partner.properties[self.partners_key].get('non_exclusive', []))
                    if partner_current >= partner_max:
                        # Mark as removed (don't remove from list to avoid errors)
                        removed_partners.add(partner.id)

        logger.info(f"  Created {affairs_created} affairs")
        logger.info(f"  {len([p for p in all_adults if self.status_key in p.properties and not p.properties[self.status_key].get('consensual', True)])} people now cheating")

