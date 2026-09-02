from may.social_networks.builder_functions.filters_and_constraints.filters import (
    _build_activity_pool,
    pool_type_builders,
)
from may.social_networks.builder_functions.geo.geo_neighbors import (
    _find_neighbours_libpysal,
    neighbour_finders,
)
from may.social_networks.builder_functions.graph.clustered_graph import (
    create_clustered_graph_watts_strogatz,
    graph_creators,
)


def test_registries_keep_original_functions():
    registered = (
        (pool_type_builders["activity"], _build_activity_pool),
        (neighbour_finders["libpysal"], _find_neighbours_libpysal),
        (graph_creators["watts_strogatz"], create_clustered_graph_watts_strogatz),
    )
    for registry_entry, function in registered:
        assert registry_entry is function
        assert callable(registry_entry)
