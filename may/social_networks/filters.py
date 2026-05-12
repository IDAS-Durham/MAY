"""
Filters for social network construction.

Defines PoolFilter (absolute single-person thresholds) and ConnectionFilter
(pairwise edge checks), with Numba-accelerated pool filtering.

Design mirrors may/residence/models.py (Category) and
may/residence/relationship_rules.py (_get_attribute_getter pattern).
"""

import numpy as np
import numba as nb
import logging
from dataclasses import dataclass
from typing import Optional

from may.utils.attribute_access import get_person_attribute

logger = logging.getLogger("social_network_filters")


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class PoolFilter:
    """
    Absolute single-person filter. Mirrors Category in may/residence/models.py.

    Numerical: person passes if min_value <= attr_value <= max_value.
    Categorical: person passes if attr_value in allowed_values.
    """
    attribute: str              # dot-path, resolved via get_person_attribute
    filter_type: str            # 'numerical' or 'categorical'
    min_value: Optional[float]
    max_value: Optional[float]
    allowed_values: Optional[set]

    def matches(self, person) -> bool:
        """Python-level match (used outside Numba path or as fallback)."""
        val = get_person_attribute(person, self.attribute)
        if val is None:
            return False
        if self.filter_type == 'numerical':
            if self.min_value is not None and val < self.min_value:
                return False
            if self.max_value is not None and val > self.max_value:
                return False
            return True
        return val in self.allowed_values


@dataclass
class ConnectionFilter:
    """
    Pairwise edge filter. Same semantics as 'filters' entries in friendship_builder.py.

    match='range': edge valid if abs(attr_u - attr_v) <= range.
    match='same':  edge valid if attr_u == attr_v.
    """
    attribute: str
    match: str              # 'range' or 'same'
    range: Optional[int]    # for 'range' only


# ============================================================================
# PARSING
# ============================================================================

def parse_pool_filter(d: dict) -> PoolFilter:
    filter_type = d.get('type', 'numerical')
    allowed = d.get('allowed_values')
    return PoolFilter(
        attribute=d['attribute'],
        filter_type=filter_type,
        min_value=d.get('min'),
        max_value=d.get('max'),
        allowed_values=set(allowed) if allowed is not None else None,
    )


def parse_connection_filter(d: dict) -> ConnectionFilter:
    return ConnectionFilter(
        attribute=d['attribute'],
        match=d['match'],
        range=d.get('range'),
    )


# ============================================================================
# ATTRIBUTE ARRAY BUILDING
# ============================================================================

def build_attribute_arrays(
    people,
    pool_filters: list,
) -> dict:
    """
    Pre-compute per-person attribute arrays for Numba pool filtering.

    Returns dict: attribute_path -> (array, encoding_map)
      Numerical:   (float32 ndarray of length n_people, {})
      Categorical: (int32 encoded ndarray of length n_people, {str_val: int_code})

    Unknown/None values encoded as -1 (categorical) or NaN (numerical).
    Uses get_person_attribute for generic dot-path resolution,
    mirroring _get_attribute_getter in relationship_rules.py.
    """
    result = {}
    for f in pool_filters:
        if f.attribute in result:
            continue
        values = [get_person_attribute(p, f.attribute) for p in people]
        if f.filter_type == 'numerical':
            arr = np.array(
                [float(v) if v is not None else np.nan for v in values],
                dtype=np.float32,
            )
            result[f.attribute] = (arr, {})
        else:
            unique = sorted({v for v in values if v is not None})
            encoding = {v: i for i, v in enumerate(unique)}
            arr = np.array(
                [encoding.get(v, -1) for v in values],
                dtype=np.int32,
            )
            result[f.attribute] = (arr, encoding)
    return result


# ============================================================================
# NUMBA POOL FILTERING
# ============================================================================

@nb.njit(cache=True)
def _apply_numerical_filter_numba(
    positions: np.ndarray,
    attr_array: np.ndarray,
    min_val: float,
    max_val: float,
    use_min: bool,
    use_max: bool,
) -> np.ndarray:
    """Return positions where attr_array[pos] satisfies numerical bounds."""
    count = 0
    result = np.empty(len(positions), dtype=np.int32)
    for i in range(len(positions)):
        pos = positions[i]
        val = attr_array[pos]
        if use_min and val < min_val:
            continue
        if use_max and val > max_val:
            continue
        result[count] = pos
        count += 1
    return result[:count]


@nb.njit(cache=True)
def _apply_categorical_filter_numba(
    positions: np.ndarray,
    attr_array: np.ndarray,
    allowed_encoded: np.ndarray,
) -> np.ndarray:
    """Return positions where attr_array[pos] is in allowed_encoded."""
    count = 0
    result = np.empty(len(positions), dtype=np.int32)
    for i in range(len(positions)):
        pos = positions[i]
        val = attr_array[pos]
        for j in range(len(allowed_encoded)):
            if val == allowed_encoded[j]:
                result[count] = pos
                count += 1
                break
    return result[:count]


def apply_pool_filters(
    positions: np.ndarray,
    pool_filters: list,
    attr_arrays: dict,
) -> np.ndarray:
    """
    AND-combine all pool_filters against positions using Numba.

    positions: int32 array of global person indices.
    attr_arrays: output of build_attribute_arrays().
    Returns filtered int32 positions array.
    """
    current = positions.astype(np.int32)
    for f in pool_filters:
        if len(current) == 0:
            break
        if f.attribute not in attr_arrays:
            logger.warning(f"pool_filter attribute '{f.attribute}' not in attr_arrays; skipping")
            continue
        arr, encoding = attr_arrays[f.attribute]
        if f.filter_type == 'numerical':
            current = _apply_numerical_filter_numba(
                current, arr,
                float(f.min_value) if f.min_value is not None else 0.0,
                float(f.max_value) if f.max_value is not None else 0.0,
                f.min_value is not None,
                f.max_value is not None,
            )
        else:
            allowed_encoded = np.array(
                [encoding[v] for v in f.allowed_values if v in encoding],
                dtype=np.int32,
            )
            if len(allowed_encoded) == 0:
                current = np.empty(0, dtype=np.int32)
            else:
                current = _apply_categorical_filter_numba(current, arr, allowed_encoded)
    return current


# ============================================================================
# CONNECTION FILTER CHECKING (Python-level, per edge in GraphRelationshipBuilder)
# ============================================================================

def build_local_attribute_arrays(
    people,
    connection_filters: list,
) -> dict:
    """
    Build local (subset-scoped) attribute arrays for connection filter checking.

    Returns dict: attribute_path -> np.ndarray indexed by local node index (0..n-1).
    Numerical -> float32, categorical -> object array (for 'same' equality check).
    """
    result = {}
    for f in connection_filters:
        if f.attribute in result:
            continue
        values = [get_person_attribute(p, f.attribute) for p in people]
        if f.match == 'range':
            result[f.attribute] = np.array(
                [float(v) if v is not None else np.nan for v in values],
                dtype=np.float32,
            )
        else:  # same — use object array to handle any type
            result[f.attribute] = np.array(values, dtype=object)
    return result


def check_connection_filters(
    local_idx_u: int,
    local_idx_v: int,
    connection_filters: list,
    local_attr_arrays: dict,
) -> bool:
    """AND-combine all connection filters for edge (u, v). All must pass."""
    for f in connection_filters:
        if f.attribute not in local_attr_arrays:
            continue
        arr = local_attr_arrays[f.attribute]
        val_u = arr[local_idx_u]
        val_v = arr[local_idx_v]
        if f.match == 'range':
            if abs(val_u - val_v) > f.range:
                return False
        elif f.match == 'same':
            if val_u != val_v:
                return False
    return True


# ============================================================================
# NUMBA-COMPATIBLE CONNECTION FILTER ENCODING
# ============================================================================

def encode_connection_filters_for_numba(
    connection_filters: list,
    local_attr_arrays: dict,
) -> tuple:
    """
    Pre-encode ConnectionFilter objects and attribute arrays for Numba.

    Returns:
        stacked_attr_matrix: (n_people, n_filters) float64 — one column per filter
        filter_match_types:  (n_filters,) int8 — 0=range, 1=same
        filter_attr_indices: (n_filters,) int32 — column index in stacked matrix
        filter_range_values: (n_filters,) float64 — threshold (range filters only)
    """
    n_filters = len(connection_filters)
    n_people = 0
    for arr in local_attr_arrays.values():
        n_people = len(arr)
        break

    stacked = np.zeros((n_people, n_filters), dtype=np.float64)
    match_types = np.zeros(n_filters, dtype=np.int8)
    attr_indices = np.arange(n_filters, dtype=np.int32)
    range_values = np.zeros(n_filters, dtype=np.float64)

    for col, f in enumerate(connection_filters):
        arr = local_attr_arrays.get(f.attribute)
        if arr is None:
            continue
        if f.match == 'range':
            match_types[col] = 0
            stacked[:, col] = arr.astype(np.float64)
            range_values[col] = float(f.range)
        else:
            match_types[col] = 1
            # Encode categorical values as contiguous integers for Numba.
            code_map: dict = {}
            next_code = 0
            encoded = np.zeros(n_people, dtype=np.float64)
            for i, v in enumerate(arr):
                if v not in code_map:
                    code_map[v] = next_code
                    next_code += 1
                encoded[i] = float(code_map[v])
            stacked[:, col] = encoded

    return stacked, match_types, attr_indices, range_values


@nb.njit(cache=True)
def _check_connection_filters_numba(
    u_idx: int,
    v_idx: int,
    stacked_attr_matrix: np.ndarray,
    filter_match_types: np.ndarray,
    filter_attr_indices: np.ndarray,
    filter_range_values: np.ndarray,
) -> bool:
    """AND-combine all encoded connection filters for edge (u, v). Numba JIT."""
    for i in range(len(filter_match_types)):
        col = filter_attr_indices[i]
        val_u = stacked_attr_matrix[u_idx, col]
        val_v = stacked_attr_matrix[v_idx, col]
        if filter_match_types[i] == 0:
            if abs(val_u - val_v) > filter_range_values[i]:
                return False
        else:
            if val_u != val_v:
                return False
    return True
