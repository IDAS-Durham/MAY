"""
Numba-compiled helper functions for performance-critical distributor operations.
"""
import numpy as np
from numba import njit


@njit
def find_subset_by_age_household(age, capacities):
    """Fast age-to-subset mapping for household venues (Numba-compiled).

    Age ranges:
        - Kids: age < 18
        - Independent children: 18 <= age < 25
        - Adults: 25 <= age < 60
        - Elderly: age >= 60

    Args:
        age: float - person's age
        capacities: bool array[4] - which subsets have capacity

    Returns:
        subset_index: int - 0-3 if found, -1 if no capacity
    """
    if age < 18.0 and capacities[0]:
        return 0
    elif 18.0 <= age < 25.0 and capacities[1]:
        return 1
    elif 25.0 <= age < 60.0 and capacities[2]:
        return 2
    elif 60.0 <= age and capacities[3]:
        return 3
    else:
        return -1


@njit
def person_in_age_range_numba(age, min_age, max_age):
    """Check if person age is in range (Numba-compiled).

    Args:
        age: float - person's age
        min_age: float - minimum age (inclusive)
        max_age: float - maximum age (inclusive)

    Returns:
        bool - True if age in range
    """
    return min_age <= age <= max_age


@njit
def find_subset_by_age_care_home(age, sex_code, capacities, age_ranges):
    """Fast age-to-subset mapping for care home venues (Numba-compiled).

    Checks age ranges and sex to find appropriate subset.

    Args:
        age: float - person's age
        sex_code: int - 0 for male, 1 for female
        capacities: bool array[n_subsets] - which subsets have capacity
        age_ranges: float array[n_subsets, 2] - [min_age, max_age] per subset

    Returns:
        subset_index: int - index if found, -1 if no capacity
    """
    n_subsets = len(capacities)

    for i in range(n_subsets):
        if capacities[i]:
            min_age = age_ranges[i, 0]
            max_age = age_ranges[i, 1]
            if min_age <= age <= max_age:
                return i

    return -1


@njit
def check_capacities_batch(member_counts, thresholds):
    """Batch capacity check (Numba-compiled).

    Args:
        member_counts: int array[n_venues, n_subsets]
        thresholds: int array[n_venues, n_subsets]

    Returns:
        capacities: bool array[n_venues, n_subsets] - True if has capacity
    """
    return member_counts < thresholds
