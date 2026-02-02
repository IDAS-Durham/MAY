"""
Graph-based relationship builder using clustered random graphs.

Uses NetworkX to generate a Watts-Strogatz graph with controllable clustering,
then maps edges to relationships between Person objects.
"""

import logging
from typing import Optional

from .clustered_graph import create_clustered_graph
from may.population.person import Person

from random import sample

logger = logging.getLogger("graph_relationships")


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
        storage_key: str = "social_contacts"
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

        # Create mapping from index to person id
        self._idx_to_person_id = {i: person.id for i, person in enumerate(people)}
        self._person_id_to_idx = {person.id: i for i, person in enumerate(people)}

    def build_all(self, store: bool = True) -> dict[int, list[int]]:
        """
        Build relationships for all people using graph-based approach.

        Args:
            store (bool): If True, store relationships in person.properties[storage_key].

        Returns:
            dict[int, list[int]]: Mapping of person_id to list of connected person_ids.

        Example:
            >>> builder = GraphRelationshipBuilder(people, mean_connections_per_person=6)
            >>> relationships = builder.build_all(store=True)
            >>> print(f"Person 0 connected to {len(relationships[0])} others")
        """
        logger.debug(f"Building graph-based relationships for {self.n_people:,} people")
        logger.debug(f"  mean_connections_per_person={self.mean_connections_per_person}, clustering_level={self.clustering_level}")

        # Ensure number of people is above 2
        if self.n_people < 2:
            logger.warning("Need at least 2 people to create relationships")
            return {}
        
        k = self.mean_connections_per_person

        # Ensure k doesn't exceed what's possible for the graph
        if k > (self.n_people - 1):
            max_k = self.n_people - 1
            logger.warning(f'Average connections {k} exceeds the max possible for the graph n_people-1={max_k}. Reducing to the max possible')
            k = max_k

        # Generate the clustered graph
        G = create_clustered_graph(
            n_nodes=self.n_people,
            k=k,
            clustering_level=self.clustering_level
        )

        # Convert graph edges to relationships
        relationships: dict[int, list[int]] = {person.id: [] for person in self.people}

        for node_u, node_v in G.edges():
            person_id_u = self._idx_to_person_id[node_u]
            person_id_v = self._idx_to_person_id[node_v]

            relationships[person_id_u].append(person_id_v)
            relationships[person_id_v].append(person_id_u)

        # Store in person properties if requested
        if store:
            for person in self.people:
                if self.storage_key in person.properties:
                    person.properties.extend(relationships[person.id])
                else:
                    person.properties[self.storage_key] = relationships[person.id]

        # Log statistics
        total_connections = sum(len(conns) for conns in relationships.values())
        avg_actual = total_connections / self.n_people if self.n_people > 0 else 0

        try:
            import networkx as nx
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
        store: bool = True
    ) -> dict[int, list[int]]:
        """
        Convenience static method to build graph-based relationships.

        Args:
            people (list[Person]): List of Person objects.
            mean_connections_per_person (int): Average connections per person (will be made even).
            clustering_level (float): 0.0 (low clustering) to 1.0 (high clustering).
            storage_key (str): Key for storing in person.properties.
            store (bool): Whether to store relationships in person objects.

        Returns:
            dict[int, list[int]]: Mapping of person_id to list of connected person_ids.

        Example:
            >>> from may.population.person import Person
            >>> people = [Person(age=30, sex='male') for _ in range(100)]
            >>> relationships = GraphRelationshipBuilder.build_graph_relationships(
            ...     people,
            ...     mean_connections_per_person=8,
            ...     clustering_level=0.8
            ... )
            >>> print(f"Person 0 has {len(relationships[0])} connections")
        """
        builder = GraphRelationshipBuilder(
            people=people,
            mean_connections_per_person=mean_connections_per_person,
            clustering_level=clustering_level,
            storage_key=storage_key
        )
        return builder.build_all(store=store)


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
