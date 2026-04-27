"""
Shared utility for resolving person attributes from dot-notation paths.

Handles all path formats used in YAML configs:
- Direct: "age", "sex"
- Properties: "properties.workplace_sgu", "properties.work_sector"
- Residence: "residence.type", "residence.properties.original_pattern"
- Geo: "geographical_unit.coordinates", "geographical_unit.name"
"""


def get_nested_value(obj, path):
    """
    Walk a dot-notation path on *obj*.

    At each step:
    1. If *obj* has a ``properties`` dict containing the part, use it.
    2. If *obj* is a dict, use dict lookup.
    3. Otherwise fall back to ``getattr``.

    Returns ``None`` when any intermediate step resolves to ``None``.
    """
    parts = path.split('.')
    current = obj

    for part in parts:
        if current is None:
            return None

        # 1. Try properties dict if it exists (Person, Venue objects)
        if hasattr(current, 'properties') and isinstance(current.properties, dict):
            if part in current.properties:
                current = current.properties[part]
                continue

        # 2. Try dict access
        if isinstance(current, dict):
            current = current.get(part)

        # 3. Try direct attribute
        else:
            current = getattr(current, part, None)

    return current


def get_person_attribute(person, path):
    """
    Canonical resolver for person attributes from YAML config paths.

    Handles the ``residence.`` prefix specially (resolves ``person.residence``
    first, then walks the remainder), then delegates to :func:`get_nested_value`.

    Returns ``None`` for any missing or unresolvable path.
    """
    if not path or person is None:
        return None

    if path.startswith('residence.'):
        residence = getattr(person, 'residence', None)
        if residence is None:
            return None
        remainder = path[len('residence.'):]
        return get_nested_value(residence, remainder)

    return get_nested_value(person, path)
