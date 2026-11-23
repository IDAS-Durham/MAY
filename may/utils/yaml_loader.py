"""Shared YAML loading for configuration files."""

import yaml

from may.utils import path_resolver as pr


def load_yaml(path):
    """Load a YAML file after applying configured path substitutions."""
    with open(pr.resolve(str(path)), "r", encoding="utf-8-sig") as stream:
        return yaml.safe_load(stream)


def invalid_yaml_message(path, error: yaml.YAMLError) -> str:
    """'<path> is not valid YAML', with line and column when the error has them."""
    mark = getattr(error, "problem_mark", None)
    if mark is None:
        return f"{path} is not valid YAML"
    return f"{path} is not valid YAML at line {mark.line + 1}, column {mark.column + 1}"
