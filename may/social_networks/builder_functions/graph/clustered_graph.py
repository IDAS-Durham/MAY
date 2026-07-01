from typing import Callable, Any
from functools import wraps
import logging

logger = logging.getLogger("create_clustered_graph")


def _require_networkx():
    """Lazily import networkx, raising a clear error if it's not installed."""
    try:
        import networkx as nx
    except ImportError as e:
        raise ImportError(
            "networkx is required for clustered-graph social network builders "
            "(watts_strogatz, barabasi_albert, etc). Install with: pip install networkx"
        ) from e
    return nx


type GraphCreator = Callable[[Any],Any]

graph_creators: dict[str, GraphCreator] = {}
def register_graph_creator(name: str):
    """
    Decorator to register a graph creation method in the graph_creators registry.

    Args:
        name (str): Name to register the graph creator under.

    Returns:
        Callable: Decorator function that registers the wrapped function.

    Example:
        >>> @register_graph_creator("my_graph")
        ... def create_my_graph(n_nodes: int, **kwargs):
        ...     return nx.complete_graph(n_nodes)
        >>> G = graph_creators["my_graph"](10)
    """
    def decorator(func: GraphCreator):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        graph_creators[name] = wrapper
        return wrapper
    return decorator

@register_graph_creator("watts_strogatz")
def create_clustered_graph_watts_strogatz(n_nodes: int , k: int = 4, clustering_level: float =0.5, **kwargs):
    """
    Create a random graph with controllable clustering according to the watts strogatz algorithm.

    Args:
        n_nodes (int): number of nodes
        k (int): each node connected to k nearest neighbors in ring topology
        clustering_level (float): 0.0 (low clustering) to 1.0 (high clustering)

    Returns:
        NetworkX Graph
    """
    nx = _require_networkx()

    # Ensure k is even as required for this graph
    if k % 2 != 0:
        k -= 1
    if k < 2:
        k = 2

    # Watts-Strogatz rewiring probability is inverse of clustering level
    p = 1.0 - clustering_level
    return nx.watts_strogatz_graph(round(n_nodes), round(k), p, **kwargs)

@register_graph_creator("connected_watts_strogatz")
def create_clustered_graph_connected_watts_strogatz(n_nodes: int, k: int =4, clustering_level: float=0.5, **kwargs):
    """
    Return a connected Watts-Strogatz small-world graph.

    Attempts to generate a connected graph by repeated generation of Watts-Strogatz
    small-world graphs. An exception is raised if the maximum number of tries is exceeded.

    Args:
        n_nodes (int): Number of nodes in the graph.
        k (int): Each node connected to k nearest neighbors in ring topology.
        clustering_level (float): 0.0 (low clustering) to 1.0 (high clustering).
        **kwargs: Additional arguments passed to nx.connected_watts_strogatz_graph.

    Returns:
        nx.Graph: A connected Watts-Strogatz small-world graph.

    Example:
        >>> G = create_clustered_graph_connected_watts_strogatz(100, k=6, clustering_level=0.8)
        >>> import networkx as nx
        >>> nx.is_connected(G)
        True
    """
    nx = _require_networkx()

    # Ensure k is even as required for this graph
    if k % 2 != 0:
        k -= 1
    if k < 2:
        k = 2

    p = 1.0 - clustering_level
    return nx.connected_watts_strogatz_graph(n_nodes, k, p, tries=100)

@register_graph_creator("barabasi_albert")
def create_clustered_barabasi_albert_graph(n_nodes: int, num_first_connections: int = 1, **kwargs):
    """Returns a random graph using Barabási–Albert preferential attachment

    A graph of n nodes is grown by attaching new nodes each with num_first_connections
    edges that are preferentially attached to existing nodes with high degree.
    """
    nx = _require_networkx()
    return nx.barabasi_albert_graph(n_nodes, num_first_connections, **kwargs)


@register_graph_creator("random_regular_graph")
def create_clustered_graph_random_regular_graph(n_nodes: int, d:int = 4, **kwargs):
    """Returns a random regular graph.

    Returns a random d-regular graph on n nodes. A regular graph is a graph where each node has the same number 'd' neighbors.
    The resulting graph has no self-loops or parallel edges.
    
    """
    nx = _require_networkx()
    if d > n_nodes-1:
        logger.error("Cannot have more neighbours than the number of nodes. Rounding down so that the degree of each node is equal to n-1")
        d = n_nodes - 1
    return nx.random_regular_graph(round(d), n_nodes, **kwargs)

@register_graph_creator("gnm_random_graph")
def create_clustered_graph_gnm_random_graph(n_nodes, avg_edges_per_node=4,**kwargs):
    """Returns a G_n,m random graph.
    
    Returns a graph where a graph with n nodes and m edges is chosen uniformly from the set of all possible graphs.
    """
    nx = _require_networkx()
    if avg_edges_per_node > n_nodes - 1:
        logger.error("Should not have an average number of edges greater than the number of nodes. Rounding down to n-1 edges per node.")
        tot_edges = int((n_nodes - 1)*n_nodes / 2)
    else:
        tot_edges = round(avg_edge_per_node * n_nodes / 2)
    return nx.gnm_random_graph(n_nodes, tot_edges, **kwargs)

@register_graph_creator("gnp_random_graph")
def create_clustered_graph_gnp_random_graph(n_nodes, avg_edges_per_node=4,**kwargs):
    nx = _require_networkx()
    probability_of_each_edge = float(avg_edge_per_node) / (n_nodes-1)
    return nx.gnp_random_graph(n_nodes, probability_of_each_edge, **kwargs)


def create_clustered_graph(*args, algorithm: str='watts_strogatz', **kwargs):
    """
    Create a random graph according to a given algorithm.

    Args:
        *args: Arguments passed to the underlying graph creation function.
        algorithm (str): The type of random graph to create. Options: 'watts_strogatz',
            'connected_watts_strogatz', 'barabasi_albert', 'random_regular_graph',
            'gnm_random_graph', 'gnp_random_graph'.
        **kwargs: Keyword arguments passed to the underlying graph creation function.

    Returns:
        nx.Graph: A NetworkX graph created by the specified algorithm.

    Example:
        >>> G = create_clustered_graph(n_nodes=100, k=6, clustering_level=0.8)
        >>> print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
    """
    graph_creator = graph_creators[algorithm]
    if graph_creator is None:
        raise ValueError(f"No algorithm given to create the clustered graph")
    return graph_creator(*args, **kwargs)


if __name__ == "__main__":
    nx = _require_networkx()

    # Example usage
    G = create_clustered_graph(n_nodes=100, k=6, clustering_level=0.8)

    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Edges: {G.number_of_edges()}")
    print(f"Clustering coefficient: {nx.average_clustering(G):.3f}")
