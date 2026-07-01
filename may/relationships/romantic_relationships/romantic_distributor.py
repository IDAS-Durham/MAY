"""
Romantic relationship distributor for large-scale simulations.

Assigns sexual orientations to all adults (and identifies existing cohabiting
couples).

The orientation source is declared explicitly by the config, one of two
mutually-exclusive paths (no silent fallback — adr/0010):

1. Data-driven (when ``data_sources`` IS set): the two declared files must
   exist or construction fails loud.
   - Demographic prior: ``P(orientation | sex, age_band)`` from the
     ``demographic_distribution`` source's ``path`` (e.g. orientation_prevalence_extended.csv).
   - Geographic marginal: ``P(orientation | geo_unit)`` from the ``geo_distribution``
     source's ``path`` (e.g. orientation_by_msoa_normalized.csv), keyed at its ``geo_level``.
   - The two are reconciled via Iterative Proportional Fitting (IPF) on a
     cell table indexed by ``(sex, age_band, area)``, then sampling is
     cell-batched and vectorized (one np.random.choice per cell), so wall
     time scales in area count, not population.

2. YAML path (when ``data_sources`` is ABSENT): hand-tuned ``probabilities``
   + ``age_adjustments`` from ``romantic_relationships.yaml`` — for non-UK /
   historical worlds without area data. Per-person; intended for small
   populations.

Cohabiting-couple compatibility (orientations must agree with partner sex)
is applied in both paths: in the vectorized path by filtering the cell
probability vector before sampling each (sex, age_band, area, partner_sex)
group.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import yaml
from may.utils import path_resolver as pr
from may.utils.attribute_access import get_person_attribute

logger = logging.getLogger("romantic_relationships")

# Encoding constants
SEX_FEMALE = 0
SEX_MALE = 1
N_SEXES = 2


class RomanticDistributor:
    """Vectorized romantic-relationship / orientation distributor."""

    def __init__(self, world, config: str | dict):
        self.world = world
        self.config = self._load_config(config)
        self.name = self.config['name']

        orient_config = self.config.get('sexual_orientations', {})
        self.orientation_names = orient_config.get(
            'types', ['heterosexual', 'homosexual', 'bisexual']
        )
        self._n_orients = len(self.orientation_names)

        # YAML-fallback age groups (only used when data sources are absent).
        self.age_groups: List[Dict] = []
        for group_str in orient_config.get('age_adjustments', {}).keys():
            if '-' in group_str:
                start, end = map(int, group_str.split('-'))
                self.age_groups.append({'name': group_str, 'start': start, 'end': end})
            elif '+' in group_str:
                start = int(group_str.replace('+', ''))
                self.age_groups.append({'name': group_str, 'start': start, 'end': 200})
        self.age_groups.append({'name': 'all_ages_default', 'start': 0, 'end': 200})
        self.age_groups.sort(key=lambda x: x['start'])

        storage = self.config.get('storage', {})
        self.orientation_key = storage.get('orientation_key', 'sexual_orientation')
        self.status_key = storage.get('status_key', 'relationship_status')

        # Eligibility predicate (same global_filters shape as distributors): a
        # person must pass ALL filters to be assigned an orientation.
        self.global_filters = self.config.get('eligibility', {}).get('global_filters', [])

        # Data-source state (set by _load_data_sources when configured).
        self._use_data_sources = False
        self._prevalence_band_names: List[str] = []
        self._prevalence_bands: List[Tuple[int, int]] = []
        # Dense prior table: shape (n_sexes, n_bands, n_orients).
        self._prevalence_table: Optional[np.ndarray] = None
        self._geo_level: Optional[str] = None  # required from config; no default (adr/0002)
        # MSOA marginal table: shape (n_msoas, n_orients), aligned to self._msoa_codes.
        self._msoa_table: Optional[np.ndarray] = None
        self._msoa_codes: List[str] = []
        self._msoa_idx_by_code: Dict[str, int] = {}

        ds = self.config.get('data_sources')
        if ds:
            self._load_data_sources(ds)

        logger.info(
            f"Initialized {self.name} distributor "
            f"(data_sources={'on' if self._use_data_sources else 'off (YAML path)'})"
        )

    @staticmethod
    def _load_config(config) -> dict:
        if isinstance(config, str):
            with open(pr.resolve(config), 'r') as f:
                return yaml.safe_load(f)
        return config

    # ------------------------------------------------------------------
    # Data-source loading
    # ------------------------------------------------------------------

    def _load_data_sources(self, ds: Dict):
        demo_src = ds.get('demographic_distribution', {})
        geo_src = ds.get('geo_distribution', {})
        prev_path = pr.resolve(demo_src.get('path', '')) or None
        area_path = pr.resolve(geo_src.get('path', '')) or None
        if not prev_path or not os.path.exists(prev_path):
            raise ValueError(
                f"{self.name}: data_sources declared but demographic_distribution.path "
                f"missing or not found: {prev_path} (adr/0010). Omit data_sources to "
                f"use the YAML probabilities path instead."
            )
        if not area_path or not os.path.exists(area_path):
            raise ValueError(
                f"{self.name}: data_sources declared but geo_distribution.path missing "
                f"or not found: {area_path} (adr/0010). Omit data_sources to use the "
                f"YAML probabilities path instead."
            )

        geo_level = geo_src.get('geo_level')
        if not geo_level:
            raise ValueError(
                f"{self.name}: data_sources.geo_distribution needs 'geo_level' (the "
                f"geography level the distribution is keyed at); no default (adr/0002)."
            )
        self._geo_level = geo_level

        # ---- National prior ---------------------------------------------------
        rows: List[Dict] = []
        with open(prev_path) as f:
            for row in csv.DictReader(f):
                rows.append(row)

        bands_seen: List[str] = []
        for r in rows:
            band = r['age_group'].strip()
            if band not in bands_seen:
                bands_seen.append(band)

        def _parse_band(b: str) -> Tuple[int, int]:
            if '-' in b:
                start, end = map(int, b.split('-'))
                return start, end
            if '+' in b:
                return int(b.replace('+', '')), 200
            raise ValueError(f"Unrecognized age band: {b!r}")

        self._prevalence_band_names = bands_seen
        self._prevalence_bands = [_parse_band(b) for b in bands_seen]

        n_bands = len(bands_seen)
        prevalence_table = np.zeros((N_SEXES, n_bands, self._n_orients), dtype=np.float64)
        band_idx_by_name = {name: i for i, name in enumerate(bands_seen)}
        orient_idx_by_name = {name: i for i, name in enumerate(self.orientation_names)}
        for r in rows:
            sex_code = SEX_MALE if r['sex'].strip().lower().startswith('m') else SEX_FEMALE
            b = band_idx_by_name[r['age_group'].strip()]
            o_name = r['orientation'].strip()
            if o_name not in orient_idx_by_name:
                continue
            prevalence_table[sex_code, b, orient_idx_by_name[o_name]] = float(r['probability'])
        # Defensive renormalization per (sex, band).
        sums = prevalence_table.sum(axis=2, keepdims=True)
        prevalence_table = np.where(sums > 0, prevalence_table / sums, 0.0)
        self._prevalence_table = prevalence_table

        # ---- MSOA marginals ---------------------------------------------------
        msoa_rows: Dict[str, np.ndarray] = {}
        with open(area_path) as f:
            for row in csv.DictReader(f):
                code = row['geo_unit'].strip()
                arr = np.zeros(self._n_orients, dtype=np.float64)
                for i, name in enumerate(self.orientation_names):
                    if name in row:
                        arr[i] = float(row[name])
                s = arr.sum()
                if s > 0:
                    msoa_rows[code] = arr / s

        self._msoa_codes = sorted(msoa_rows.keys())
        self._msoa_idx_by_code = {c: i for i, c in enumerate(self._msoa_codes)}
        msoa_table = np.zeros((len(self._msoa_codes), self._n_orients), dtype=np.float64)
        for code, arr in msoa_rows.items():
            msoa_table[self._msoa_idx_by_code[code]] = arr
        self._msoa_table = msoa_table

        self._use_data_sources = True
        logger.info(
            f"Loaded prevalence ({n_bands} bands x {N_SEXES} sexes) and "
            f"{len(self._msoa_codes)} MSOA marginals"
        )

    def _age_to_band_idx(self, age: int) -> Optional[int]:
        for i, (start, end) in enumerate(self._prevalence_bands):
            if start <= age <= end:
                return i
        if self._prevalence_bands and age > self._prevalence_bands[-1][1]:
            return len(self._prevalence_bands) - 1
        return None

    def _age_array_to_band_idx(self, ages: np.ndarray) -> np.ndarray:
        """Vectorized band lookup. Returns -1 for ages below the first band."""
        out = np.full(ages.shape, -1, dtype=np.int64)
        for i, (start, end) in enumerate(self._prevalence_bands):
            mask = (ages >= start) & (ages <= end) & (out < 0)
            out[mask] = i
        if self._prevalence_bands:
            tail = (ages > self._prevalence_bands[-1][1]) & (out < 0)
            out[tail] = len(self._prevalence_bands) - 1
        return out

    # ------------------------------------------------------------------
    # Geography indexing (SGU → MSOA cache)
    # ------------------------------------------------------------------

    def _build_sgu_to_msoa_cache(self) -> Dict[str, int]:
        """Map every SGU code to its MSOA index, once.

        At 60M people the per-person ``get_ancestor_by_level`` walks were
        the bottleneck; iterating geography units directly is ~200k walks
        regardless of population.
        """
        cache: Dict[str, int] = {}
        geo = getattr(self.world, 'geography', None)
        if geo is None:
            return cache
        # Try the geography levels declared by the world.
        for level_name in getattr(geo, 'levels', []) or []:
            try:
                units = geo.get_units_by_level(level_name)
            except Exception:
                continue
            if not units:
                continue
            iterator = units.values() if isinstance(units, dict) else units
            for unit in iterator:
                try:
                    ancestor = unit.get_ancestor_by_level(self._geo_level)
                except Exception:
                    ancestor = None
                if ancestor is None:
                    continue
                idx = self._msoa_idx_by_code.get(ancestor.name)
                if idx is not None:
                    cache[unit.name] = idx
        return cache

    def _msoa_idx_for_person(self, person, sgu_cache: Dict[str, int]) -> int:
        unit = getattr(person, 'geographical_unit', None)
        if unit is None:
            return -1
        # Fast path: SGU cache hit.
        idx = sgu_cache.get(unit.name)
        if idx is not None:
            return idx
        # Fallback: walk the parent chain on demand (used by mocks in tests).
        try:
            ancestor = unit.get_ancestor_by_level(self._geo_level)
        except Exception:
            return -1
        if ancestor is None:
            return -1
        return self._msoa_idx_by_code.get(ancestor.name, -1)

    # ------------------------------------------------------------------
    # IPF
    # ------------------------------------------------------------------

    def _build_cell_table(self,
                          sex_arr: np.ndarray,
                          band_arr: np.ndarray,
                          msoa_arr: np.ndarray,
                          max_iter: int = 50,
                          tol: float = 1e-4) -> np.ndarray:
        """Build a (sex, band, msoa, orientation) probability table via IPF.

        The cell table is initialized as ``cell_pop[s,b,m] · P_nat[s,b,o]``
        and then alternately scaled to satisfy:
          - The MSOA marginal: Σ_(s,b) C[s,b,m,o] = msoa_pop[m] · P_msoa[m,o]
          - The (sex, band) marginal: Σ_m C[s,b,m,o] = sb_pop[s,b] · P_nat[s,b,o]
        until both ratios are within ``tol`` of 1.0. Empty cells (zero
        population) stay zero throughout and don't influence either marginal.

        Returns a (n_sexes, n_bands, n_msoas, n_orients) probability array
        whose rows sum to 1 along the orientation axis (and falls back to
        ``P_nat`` for any cell with zero population)."""
        n_bands = len(self._prevalence_band_names)
        n_msoas = len(self._msoa_codes)

        # Population per cell (only counts adults with a valid (band, msoa)).
        cell_pop = np.zeros((N_SEXES, n_bands, n_msoas), dtype=np.float64)
        valid = (band_arr >= 0) & (msoa_arr >= 0)
        if valid.any():
            np.add.at(
                cell_pop,
                (sex_arr[valid], band_arr[valid], msoa_arr[valid]),
                1,
            )

        # Initial cell counts, target marginals.
        target_nat = self._prevalence_table  # (n_sexes, n_bands, n_orients)
        target_msoa = self._msoa_table       # (n_msoas, n_orients)

        cell_count = cell_pop[..., None] * target_nat[:, :, None, :]

        sb_pop = cell_pop.sum(axis=2, keepdims=True)               # (S, B, 1)
        msoa_pop = cell_pop.sum(axis=(0, 1))[:, None]              # (M, 1)
        target_msoa_count = msoa_pop * target_msoa                # (M, O)
        target_nat_count = sb_pop * target_nat                    # (S, B, O)

        # Convergence criterion: max relative change in cell_count between
        # iterations. This works whether the two marginals are mutually
        # consistent (the usual case in a representative population) or
        # inconsistent (the result is then the I-projection — IPF still
        # converges to a stable fixed point, the marginals just don't both
        # match exactly).
        prev_count = cell_count.copy()
        for it in range(max_iter):
            # Step A: rescale to MSOA marginal.
            current_msoa = cell_count.sum(axis=(0, 1))            # (M, O)
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio_a = np.where(current_msoa > 0,
                                   target_msoa_count / current_msoa,
                                   1.0)
            cell_count = cell_count * ratio_a[None, None, :, :]

            # Step B: rescale to (sex, band) marginal.
            current_nat = cell_count.sum(axis=2)                  # (S, B, O)
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio_b = np.where(current_nat > 0,
                                   target_nat_count / current_nat,
                                   1.0)
            cell_count = cell_count * ratio_b[:, :, None, :]

            denom = np.maximum(prev_count, 1e-12)
            delta = float(np.max(np.abs(cell_count - prev_count) / denom))
            prev_count = cell_count.copy()
            if delta < tol:
                logger.info(
                    f"IPF converged in {it + 1} iterations (max cell-count change = {delta:.2e})"
                )
                break
        else:
            logger.info(
                f"IPF reached max iterations ({max_iter}); "
                f"last cell-count change = {delta:.2e} — accepting current fit"
            )

        # Convert counts → probabilities; empty cells fall back to P_nat.
        with np.errstate(divide='ignore', invalid='ignore'):
            cell_prob = np.where(
                cell_pop[..., None] > 0,
                cell_count / np.maximum(cell_pop[..., None], 1.0),
                target_nat[:, :, None, :],
            )

        # Final defensive renormalization in case of round-off drift.
        sums = cell_prob.sum(axis=3, keepdims=True)
        cell_prob = np.where(sums > 0, cell_prob / sums, target_nat[:, :, None, :])
        return cell_prob

    # ------------------------------------------------------------------
    # Vectorized sampling
    # ------------------------------------------------------------------

    def _sample_orientations_vectorized(self,
                                        arrays: Dict[str, np.ndarray],
                                        sex_arr: np.ndarray,
                                        band_arr: np.ndarray,
                                        msoa_arr: np.ndarray,
                                        partner_sex_arr: np.ndarray,
                                        cell_prob: np.ndarray,
                                        compatibility: Dict[str, Dict[str, List[str]]]) -> np.ndarray:
        """Cell-batched np.random.choice — one call per unique group.

        Groups are keyed on ``(sex, band, msoa, partner_sex)``. Singles share
        groups across partner_sex by encoding "no partner" as -1, so they
        get the unfiltered cell distribution. Coupled people get the cell
        distribution with incompatible orientations zeroed and renormalized.
        """
        n = arrays['n']
        n_orients = self._n_orients
        orientations = np.zeros(n, dtype=np.int8)

        # Encode group key as a single int32. Bounds: msoa+1 in [0, n_msoas],
        # band+1 in [0, n_bands], partner_sex+1 in [0, 2]. With current data
        # (n_msoas≈7k, n_bands≈9) the key stays well below 2**31.
        n_bands = len(self._prevalence_band_names)
        n_msoas = len(self._msoa_codes)
        ps_card = 3      # -1 (no partner), 0 (female), 1 (male)
        sex_card = N_SEXES

        key = (
            (sex_arr.astype(np.int64) * (n_bands + 1) + (band_arr.astype(np.int64) + 1))
            * (n_msoas + 1) + (msoa_arr.astype(np.int64) + 1)
        ) * ps_card + (partner_sex_arr.astype(np.int64) + 1)

        # `argsort + diff` gives us groups without ever materializing a Python loop
        # over individuals.
        order = np.argsort(key, kind='stable')
        sorted_key = key[order]
        boundaries = np.concatenate(([0], np.flatnonzero(np.diff(sorted_key)) + 1, [n]))

        # Compatibility lookup per (own_sex, partner_sex) → boolean mask of valid orientations.
        compat_mask = np.ones((sex_card, ps_card, n_orients), dtype=bool)
        for own_code in (SEX_MALE, SEX_FEMALE):
            own_name = 'male' if own_code == SEX_MALE else 'female'
            for ps_code in (-1, SEX_FEMALE, SEX_MALE):
                ps_idx = ps_code + 1
                if ps_code < 0:
                    continue  # singles get the full mask
                ps_name = 'male' if ps_code == SEX_MALE else 'female'
                for o_idx, o_name in enumerate(self.orientation_names):
                    compat_sexes = compatibility.get(o_name, {}).get(own_name, [])
                    compat_mask[own_code, ps_idx, o_idx] = ps_name in compat_sexes

        # Decode key → (sex, band, msoa, partner_sex) with the same arithmetic.
        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i + 1]
            run = order[start:end]
            n_run = end - start

            k = int(sorted_key[start])
            ps_idx = k % ps_card
            k //= ps_card
            m_plus_one = k % (n_msoas + 1)
            k //= (n_msoas + 1)
            b_plus_one = k % (n_bands + 1)
            s_code = k // (n_bands + 1)
            m_idx = m_plus_one - 1
            b_idx = b_plus_one - 1

            # Cell probability vector. If band/msoa are missing (e.g. person
            # has no MSOA), fall back to P_nat for the (sex, band) cell.
            if b_idx < 0:
                # Should not happen given _age_array_to_band_idx clamping.
                probs = np.zeros(n_orients)
                probs[0] = 1.0
            elif m_idx < 0:
                probs = self._prevalence_table[s_code, b_idx].copy()
            else:
                probs = cell_prob[s_code, b_idx, m_idx].copy()

            if ps_idx > 0:  # coupled
                mask = compat_mask[s_code, ps_idx]
                probs = probs * mask
                total = probs.sum()
                if total > 0:
                    probs = probs / total
                else:
                    # No compatible orientation under the current cell distribution.
                    # Force-map to the first compatible orientation.
                    forced = np.zeros(n_orients)
                    valid = np.flatnonzero(mask)
                    forced[valid[0] if valid.size else 0] = 1.0
                    probs = forced

            orientations[run] = np.random.choice(n_orients, size=n_run, p=probs).astype(np.int8)

        return orientations

    # ------------------------------------------------------------------
    # YAML fallback (per-person, used by Medieval / tests)
    # ------------------------------------------------------------------

    def _yaml_base_probs(self, sex_code: int, age: int) -> np.ndarray:
        orient_config = self.config.get('sexual_orientations', {})
        s_name = 'male' if sex_code == SEX_MALE else 'female'
        base = orient_config.get('probabilities', {}).get(s_name, {})
        probs = np.array(
            [base.get(name, 0.0) for name in self.orientation_names],
            dtype=np.float64,
        )
        s = probs.sum()
        if s > 0:
            probs /= s
        else:
            probs[0] = 1.0

        for group in self.age_groups:
            if group['start'] <= age <= group['end']:
                adj = orient_config.get('age_adjustments', {}).get(group['name'], {})
                for i, name in enumerate(self.orientation_names):
                    if name in adj:
                        probs[i] *= adj[name]
                break
        s = probs.sum()
        if s > 0:
            probs /= s
        else:
            probs = np.zeros(len(self.orientation_names))
            probs[0] = 1.0
        return probs

    def _sample_orientations_yaml(self,
                                  adults: List,
                                  arrays: Dict[str, np.ndarray]) -> np.ndarray:
        n = arrays['n']
        orientations = np.zeros(n, dtype=np.int8)
        compatibility = self.config.get('sexual_orientations', {}).get('compatibility', {})
        sex = arrays['sex']
        cohabiting_couple = arrays['cohabiting_couple']
        ids = arrays['ids']
        n_orients = self._n_orients

        id_to_sex = {
            p.id: (SEX_MALE if p.sex.lower().startswith('m') else SEX_FEMALE)
            for p in self.world.population.people
        }

        for idx, person in enumerate(adults):
            s_code = int(sex[idx])
            s_name = 'male' if s_code == SEX_MALE else 'female'
            probs = self._yaml_base_probs(s_code, int(person.age))

            partner_id = cohabiting_couple[idx]
            partner_sex_code = None
            if partner_id >= 0:
                partner_sex_code = id_to_sex.get(int(partner_id))
                if partner_sex_code is not None:
                    ps_name = 'male' if partner_sex_code == SEX_MALE else 'female'
                    for i, o_name in enumerate(self.orientation_names):
                        if ps_name not in compatibility.get(o_name, {}).get(s_name, []):
                            probs[i] = 0.0

            total = probs.sum()
            if total > 0:
                probs = probs / total
            elif partner_id >= 0 and partner_sex_code is not None:
                ps_name = 'male' if partner_sex_code == SEX_MALE else 'female'
                valid = [
                    i for i, o_name in enumerate(self.orientation_names)
                    if ps_name in compatibility.get(o_name, {}).get(s_name, [])
                ]
                probs = np.zeros(n_orients)
                probs[valid[0] if valid else 0] = 1.0
            else:
                probs = np.zeros(n_orients)
                probs[0] = 1.0

            orientations[idx] = np.random.choice(n_orients, p=probs)

        return orientations

    def _passes_filters(self, person) -> bool:
        """True if the person passes ALL eligibility.global_filters (AND-ed).

        Same shape/semantics as distributor global_filters: numerical uses
        inclusive min/max; categorical uses value/values; a missing attribute
        fails the filter.
        """
        for f in self.global_filters:
            val = get_person_attribute(person, f['attribute'])
            if val is None:
                return False
            if f.get('type', 'numerical') == 'numerical':
                lo, hi = f.get('min'), f.get('max')
                if lo is not None and val < lo:
                    return False
                if hi is not None and val > hi:
                    return False
            else:  # categorical
                if 'value' in f and val != f['value']:
                    return False
                if 'values' in f and val not in f['values']:
                    return False
        return True

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    def distribute_all(self):
        total_start = time.time()

        logger.info("=" * 60)
        logger.info(f"Starting {self.name} distribution")
        logger.info("=" * 60)

        eligible_people = [
            p for p in self.world.population.people
            if self._passes_filters(p)
        ]
        n = len(eligible_people)
        logger.info(f"Processing {n:,} eligible people")

        arrays = self._build_attribute_arrays(eligible_people)

        if self._use_data_sources and n > 0:
            t0 = time.time()
            sgu_cache = self._build_sgu_to_msoa_cache()
            logger.info(
                f"Built SGU→MSOA cache in {time.time() - t0:.2f}s "
                f"({len(sgu_cache):,} entries)"
            )

            t0 = time.time()
            band_arr = self._age_array_to_band_idx(arrays['age'])
            msoa_arr = np.fromiter(
                (self._msoa_idx_for_person(p, sgu_cache) for p in eligible_people),
                dtype=np.int64, count=n,
            )
            partner_sex_arr = self._build_partner_sex_array(arrays['cohabiting_couple'])
            logger.info(f"Built per-person index arrays in {time.time() - t0:.2f}s")

            t0 = time.time()
            cell_prob = self._build_cell_table(arrays['sex'].astype(np.int64), band_arr, msoa_arr)
            logger.info(f"IPF cell table built in {time.time() - t0:.2f}s")

            t0 = time.time()
            compatibility = self.config.get('sexual_orientations', {}).get('compatibility', {})
            orientations = self._sample_orientations_vectorized(
                arrays,
                arrays['sex'].astype(np.int64),
                band_arr,
                msoa_arr,
                partner_sex_arr,
                cell_prob,
                compatibility,
            )
            logger.info(f"Sampled {n:,} orientations in {time.time() - t0:.2f}s")
        else:
            t0 = time.time()
            orientations = self._sample_orientations_yaml(eligible_people, arrays)
            logger.info(f"Sampled {n:,} orientations in {time.time() - t0:.2f}s (YAML path)")

        self._write_results(eligible_people, arrays, orientations)

        total_time = time.time() - total_start
        logger.info(f"Relationship processing complete in {total_time:.2f}s")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
            'n': n,
        }

    def _build_partner_sex_array(self, cohabiting_couple: np.ndarray) -> np.ndarray:
        """For each adult, return the sex code of their partner, or -1 if none."""
        id_to_sex = {
            p.id: (SEX_MALE if p.sex.lower().startswith('m') else SEX_FEMALE)
            for p in self.world.population.people
        }
        out = np.full(cohabiting_couple.shape, -1, dtype=np.int64)
        for i, pid in enumerate(cohabiting_couple):
            if pid >= 0:
                ps = id_to_sex.get(int(pid))
                if ps is not None:
                    out[i] = ps
        return out

    def _write_results(self, adults: List, arrays: Dict, orientations: np.ndarray):
        cohabiting_couple_ids = arrays['cohabiting_couple']
        for i, person in enumerate(adults):
            person.properties[self.orientation_key] = self.orientation_names[orientations[i]]
            if cohabiting_couple_ids[i] >= 0:
                person.properties[self.status_key] = {'type': 'exclusive', 'consensual': True}
            else:
                person.properties[self.status_key] = {'type': 'no_partner', 'consensual': True}
