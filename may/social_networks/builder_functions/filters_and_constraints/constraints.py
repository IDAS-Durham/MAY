"""
Typed constraint parsing for social network edge validation.

Converts YAML constraint blocks (aligned with relationship_rules.yaml
vocabulary) into ConnectionFilter objects used by network builders.

To add a new constraint type, handle its 'type' key in parse_constraints
and return the appropriate ConnectionFilter.

Supported types:
    numerical_attribute_difference:
        attribute     – person attribute to compare (e.g. 'age')
        max_difference – maximum allowed absolute difference
    categorical_attribute_match:
        attribute     – person attribute both ends of the edge must share
"""

from .filters import ConnectionFilter


def parse_constraints(constraints: list) -> list:
    """
    Convert a YAML constraints list to ConnectionFilter objects.

    Raises ValueError for unknown constraint types.
    """
    result = []
    for entry in constraints:
        constraint_type = entry.get("type")
        if constraint_type == "numerical_attribute_difference":
            result.append(ConnectionFilter(
                attribute=entry["attribute"],
                match="range",
                range=entry["max_difference"],
            ))
        elif constraint_type == "categorical_attribute_match":
            result.append(ConnectionFilter(
                attribute=entry["attribute"],
                match="same",
                range=None,
            ))
        else:
            raise ValueError(
                f"Unknown constraint type '{constraint_type}'. "
                f"Supported: numerical_attribute_difference, "
                f"categorical_attribute_match"
            )
    return result
