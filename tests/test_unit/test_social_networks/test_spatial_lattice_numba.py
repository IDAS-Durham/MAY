import numpy as np

from may.social_networks.builder_functions.spatial_kernels import _spatial_ws_build_lattice


def _build_two_unit_csr(g_size: int, h_size: int):
    """
    Two geo_units: g (source, g_size people) and h (target, h_size people).
    g's only neighbour is h; h has no neighbours (irrelevant for this test).
    """
    unit_starts = np.array([0, g_size], dtype=np.int32)
    unit_ends = np.array([g_size, g_size + h_size], dtype=np.int32)
    n_people = g_size + h_size
    unit_people_flat = np.arange(n_people, dtype=np.int32)
    person_unit = np.array([0] * g_size + [1] * h_size, dtype=np.int32)

    neighbor_starts = np.array([0, 1], dtype=np.int32)
    neighbor_ends = np.array([1, 1], dtype=np.int32)
    neighbor_flat = np.array([1], dtype=np.int32)  # g's only neighbour is unit 1 (h)

    return (
        neighbor_starts, neighbor_ends, neighbor_flat,
        unit_starts, unit_ends, unit_people_flat, person_unit,
        n_people,
    )


class TestSpatialWsBuildLattice:
    def test_truncated_neighbour_spreads_targets_across_h(self):
        """
        Reproduces the hub-collapse bug shape: a large source unit g connecting
        into a small target unit h, where k exceeds h's population (truncated).
        Targets must spread across h's people as the source person's global
        index varies, not collapse onto the same 1-2 people in h.
        """
        g_size, h_size, k = 200, 5, 2
        (neighbor_starts, neighbor_ends, neighbor_flat,
         unit_starts, unit_ends, unit_people_flat, person_unit,
         n_people) = _build_two_unit_csr(g_size, h_size)

        all_connections = np.full((n_people, k), -1, dtype=np.int32)
        _spatial_ws_build_lattice(
            neighbor_starts, neighbor_ends, neighbor_flat,
            unit_starts, unit_ends, unit_people_flat,
            person_unit, all_connections, np.int32(k),
        )

        g_connections = all_connections[:g_size]
        assert (g_connections >= 0).all(), "every g person should fill all k slots from h"

        targets_in_h = g_connections - unit_starts[1]  # local index within h
        distinct_targets = np.unique(targets_in_h)
        assert len(distinct_targets) == h_size, (
            f"expected all {h_size} people in h to be reachable, "
            f"got only {len(distinct_targets)} distinct targets: {distinct_targets}"
        )

        in_degree = np.bincount(targets_in_h.ravel(), minlength=h_size)
        assert in_degree.max() <= in_degree.min() + 1, (
            f"in-degree should be near-uniform across h, got {in_degree}"
        )

    def test_fully_exhausted_neighbour_connects_everyone(self):
        """When k >= unit_size(h), every g person connects to all of h — no bias possible."""
        g_size, h_size, k = 10, 3, 5
        (neighbor_starts, neighbor_ends, neighbor_flat,
         unit_starts, unit_ends, unit_people_flat, person_unit,
         n_people) = _build_two_unit_csr(g_size, h_size)

        all_connections = np.full((n_people, k), -1, dtype=np.int32)
        _spatial_ws_build_lattice(
            neighbor_starts, neighbor_ends, neighbor_flat,
            unit_starts, unit_ends, unit_people_flat,
            person_unit, all_connections, np.int32(k),
        )

        g_connections = all_connections[:g_size]
        for row in g_connections:
            assigned = row[row >= 0] - unit_starts[1]
            assert sorted(assigned.tolist()) == list(range(h_size))

    def test_no_self_loops(self):
        g_size, h_size, k = 50, 4, 3
        (neighbor_starts, neighbor_ends, neighbor_flat,
         unit_starts, unit_ends, unit_people_flat, person_unit,
         n_people) = _build_two_unit_csr(g_size, h_size)

        all_connections = np.full((n_people, k), -1, dtype=np.int32)
        _spatial_ws_build_lattice(
            neighbor_starts, neighbor_ends, neighbor_flat,
            unit_starts, unit_ends, unit_people_flat,
            person_unit, all_connections, np.int32(k),
        )

        for i, row in enumerate(all_connections):
            assert i not in row[row >= 0]
