"""
Romantic relationship distributor for large-scale simulations.

This module provides a high-performance implementation that can handle 60M+ people
using optimized array operations and specialized matching kernels.
"""

import logging
import yaml
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import time

from .matcher_kernels import (
    match_two_pools,
    match_single_pool,
    match_with_attribute_weighting,
    filter_by_age
)
from .relationship_exporter import (
    export_relationships_csv,
    export_cheating_network_csv
)

logger = logging.getLogger("romantic_relationships")

# Encoding constants
SEX_FEMALE = 0
SEX_MALE = 1

REL_NO_PARTNER = 0
REL_EXCLUSIVE = 1
REL_NON_EXCLUSIVE = 2


class RomanticDistributor:
    """
    High-performance romantic relationship distributor for large-scale simulations.
    Fully data-driven based on YAML configuration.
    """

    def __init__(self, world, config: str | dict):
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']

        # 1. Dynamic Orientations
        orient_config = self.config.get('sexual_orientations', {})
        self.orientation_names = orient_config.get('types', ['heterosexual', 'homosexual', 'bisexual'])
        self.orient_to_id = {name: i for i, name in enumerate(self.orientation_names)}
        self.id_to_orient = {i: name for i, name in enumerate(self.orientation_names)}

        # 2. Dynamic Age Groups
        age_diff_config = self.config.get('age_differences', {})
        self.age_groups = []
        for group_str in age_diff_config.keys():
            if '-' in group_str:
                start, end = map(int, group_str.split('-'))
                self.age_groups.append({'name': group_str, 'start': start, 'end': end})
            elif '+' in group_str:
                start = int(group_str.replace('+', ''))
                self.age_groups.append({'name': group_str, 'start': start, 'end': 200})
        
        # Sort age groups by start age for consistent lookup
        self.age_groups.sort(key=lambda x: x['start'])

        # Storage keys
        storage = self.config.get('storage', {})
        self.orientation_key = storage.get('orientation_key', 'sexual_orientation')
        self.partners_key = storage.get('partners_key', 'romantic_partners')
        self.status_key = storage.get('status_key', 'relationship_status')

        # Statistics
        self.stats = defaultdict(int)

        # Load attribute matching matrix if enabled
        self.attribute_matrix = None
        self.attribute_codes = {}
        attr_config = self.config.get('attribute_matching', {})
        self.matching_attr = attr_config.get('attribute', 'ethnicity')
        
        if self._is_attribute_matching_enabled():
            self._load_attribute_matrix()

        logger.info(f"Initialized {self.name} distributor with {len(self.orientation_names)} orientations and {len(self.age_groups)} age groups")

    def _load_config(self, config) -> dict:
        if isinstance(config, str):
            with open(config, 'r') as f:
                return yaml.safe_load(f)
        return config

    def _is_attribute_matching_enabled(self) -> bool:
        return self.config.get('attribute_matching', {}).get('enabled', False)

    def _load_attribute_matrix(self):
        """Load attribute partnership probabilities as a NumPy matrix for fast lookup."""
        attr_config = self.config['attribute_matching']
        data_file = attr_config['data_file']
        code_mapping = attr_config.get('code_mapping', {})

        try:
            df = pd.read_csv(data_file)

            # Get unique attribute values
            all_vals = set(df['person_ethnicity'].unique()) | set(df['partner_ethnicity'].unique())

            # Expand code mappings
            expanded_vals = set()
            for val in all_vals:
                if val in code_mapping:
                    codes = code_mapping[val]
                    if isinstance(codes, list):
                        expanded_vals.update(codes)
                    else:
                        expanded_vals.add(codes)
                else:
                    expanded_vals.add(val)

            # Create encoding
            self.attribute_codes = {val: i for i, val in enumerate(sorted(expanded_vals))}
            n_attr = len(self.attribute_codes)

            # Build probability matrix
            self.attribute_matrix = np.ones((n_attr, n_attr), dtype=np.float32)

            for _, row in df.iterrows():
                p_val = row['person_ethnicity']
                partner_val = row['partner_ethnicity']
                prob = row['probability']

                # Get all codes this maps to
                p_codes = code_mapping.get(p_val, [p_val])
                partner_codes = code_mapping.get(partner_val, [partner_val])

                if not isinstance(p_codes, list):
                    p_codes = [p_codes]
                if not isinstance(partner_codes, list):
                    partner_codes = [partner_codes]

                for pc in p_codes:
                    for ptc in partner_codes:
                        if pc in self.attribute_codes and ptc in self.attribute_codes:
                            i, j = self.attribute_codes[pc], self.attribute_codes[ptc]
                            self.attribute_matrix[i, j] = prob

            logger.info(f"Loaded attribute matching matrix: {n_attr}x{n_attr}")

        except Exception as e:
            logger.error(f"Failed to load attribute partnership probabilities: {e}")
            self.attribute_matrix = None

    def _sample_intended_rel_types(self, arrays: Dict) -> np.ndarray:
        """Sample intended relationship types using dynamic categorical distribution."""
        n = arrays['n']
        rel_config = self.config.get('relationship_types', {}).get('base_probabilities', {})
        
        # Get probabilities in correct order: 0=No, 1=Exclusive, 2=Non-Exclusive
        probs = np.array([
            rel_config.get('no_partner', 0.0),
            rel_config.get('exclusive', 0.0),
            rel_config.get('non_exclusive', 0.0)
        ], dtype=np.float32)
        
        # Normalize
        prob_sum = probs.sum()
        if prob_sum > 0:
            probs = probs / prob_sum
        else:
            probs = np.array([1.0, 0.0, 0.0]) # Default to no partner

        # Sample for everyone initially
        samples = np.random.choice(
            np.array([REL_NO_PARTNER, REL_EXCLUSIVE, REL_NON_EXCLUSIVE], dtype=np.int8),
            size=n,
            p=probs
        )
        
        # Track stats
        self.stats['intended_no_partner'] = (samples == REL_NO_PARTNER).sum()
        self.stats['intended_exclusive'] = (samples == REL_EXCLUSIVE).sum()
        self.stats['intended_non_exclusive'] = (samples == REL_NON_EXCLUSIVE).sum()
        
        return samples

    def distribute_all(self):
        """Main entry point for relationship distribution."""
        total_start = time.time()

        logger.info("=" * 60)
        logger.info(f"Starting {self.name} distribution")
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

        # Step 2: Assign sexual orientations
        logger.info("\n[Step 2] Assigning sexual orientations...")
        t0 = time.time()
        orientations = self._assign_orientations(arrays)
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 3: Sample intended relationship types
        logger.info("\n[Step 3] Sampling intended relationship types...")
        t0 = time.time()
        intended_rel_types = self._sample_intended_rel_types(arrays)
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 4: Process household couples
        logger.info("\n[Step 4] Process household couples...")
        t0 = time.time()
        partners, rel_types, consensual = self._process_household_couples(
            arrays, orientations, intended_rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 5: Create exclusive relationships for singles
        logger.info("\n[Step 5] Creating exclusive relationships...")
        t0 = time.time()
        partners, rel_types = self._create_exclusive_relationships(
            arrays, orientations, partners, rel_types, intended_rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 6: Create non-exclusive relationships
        logger.info("\n[Step 6] Creating non-exclusive relationships...")
        t0 = time.time()
        partners, rel_types, non_exclusive_partners = self._create_non_exclusive_relationships(
            arrays, orientations, partners, rel_types, intended_rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 7: Handle cheating and affairs
        logger.info("\n[Step 6] Processing cheating and affairs...")
        t0 = time.time()
        partners, consensual, affair_partners = self._process_cheating_and_affairs(
            arrays, orientations, partners, rel_types, consensual, intended_rel_types
        )
        logger.info(f"  Time: {time.time() - t0:.2f}s")

        # Step 8: Write results back to person objects
        logger.info("\n[Step 8] Writing results to person objects...")
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
        logger.info(f"Romantic distribution complete in {total_time:.2f}s")
        logger.info(f"Throughput: {n / total_time:,.0f} people/second")
        logger.info("=" * 60)

    def _build_attribute_arrays(self, adults: List) -> Dict[str, np.ndarray]:
        """Extract all relevant attributes into NumPy arrays for fast access."""
        n = len(adults)

        # Pre-allocate arrays
        ids = np.empty(n, dtype=np.int64)
        sex = np.empty(n, dtype=np.int8)
        age = np.empty(n, dtype=np.int64) # Use int64 for Numba compatibility
        mgu_codes = np.empty(n, dtype=np.int32)
        lgu_codes = np.empty(n, dtype=np.int32)
        eth_codes = np.empty(n, dtype=np.int64) # Use int64 for Numba compatibility (now generic attribute)
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

            # Attribute encoding
            attr_val = person.properties.get(self.matching_attr, 'unknown')
            if attr_val not in self.attribute_codes:
                self.attribute_codes[attr_val] = len(self.attribute_codes)
            eth_codes[i] = self.attribute_codes[attr_val]

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

    def _assign_orientations(self, arrays: Dict[str, np.ndarray]) -> np.ndarray:
        """Assign sexual orientations to all adults using dynamic config."""
        n = len(arrays['age'])
        sex = arrays['sex']
        household_couple = arrays['household_couple']
        age = arrays['age']

        orientations = np.zeros(n, dtype=np.int8)
        orientation_config = self.config.get('sexual_orientations', {})
        age_adjustments = orientation_config.get('age_adjustments', {})

        # Get base probabilities by sex
        probs_by_sex = {}
        for s_name in ['male', 'female']:
            s_code = SEX_MALE if s_name == 'male' else SEX_FEMALE
            base = orientation_config.get('probabilities', {}).get(s_name, {})
            
            # Build prob array based on dynamic orientation order
            p_arr = np.array([base.get(name, 0.0) for name in self.orientation_names], dtype=np.float32)
            if p_arr.sum() == 0:
                p_arr[0] = 1.0  # Default to first orientation if none defined
            probs_by_sex[s_code] = p_arr / p_arr.sum()

        # Assign to non-household-coupled people first
        not_coupled = household_couple < 0

        for s_code, s_name in [(SEX_MALE, 'male'), (SEX_FEMALE, 'female')]:
            base_probs = probs_by_sex[s_code]

            for group in self.age_groups:
                group_name = group['name']
                mask = (sex == s_code) & (age >= group['start']) & (age <= group['end']) & not_coupled
                indices = np.where(mask)[0]

                if len(indices) == 0:
                    continue

                # Apply adjustments for this age group
                adj = age_adjustments.get(group_name, {})
                probs = base_probs.copy()

                # Apply multipliers to base probabilities dynamically
                for i, name in enumerate(self.orientation_names):
                    if name in adj:
                        probs[i] *= adj[name]

                # Normalize (important for random.choice)
                prob_sum = probs.sum()
                if prob_sum > 0:
                    probs = probs / prob_sum
                else:
                    probs = np.zeros(len(self.orientation_names))
                    probs[0] = 1.0  # Fallback

                # Batch sampling for this specific cohort
                orientations[indices] = np.random.choice(
                    np.arange(len(self.orientation_names), dtype=np.int8),
                    size=len(indices),
                    p=probs
                )

        # Track stats
        for i, name in enumerate(self.orientation_names):
            self.stats[f'orientation_{name}'] = (orientations[not_coupled] == i).sum()

        logger.info(f"  Assigned {len(self.orientation_names)} orientations to {not_coupled.sum():,} non-household adults using dynamic adjustments")
        dist_str = ", ".join([f"{name.upper()}={self.stats[f'orientation_{name}']:,}" for name in self.orientation_names])
        logger.info(f"  Overall Distribution: {dist_str}")

        return orientations

    def _is_attracted_to(self, orientation_id: int, own_sex: int, target_sex: int) -> bool:
        """Check if an orientation/sex combination is attracted to a target sex."""
        o_name = self.id_to_orient[orientation_id]
        s_name = 'male' if own_sex == SEX_MALE else 'female'
        target_s_name = 'male' if target_sex == SEX_MALE else 'female'
        
        rules = self.config.get('compatibility_rules', {})
        allowed_sexes = rules.get(o_name, {}).get(s_name, [])
        return target_s_name in allowed_sexes

    def _are_orientation_compatible(
        self,
        o_id1: int,
        s1: int,
        o_id2: int,
        s2: int
    ) -> bool:
        """Check mutual attraction between two people."""
        return self._is_attracted_to(o_id1, s1, s2) and self._is_attracted_to(o_id2, s2, s1)

    def _get_matching_groups(self) -> List[Tuple[Tuple[int, int], Tuple[int, int]]]:
        """Identify all compatible (sex, orientation) group pairs from config."""
        groups = []
        categories = []
        for s_code in [SEX_MALE, SEX_FEMALE]:
            for o_id in range(len(self.orientation_names)):
                categories.append((s_code, o_id))
        
        for i, c1 in enumerate(categories):
            for j, c2 in enumerate(categories):
                if j < i: continue
                if self._are_orientation_compatible(c1[1], c1[0], c2[1], c2[0]):
                    groups.append((c1, c2))
        return groups

    def _process_household_couples(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        intended_rel_types: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Process household couples using dynamic orientation logic."""
        n = arrays['n']
        ids = arrays['ids']
        sex = arrays['sex']
        household_couple = arrays['household_couple']
        id_to_idx = arrays['id_to_idx']

        # Initialize partner arrays
        partners = np.full(n, -1, dtype=np.int64)
        rel_types = np.full(n, REL_NO_PARTNER, dtype=np.int8)
        consensual = np.ones(n, dtype=bool)

        # Find all people with household couples
        has_couple = household_couple >= 0
        coupled_indices = np.where(has_couple)[0]

        rel_config = self.config['relationship_types']['base_probabilities']
        prob_exclusive = rel_config['exclusive']
        prob_non_exclusive = rel_config['non_exclusive']
        total_prob = prob_exclusive + prob_non_exclusive
        prob_exclusive_normalized = prob_exclusive / total_prob

        # Determine valid orientations for same-sex and mixed-sex couples based on rules
        valid_orientations = {}
        for s1 in [SEX_MALE, SEX_FEMALE]:
            for s2 in [SEX_MALE, SEX_FEMALE]:
                # Find orientations for person 1 that are attracted to s2, 
                # AND person 2 (with that same orientation) would be attracted to s1
                # (Simplified assumption: both partners in a couple have orientations 
                # that allow this relationship)
                valid = []
                for o_id in range(len(self.orientation_names)):
                    if self._are_orientation_compatible(o_id, s1, o_id, s2):
                        valid.append(o_id)
                
                if not valid:
                    # Fallback to all if rules are too strict for existing couples
                    valid = list(range(len(self.orientation_names)))
                
                valid_orientations[(s1, s2)] = valid

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
            sex1, sex2 = sex[idx], sex[partner_idx]

            # Assign compatible orientations dynamically
            valid = valid_orientations[(sex1, sex2)]
            
            # Simple uniform choice among valid orientations for existing couples
            orientations[idx] = np.random.choice(valid)
            
            # Ensure partner also has a compatible orientation
            # (In most cases it will be the same orientation name, but we check compatibility)
            valid2 = [o for o in range(len(self.orientation_names)) 
                     if self._are_orientation_compatible(orientations[idx], sex1, o, sex2)]
            if not valid2: valid2 = valid
            orientations[partner_idx] = np.random.choice(valid2)

            # Sample relationship type if not already assigned
            # Correct categorical logic: forces existing household couples 
            # to be either REL_EXCLUSIVE or REL_NON_EXCLUSIVE based on weights.
            if np.random.random() < prob_exclusive_normalized:
                rel_type = REL_EXCLUSIVE
                exclusive_count += 1
            else:
                rel_type = REL_NON_EXCLUSIVE
                non_exclusive_count += 1

            # Update intended types so they don't try to find ANOTHER partner
            intended_rel_types[idx] = rel_type
            intended_rel_types[partner_idx] = rel_type

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
        logger.info(f"  Processed {couples_count:,} household couples using dynamic orientation logic")

        return partners, rel_types, consensual

    def _create_exclusive_relationships(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        intended_rel_types: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create exclusive relationships using batch matching.
        Fully dynamic based on compatibility rules.
        """
        n = arrays['n']
        sex = arrays['sex']
        age = arrays['age']
        mgu = arrays['mgu']
        eth = arrays['eth']
        venue_to_people = arrays['venue_to_people']

        age_config = self.config['age_differences']
        matching_groups = self._get_matching_groups()

        # Identify singles who want exclusive relationships (explicit choice)
        is_single = partners < 0
        seeking_exclusive = is_single & (intended_rel_types == REL_EXCLUSIVE)
        initial_seekers = seeking_exclusive.sum()
        logger.info(f"  {initial_seekers:,} singles seeking exclusive relationships")

        total_matches = 0

        # ================================================================
        # PHASE 1: Venue-based matching (coworkers/classmates priority)
        # ================================================================
        logger.info("  Phase 1: Matching coworkers/classmates...")
        venue_matches = 0

        for venue_id, people_at_venue in venue_to_people.items():
            # Get seekers at this venue - enforce int64
            venue_seekers = np.array([p for p in people_at_venue if seeking_exclusive[p]], dtype=np.int64)

            if len(venue_seekers) < 2:
                continue

            # Match within venue using dynamic compatibility logic
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
            in_mgu = (mgu == mgu_code)
            
            for (s1, o1), (s2, o2) in matching_groups:
                if s1 == s2 and o1 == o2:
                    pool = np.where(seeking_exclusive & in_mgu & (sex == s1) & (orientations == o1))[0]
                    if len(pool) >= 2:
                        matches = self._match_single_pool(pool, age, eth, age_config)
                        for a, b in matches:
                            partners[a] = b
                            partners[b] = a
                            rel_types[a] = REL_EXCLUSIVE
                            rel_types[b] = REL_EXCLUSIVE
                            seeking_exclusive[a] = False
                            seeking_exclusive[b] = False
                            total_matches += 1
                else:
                    pool1 = np.where(seeking_exclusive & in_mgu & (sex == s1) & (orientations == o1))[0]
                    pool2 = np.where(seeking_exclusive & in_mgu & (sex == s2) & (orientations == o2))[0]
                    if len(pool1) > 0 and len(pool2) > 0:
                        matches = self._match_pools(pool1, pool2, age, eth, age_config)
                        for a, b in matches:
                            partners[a] = b
                            partners[b] = a
                            rel_types[a] = REL_EXCLUSIVE
                            rel_types[b] = REL_EXCLUSIVE
                            seeking_exclusive[a] = False
                            seeking_exclusive[b] = False
                            total_matches += 1

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
            lgu_matches_count = 0

            for lgu_code in unique_lgus:
                in_lgu = (lgu == lgu_code)

                for (s1, o1), (s2, o2) in matching_groups:
                    if s1 == s2 and o1 == o2:
                        pool = np.where(seeking_exclusive & in_lgu & (sex == s1) & (orientations == o1))[0]
                        if len(pool) >= 2:
                            matches = self._match_single_pool(pool, age, eth, age_config)
                            for a, b in matches:
                                partners[a] = b
                                partners[b] = a
                                rel_types[a] = REL_EXCLUSIVE
                                rel_types[b] = REL_EXCLUSIVE
                                seeking_exclusive[a] = False
                                seeking_exclusive[b] = False
                                lgu_matches_count += 1
                                total_matches += 1
                    else:
                        pool1 = np.where(seeking_exclusive & in_lgu & (sex == s1) & (orientations == o1))[0]
                        pool2 = np.where(seeking_exclusive & in_lgu & (sex == s2) & (orientations == o2))[0]
                        if len(pool1) > 0 and len(pool2) > 0:
                            matches = self._match_pools(pool1, pool2, age, eth, age_config)
                            for a, b in matches:
                                partners[a] = b
                                partners[b] = a
                                rel_types[a] = REL_EXCLUSIVE
                                rel_types[b] = REL_EXCLUSIVE
                                seeking_exclusive[a] = False
                                seeking_exclusive[b] = False
                                lgu_matches_count += 1
                                total_matches += 1

            logger.info(f"    Created {lgu_matches_count:,} relationships from LGU fallback")

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

        # Find parameters for the younger pool
        min_age = min(age[pool_a].min(), age[pool_b].min())
        
        # Defaults
        min_age_diff = 0
        max_age_diff = 10
        pref_mean = 2.5
        pref_std = 2.0

        for group in self.age_groups:
            if group['start'] <= min_age <= group['end']:
                cfg = age_config.get(group['name'], {})
                min_age_diff = cfg.get('min', 0)
                max_age_diff = cfg.get('max', 10)
                pref_mean = cfg.get('preferred_mean', 2.5)
                pref_std = cfg.get('preferred_std', 2.0)
                break

        matches_a, matches_b = np.empty(0), np.empty(0)
        seed = int(time.time() * 1000) % 1000000

        # Use Numba kernel - age and eth are already int64 from _build_attribute_arrays
        if self.attribute_matrix is not None:
            matches_a, matches_b = match_with_attribute_weighting(
                pool_a,
                pool_b,
                age,
                eth,
                self.attribute_matrix,
                min_age_diff,
                max_age_diff,
                pref_mean,
                pref_std,
                seed
            )
        else:
            matches_a, matches_b = match_two_pools(
                pool_a,
                pool_b,
                age,
                min_age_diff,
                max_age_diff,
                pref_mean,
                pref_std,
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

        # Compute params based on median age in pool
        median_age = int(np.median(age[pool]))
        
        # Defaults
        min_age_diff = 0
        max_age_diff = 10
        pref_mean = 2.5
        pref_std = 2.0

        for group in self.age_groups:
            if group['start'] <= median_age <= group['end']:
                cfg = age_config.get(group['name'], {})
                min_age_diff = cfg.get('min', 0)
                max_age_diff = cfg.get('max', 10)
                pref_mean = cfg.get('preferred_mean', 2.5)
                pref_std = cfg.get('preferred_std', 2.0)
                break
        
        seed = np.random.randint(0, 2**31)

        matches_a, matches_b = match_single_pool(
            pool,
            age,
            min_age_diff,
            max_age_diff,
            pref_mean,
            pref_std,
            seed
        )

        return list(zip(matches_a, matches_b))

    def _match_within_group(self, group_indices, sex, age, eth, orientations, seeking, age_config):
        """Match compatible people within a group (e.g., coworkers at same venue) using dynamic matching groups."""
        all_matches = []
        matching_groups = self._get_matching_groups()

        # Filter to only those still seeking
        active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
        if len(active) < 2:
            return []

        for (s1, o1), (s2, o2) in matching_groups:
            # Refresh active list
            active = np.array([i for i in group_indices if seeking[i]], dtype=np.int64)
            if len(active) < 2:
                break

            if s1 == s2 and o1 == o2:
                pool = active[(sex[active] == s1) & (orientations[active] == o1)]
                if len(pool) >= 2:
                    matches = self._match_single_pool(pool, age, eth, age_config)
                    for a, b in matches:
                        seeking[a] = False
                        seeking[b] = False
                    all_matches.extend(matches)
            else:
                pool1 = active[(sex[active] == s1) & (orientations[active] == o1)]
                pool2 = active[(sex[active] == s2) & (orientations[active] == o2)]
                if len(pool1) > 0 and len(pool2) > 0:
                    matches = self._match_pools(pool1, pool2, age, eth, age_config)
                    for a, b in matches:
                        seeking[a] = False
                        seeking[b] = False
                    all_matches.extend(matches)

        return all_matches

    def _create_non_exclusive_relationships(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        intended_rel_types: np.ndarray
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

        # Identify who wants non-exclusive (explicit choice)
        is_single = partners < 0
        seeking = is_single & (intended_rel_types == REL_NON_EXCLUSIVE)
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
            venue_seekers = np.array([p for p in people_at_venue if seeking[p]], dtype=np.int64)
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
        """Helper to match by orientation pools within a geographic mask using dynamic rules."""
        matches_created = 0
        matching_groups = self._get_matching_groups()

        for (s1, o1), (s2, o2) in matching_groups:
            if s1 == s2 and o1 == o2:
                pool = np.where(mask & (sex == s1) & (orientations == o1))[0]
                if len(pool) >= 2:
                    matches = self._match_single_pool(pool, age, eth, age_config)
                    for a, b in matches:
                        partners_dict[a].append(b)
                        partners_dict[b].append(a)
                        seeking[a] = False
                        seeking[b] = False
                        matches_created += 1
            else:
                pool1 = np.where(mask & (sex == s1) & (orientations == o1))[0]
                pool2 = np.where(mask & (sex == s2) & (orientations == o2))[0]
                if len(pool1) > 0 and len(pool2) > 0:
                    matches = self._match_pools(pool1, pool2, age, eth, age_config)
                    for a, b in matches:
                        partners_dict[a].append(b)
                        partners_dict[b].append(a)
                        seeking[a] = False
                        seeking[b] = False
                        matches_created += 1

        return matches_created

    def _process_cheating_and_affairs(
        self,
        arrays: Dict,
        orientations: np.ndarray,
        partners: np.ndarray,
        rel_types: np.ndarray,
        consensual: np.ndarray,
        intended_rel_types: np.ndarray
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
        # Willing singles are those who explicitly chose non-exclusive but haven't found a primary partner
        willing_singles = is_single & (intended_rel_types == REL_NON_EXCLUSIVE)

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
            venue_cheaters = np.array([p for p in people_at_venue if cheater_seeking[p]], dtype=np.int64)
            venue_pool = np.array([p for p in people_at_venue if affair_available[p]], dtype=np.int64)

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
        """Match cheaters with affair partners by orientation pools using dynamic rules."""
        affairs_created = 0
        matching_groups = self._get_matching_groups()

        for (s1, o1), (s2, o2) in matching_groups:
            # Direction 1: Cheaters of cat1 with Pool of cat2
            c1_indices = np.where((sex[cheaters] == s1) & (orientations[cheaters] == o1))[0]
            p2_indices = np.where((sex[pool] == s2) & (orientations[pool] == o2))[0]
            
            c1 = cheaters[c1_indices]
            p2 = pool[p2_indices]
            
            if len(c1) > 0 and len(p2) > 0:
                matches = self._match_pools(c1, p2, age, eth, age_config)
                for cheater, partner in matches:
                    affair_partners[cheater].append(partner)
                    consensual[cheater] = False
                    cheater_seeking[cheater] = False
                    affair_available[partner] = False
                    affairs_created += 1

            # Direction 2: Cheaters of cat2 with Pool of cat1 (if different)
            if s1 != s2 or o1 != o2:
                c2_indices = np.where((sex[cheaters] == s2) & (orientations[cheaters] == o2))[0]
                p1_indices = np.where((sex[pool] == s1) & (orientations[pool] == o1))[0]
                
                c2 = cheaters[c2_indices]
                p1 = pool[p1_indices]
                
                if len(c2) > 0 and len(p1) > 0:
                    matches = self._match_pools(c2, p1, age, eth, age_config)
                    for cheater, partner in matches:
                        affair_partners[cheater].append(partner)
                        consensual[cheater] = False
                        cheater_seeking[cheater] = False
                        affair_available[partner] = False
                        affairs_created += 1

        return affairs_created

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
        orientation_names = self.orientation_names
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

            # Partners
            exclusive_partners_list = []
            non_exclusive_partners_list = []

            if partners[i] >= 0:
                partner_id = int(ids[partners[i]])
                rel_type = rel_type_names[rel_types[i]]
                if rel_type == 'exclusive':
                    exclusive_partners_list.append(partner_id)
                elif rel_type == 'non_exclusive':
                    non_exclusive_partners_list.append(partner_id)

            if i in non_exclusive_partners:
                for partner_idx in non_exclusive_partners[i]:
                    pid = int(ids[partner_idx])
                    if pid not in non_exclusive_partners_list:
                        non_exclusive_partners_list.append(pid)

            if i in affair_partners:
                for affair_idx in affair_partners[i]:
                    aid = int(ids[affair_idx])
                    if aid not in non_exclusive_partners_list:
                        non_exclusive_partners_list.append(aid)

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
        logger.info("\n" + "=" * 40 + "\nDISTRIBUTION STATISTICS\n" + "=" * 40)

        # Orientations
        logger.info("\nSexual Orientations:")
        for i, name in enumerate(self.orientation_names):
            count = (orientations == i).sum()
            logger.info(f"  {name.capitalize()}: {count:,} ({100*count/n:.1f}%)")

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
