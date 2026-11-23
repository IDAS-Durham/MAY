"""Shared YAML loading for configuration files."""

import os

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


def unreadable_file_message(path, error: Exception) -> str:
    """'<path> could not be read: <reason>' for an `OSError` or `UnicodeDecodeError`."""
    if isinstance(error, UnicodeDecodeError):
        reason = "not UTF-8 text"
    else:
        reason = error.strerror or os.strerror(error.errno or 0)
    return f"{path} could not be read: {reason}"
