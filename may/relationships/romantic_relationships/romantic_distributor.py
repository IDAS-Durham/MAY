"""
Romantic relationship distributor for large-scale simulations.

This simplified version handles sexual orientation assignment and 
identifies existing cohabiting couples.
"""

import logging
import yaml
import numpy as np
from typing import Dict, List, Optional
import time

logger = logging.getLogger("romantic_relationships")

# Encoding constants
SEX_FEMALE = 0
SEX_MALE = 1

class RomanticDistributor:
    """
    Simplified romantic relationship distributor.
    Assigns sexual orientations and flags cohabiting couples.
    """

    def __init__(self, world, config: str | dict):
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']

        # 1. Dynamic Orientations
        orient_config = self.config.get('sexual_orientations', {})
        self.orientation_names = orient_config.get('types', ['heterosexual', 'homosexual', 'bisexual'])
        
        # 2. Dynamic Age Groups (for orientation assignment)
        age_diff_config = self.config.get('age_differences', {})
        self.age_groups = []
        # We still need age groups if the config uses them for orientation adjustments
        # We only parse what orientation logic needs.
        orient_adj = orient_config.get('age_adjustments', {})
        for group_str in orient_adj.keys():
            if '-' in group_str:
                start, end = map(int, group_str.split('-'))
                self.age_groups.append({'name': group_str, 'start': start, 'end': end})
            elif '+' in group_str:
                start = int(group_str.replace('+', ''))
                self.age_groups.append({'name': group_str, 'start': start, 'end': 200})
        
        # Default age group if none defined in adjustments
        if not self.age_groups:
            self.age_groups = [{'name': 'all', 'start': 0, 'end': 200}]

        self.age_groups.sort(key=lambda x: x['start'])

        # Storage keys
        storage = self.config.get('storage', {})
        self.orientation_key = storage.get('orientation_key', 'sexual_orientation')
        self.status_key = storage.get('status_key', 'relationship_status')

        # General constraints
        self.min_age = self.config.get('min_age', 18)
        self.max_age = self.config.get('max_age', 120)

        logger.info(f"Initialized simplified {self.name} distributor")

    def _load_config(self, config) -> dict:
        if isinstance(config, str):
            with open(config, 'r') as f:
                return yaml.safe_load(f)
        return config

    def distribute_all(self):
        """Main entry point for orientation assignment and cohabiting couple processing."""
        total_start = time.time()

        logger.info("=" * 60)
        logger.info(f"Starting {self.name} distribution")
        logger.info("=" * 60)

        # Get all eligible people
        eligible_people = [p for p in self.world.population.people if self.min_age <= p.age <= self.max_age]
        n = len(eligible_people)
        logger.info(f"Processing {n:,} eligible people")

        # Step 1: Extract attributes
        arrays = self._build_attribute_arrays(eligible_people)

        # Step 2: Assign orientations
        orientations = self._assign_orientations(arrays)
        logger.info(f"Assigned {len(orientations)} orientations")

        # Step 3: Write results back to person objects
        self._write_results(eligible_people, arrays, orientations)

        total_time = time.time() - total_start
        logger.info(f"Relationship processing complete in {total_time:.2f}s")

    def _build_attribute_arrays(self, adults: List) -> Dict[str, np.ndarray]:
        n = len(adults)
        ids = np.empty(n, dtype=np.int64)
        sex = np.empty(n, dtype=np.int8)
        age = np.empty(n, dtype=np.int64)
        cohabiting_couple = np.full(n, -1, dtype=np.int64)

        for i, person in enumerate(adults):
            ids[i] = person.id
            sex[i] = SEX_MALE if person.sex.lower().startswith('m') else SEX_FEMALE
            age[i] = person.age
            cc = person.properties.get('cohabiting_couple')
            if cc and isinstance(cc, list) and len(cc) > 0:
                cohabiting_couple[i] = cc[0]

        return {
            'ids': ids,
            'sex': sex,
            'age': age,
            'cohabiting_couple': cohabiting_couple,
            'n': n
        }

    def _assign_orientations(self, arrays: Dict[str, np.ndarray]) -> np.ndarray:
        n = arrays['n']
        orientations = np.zeros(n, dtype=np.int8)
        orientation_config = self.config.get('sexual_orientations', {})
        age_adjustments = orientation_config.get('age_adjustments', {})

        probs_by_sex = {}
        for s_name in ['male', 'female']:
            s_code = SEX_MALE if s_name == 'male' else SEX_FEMALE
            base = orientation_config.get('probabilities', {}).get(s_name, {})
            p_arr = np.array([base.get(name, 0.0) for name in self.orientation_names], dtype=np.float32)
            if p_arr.sum() == 0: p_arr[0] = 1.0
            probs_by_sex[s_code] = p_arr / p_arr.sum()

        sex = arrays['sex']
        age = arrays['age']

        for s_code in [SEX_MALE, SEX_FEMALE]:
            base_probs = probs_by_sex[s_code]
            for group in self.age_groups:
                mask = (sex == s_code) & (age >= group['start']) & (age <= group['end'])
                indices = np.where(mask)[0]
                if len(indices) == 0: continue

                adj = age_adjustments.get(group['name'], {})
                probs = base_probs.copy()
                for i, name in enumerate(self.orientation_names):
                    if name in adj: probs[i] *= adj[name]

                prob_sum = probs.sum()
                if prob_sum > 0: probs = probs / prob_sum
                else:
                    probs = np.zeros(len(self.orientation_names))
                    probs[0] = 1.0

                orientations[indices] = np.random.choice(
                    np.arange(len(self.orientation_names), dtype=np.int8),
                    size=len(indices),
                    p=probs
                )

        return orientations

    def _write_results(self, adults: List, arrays: Dict, orientations: np.ndarray):
        cohabiting_couple_ids = arrays['cohabiting_couple']
        for i, person in enumerate(adults):
            person.properties[self.orientation_key] = self.orientation_names[orientations[i]]
            if cohabiting_couple_ids[i] >= 0:
                person.properties[self.status_key] = {'type': 'exclusive', 'consensual': True}
            else:
                person.properties[self.status_key] = {'type': 'no_partner', 'consensual': True}
