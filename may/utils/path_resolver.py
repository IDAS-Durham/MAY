"""
Module-level singleton for resolving ${config_root}, ${data_root}, ${output_root}
template variables in YAML path strings.

Call init() once at startup (after loading config.yaml). resolve() is a no-op
until init() is called, so bare paths continue to work unchanged.
"""

import os
import re
from typing import List, Optional

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


class ConfigFileNotFoundError(FileNotFoundError):
    """Config file not found at any tried location. Message omits the config key; caller adds it."""

    def __init__(self, path: str, tried: List[str]):
        self.path = path
        self.tried = tried
        super().__init__(f"not found; tried {', '.join(tried)}")


def find_config_file(path: str, data_dir: Optional[str]) -> str:
    """Find a config file: absolute as written; relative in working dir, then under data_dir.

    Returns the path as found. Raises ConfigFileNotFoundError listing every path tried.
    """
    path = resolve(path)
    data_dir = resolve(data_dir) if data_dir else data_dir
    tried = [path]
    if not os.path.isabs(path) and data_dir:
        tried.append(os.path.join(data_dir, path))
    for candidate in tried:
        if os.path.exists(candidate):
            return candidate
    raise ConfigFileNotFoundError(path, tried)
