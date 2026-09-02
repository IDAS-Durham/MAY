"""Shared YAML loading for configuration files."""

import yaml

from may.utils import path_resolver as pr


def load_yaml(path):
    """Load a YAML file after applying configured path substitutions."""
    with open(pr.resolve(str(path)), "r", encoding="utf-8-sig") as stream:
        return yaml.safe_load(stream)
