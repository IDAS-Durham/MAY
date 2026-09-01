"""Small, shared boundary for configuration-driven attribute access.

Objects expose normal attributes and may also store extensible values in a
``properties`` dictionary. Nested access checks that dictionary at each step;
flat access checks the root dictionary for the complete path first.
"""

from functools import lru_cache
from typing import Any, Callable, Optional

_MISSING = object()
_RESIDENCE_PREFIX = "residence."
Getter = Callable[[Any], Any]


def _part(obj: Any, name: str, nested_properties: bool) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, _MISSING)
    if nested_properties:
        properties = getattr(obj, "properties", _MISSING)
        if isinstance(properties, dict) and name in properties:
            return properties[name]
    return getattr(obj, name, _MISSING)


def _walk(obj: Any, parts: tuple[str, ...], nested_properties: bool) -> Any:
    current = obj
    for part in parts:
        if current is None:
            return None
        current = _part(current, part, nested_properties)
        if current is _MISSING:
            return _MISSING
    return current


@lru_cache(maxsize=None)
def _resolve_attribute(path: str, nested_properties: bool = True) -> Getter:
    """Compile a reusable getter for a dot-separated configuration path."""
    if not path:
        if nested_properties:
            return lambda obj: None
        raise ValueError(
            "empty attribute path: a distributor config is missing the name "
            "of the attribute to read"
        )

    if path.startswith(_RESIDENCE_PREFIX):
        parts = tuple(path[len(_RESIDENCE_PREFIX):].split("."))

        def from_residence(person: Any) -> Any:
            residence = _part(person, "residence", False)
            return None if residence is _MISSING else _walk(
                residence, parts, nested_properties
            )

        return from_residence

    parts = tuple(path.split("."))
    if nested_properties:
        return lambda obj: _walk(obj, parts, True)

    def flat(obj: Any) -> Any:
        if obj is None:
            return None
        properties = getattr(obj, "properties", _MISSING)
        if isinstance(properties, dict) and path in properties:
            return properties[path]
        return _walk(obj, parts, False)

    return flat


@lru_cache(maxsize=None)
def _compile_attribute(path: str, nested_properties: bool = True) -> Getter:
    """Return a cached getter with the public missing-value semantics."""
    getter = _resolve_attribute(path, nested_properties)

    def read(obj: Any) -> Any:
        value = getter(obj)
        return None if value is _MISSING else value

    return read


def get_attribute(
    obj: Any,
    path: Optional[str],
    default: Any = None,
    *,
    nested_properties: bool = True,
) -> Any:
    """Read an attribute, property, dictionary key, or dotted path."""
    if obj is None or not path:
        return default
    value = _resolve_attribute(path, nested_properties)(obj)
    return default if value is _MISSING else value
