import numpy as np
import pytest
import networkx as nx
import scipy.sparse

from may.social_networks.builder_functions.filters_and_constraints.filters import ConnectionFilter, encode_connection_filters_for_numba
from may.social_networks.builder_functions.graph.graph_relationship_builder import _apply_filters_and_rewire


# helpers

def _range_filter(attribute: str, range_val: float) -> ConnectionFilter:
    return ConnectionFilter(attribute=attribute, match='range', range=range_val)


def _make_graph_csr(n_nodes: int, edges: list[tuple[int, int]]):
    """Return (edge_array int32, adj_indices, adj_indptr) from an edge list."""
    G = nx.Graph()
    G.add_nodes_from(range(n_nodes))
    G.add_edges_from(edges)
    adj = nx.to_scipy_sparse_array(G, nodelist=range(n_nodes), format='csr', dtype=np.int32)
    edge_array = np.array(list(G.edges()), dtype=np.int32)
    return edge_array, adj.indices, adj.indptr


def _empty_filter_arrays(n_people: int):
    """Return encoded arrays for the case of no filters."""
    stacked = np.zeros((n_people, 0), dtype=np.float64)
    match_types = np.zeros(0, dtype=np.int8)
    attr_indices = np.zeros(0, dtype=np.int32)
    range_values = np.zeros(0, dtype=np.float64)
    return stacked, match_types, attr_indices, range_values


class TestApplyFiltersAndRewire:
    def test_no_filters_preserves_all_edges(self):
        edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
        n = 5
        edge_array, adj_indices, adj_indptr = _make_graph_csr(n, edges)
        stacked, match_types, attr_indices, range_values = _empty_filter_arrays(n)

        kept = _apply_filters_and_rewire(
            edge_array, adj_indices, adj_indptr, n,
            stacked, match_types, attr_indices, range_values,
            max_rewire_attempts=5, rng_seed=42,
        )
        # All 4 edges kept; order may differ but same set
        kept_set = {(min(u, v), max(u, v)) for u, v in kept}
        expected_set = {(min(u, v), max(u, v)) for u, v in edges}
        assert kept_set == expected_set

    def test_rewired_edges_satisfy_filters(self):
        """All original edges violate the filter; rewired replacements must satisfy it."""
        # 10 people: odd-indexed have age 0-9; even-indexed have age 50-59
        # range filter = 5 → only pairs within same parity will pass
        n = 10
        ages = np.array([i * 10.0 for i in range(n)], dtype=np.float32)
        # Force all edges to connect people whose age diff >> 5
        edges = [(0, 9), (1, 8), (2, 7), (3, 6)]
        edge_array, adj_indices, adj_indptr = _make_graph_csr(n, edges)

        filters = [_range_filter('age', 5.0)]
        local_arrays = {'age': ages}
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)

        kept = _apply_filters_and_rewire(
            edge_array, adj_indices, adj_indptr, n,
            stacked, match_types, attr_indices, range_values,
            max_rewire_attempts=50, rng_seed=0,
        )
        for u, v in kept:
            assert abs(ages[u] - ages[v]) <= 5.0 + 1e-6, f"Edge ({u},{v}) violates filter: ages {ages[u]}, {ages[v]}"

    def test_deterministic_with_seed(self):
        n = 20
        ages = np.arange(n, dtype=np.float32) * 3.0
        edges = [(i, (i + 7) % n) for i in range(n)]
        edge_array, adj_indices, adj_indptr = _make_graph_csr(n, edges)

        filters = [_range_filter('age', 10.0)]
        local_arrays = {'age': ages}
        stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(filters, local_arrays)

        def run(seed):
            return _apply_filters_and_rewire(
                edge_array, adj_indices, adj_indptr, n,
                stacked, match_types, attr_indices, range_values,
                max_rewire_attempts=10, rng_seed=seed,
            )

        result_a = run(99)
        result_b = run(99)
        assert np.array_equal(result_a, result_b)

        result_c = run(12)
        # A different seed may produce a different result; both must still satisfy the filter
        for u, v in result_c:
            assert abs(ages[u] - ages[v]) <= 10.0 + 1e-6
