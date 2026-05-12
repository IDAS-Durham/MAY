import numpy as np
import pytest

from may.social_networks.filters import (
    ConnectionFilter,
    encode_connection_filters_for_numba,
    _check_connection_filters_numba,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _range_filter(attribute: str, range_val: float) -> ConnectionFilter:
    return ConnectionFilter(attribute=attribute, match='range', range=range_val)


def _same_filter(attribute: str) -> ConnectionFilter:
    return ConnectionFilter(attribute=attribute, match='same', range=None)


def _local_attr_arrays_range(values: list) -> dict:
    return {'age': np.array(values, dtype=np.float32)}


def _local_attr_arrays_same(values: list) -> dict:
    return {'group': np.array(values, dtype=object)}


# ---------------------------------------------------------------------------
# encode_connection_filters_for_numba
# ---------------------------------------------------------------------------

class TestEncodeConnectionFilters:
    def test_range_filter_encoded_correctly(self):
        filters = [_range_filter('age', 10.0)]
        local_arrays = _local_attr_arrays_range([20.0, 25.0, 30.0])
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)
        assert match_types[0] == 0
        assert range_values[0] == pytest.approx(10.0)

    def test_same_filter_encoded_correctly(self):
        filters = [_same_filter('group')]
        local_arrays = _local_attr_arrays_same(['A', 'B', 'A'])
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)
        assert match_types[0] == 1

    def test_stacked_attr_matrix_shape(self):
        filters = [_range_filter('age', 5.0), _same_filter('group')]
        local_arrays = {
            'age': np.array([10.0, 20.0, 30.0, 40.0, 50.0], dtype=np.float32),
            'group': np.array(['X', 'Y', 'X', 'Y', 'X'], dtype=object),
        }
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)
        assert stacked.shape == (5, 2)

    def test_same_filter_preserves_equality(self):
        """People with the same group value get the same encoded integer."""
        filters = [_same_filter('group')]
        local_arrays = _local_attr_arrays_same(['A', 'B', 'A'])
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)
        col = attr_indices[0]
        assert stacked[0, col] == stacked[2, col]   # both 'A'
        assert stacked[0, col] != stacked[1, col]   # 'A' != 'B'

    def test_range_filter_values_in_stacked(self):
        filters = [_range_filter('age', 5.0)]
        values = [10.0, 25.0, 40.0]
        local_arrays = _local_attr_arrays_range(values)
        stacked, _, attr_indices, _ = encode_connection_filters_for_numba(filters, local_arrays)
        col = attr_indices[0]
        for i, v in enumerate(values):
            assert stacked[i, col] == pytest.approx(v, abs=1e-4)


# ---------------------------------------------------------------------------
# _check_connection_filters_numba
# ---------------------------------------------------------------------------

class TestCheckConnectionFiltersNumba:
    def _encode_range(self, values, range_val):
        filters = [_range_filter('age', range_val)]
        local_arrays = {'age': np.array(values, dtype=np.float32)}
        return encode_connection_filters_for_numba(filters, local_arrays)

    def _encode_same(self, values):
        filters = [_same_filter('group')]
        local_arrays = {'group': np.array(values, dtype=object)}
        return encode_connection_filters_for_numba(filters, local_arrays)

    def test_range_check_pass(self):
        stacked, match_types, attr_indices, range_values = self._encode_range([20.0, 25.0], 10.0)
        assert _check_connection_filters_numba(0, 1, stacked, match_types, attr_indices, range_values) is True

    def test_range_check_fail(self):
        stacked, match_types, attr_indices, range_values = self._encode_range([20.0, 40.0], 10.0)
        assert _check_connection_filters_numba(0, 1, stacked, match_types, attr_indices, range_values) is False

    def test_same_check_pass(self):
        stacked, match_types, attr_indices, range_values = self._encode_same(['A', 'A'])
        assert _check_connection_filters_numba(0, 1, stacked, match_types, attr_indices, range_values) is True

    def test_same_check_fail(self):
        stacked, match_types, attr_indices, range_values = self._encode_same(['A', 'B'])
        assert _check_connection_filters_numba(0, 1, stacked, match_types, attr_indices, range_values) is False

    def test_multi_filter_all_must_pass(self):
        """Both a range and same filter; one fails → overall False."""
        filters = [_range_filter('age', 5.0), _same_filter('group')]
        local_arrays = {
            'age': np.array([20.0, 22.0], dtype=np.float32),   # range ok (diff=2)
            'group': np.array(['A', 'B'], dtype=object),         # same fails
        }
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)
        assert _check_connection_filters_numba(0, 1, stacked, match_types, attr_indices, range_values) is False

    def test_round_trip_consistency(self):
        """Numba and Python check_connection_filters agree on all pairs."""
        from may.social_networks.filters import check_connection_filters

        filters = [_range_filter('age', 8.0)]
        ages = [20.0, 25.0, 35.0, 50.0]
        local_arrays = {'age': np.array(ages, dtype=np.float32)}
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)

        n = len(ages)
        for u in range(n):
            for v in range(n):
                if u == v:
                    continue
                python_result = check_connection_filters(u, v, filters, local_arrays)
                numba_result = _check_connection_filters_numba(u, v, stacked, match_types, attr_indices, range_values)
                assert python_result == numba_result, f"Mismatch at ({u},{v}): python={python_result}, numba={numba_result}"
