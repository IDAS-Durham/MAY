"""
Shared utility for resolving person attributes from dot-notation paths.

Handles all path formats used in YAML configs:
- Direct: "age", "sex"
- Properties: "properties.workplace_sgu", "properties.work_sector"
- Residence: "residence.type", "residence.properties.original_pattern"
- Geo: "geographical_unit.coordinates", "geographical_unit.name"

Two property conventions are in use. Under the nested convention a
``properties`` dict is consulted at every step of the walk, so an
intermediate object can supply the next part of the path. Under the flat
convention only the starting object has its ``properties`` searched, and
then only for the whole undivided path; every step after that is a plain
attribute or dict access.

Paths come from configuration and are resolved once per person, so the
per-path work (splitting, prefix detection, choosing a convention) is done
once in :func:`compile_path` and the result cached. Call it directly with a
path held in a loop, and use the module-level functions for one-off lookups.
"""

from functools import lru_cache

_RESIDENCE_PREFIX = 'residence.'


def _none_getter(obj):
    return None


def _identity(obj):
    return obj


@lru_cache(maxsize=None)
def _compile_walk(path, nested_properties):
    """Build a getter that walks *path* over an object, with no residence handling."""
    if nested_properties:
        parts = path.split('.')

        if len(parts) == 1:
            part = parts[0]

            def single(obj):
                if obj is None:
                    return None
                props = getattr(obj, 'properties', None)
                if isinstance(props, dict) and part in props:
                    return props[part]
                if isinstance(obj, dict):
                    return obj.get(part)
                return getattr(obj, part, None)

            return single

        def walk(obj):
            current = obj
            for part in parts:
                if current is None:
                    return None
                props = getattr(current, 'properties', None)
                if isinstance(props, dict) and part in props:
                    current = props[part]
                    continue
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    current = getattr(current, part, None)
            return current

        return walk

    if not path:
        return _identity

    parts = path.split('.')

    def walk_flat(obj):
        current = obj
        for part in parts:
            if current is None:
                return None
            if type(current) is dict:
                current = current.get(part)
            else:
                current = getattr(current, part, None)
        return current

    return walk_flat


@lru_cache(maxsize=None)
def compile_path(path, nested_properties=True):
    """
    Compile a config path into a getter taking a person and returning a value.

    The getter returns ``None`` for a missing person or any step that resolves
    to ``None``. Results are cached per path, so calling this in a hot loop is
    cheap, though hoisting it out of the loop is cheaper.

    An empty path returns ``None`` under the nested convention, where callers
    pass optional paths. Under the flat convention it means a distributor
    config left out the attribute name. That raises, because returning
    ``None`` would make every person fail the filter and be skipped with no
    error reported.
    """
    if not path:
        if nested_properties:
            return _none_getter
        raise ValueError(
            "empty attribute path: a distributor config is missing the name "
            "of the person attribute to read"
        )

    if path.startswith(_RESIDENCE_PREFIX):
        walk = _compile_walk(path[len(_RESIDENCE_PREFIX):], nested_properties)

        def from_residence(person):
            residence = getattr(person, 'residence', None)
            if residence is None:
                return None
            return walk(residence)

        return from_residence

    if nested_properties:
        return _compile_walk(path, True)

    walk = _compile_walk(path, False)

    def flat(person):
        if person is None:
            return None
        props = getattr(person, 'properties', None)
        if props is not None and path in props:
            return props[path]
        return walk(person)

    return flat


def get_nested_value(obj, path):
    """
    Walk a dot-notation path on *obj* under the nested property convention.

    Returns ``None`` when any intermediate step resolves to ``None``.
    """
    return _compile_walk(path, True)(obj)


def get_person_attribute(person, path):
    """
    Canonical resolver for person attributes from YAML config paths.

    Handles the ``residence.`` prefix specially, resolving ``person.residence``
    first and then walking the remainder.

    Returns ``None`` for any missing or unresolvable path.
    """
    if person is None:
        return None
    return compile_path(path, True)(person)
