"""
Graph-based relationship builder using clustered random graphs.

Uses NetworkX to generate a Watts-Strogatz graph with controllable clustering,
then maps edges to relationships between Person objects.
"""

import logging
from typing import Optional

import numpy as np
import numba as nb

from .clustered_graph import create_clustered_graph, _require_networkx
from ..filters_and_constraints.filters import (
    ConnectionFilter,
    build_local_attribute_arrays,
    check_connection_filters,
    encode_connection_filters_for_numba,
)
from ..store import store_contacts
from may.population.person import Person

from random import sample

logger = logging.getLogger("graph_relationships")


@nb.njit(cache=True)
def _apply_filters_and_rewire(
    edge_array: np.ndarray,
    adj_indices: np.ndarray,
    adj_indptr: np.ndarray,
    n_nodes: int,
    stacked_attr_matrix: np.ndarray,
    filter_match_types: np.ndarray,
    filter_attr_indices: np.ndarray,
    filter_range_values: np.ndarray,
    max_rewire_attempts: int,
    rng_seed: int,
) -> np.ndarray:
    """
    Validate edges against encoded connection filters, rewiring failures.

    For each edge (u, v): keep if filters pass, else try up to max_rewire_attempts
    random replacements (u, w). Drops the edge if no valid w is found.
    Returns (n_kept, 2) int32 array of kept/rewired edges.
    """
    np.random.seed(rng_seed)
    n_edges = len(edge_array)
    n_filters = len(filter_match_types)

    kept = np.empty((n_edges, 2), dtype=np.int32)
    n_kept = 0

    for e in range(n_edges):
        u = int(edge_array[e, 0])
        v = int(edge_array[e, 1])

        # Check whether this edge passes all filters
        passes = True
        for i in range(n_filters):
            col = filter_attr_indices[i]
            diff = stacked_attr_matrix[u, col] - stacked_attr_matrix[v, col]
            if filter_match_types[i] == 0:
                if abs(diff) > filter_range_values[i]:
                    passes = False
                    break
            else:
                if diff != 0.0:
                    passes = False
                    break

        if passes:
            kept[n_kept, 0] = u
            kept[n_kept, 1] = v
            n_kept += 1
        else:
            for _ in range(max_rewire_attempts):
                w = int(np.random.random() * n_nodes)
                if w == u:
                    continue
                # Reject if w is already a neighbour of u
                is_neighbour = False
                for k in range(adj_indptr[u], adj_indptr[u + 1]):
                    if adj_indices[k] == w:
                        is_neighbour = True
                        break
                if is_neighbour:
                    continue
                # Check filters for (u, w)
                passes_w = True
                for i in range(n_filters):
                    col = filter_attr_indices[i]
                    diff = stacked_attr_matrix[u, col] - stacked_attr_matrix[w, col]
                    if filter_match_types[i] == 0:
                        if abs(diff) > filter_range_values[i]:
                            passes_w = False
                            break
                    else:
                        if diff != 0.0:
                            passes_w = False
                            break
                if passes_w:
                    kept[n_kept, 0] = u
                    kept[n_kept, 1] = w
                    n_kept += 1
                    break

    return kept[:n_kept]


class GraphRelationshipBuilder:
    """
    Builds relationship networks between people using graph-based approach.

    Uses a random graph to create relationships, ideally with
    controllable clustering. Each node in the graph corresponds to a person,
    and each edge represents a relationship.
    Default is to use the Watts-Strogatz small-world graph.

    Attributes:
        people (list[Person]): List of Person objects to create relationships for.
        n_people (int): Number of people in the population.
        mean_connections_per_person (int): Target average connections per person.
        clustering_level (float): Target clustering coefficient (0.0 to 1.0).
        storage_key (str): Key used to store relationships in person.properties.
    """
    def __init__(
        self,
        people: list[Person],
        mean_connections_per_person: int = 6,
        clustering_level: float = 0.7,
        storage_key: str = "social_contacts",
        connection_filters: Optional[list] = None,
        symmetric: bool = True,
        max_rewire_attempts: int = 10,
        **kwargs,
    ):
        """
        Initialize the graph relationship builder.

        Args:
            people (list[Person]): List of Person objects to create relationships for.
            mean_connections_per_person (int): Average number of connections per person
                (must be even for the Watts-Strogatz method).
            clustering_level (float): 0.0 (random-like) to 1.0 (high clustering).
            storage_key (str): Key to use when storing relationships in person.properties.
        """
        self.people = people
        self.n_people = len(people)
        self.mean_connections_per_person = mean_connections_per_person
        self.clustering_level = clustering_level
        self.storage_key = storage_key
        self.connection_filters = connection_filters or []
        self.symmetric = symmetric
        self.max_rewire_attempts = max_rewire_attempts

        # Create mapping from index to person id
        self._idx_to_person_id = {i: person.id for i, person in enumerate(people)}
        self._person_id_to_idx = {person.id: i for i, person in enumerate(people)}
        self.kwargs = kwargs

    def build_all(self) -> dict[int, list[Person]]:
        """
        Build relationships for all people using graph-based approach.

        Returns:
            dict[int, list[Person]]: Mapping of person_id to list of connected Person objects.

        Example:
            >>> builder = GraphRelationshipBuilder(people, mean_connections_per_person=6)
            >>> relationships = builder.build_all()
            >>> print(f"Person 0 connected to {len(relationships[0])} others")
        """
        nx = _require_networkx()

        logger.debug(f"Building graph-based relationships for {self.n_people:,} people")
        logger.debug(f"  mean_connections_per_person={self.mean_connections_per_person}, clustering_level={self.clustering_level}")

        # Ensure number of people is above 2
        if self.n_people < 2:
            logger.warning("Need at least 2 people to create relationships")
            return {}
        k = self.mean_connections_per_person

        # Ensure k doesn't exceed what's possible for the graph Or below 0
        if k > (self.n_people - 1):
            max_k = self.n_people - 1
            logger.warning(f'Average connections {k} exceeds the max possible for the graph n_people-1={max_k}. Reducing to the max possible')
            k = max_k

        if k < 0:
            logger.error(f"Average connections {k} is below zero.")
            raise ValueError(f"Average connections {k} is below zero.")

        # Generate the clustered graph
        G = create_clustered_graph(
            n_nodes=self.n_people,
            k=min(self.mean_connections_per_person, self.n_people-1),
            clustering_level=self.clustering_level,
            **self.kwargs,
        )

        # Apply connection filters with Numba-accelerated rewiring on rejection
        if self.connection_filters:
            local_attr_arrays = build_local_attribute_arrays(self.people, self.connection_filters)
            stacked, match_types, attr_indices, range_values = encode_connection_filters_for_numba(
                self.connection_filters, local_attr_arrays
            )
            adj = nx.to_scipy_sparse_array(G, nodelist=range(self.n_people), format='csr', dtype=np.int32)
            edge_array = np.array(list(G.edges()), dtype=np.int32)
            rng_seed = int(np.random.randint(0, 2**31))
            kept_array = _apply_filters_and_rewire(
                edge_array, adj.indices, adj.indptr, self.n_people,
                stacked, match_types, attr_indices, range_values,
                self.max_rewire_attempts, rng_seed,
            )
            G = nx.Graph()
            G.add_nodes_from(range(self.n_people))
            G.add_edges_from(kept_array.tolist())

        # Convert graph edges to relationships (Person objects, not IDs)
        relationships: dict[int, list[Person]] = {person.id: [] for person in self.people}

        for node_u, node_v in G.edges():
            person_u = self.people[node_u]
            person_v = self.people[node_v]

            relationships[person_u.id].append(person_v)
            if self.symmetric:
                relationships[person_v.id].append(person_u)

        for person in self.people:
            if relationships[person.id]:
                store_contacts(person, relationships[person.id], self.storage_key)

        # Log statistics
        total_connections = sum(len(conns) for conns in relationships.values())
        avg_actual = total_connections / self.n_people if self.n_people > 0 else 0

        try:
            actual_clustering = nx.average_clustering(G)
            logger.debug(f"Built {total_connections:,} total connections "
                       f"(avg {avg_actual:.1f} per person, clustering={actual_clustering:.3f})")
        except Exception:
            logger.debug(f"Built {total_connections:,} total connections "
                       f"(avg {avg_actual:.1f} per person)")

        return relationships

    @staticmethod
    def build_graph_relationships(
        people: list[Person],
        mean_connections_per_person: int = 6,
        clustering_level: float = 0.7,
        storage_key: str = "social_contacts",
        connection_filters: Optional[list] = None,
        symmetric: bool = True,
        max_rewire_attempts: int = 10,
        **kwargs,
    ) -> dict[int, list[Person]]:
        """
        Convenience static method to build graph-based relationships.

        Args:
            people (list[Person]): List of Person objects.
            mean_connections_per_person (int): Average connections per person.
            clustering_level (float): 0.0 (low clustering) to 1.0 (high clustering).
            storage_key (str): Key for storing in person.properties.
            connection_filters (list[ConnectionFilter] | None): Pairwise edge filters.
            symmetric (bool): If True, both u→v and v→u are stored per edge.
            max_rewire_attempts (int): Retry cap when an edge fails connection_filters.
        """
        builder = GraphRelationshipBuilder(
            people=people,
            mean_connections_per_person=mean_connections_per_person,
            clustering_level=clustering_level,
            storage_key=storage_key,
            connection_filters=connection_filters,
            symmetric=symmetric,
            max_rewire_attempts=max_rewire_attempts,
            **kwargs,
        )
        return builder.build_all()


if __name__ == "__main__":
    import networkx as nx
    import time
    
    logging.basicConfig(level=logging.INFO)

    start_time = time.perf_counter()
    # Create sample population
    logger.info("Creating sample population...")
    people = [Person(age=25 + i % 50, sex='male' if i % 2 == 0 else 'female')
              for i in range(10000000)]

    laptime=time.perf_counter()
    logger.info(f"Created sample population of {len(people):,} people in {laptime-start_time:.2g} s")

    # Build relationships with different clustering levels
    for clustering in [0.001, 0.1, 0.5]:
        laptime=time.perf_counter()
        logger.info(f"\n--- Clustering level: {clustering} ---")
        relationships = GraphRelationshipBuilder.build_graph_relationships(
            people,
            mean_connections_per_person=6,
            clustering_level=clustering,
            storage_key=f"contacts_{clustering}",
            store=True
        )
        
        # Show sample relationships
        if len(people) >= 5:
            sample_people = sample(people, 5)
            for sample_person in sample_people:
                contacts = sample_person.properties.get(f"contacts_{clustering}", [])
                logger.info(f"Person {sample_person.id} has {len(contacts)} contacts: {contacts[:10]}...")
        logger.info(f"Building relationships took {time.perf_counter() - laptime:.2g} s")
