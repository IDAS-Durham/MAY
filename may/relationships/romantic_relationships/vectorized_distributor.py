"""
Vectorized romantic relationship distributor for large-scale simulations.

This module provides a NumPy-based implementation that can handle 60M+ people
by avoiding Python loops and using batch operations.

Key optimizations:
1. All attributes extracted into NumPy arrays upfront
2. Vectorized orientation assignment
3. Pool-based batch matching instead of per-person search
4. Geographic partitioning with NumPy fancy indexing
5. Accept/reject sampling for constraints (age, ethnicity)
"""

import logging
import yaml
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import time

from .numba_matcher import (
    match_two_pools_fast,
    match_single_pool_fast,
    match_with_ethnicity_fast,
    vectorized_age_filter
)
from .relationship_exporter import (
    export_relationships_csv,
    export_cheating_network_csv
)

logger = logging.getLogger("romantic_relationships")

# Encoding constants
ORIENTATION_HET = 0
ORIENTATION_HOM = 1
ORIENTATION_BI = 2

SEX_FEMALE = 0
SEX_MALE = 1

REL_NO_PARTNER = 0
REL_EXCLUSIVE = 1
REL_NON_EXCLUSIVE = 2


class VectorizedRomanticDistributor:
    """
    High-performance romantic relationship distributor using vectorized operations.

    Designed for 60M+ population scale where every second matters.
    """

    def __init__(self, world, config: str | dict):
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']

        # Storage keys
        storage = self.config.get('storage', {})
        self.orientation_key = storage.get('orientation_key', 'sexual_orientation')
        self.partners_key = storage.get('partners_key', 'romantic_partners')
        self.status_key = storage.get('status_key', 'relationship_status')

        # Statistics
        self.stats = defaultdict(int)

        # Load ethnicity matrix if enabled
        self.ethnicity_matrix = None
        self.ethnicity_codes = {}
        if self._is_ethnicity_enabled():
            self._load_ethnicity_matrix()

        logger.info(f"Initialized vectorized {self.name} distributor")

    def _load_config(self, config) -> dict:
        if isinstance(config, str):
            with open(config, 'r') as f:
                return yaml.safe_load(f)
        return config

    def _is_ethnicity_enabled(self) -> bool:
        return self.config.get('compatibility_scoring', {}).get('ethnicity', {}).get('enabled', False)

    def _load_ethnicity_matrix(self):
        """Load ethnicity probabilities as a NumPy matrix for fast lookup."""
        ethnicity_config = self.config['compatibility_scoring']['ethnicity']
        data_file = ethnicity_config['data_file']
        code_mapping = ethnicity_config.get('code_mapping', {})

        try:
            df = pd.read_csv(data_file)

            # Get unique ethnicities
            all_eths = set(df['person_ethnicity'].unique()) | set(df['partner_ethnicity'].unique())

            # Expand code mappings
            expanded_eths = set()
            for eth in all_eths:
                if eth in code_mapping:
                    codes = code_mapping[eth]
                    if isinstance(codes, list):
                        expanded_eths.update(codes)
                    else:
                        expanded_eths.add(codes)
                else:
                    expanded_eths.add(eth)

            # Create encoding
            self.ethnicity_codes = {eth: i for i, eth in enumerate(sorted(expanded_eths))}
            n_eth = len(self.ethnicity_codes)

            # Build probability matrix
            self.ethnicity_matrix = np.ones((n_eth, n_eth), dtype=np.float32)

            for _, row in df.iterrows():
                p_eth = row['person_ethnicity']
                partner_eth = row['partner_ethnicity']
                prob = row['probability']

                # Get all codes this maps to
                p_codes = code_mapping.get(p_eth, [p_eth])
                partner_codes = code_mapping.get(partner_eth, [partner_eth])

                if not isinstance(p_codes, list):
                    p_codes = [p_codes]
                if not isinstance(partner_codes, list):
                    partner_codes = [partner_codes]

                for pc in p_codes:
                    for ptc in partner_codes:
                        if pc in self.ethnicity_codes and ptc in self.ethnicity_codes:
                            i, j = self.ethnicity_codes[pc], self.ethnicity_codes[ptc]
                            self.ethnicity_matrix[i, j] = prob

            logger.info(f"Loaded ethnicity matrix: {n_eth}x{n_eth}")

        except Exception as e:
            logger.error(f"Failed to load ethnicity probabilities: {e}")
            self.ethnicity_matrix = None

    def distribute_all(self):
        """Main entry point for relationship distribution."""
        total_start = time.time()

        logger.info("=" * 60)
        logger.info("Starting VECTORIZED romantic relationship distribution")
        logger.info("=" * 60)

        # Get all adults
        all_adults = [p for p in self.world.population.people if p.age >= 18]
        n = len(all_adults)
        logger.info(f"Processing {n:,} adults")

        # Step 1: Extract all attributes into NumPy arrays
        logger.info("\n[Step 1] Extracting attributes to NumPy arrays...")
        t0 = time.time()
        arrays = self._build_attribute_arrays(all_adults)
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 2: Assign sexual orientations (vectorized)
        logger.info("\n[Step 2] Assigning sexual orientations (vectorized)...")
        t0 = time.time()
        orientations = self._vectorized_orientation_assignment(arrays)
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 3: Process household couples
        logger.info("\n[Step 3] Processing household couples...")
        t0 = time.time()
        partners, rel_types, consensual = self._process_household_couples_vectorized(
            arrays, orientations
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 4: Create exclusive relationships for singles
        logger.info("\n[Step 4] Creating exclusive relationships (batch matching)...")
        t0 = time.time()
        partners, rel_types = self._batch_exclusive_matching(
            arrays, orientations, partners, rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 5: Create non-exclusive relationships
        logger.info("\n[Step 5] Creating non-exclusive relationships...")
        t0 = time.time()
        partners, rel_types, non_exclusive_partners = self._batch_non_exclusive_matching(
            arrays, orientations, partners, rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 6: Handle cheating
        logger.info("\n[Step 6] Processing cheating/affairs...")
        t0 = time.time()
        partners, consensual, affair_partners = self._process_cheating_vectorized(
            arrays, orientations, partners, rel_types, consensual
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 7: Write results back to person objects
        logger.info("\n[Step 7] Writing results to person objects...")
        t0 = time.time()
        self._write_results(all_adults, arrays, orientations, partners, rel_types, consensual, affair_partners, non_exclusive_partners)
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Print statistics
        self._print_statistics(orientations, partners, rel_types, consensual)

        # Export detailed CSVs
        person_by_id = {p.id: p for p in all_adults}
        export_relationships_csv(
            self.world.population,
            person_by_id,
            self.partners_key,
            self.status_key,
            self.orientation_key,
            "romantic_relationships_detailed.csv"
        )
        export_cheating_network_csv(
            self.world.population,
            person_by_id,
            self.partners_key,
            self.status_key,
            self.orientation_key,
            "cheating_network_detailed.csv"
        )

        total_time = time.time() - total_start
        logger.info("\n" + "=" * 60)
        logger.info(f"Vectorized distribution complete in {total_time:.2f}s")
        logger.info(f"Throughput: {n / total_time:,.0f} people/second")
        logger.info("=" * 60)

    def _build_attribute_arrays(self, adults: List) -> Dict[str, np.ndarray]:
        """Extract all relevant attributes into NumPy arrays for fast access."""
        n = len(adults)

        # Pre-allocate arrays
        ids = np.empty(n, dtype=np.int64)
        sex = np.empty(n, dtype=np.int8)
        age = np.empty(n, dtype=np.int16)
        mgu_codes = np.empty(n, dtype=np.int32)
        lgu_codes = np.empty(n, dtype=np.int32)
        eth_codes = np.empty(n, dtype=np.int16)
        household_couple = np.full(n, -1, dtype=np.int64)
        residence_ids = np.full(n, -1, dtype=np.int64)

        # Build MGU/LGU encodings
        mgu_encoder = {}
        lgu_encoder = {}
        mgu_to_lgu = {}
        mgu_counter = 0
        lgu_counter = 0

        # Build venue -> people index for activity matching
        # venue_id -> set of person indices who work/study there
        venue_to_people = defaultdict(set)

        # Single pass to extract all attributes
        for i, person in enumerate(adults):
            ids[i] = person.id
            sex[i] = SEX_MALE if person.sex.lower().startswith('m') else SEX_FEMALE
            age[i] = person.age

            # Geography encoding
            if person.geographical_unit:
                unit = person.geographical_unit
                mgu = unit.parent if unit.parent else unit
                lgu = mgu.parent if mgu and mgu.parent else mgu

                mgu_name = mgu.name if mgu else "unknown"
                lgu_name = lgu.name if lgu else "unknown"

                if mgu_name not in mgu_encoder:
                    mgu_encoder[mgu_name] = mgu_counter
                    mgu_counter += 1

                if lgu_name not in lgu_encoder:
                    lgu_encoder[lgu_name] = lgu_counter
                    lgu_counter += 1

                mgu_codes[i] = mgu_encoder[mgu_name]
                lgu_codes[i] = lgu_encoder[lgu_name]
                mgu_to_lgu[mgu_encoder[mgu_name]] = lgu_encoder[lgu_name]
            else:
                mgu_codes[i] = -1
                lgu_codes[i] = -1

            # Ethnicity encoding
            eth = person.properties.get('ethnicity', 'unknown')
            if eth not in self.ethnicity_codes:
                self.ethnicity_codes[eth] = len(self.ethnicity_codes)
            eth_codes[i] = self.ethnicity_codes[eth]

            # Household couple
            if 'household_couple' in person.properties:
                household_couple[i] = person.properties['household_couple']

            # Residence
            if person.residence:
                residence_ids[i] = person.residence.id

            # Extract activity venues (workplace, school, etc.)
            if hasattr(person, 'activity_map') and 'primary_activity' in person.activity_map:
                for _, subsets in person.activity_map['primary_activity'].items():
                    for subset in subsets:
                        if subset.venue:
                            venue_to_people[subset.venue.id].add(i)

        # Build reverse lookup: id -> index
        id_to_idx = {ids[i]: i for i in range(n)}

        # Build person -> venues mapping for fast lookup
        person_venues = defaultdict(set)
        for venue_id, people_set in venue_to_people.items():
            for person_idx in people_set:
                person_venues[person_idx].add(venue_id)

        logger.info(f"  Extracted {n:,} adults into arrays")
        logger.info(f"  {len(mgu_encoder)} unique MGUs, {len(lgu_encoder)} unique LGUs")
        logger.info(f"  {len(venue_to_people)} unique activity venues indexed")

        return {
            'ids': ids,
            'sex': sex,
            'age': age,
            'mgu': mgu_codes,
            'lgu': lgu_codes,
            'eth': eth_codes,
            'household_couple': household_couple,
            'residence': residence_ids,
            'id_to_idx': id_to_idx,
            'mgu_to_lgu': mgu_to_lgu,
            'venue_to_people': dict(venue_to_people),
            'person_venues': dict(person_venues),
            'n': n
        }

    def _vectorized_orientation_assignment(self, arrays: Dict[str, np.ndarray]) -> np.ndarray:
        """Assign sexual orientations to all adults using weighted sampling."""
        n = len(arrays['age'])
        sex = arrays['sex']
        household_couple = arrays['household_couple']

        orientations = np.zeros(n, dtype=np.int8)  # Default to HET (0)
        orientation_config = self.config['sexual_orientations']
        age_adjustments = orientation_config.get('age_adjustments', {})

        # Get base probabilities by sex
        probs_by_sex = {}
        for s, s_code in [('male', SEX_MALE), ('female', SEX_FEMALE)]:
            base = orientation_config['probabilities'].get(s, {})
            probs_by_sex[s_code] = np.array([
                base.get('heterosexual', 0.95),
                base.get('homosexual', 0.03),
                base.get('bisexual', 0.02)
            ])

        # Assign to non-household-coupled people first
        not_coupled = household_couple < 0

        for s_code in [SEX_MALE, SEX_FEMALE]:
            mask = (sex == s_code) & not_coupled
            indices = np.where(mask)[0]

            if len(indices) == 0:
                continue

            # Get base probabilities
            probs = probs_by_sex[s_code].copy()

            # For simplicity, use base probabilities (age adjustment would require
            # per-person probabilities which is slower but still vectorizable)
            probs = probs / probs.sum()

            # Vectorized sampling
            orientations[indices] = np.random.choice(
                [ORIENTATION_HET, ORIENTATION_HOM, ORIENTATION_BI],
                size=len(indices),
                p=probs
            )

        # Track stats
        self.stats['orientation_heterosexual'] = (orientations[not_coupled] == ORIENTATION_HET).sum()
        self.stats['orientation_homosexual'] = (orientations[not_coupled] == ORIENTATION_HOM).sum()
        self.stats['orientation_bisexual'] = (orientations[not_coupled] == ORIENTATION_BI).sum()

        logger.info(f"  Assigned orientations to {not_coupled.sum():,} non-household adults")
        logger.info(f"  Distribution: HET={self.stats['orientation_heterosexual']:,}, "
                    f"HOM={self.stats['orientation_homosexual']:,}, "
                    f"BI={self.stats['orientation_bisexual']:,}")

        return orientations

    def _process_household_couples_vectorized(
        self,
        arrays: Dict,
        orientations: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Process household couples using vectorized operations."""
        n = arrays['n']
        ids = arrays['ids']
        sex = arrays['sex']
        household_couple = arrays['household_couple']
        id_to_idx = arrays['id_to_idx']

        # Initialize partner arrays
        # partners[i] stores list of partner indices (as variable-length, we use -1 padding)
        # For simplicity, store primary exclusive partner only
        partners = np.full(n, -1, dtype=np.int64)
        rel_types = np.full(n, REL_NO_PARTNER, dtype=np.int8)
        consensual = np.ones(n, dtype=bool)

        # Find all people with household couples
        has_couple = household_couple >= 0
        coupled_indices = np.where(has_couple)[0]

        # Get relationship type probabilities for household couples
        # (only exclusive or non_exclusive - no "no_partner" since they live together)
        rel_config = self.config['relationship_types']['base_probabilities']
        prob_exclusive = rel_config['exclusive']
        prob_non_exclusive = rel_config['non_exclusive']
        total_prob = prob_exclusive + prob_non_exclusive
        prob_exclusive_normalized = prob_exclusive / total_prob

        # Process each coupled person
        processed = set()
        couples_count = 0
        exclusive_count = 0
        non_exclusive_count = 0

        for idx in coupled_indices:
            if idx in processed:
                continue

            partner_id = household_couple[idx]
            if partner_id not in id_to_idx:
                continue

            partner_idx = id_to_idx[partner_id]

            # Assign compatible orientations
            sex1, sex2 = sex[idx], sex[partner_idx]

            if sex1 == sex2:
                # Same-sex couple: homosexual or bisexual
                valid = [ORIENTATION_HOM, ORIENTATION_BI]
                probs = np.array([0.6, 0.4])
            else:
                # Different-sex couple: heterosexual or bisexual
                valid = [ORIENTATION_HET, ORIENTATION_BI]
                probs = np.array([0.9, 0.1])

            probs = probs / probs.sum()
            orientations[idx] = np.random.choice(valid, p=probs)
            orientations[partner_idx] = np.random.choice(valid, p=probs)

            # Sample relationship type (exclusive or non-exclusive)
            if np.random.random() < prob_exclusive_normalized:
                rel_type = REL_EXCLUSIVE
                exclusive_count += 1
            else:
                rel_type = REL_NON_EXCLUSIVE
                non_exclusive_count += 1

            # Create relationship
            partners[idx] = partner_idx
            partners[partner_idx] = idx
            rel_types[idx] = rel_type
            rel_types[partner_idx] = rel_type

            processed.add(idx)
            processed.add(partner_idx)
            couples_count += 1

        self.stats['household_couples_processed'] = couples_count
        self.stats['household_exclusive'] = exclusive_count
        self.stats['household_non_exclusive'] = non_exclusive_count
        logger.info(f"  Processed {couples_count:,} household couples")
        logger.info(f"    Exclusive: {exclusive_count:,}, Non-exclusive: {non_exclusive_count:,}")

        return partners, rel_types, consensual

    def _batch_exclusive_matching(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create exclusive relationships using batch matching.

        Two-phase approach:
        1. VENUE-BASED: Match coworkers/classmates first (shared activity bonus)
        2. GEOGRAPHY-BASED: Match remaining seekers within MGU
        """
        n = arrays['n']
        sex = arrays['sex']
        age = arrays['age']
        mgu = arrays['mgu']
        eth = arrays['eth']
        venue_to_people = arrays['venue_to_people']

        age_config = self.config['age_differences']

        # Identify singles who want exclusive relationships
        is_single = partners < 0

        # Sample who wants exclusive (vectorized)
        base_exclusive_prob = self.config['relationship_types']['base_probabilities']['exclusive']
        wants_exclusive = np.random.random(n) < base_exclusive_prob

        seeking_exclusive = is_single & wants_exclusive
        initial_seekers = seeking_exclusive.sum()
        logger.info(f"  {initial_seekers:,} singles seeking exclusive relationships")

        total_matches = 0

        # ================================================================
        # PHASE 1: Venue-based matching (coworkers/classmates priority)
        # ================================================================
        logger.info("  Phase 1: Matching coworkers/classmates...")
        venue_matches = 0

        for venue_id, people_at_venue in venue_to_people.items():
            # Get seekers at this venue
            venue_seekers = np.array([p for p in people_at_venue if seeking_exclusive[p]])

            if len(venue_seekers) < 2:
                continue

            # Match within venue using same compatibility logic
            matches = self._match_within_group(
                venue_seekers, sex, age, eth, orientations, seeking_exclusive, age_config
            )

            for a, b in matches:
                partners[a] = b
                partners[b] = a
                rel_types[a] = REL_EXCLUSIVE
                rel_types[b] = REL_EXCLUSIVE
                seeking_exclusive[a] = False
                seeking_exclusive[b] = False

            venue_matches += len(matches)

        total_matches += venue_matches
        logger.info(f"    Created {venue_matches:,} relationships from shared venues")

        # ================================================================
        # PHASE 2: Geography-based matching (remaining seekers)
        # ================================================================
        logger.info("  Phase 2: Matching by geography...")

        unique_mgus = np.unique(mgu[mgu >= 0])

        for mgu_code in unique_mgus:
            in_mgu = mgu == mgu_code

            # Pool 1: Het males + Het/Bi females
            het_males = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_MALE) &
                (orientations == ORIENTATION_HET)
            )[0]

            het_bi_females = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_FEMALE) &
                ((orientations == ORIENTATION_HET) | (orientations == ORIENTATION_BI))
            )[0]

            matches = self._match_pools(
                het_males, het_bi_females, age, eth, age_config
            )

            for a, b in matches:
                partners[a] = b
                partners[b] = a
                rel_types[a] = REL_EXCLUSIVE
                rel_types[b] = REL_EXCLUSIVE
                seeking_exclusive[a] = False
                seeking_exclusive[b] = False

            total_matches += len(matches)

            # Pool 2: Het females + Het/Bi males (handles remaining het females)
            het_females = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_FEMALE) &
                (orientations == ORIENTATION_HET)
            )[0]

            het_bi_males = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_MALE) &
                ((orientations == ORIENTATION_HET) | (orientations == ORIENTATION_BI))
            )[0]

            matches = self._match_pools(
                het_females, het_bi_males, age, eth, age_config
            )

            for a, b in matches:
                partners[a] = b
                partners[b] = a
                rel_types[a] = REL_EXCLUSIVE
                rel_types[b] = REL_EXCLUSIVE
                seeking_exclusive[a] = False
                seeking_exclusive[b] = False

            total_matches += len(matches)

            # Pool 3: Homosexual males
            hom_males = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_MALE) &
                ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
            )[0]

            if len(hom_males) >= 2:
                matches = self._match_single_pool(hom_males, age, eth, age_config)

                for a, b in matches:
                    partners[a] = b
                    partners[b] = a
                    rel_types[a] = REL_EXCLUSIVE
                    rel_types[b] = REL_EXCLUSIVE
                    seeking_exclusive[a] = False
                    seeking_exclusive[b] = False

                total_matches += len(matches)

            # Pool 4: Homosexual females
            hom_females = np.where(
                seeking_exclusive & in_mgu &
                (sex == SEX_FEMALE) &
                ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
            )[0]

            if len(hom_females) >= 2:
                matches = self._match_single_pool(hom_females, age, eth, age_config)

                for a, b in matches:
                    partners[a] = b
                    partners[b] = a
                    rel_types[a] = REL_EXCLUSIVE
                    rel_types[b] = REL_EXCLUSIVE
                    seeking_exclusive[a] = False
                    seeking_exclusive[b] = False

                total_matches += len(matches)

        mgu_matches = total_matches - venue_matches
        logger.info(f"    Created {mgu_matches:,} relationships from MGU matching")

        # ================================================================
        # PHASE 3: LGU fallback for remaining seekers
        # ================================================================
        remaining_seekers = seeking_exclusive.sum()
        if remaining_seekers > 0:
            logger.info(f"  Phase 3: LGU fallback for {remaining_seekers:,} remaining seekers...")
            lgu = arrays['lgu']
            unique_lgus = np.unique(lgu[lgu >= 0])
            lgu_matches = 0

            for lgu_code in unique_lgus:
                in_lgu = lgu == lgu_code

                # Same matching logic as MGU but at LGU level
                het_males = np.where(
                    seeking_exclusive & in_lgu &
                    (sex == SEX_MALE) &
                    (orientations == ORIENTATION_HET)
                )[0]

                het_bi_females = np.where(
                    seeking_exclusive & in_lgu &
                    (sex == SEX_FEMALE) &
                    ((orientations == ORIENTATION_HET) | (orientations == ORIENTATION_BI))
                )[0]

                if len(het_males) > 0 and len(het_bi_females) > 0:
                    matches = self._match_pools(het_males, het_bi_females, age, eth, age_config)
                    for a, b in matches:
                        partners[a] = b
                        partners[b] = a
                        rel_types[a] = REL_EXCLUSIVE
                        rel_types[b] = REL_EXCLUSIVE
                        seeking_exclusive[a] = False
                        seeking_exclusive[b] = False
                    lgu_matches += len(matches)
                    total_matches += len(matches)

                # Homosexual males at LGU level
                hom_males = np.where(
                    seeking_exclusive & in_lgu &
                    (sex == SEX_MALE) &
                    ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
                )[0]

                if len(hom_males) >= 2:
                    matches = self._match_single_pool(hom_males, age, eth, age_config)
                    for a, b in matches:
                        partners[a] = b
                        partners[b] = a
                        rel_types[a] = REL_EXCLUSIVE
                        rel_types[b] = REL_EXCLUSIVE
                        seeking_exclusive[a] = False
                        seeking_exclusive[b] = False
                    lgu_matches += len(matches)
                    total_matches += len(matches)

                # Homosexual females at LGU level
                hom_females = np.where(
                    seeking_exclusive & in_lgu &
                    (sex == SEX_FEMALE) &
                    ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
                )[0]

                if len(hom_females) >= 2:
                    matches = self._match_single_pool(hom_females, age, eth, age_config)
                    for a, b in matches:
                        partners[a] = b
                        partners[b] = a
                        rel_types[a] = REL_EXCLUSIVE
                        rel_types[b] = REL_EXCLUSIVE
                        seeking_exclusive[a] = False
                        seeking_exclusive[b] = False
                    lgu_matches += len(matches)
                    total_matches += len(matches)

            logger.info(f"    Created {lgu_matches:,} relationships from LGU fallback")

        self.stats['exclusive_relationships_created'] = total_matches
        logger.info(f"  Created {total_matches:,} exclusive relationships total")
        logger.info(f"  {seeking_exclusive.sum():,} seekers remain unmatched")

        return partners, rel_types

    def _match_pools(
        self,
        pool_a: np.ndarray,
        pool_b: np.ndarray,
        age: np.ndarray,
        eth: np.ndarray,
        age_config: Dict
    ) -> List[Tuple[int, int]]:
        """
        Match two pools with age filtering and ethnicity weighting.

        Uses Numba-accelerated matching for C-speed performance.
        """
        if len(pool_a) == 0 or len(pool_b) == 0:
            return []

        # Find max age diff for the younger pool
        min_age = min(age[pool_a].min(), age[pool_b].min())
        max_age_diff = 10  # Default
        for bracket, cfg in age_config.items():
            if '-' in bracket:
                start, end = map(int, bracket.split('-'))
                if start <= min_age <= end:
                    max_age_diff = cfg.get('max', 10)
                    break

        matches_a, matches_b = np.empty(0), np.empty(0)
        seed = int(time.time() * 1000) % 1000000

        # Use Numba kernel
        if self.ethnicity_matrix is not None:
            matches_a, matches_b = match_with_ethnicity_fast(
                pool_a.astype(np.int64),
                pool_b.astype(np.int64),
                age.astype(np.int64),
                eth.astype(np.int64),
                self.ethnicity_matrix,
                max_age_diff,
                seed
            )
        else:
            matches_a, matches_b = match_two_pools_fast(
                pool_a.astype(np.int64),
                pool_b.astype(np.int64),
                age.astype(np.int64),
                max_age_diff,
                seed
            )

        return list(zip(matches_a, matches_b))

    def _match_single_pool(
        self,
        pool: np.ndarray,
        age: np.ndarray,
        eth: np.ndarray,
        age_config: Dict
    ) -> List[Tuple[int, int]]:
        """Match within a single pool (for same-sex matching). Uses Numba kernel."""
        if len(pool) < 2:
            return []

        # Compute max age diff based on median age in pool
        median_age = int(np.median(age[pool]))
        max_age_diff = self._get_max_age_diff(median_age)
        seed = np.random.randint(0, 2**31)

        matches_a, matches_b = match_single_pool_fast(
            pool.astype(np.int64),
            age.astype(np.int64),
            max_age_diff,
            seed
        )

        return list(zip(matches_a, matches_b))

    def _match_within_group(self, group_indices, sex, age, eth, orientations, seeking, age_config):
        """Match compatible people within a group (e.g., coworkers at same venue)."""
        all_matches = []

        # Filter to only those still seeking
        active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
        if len(active) < 2:
            return []

        # Het males seeking het/bi females
        het_males = active[(sex[active] == SEX_MALE) & (orientations[active] == ORIENTATION_HET)]
        het_bi_females = active[
            (sex[active] == SEX_FEMALE) &
            ((orientations[active] == ORIENTATION_HET) | (orientations[active] == ORIENTATION_BI))
        ]

        if len(het_males) > 0 and len(het_bi_females) > 0:
            matches = self._match_pools(het_males, het_bi_females, age, eth, age_config)
            for a, b in matches:
                seeking[a] = False
                seeking[b] = False
            all_matches.extend(matches)

        # Refresh active list
        active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
        if len(active) < 2:
            return all_matches

        # Het females seeking het/bi males
        het_females = active[(sex[active] == SEX_FEMALE) & (orientations[active] == ORIENTATION_HET)]
        het_bi_males = active[
            (sex[active] == SEX_MALE) &
            ((orientations[active] == ORIENTATION_HET) | (orientations[active] == ORIENTATION_BI))
        ]

        if len(het_females) > 0 and len(het_bi_males) > 0:
            matches = self._match_pools(het_females, het_bi_males, age, eth, age_config)
            for a, b in matches:
                seeking[a] = False
                seeking[b] = False
            all_matches.extend(matches)

        # Refresh active list
        active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
        if len(active) < 2:
            return all_matches

        # Homosexual males
        hom_males = active[
            (sex[active] == SEX_MALE) &
            ((orientations[active] == ORIENTATION_HOM) | (orientations[active] == ORIENTATION_BI))
        ]

        if len(hom_males) >= 2:
            matches = self._match_single_pool(hom_males, age, eth, age_config)
            for a, b in matches:
                seeking[a] = False
                seeking[b] = False
            all_matches.extend(matches)

        # Refresh active list
        active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
        if len(active) < 2:
            return all_matches

        # Homosexual females
        hom_females = active[
            (sex[active] == SEX_FEMALE) &
            ((orientations[active] == ORIENTATION_HOM) | (orientations[active] == ORIENTATION_BI))
        ]

        if len(hom_females) >= 2:
            matches = self._match_single_pool(hom_females, age, eth, age_config)
            for a, b in matches:
                seeking[a] = False
                seeking[b] = False
            all_matches.extend(matches)

        return all_matches

    def _batch_non_exclusive_matching(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, Dict[int, List[int]]]:
        """
        Create non-exclusive relationships using three-phase matching:
        1. Venue-based (coworkers/classmates)
        2. MGU (neighborhood)
        3. LGU fallback
        """
        n = arrays['n']
        sex = arrays['sex']
        age = arrays['age']
        eth = arrays['eth']
        mgu = arrays['mgu']
        lgu = arrays['lgu']
        venue_to_people = arrays['venue_to_people']

        # Identify remaining singles
        is_single = partners < 0

        # Sample who wants non-exclusive
        base_prob = self.config['relationship_types']['base_probabilities']['non_exclusive']
        wants_non_exclusive = np.random.random(n) < base_prob

        seeking = is_single & wants_non_exclusive
        n_seeking = seeking.sum()

        logger.info(f"  {n_seeking:,} singles seeking non-exclusive relationships")

        if n_seeking == 0:
            return partners, rel_types, {}

        # Mark as non-exclusive
        rel_types[seeking] = REL_NON_EXCLUSIVE

        # Track relationships
        non_exclusive_partners = defaultdict(list)
        total_created = 0
        age_config = self.config['age_differences']

        # ================================================================
        # PHASE 1: Venue-based matching (coworkers/classmates)
        # ================================================================
        venue_matches = 0
        for venue_id, people_at_venue in venue_to_people.items():
            venue_seekers = np.array([p for p in people_at_venue if seeking[p]])
            if len(venue_seekers) < 2:
                continue

            matches = self._match_within_group(
                venue_seekers, sex, age, eth, orientations, seeking, age_config
            )
            for a, b in matches:
                non_exclusive_partners[a].append(b)
                non_exclusive_partners[b].append(a)
                seeking[a] = False
                seeking[b] = False
                venue_matches += 1

        total_created += venue_matches
        logger.info(f"    Phase 1 (venues): {venue_matches:,} relationships")

        # ================================================================
        # PHASE 2: MGU matching
        # ================================================================
        mgu_matches = 0
        unique_mgus = np.unique(mgu[mgu >= 0])

        for mgu_code in unique_mgus:
            in_mgu = mgu == mgu_code
            mgu_matches += self._match_by_orientation_pools(
                seeking & in_mgu, sex, age, eth, orientations, seeking,
                non_exclusive_partners, age_config
            )

        total_created += mgu_matches
        logger.info(f"    Phase 2 (MGU): {mgu_matches:,} relationships")

        # ================================================================
        # PHASE 3: LGU fallback
        # ================================================================
        remaining = seeking.sum()
        if remaining > 0:
            lgu_matches = 0
            unique_lgus = np.unique(lgu[lgu >= 0])

            for lgu_code in unique_lgus:
                in_lgu = lgu == lgu_code
                lgu_matches += self._match_by_orientation_pools(
                    seeking & in_lgu, sex, age, eth, orientations, seeking,
                    non_exclusive_partners, age_config
                )

            total_created += lgu_matches
            logger.info(f"    Phase 3 (LGU): {lgu_matches:,} relationships")

        self.stats['non_exclusive_relationships_created'] = total_created
        logger.info(f"  Created {total_created:,} non-exclusive relationships total")

        return partners, rel_types, dict(non_exclusive_partners)

    def _match_by_orientation_pools(
        self,
        mask: np.ndarray,
        sex: np.ndarray,
        age: np.ndarray,
        eth: np.ndarray,
        orientations: np.ndarray,
        seeking: np.ndarray,
        partners_dict: Dict[int, List[int]],
        age_config: Dict
    ) -> int:
        """Helper to match by orientation pools within a geographic mask."""
        matches_created = 0

        # Het males + het/bi females
        het_males = np.where(mask & (sex == SEX_MALE) & (orientations == ORIENTATION_HET))[0]
        het_bi_females = np.where(
            mask & (sex == SEX_FEMALE) &
            ((orientations == ORIENTATION_HET) | (orientations == ORIENTATION_BI))
        )[0]

        if len(het_males) > 0 and len(het_bi_females) > 0:
            matches = self._match_pools(het_males, het_bi_females, age, eth, age_config)
            for a, b in matches:
                partners_dict[a].append(b)
                partners_dict[b].append(a)
                seeking[a] = False
                seeking[b] = False
                matches_created += 1

        # Homosexual males
        hom_males = np.where(
            mask & (sex == SEX_MALE) &
            ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
        )[0]

        if len(hom_males) >= 2:
            matches = self._match_single_pool(hom_males, age, eth, age_config)
            for a, b in matches:
                partners_dict[a].append(b)
                partners_dict[b].append(a)
                seeking[a] = False
                seeking[b] = False
                matches_created += 1

        # Homosexual females
        hom_females = np.where(
            mask & (sex == SEX_FEMALE) &
            ((orientations == ORIENTATION_HOM) | (orientations == ORIENTATION_BI))
        )[0]

        if len(hom_females) >= 2:
            matches = self._match_single_pool(hom_females, age, eth, age_config)
            for a, b in matches:
                partners_dict[a].append(b)
                partners_dict[b].append(a)
                seeking[a] = False
                seeking[b] = False
                matches_created += 1

        return matches_created

    def _process_cheating_vectorized(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        consensual: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, Dict[int, List[int]]]:
        """
        Process cheating/affairs using three-phase matching:
        1. Venue-based (coworkers/classmates)
        2. MGU (neighborhood)
        3. LGU fallback
        """
        n = arrays['n']
        sex = arrays['sex']
        age = arrays['age']
        eth = arrays['eth']
        mgu = arrays['mgu']
        lgu = arrays['lgu']
        venue_to_people = arrays['venue_to_people']

        # Find people in exclusive relationships who want to cheat
        in_exclusive = rel_types == REL_EXCLUSIVE
        base_prob = self.config['cheating']['base_probability']
        wants_to_cheat = np.random.random(n) < base_prob
        cheater_mask = in_exclusive & wants_to_cheat

        # Track which cheaters still need affair partners
        cheater_seeking = cheater_mask.copy()

        n_cheaters = cheater_mask.sum()
        logger.info(f"  {n_cheaters:,} potential cheaters")

        if n_cheaters == 0:
            return partners, consensual, {}

        # Build affair partner pool
        in_non_exclusive = rel_types == REL_NON_EXCLUSIVE
        is_single = rel_types == REL_NO_PARTNER
        non_excl_prob = self.config['relationship_types']['base_probabilities']['non_exclusive']
        willing_singles = is_single & (np.random.random(n) < non_excl_prob)

        # Affair partners: non-exclusive OR willing singles, but NOT cheaters
        affair_pool_mask = (in_non_exclusive | willing_singles) & ~cheater_mask
        affair_available = affair_pool_mask.copy()

        n_pool = affair_pool_mask.sum()
        logger.info(f"  {n_pool:,} potential affair partners")

        if n_pool == 0:
            return partners, consensual, {}

        # Track affairs
        affair_partners = defaultdict(list)
        total_affairs = 0
        age_config = self.config['age_differences']

        # ================================================================
        # PHASE 1: Venue-based matching (coworkers having affairs)
        # ================================================================
        venue_affairs = 0
        for venue_id, people_at_venue in venue_to_people.items():
            # Get cheaters and available affair partners at this venue
            venue_cheaters = np.array([p for p in people_at_venue if cheater_seeking[p]])
            venue_pool = np.array([p for p in people_at_venue if affair_available[p]])

            if len(venue_cheaters) == 0 or len(venue_pool) == 0:
                continue

            # Match cheaters with affair partners at same venue
            affairs = self._match_cheaters_with_pool(
                venue_cheaters, venue_pool, sex, age, eth, orientations,
                cheater_seeking, affair_available, affair_partners, consensual, age_config
            )
            venue_affairs += affairs

        total_affairs += venue_affairs
        logger.info(f"    Phase 1 (venues): {venue_affairs:,} affairs")

        # ================================================================
        # PHASE 2: MGU matching
        # ================================================================
        mgu_affairs = 0
        unique_mgus = np.unique(mgu[mgu >= 0])

        for mgu_code in unique_mgus:
            in_mgu = mgu == mgu_code
            mgu_cheaters = np.where(cheater_seeking & in_mgu)[0]
            mgu_pool = np.where(affair_available & in_mgu)[0]

            if len(mgu_cheaters) == 0 or len(mgu_pool) == 0:
                continue

            affairs = self._match_cheaters_with_pool(
                mgu_cheaters, mgu_pool, sex, age, eth, orientations,
                cheater_seeking, affair_available, affair_partners, consensual, age_config
            )
            mgu_affairs += affairs

        total_affairs += mgu_affairs
        logger.info(f"    Phase 2 (MGU): {mgu_affairs:,} affairs")

        # ================================================================
        # PHASE 3: LGU fallback
        # ================================================================
        remaining_cheaters = cheater_seeking.sum()
        if remaining_cheaters > 0:
            lgu_affairs = 0
            unique_lgus = np.unique(lgu[lgu >= 0])

            for lgu_code in unique_lgus:
                in_lgu = lgu == lgu_code
                lgu_cheaters = np.where(cheater_seeking & in_lgu)[0]
                lgu_pool = np.where(affair_available & in_lgu)[0]

                if len(lgu_cheaters) == 0 or len(lgu_pool) == 0:
                    continue

                affairs = self._match_cheaters_with_pool(
                    lgu_cheaters, lgu_pool, sex, age, eth, orientations,
                    cheater_seeking, affair_available, affair_partners, consensual, age_config
                )
                lgu_affairs += affairs

            total_affairs += lgu_affairs
            logger.info(f"    Phase 3 (LGU): {lgu_affairs:,} affairs")

        self.stats['affairs_created'] = total_affairs
        logger.info(f"  Created {total_affairs:,} affairs total")
        logger.info(f"  {(~consensual & in_exclusive).sum():,} people now cheating")

        return partners, consensual, dict(affair_partners)

    def _match_cheaters_with_pool(
        self,
        cheaters: np.ndarray,
        pool: np.ndarray,
        sex: np.ndarray,
        age: np.ndarray,
        eth: np.ndarray,
        orientations: np.ndarray,
        cheater_seeking: np.ndarray,
        affair_available: np.ndarray,
        affair_partners: Dict[int, List[int]],
        consensual: np.ndarray,
        age_config: Dict
    ) -> int:
        """Match cheaters with affair partners by orientation pools."""
        affairs_created = 0

        # Het male cheaters + het/bi female pool
        het_male_cheaters = cheaters[(sex[cheaters] == SEX_MALE) & (orientations[cheaters] == ORIENTATION_HET)]
        het_bi_female_pool = pool[
            (sex[pool] == SEX_FEMALE) &
            ((orientations[pool] == ORIENTATION_HET) | (orientations[pool] == ORIENTATION_BI))
        ]

        if len(het_male_cheaters) > 0 and len(het_bi_female_pool) > 0:
            matches = self._match_pools(het_male_cheaters, het_bi_female_pool, age, eth, age_config)
            for cheater, partner in matches:
                affair_partners[cheater].append(partner)
                consensual[cheater] = False
                cheater_seeking[cheater] = False
                affair_available[partner] = False
                affairs_created += 1

        # Het female cheaters + het/bi male pool
        het_female_cheaters = cheaters[(sex[cheaters] == SEX_FEMALE) & (orientations[cheaters] == ORIENTATION_HET)]
        het_bi_male_pool = pool[
            (sex[pool] == SEX_MALE) &
            ((orientations[pool] == ORIENTATION_HET) | (orientations[pool] == ORIENTATION_BI))
        ]

        if len(het_female_cheaters) > 0 and len(het_bi_male_pool) > 0:
            matches = self._match_pools(het_female_cheaters, het_bi_male_pool, age, eth, age_config)
            for cheater, partner in matches:
                affair_partners[cheater].append(partner)
                consensual[cheater] = False
                cheater_seeking[cheater] = False
                affair_available[partner] = False
                affairs_created += 1

        # Homosexual male cheaters
        hom_male_cheaters = cheaters[
            (sex[cheaters] == SEX_MALE) &
            ((orientations[cheaters] == ORIENTATION_HOM) | (orientations[cheaters] == ORIENTATION_BI))
        ]
        hom_bi_male_pool = pool[
            (sex[pool] == SEX_MALE) &
            ((orientations[pool] == ORIENTATION_HOM) | (orientations[pool] == ORIENTATION_BI))
        ]

        if len(hom_male_cheaters) > 0 and len(hom_bi_male_pool) > 0:
            matches = self._match_pools(hom_male_cheaters, hom_bi_male_pool, age, eth, age_config)
            for cheater, partner in matches:
                affair_partners[cheater].append(partner)
                consensual[cheater] = False
                cheater_seeking[cheater] = False
                affair_available[partner] = False
                affairs_created += 1

        # Homosexual female cheaters
        hom_female_cheaters = cheaters[
            (sex[cheaters] == SEX_FEMALE) &
            ((orientations[cheaters] == ORIENTATION_HOM) | (orientations[cheaters] == ORIENTATION_BI))
        ]
        hom_bi_female_pool = pool[
            (sex[pool] == SEX_FEMALE) &
            ((orientations[pool] == ORIENTATION_HOM) | (orientations[pool] == ORIENTATION_BI))
        ]

        if len(hom_female_cheaters) > 0 and len(hom_bi_female_pool) > 0:
            matches = self._match_pools(hom_female_cheaters, hom_bi_female_pool, age, eth, age_config)
            for cheater, partner in matches:
                affair_partners[cheater].append(partner)
                consensual[cheater] = False
                cheater_seeking[cheater] = False
                affair_available[partner] = False
                affairs_created += 1

        return affairs_created

    def _get_age_group(self, age: int) -> str:
        """Get age group string for an age value."""
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

    def _get_max_age_diff(self, age: int) -> int:
        """Get maximum age difference from config based on person's age group."""
        age_group = self._get_age_group(age)
        age_config = self.config.get('age_differences', {})
        group_config = age_config.get(age_group, {})
        return group_config.get('max', 15)  # Default to 15 if not configured

    def _are_orientation_compatible(
        self,
        orientation1: int,
        sex1: int,
        orientation2: int,
        sex2: int
    ) -> bool:
        """Check if two people are orientation-compatible for a relationship."""
        # Heterosexual: attracted to opposite sex
        # Homosexual: attracted to same sex
        # Bisexual: attracted to both

        def is_attracted_to(orientation, own_sex, target_sex):
            if orientation == ORIENTATION_HET:
                return own_sex != target_sex
            elif orientation == ORIENTATION_HOM:
                return own_sex == target_sex
            else:  # Bisexual
                return True

        return (is_attracted_to(orientation1, sex1, sex2) and
                is_attracted_to(orientation2, sex2, sex1))

    def _write_results(
        self,
        adults: List,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        consensual: np.ndarray,
        affair_partners: Dict[int, List[int]],
        non_exclusive_partners: Dict[int, List[int]]
    ):
        """Write results from arrays back to person objects."""
        orientation_names = ['heterosexual', 'homosexual', 'bisexual']
        
        rel_type_names = ['no_partner', 'exclusive', 'non_exclusive']

        ids = arrays['ids']

        for i, person in enumerate(adults):
            # Orientation
            person.properties[self.orientation_key] = orientation_names[orientations[i]]

            # Relationship status
            person.properties[self.status_key] = {
                'type': rel_type_names[rel_types[i]],
                'consensual': bool(consensual[i])
            }

            # Partners (convert numpy int64 to Python int for JSON serialization)
            exclusive_partners_list = []
            non_exclusive_partners_list = []

            # Primary partner (from exclusive or household couples)
            if partners[i] >= 0:
                partner_id = int(ids[partners[i]])  # Convert to Python int
                rel_type = rel_type_names[rel_types[i]]

                if rel_type == 'exclusive':
                    exclusive_partners_list.append(partner_id)
                elif rel_type == 'non_exclusive':
                    non_exclusive_partners_list.append(partner_id)

            # Non-exclusive partners from batch matching
            if i in non_exclusive_partners:
                for partner_idx in non_exclusive_partners[i]:
                    partner_id = int(ids[partner_idx])  # Convert to Python int
                    if partner_id not in non_exclusive_partners_list:
                        non_exclusive_partners_list.append(partner_id)

            # Affair partners (added as non_exclusive)
            if i in affair_partners:
                for affair_idx in affair_partners[i]:
                    affair_id = int(ids[affair_idx])  # Convert to Python int
                    if affair_id not in non_exclusive_partners_list:
                        non_exclusive_partners_list.append(affair_id)

            person.properties[self.partners_key] = {
                'exclusive': exclusive_partners_list,
                'non_exclusive': non_exclusive_partners_list
            }

        logger.info(f"  Wrote results to {len(adults):,} person objects")

    def _print_statistics(
        self,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        consensual: np.ndarray
    ):
        """Print distribution statistics."""
        n = len(orientations)

        logger.info("\n" + "=" * 40)
        logger.info("DISTRIBUTION STATISTICS")
        logger.info("=" * 40)

        # Orientations
        logger.info("\nSexual Orientations:")
        logger.info(f"  Heterosexual: {(orientations == ORIENTATION_HET).sum():,} ({100*(orientations == ORIENTATION_HET).mean():.1f}%)")
        logger.info(f"  Homosexual: {(orientations == ORIENTATION_HOM).sum():,} ({100*(orientations == ORIENTATION_HOM).mean():.1f}%)")
        logger.info(f"  Bisexual: {(orientations == ORIENTATION_BI).sum():,} ({100*(orientations == ORIENTATION_BI).mean():.1f}%)")

        # Relationship types
        logger.info("\nRelationship Types:")
        logger.info(f"  No partner: {(rel_types == REL_NO_PARTNER).sum():,} ({100*(rel_types == REL_NO_PARTNER).mean():.1f}%)")
        logger.info(f"  Exclusive: {(rel_types == REL_EXCLUSIVE).sum():,} ({100*(rel_types == REL_EXCLUSIVE).mean():.1f}%)")
        logger.info(f"  Non-exclusive: {(rel_types == REL_NON_EXCLUSIVE).sum():,} ({100*(rel_types == REL_NON_EXCLUSIVE).mean():.1f}%)")

        # Partnered
        has_partner = partners >= 0
        logger.info(f"\nPartnered: {has_partner.sum():,} ({100*has_partner.mean():.1f}%)")

        # Cheating
        cheating = ~consensual & (rel_types == REL_EXCLUSIVE)
        logger.info(f"Cheating: {cheating.sum():,} ({100*cheating.mean():.1f}%)")
