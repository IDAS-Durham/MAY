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
def create_clustered_graph_watts_strogatz(n_nodes, k=4, clustering_level=0.5):
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
    return nx.watts_strogatz_graph(n_nodes, k, p)

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




    
if __name__ == "__main__":
    # Example usage
    G = create_clustered_graph(n_nodes=100, k=6, clustering_level=0.8)

    print(f"Nodes: {G.number_of_nodes()}")
    print(f"Edges: {G.number_of_edges()}")
    print(f"Clustering coefficient: {nx.average_clustering(G):.3f}")
