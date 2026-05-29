"""
Module-level singleton for resolving ${config_root}, ${data_root}, ${output_root}
template variables in YAML path strings.

Call init() once at startup (after loading config.yaml). resolve() is a no-op
until init() is called, so bare paths continue to work unchanged.
"""

import re
from typing import Optional

_resolver: Optional["PathResolver"] = None


class PathResolver:
    def __init__(self, config_root: str, data_root: Optional[str], output_root: str):
        self._roots = {
            "config_root": config_root,
            "data_root": data_root or "",
            "output_root": output_root,
        }

    def resolve(self, path: str) -> str:
        if not isinstance(path, str):
            return path
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: self._roots.get(m.group(1), m.group(0)),
            path,
        )


def init(config_root: str, data_root: Optional[str], output_root: str) -> None:
    global _resolver
    _resolver = PathResolver(config_root, data_root, output_root)


def resolve(path: str) -> str:
    """Resolve template variables in path. No-op if init() has not been called."""
    if _resolver is None:
        return path
    return _resolver.resolve(path)
