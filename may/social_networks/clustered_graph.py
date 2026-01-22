import networkx as nx
from typing import Callable, Any
from functools import wraps
import logging

logger = logging.getLogger("create_clustered_graph")

type GraphCreator = Callable[[Any],Any]

graph_creators: dict[str, GraphCreator] = {}
def register_graph_creator(name: str):
    """
    Used to catalog the different graph creation methods and their defaults. 
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
    # Watts-Strogatz rewiring probability is inverse of clustering level
    p = 1.0 - clustering_level
    return nx.watts_strogatz_graph(n_nodes, k, p, **kwargs)

@register_graph_creator("connected_watts_strogatz")
def create_clustered_graph_connected_watts_strogatz(n_nodes: int, k: int =4, clustering_level: float=0.5, **kwargs):
    """Returns a connected Watts–Strogatz small-world graph.

    Attempts to generate a connected graph by repeated generation of Watts–Strogatz small-world graphs. An exception is raised if the maximum number of tries is exceeded.

    """
    p = 1.0 - clustering_level
    return nx.connected_watts_strogatz_graph(n_nodes, k, p, tries=100)

@register_graph_creator("random_regular_graph")
def create_clustered_graph_random_regular_graph(n_nodes: int, d:int = 4, **kwargs):
    """Returns a random regular graph.

    Returns a random d-regular graph on n nodes. A regular graph is a graph where each node has the same number 'd' neighbors.
    The resulting graph has no self-loops or parallel edges.
    
    """
    if d > n_nodes-1:
        logger.error("Cannot have more neighbours than the number of nodes. Rounding down so that the degree of each node is equal to n-1")
        d = n_nodes - 1
    return nx.random_regular_graph(round(d), n_nodes, **kwargs)

@register_graph_creator("gnm_random_graph")
def create_clustered_graph_gnm_random_graph(n_nodes, avg_edges_per_node=4,**kwargs):
    """Returns a G_n,m random graph.
    
    Returns a graph where a graph with n nodes and m edges is chosen uniformly from the set of all possible graphs. 
    """
    if avg_edges_per_node > n_nodes - 1:
        logger.error("Should not have an average number of edges greater than the number of nodes. Rounding down to n-1 edges per node.")
        tot_edges = int((n_nodes - 1)*n_nodes / 2)
    else:
        tot_edges = round(avg_edge_per_node * n_nodes / 2)
    return nx.gnm_random_graph(n_nodes, tot_edges, **kwargs)

@register_graph_creator("gnp_random_graph")
def create_clustered_graph_gnp_random_graph(n_nodes, avg_edges_per_node=4,**kwargs):
    probability_of_each_edge = float(avg_edge_per_node) / (n_nodes-1)
    return nx.gnp_random_graph(n_nodes, probability_of_each_edge, **kwargs)

###########################################################################

def create_clustered_graph(*args, algorithm: str='watts_strogatz', **kwargs):
    """
    Creates a random graph according to a given algorithm.

    Args:
        *args : Any arguments to be passed to the function
        format (str): The type of random graph to be created

    Returns:
        a clustered random graph. 
    """
    graph_creator = graph_creators[algorithm]
    if graph_creator is None:
        raise ValueError(f"No algorithm given to create the clustered graph")
    return graph_creator(*args, **kwargs)

###########################################################################
###########################################################################
    
if __name__ == "__main__":
    # Example usage
    G = create_clustered_graph(n_nodes=100, k=6, clustering_level=0.8)

    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Edges: {G.number_of_edges()}")
    print(f"Clustering coefficient: {nx.average_clustering(G):.3f}")
