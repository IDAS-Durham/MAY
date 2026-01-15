"""
Numba-accelerated matching kernels for romantic relationship distribution.

These functions are JIT-compiled to machine code for maximum performance.
Designed for 60M+ scale where Python loops are prohibitively slow.
"""

import numpy as np
from numba import njit, prange
from numba.typed import List as NumbaList
from typing import Tuple


@njit(cache=True)
def fast_shuffle(arr: np.ndarray, seed: int) -> np.ndarray:
    """Fisher-Yates shuffle with explicit seed for reproducibility."""
    n = len(arr)
    result = arr.copy()
    np.random.seed(seed)
    for i in range(n - 1, 0, -1):
        j = np.random.randint(0, i + 1)
        result[i], result[j] = result[j], result[i]
    return result


@njit(cache=True)
def match_two_pools_fast(
    pool_a: np.ndarray,
    pool_b: np.ndarray,
    age: np.ndarray,
    max_age_diff: int,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fast two-pool matching with age constraints.

    Returns arrays of matched pairs (indices into original pool arrays).
    Uses greedy matching after shuffle for O(n) average case.
    """
    n_a = len(pool_a)
    n_b = len(pool_b)

    if n_a == 0 or n_b == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    # Shuffle pools
    shuffled_a = fast_shuffle(pool_a, seed)
    shuffled_b = fast_shuffle(pool_b, seed + 1)

    # Pre-allocate output arrays (max possible matches)
    max_matches = min(n_a, n_b)
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    # Track which indices in pool_b are used
    used_b = np.zeros(n_b, dtype=np.bool_)

    match_count = 0

    for i in range(n_a):
        a_idx = shuffled_a[i]
        age_a = age[a_idx]

        # Find first compatible match in pool_b
        for j in range(n_b):
            if used_b[j]:
                continue

            b_idx = shuffled_b[j]
            age_diff = abs(age[b_idx] - age_a)

            if age_diff <= max_age_diff:
                # Match found
                matches_a[match_count] = a_idx
                matches_b[match_count] = b_idx
                used_b[j] = True
                match_count += 1
                break

    return matches_a[:match_count], matches_b[:match_count]


@njit(cache=True)
def match_single_pool_fast(
    pool: np.ndarray,
    age: np.ndarray,
    max_age_diff: int,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fast single-pool matching (for same-sex pairs).

    Pairs up elements within a single pool.
    """
    n = len(pool)

    if n < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    shuffled = fast_shuffle(pool, seed)

    max_matches = n // 2
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    used = np.zeros(n, dtype=np.bool_)
    match_count = 0

    for i in range(n):
        if used[i]:
            continue

        a_idx = shuffled[i]
        age_a = age[a_idx]

        for j in range(i + 1, n):
            if used[j]:
                continue

            b_idx = shuffled[j]
            age_diff = abs(age[b_idx] - age_a)

            if age_diff <= max_age_diff:
                matches_a[match_count] = a_idx
                matches_b[match_count] = b_idx
                used[i] = True
                used[j] = True
                match_count += 1
                break

    return matches_a[:match_count], matches_b[:match_count]


@njit(cache=True)
def match_with_ethnicity_fast(
    pool_a: np.ndarray,
    pool_b: np.ndarray,
    age: np.ndarray,
    eth: np.ndarray,
    eth_matrix: np.ndarray,
    max_age_diff: int,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Two-pool matching with age AND ethnicity constraints.

    Ethnicity is handled via probabilistic accept/reject.
    """
    n_a = len(pool_a)
    n_b = len(pool_b)

    if n_a == 0 or n_b == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    shuffled_a = fast_shuffle(pool_a, seed)
    shuffled_b = fast_shuffle(pool_b, seed + 1)

    max_matches = min(n_a, n_b)
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    used_b = np.zeros(n_b, dtype=np.bool_)
    match_count = 0

    np.random.seed(seed + 2)
    n_eth = eth_matrix.shape[0]

    for i in range(n_a):
        a_idx = shuffled_a[i]
        age_a = age[a_idx]
        eth_a = eth[a_idx]

        for j in range(n_b):
            if used_b[j]:
                continue

            b_idx = shuffled_b[j]

            # Age check
            age_diff = abs(age[b_idx] - age_a)
            if age_diff > max_age_diff:
                continue

            # Ethnicity check (probabilistic)
            eth_b = eth[b_idx]
            if eth_a < n_eth and eth_b < n_eth:
                eth_prob = eth_matrix[eth_a, eth_b]
                if np.random.random() > eth_prob:
                    continue  # Reject

            # Match!
            matches_a[match_count] = a_idx
            matches_b[match_count] = b_idx
            used_b[j] = True
            match_count += 1
            break

    return matches_a[:match_count], matches_b[:match_count]


@njit(parallel=True, cache=True)
def batch_match_by_geography(
    pool_a_starts: np.ndarray,
    pool_a_ends: np.ndarray,
    pool_b_starts: np.ndarray,
    pool_b_ends: np.ndarray,
    all_pool_a: np.ndarray,
    all_pool_b: np.ndarray,
    age: np.ndarray,
    max_age_diff: int,
    base_seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Parallel matching across multiple geographic regions.

    Each region is processed in parallel using prange.
    """
    n_regions = len(pool_a_starts)

    # Pre-compute max possible matches per region
    # We'll collect all matches then concatenate
    all_matches_a = np.empty(len(all_pool_a), dtype=np.int64)
    all_matches_b = np.empty(len(all_pool_b), dtype=np.int64)
    match_counts = np.zeros(n_regions, dtype=np.int64)

    # Process each region in parallel
    for r in prange(n_regions):
        a_start, a_end = pool_a_starts[r], pool_a_ends[r]
        b_start, b_end = pool_b_starts[r], pool_b_ends[r]

        pool_a = all_pool_a[a_start:a_end]
        pool_b = all_pool_b[b_start:b_end]

        if len(pool_a) == 0 or len(pool_b) == 0:
            continue

        seed = base_seed + r * 1000

        matches_a, matches_b = match_two_pools_fast(
            pool_a, pool_b, age, max_age_diff, seed
        )

        # Store matches (use region start as offset)
        n_matches = len(matches_a)
        match_counts[r] = n_matches

        # Note: In parallel, we need to write to non-overlapping regions
        # This is a simplified version; real implementation would use atomic ops
        # or pre-allocated per-region buffers

    # For now, return empty - the serial version works better for correctness
    return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)


@njit(cache=True)
def vectorized_age_filter(
    candidates: np.ndarray,
    person_age: int,
    ages: np.ndarray,
    max_age_diff: int
) -> np.ndarray:
    """Filter candidates by age difference (vectorized)."""
    n = len(candidates)
    mask = np.empty(n, dtype=np.bool_)

    for i in range(n):
        age_diff = abs(ages[candidates[i]] - person_age)
        mask[i] = age_diff <= max_age_diff

    return candidates[mask]


@njit(cache=True)
def sample_with_replacement_check(
    pool: np.ndarray,
    weights: np.ndarray,
    n_samples: int,
    seed: int
) -> np.ndarray:
    """
    Weighted sampling without replacement.

    Used for selecting multiple partners with weighted probabilities.
    """
    n = len(pool)
    if n == 0 or n_samples == 0:
        return np.empty(0, dtype=np.int64)

    np.random.seed(seed)

    # Normalize weights
    total = weights.sum()
    if total == 0:
        return np.empty(0, dtype=np.int64)

    norm_weights = weights / total

    # Sample without replacement
    available = np.ones(n, dtype=np.bool_)
    samples = np.empty(min(n_samples, n), dtype=np.int64)
    sample_count = 0

    for _ in range(n_samples):
        if sample_count >= n:
            break

        # Compute weights for available items
        current_weights = norm_weights * available
        total = current_weights.sum()

        if total == 0:
            break

        current_weights = current_weights / total

        # Sample one
        r = np.random.random()
        cumsum = 0.0
        selected = -1

        for i in range(n):
            if not available[i]:
                continue
            cumsum += current_weights[i]
            if r <= cumsum:
                selected = i
                break

        if selected >= 0:
            samples[sample_count] = pool[selected]
            available[selected] = False
            sample_count += 1

    return samples[:sample_count]


@njit(cache=True)
def compute_geo_weights(
    person_mgu: int,
    person_lgu: int,
    candidate_mgus: np.ndarray,
    candidate_lgus: np.ndarray,
    same_mgu_bonus: float,
    same_lgu_bonus: float
) -> np.ndarray:
    """Compute geographic proximity weights for candidates."""
    n = len(candidate_mgus)
    weights = np.ones(n, dtype=np.float64)

    for i in range(n):
        if candidate_mgus[i] == person_mgu:
            weights[i] *= same_mgu_bonus
        elif candidate_lgus[i] == person_lgu:
            weights[i] *= same_lgu_bonus

    return weights
