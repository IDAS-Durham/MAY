"""
Matching kernels for romantic relationship distribution.

These functions provide high-performance matching logic for large-scale populations.
"""

import numpy as np
from numba import njit
from numba.typed import List as NumbaList
from typing import Tuple


@njit(cache=True)
def shuffle_indices(arr: np.ndarray, seed: int) -> np.ndarray:
    """Fisher-Yates shuffle with explicit seed for reproducibility."""
    n = len(arr)
    result = arr.copy()
    np.random.seed(seed)
    for i in range(n - 1, 0, -1):
        j = np.random.randint(0, i + 1)
        result[i], result[j] = result[j], result[i]
    return result


@njit(cache=True)
def match_two_pools(
    pool_a: np.ndarray,
    pool_b: np.ndarray,
    age: np.ndarray,
    min_age_diff: int,
    max_age_diff: int,
    pref_mean: float,
    pref_std: float,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fast two-pool matching with age constraints and preference distribution.

    Returns arrays of matched pairs (indices into original pool arrays).
    Uses greedy matching after shuffle for O(n) average case.
    """
    n_a = len(pool_a)
    n_b = len(pool_b)

    if n_a == 0 or n_b == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    # Shuffle pools
    shuffled_a = shuffle_indices(pool_a, seed)
    shuffled_b = shuffle_indices(pool_b, seed + 1)

    # Pre-allocate output arrays (max possible matches)
    max_matches = min(n_a, n_b)
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    # Track which indices in pool_b are used
    used_b = np.zeros(n_b, dtype=np.bool_)

    match_count = 0
    np.random.seed(seed + 2)

    for i in range(n_a):
        a_idx = shuffled_a[i]
        age_a = age[a_idx]

        # Find first compatible match in pool_b
        for j in range(n_b):
            if used_b[j]:
                continue

            b_idx = shuffled_b[j]
            age_diff = abs(age[b_idx] - age_a)

            # Hard constraints
            if age_diff < min_age_diff or age_diff > max_age_diff:
                continue
            
            # Preference matching (Gaussian likelihood)
            # If pref_std is very small, we treat it as a hard preference for pref_mean
            if pref_std > 0:
                dist = (float(age_diff) - pref_mean) / pref_std
                prob = np.exp(-0.5 * dist * dist)
                if np.random.random() > prob:
                    continue # Reject based on preference

            # Match found
            matches_a[match_count] = a_idx
            matches_b[match_count] = b_idx
            used_b[j] = True
            match_count += 1
            break

    return matches_a[:match_count], matches_b[:match_count]


@njit(cache=True)
def match_single_pool(
    pool: np.ndarray,
    age: np.ndarray,
    min_age_diff: int,
    max_age_diff: int,
    pref_mean: float,
    pref_std: float,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fast single-pool matching (for same-sex pairs) with age preference distribution.

    Pairs up elements within a single pool.
    """
    n = len(pool)

    if n < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    shuffled = shuffle_indices(pool, seed)

    max_matches = n // 2
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    used = np.zeros(n, dtype=np.bool_)
    match_count = 0
    np.random.seed(seed + 1)

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

            # Hard constraints
            if age_diff < min_age_diff or age_diff > max_age_diff:
                continue
            
            # Preference matching (Gaussian likelihood)
            if pref_std > 0:
                dist = (float(age_diff) - pref_mean) / pref_std
                prob = np.exp(-0.5 * dist * dist)
                if np.random.random() > prob:
                    continue # Reject

            matches_a[match_count] = a_idx
            matches_b[match_count] = b_idx
            used[i] = True
            used[j] = True
            match_count += 1
            break

    return matches_a[:match_count], matches_b[:match_count]


@njit(cache=True)
def match_with_attribute_weighting(
    pool_a: np.ndarray,
    pool_b: np.ndarray,
    age: np.ndarray,
    attr_vals: np.ndarray,
    weight_matrix: np.ndarray,
    min_age_diff: int,
    max_age_diff: int,
    pref_mean: float,
    pref_std: float,
    seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Two-pool matching with age AND attribute weighting (e.g., ethnicity).

    Attribute weighting is handled via probabilistic accept/reject.
    Age preferences follow a Gaussian distribution.
    """
    n_a = len(pool_a)
    n_b = len(pool_b)

    if n_a == 0 or n_b == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)

    shuffled_a = shuffle_indices(pool_a, seed)
    shuffled_b = shuffle_indices(pool_b, seed + 1)

    max_matches = min(n_a, n_b)
    matches_a = np.empty(max_matches, dtype=np.int64)
    matches_b = np.empty(max_matches, dtype=np.int64)

    used_b = np.zeros(n_b, dtype=np.bool_)
    match_count = 0

    np.random.seed(seed + 2)
    n_attr = weight_matrix.shape[0]

    for i in range(n_a):
        a_idx = shuffled_a[i]
        age_a = age[a_idx]
        attr_a = attr_vals[a_idx]

        for j in range(n_b):
            if used_b[j]:
                continue

            b_idx = shuffled_b[j]
            age_diff = abs(age[b_idx] - age_a)

            # Age constraints (Hard)
            if age_diff < min_age_diff or age_diff > max_age_diff:
                continue

            # Age preference (Gaussian)
            if pref_std > 0:
                dist = (float(age_diff) - pref_mean) / pref_std
                prob = np.exp(-0.5 * dist * dist)
                if np.random.random() > prob:
                    continue # Reject based on age preference

            # Attribute weighting (probabilistic)
            attr_b = attr_vals[b_idx]
            if attr_a < n_attr and attr_b < n_attr:
                weight = weight_matrix[attr_a, attr_b]
                if np.random.random() > weight:
                    continue  # Reject based on attribute weighting

            # Match!
            matches_a[match_count] = a_idx
            matches_b[match_count] = b_idx
            used_b[j] = True
            match_count += 1
            break

    return matches_a[:match_count], matches_b[:match_count]



@njit(cache=True)
def filter_by_age(
    candidates: np.ndarray,
    person_age: int,
    ages: np.ndarray,
    max_age_diff: int
) -> np.ndarray:
    """Filter candidates by age difference."""
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