"""Preflight coordinator: run every stage's config check and the cross-block checks."""

import logging
import os
from typing import Optional

import yaml

from may.geography.venue_manager import VenueConfig, VenueManager
from may.preflight.report import PreflightError, PreflightReport, not_mapping_message
from may.serialization.preflight import venue_property_gaps
from may.utils import path_resolver as pr
from may.utils.yaml_loader import invalid_yaml_message, load_yaml

logger = logging.getLogger("preflight")

SERIALIZATION_CONFIG_FILE_KEY = "serialization.config_file"


def check_world_config(config: dict) -> PreflightReport:
    """Check a whole world config without loading data. Pure: no logging, no raising."""
    block_report = PreflightReport()
    venues_block = _mapping_block(config, "venues", block_report)
    serialization_block = _mapping_block(config, "serialization", block_report)
    venue_config = None
    report = block_report
    if venues_block is not None:
        venue_config, venue_report = VenueManager.parse_config(venues_block)
        report = PreflightReport.merge(report, venue_report.under("venues", sep="."))
    loaded_schema = None
    if serialization_block is not None:
        schema_report = PreflightReport()
        loaded_schema = _load_serialization_schema(serialization_block, schema_report)
        report = PreflightReport.merge(report, schema_report)
    if venue_config is not None and loaded_schema is not None:
        report = PreflightReport.merge(
            report, _venue_property_gap_report(*loaded_schema, venue_config)
        )
    return report


def run_preflight(config: dict) -> PreflightReport:
    """Check a world config, log the report at INFO; `PreflightError` if any problem."""
    report = check_world_config(config)
    logger.info(report.format())
    if report.has_problems:
        raise PreflightError(report)
    return report


def _mapping_block(config: dict, name: str, report: PreflightReport) -> Optional[dict]:
    """The `name` block, `{}` if absent or blank; `None` with a problem if not a mapping."""
    block = config.get(name)
    if block is None:
        return {}
    if not isinstance(block, dict):
        report.problem(name, not_mapping_message(block))
        return None
    return block


def _load_serialization_schema(
    serialization_block: dict, report: PreflightReport
) -> Optional[tuple]:
    """(path, parsed schema) if serialisation enabled with a readable config file, else `None`.

    A missing or unreadable config file is a problem in `report`: export would
    fail after the build.
    """
    if not serialization_block.get("enabled", True):
        return None
    config_file = serialization_block.get("config_file")
    if not config_file:
        report.problem(SERIALIZATION_CONFIG_FILE_KEY, "not set; serialisation is enabled")
        return None
    path = pr.resolve(config_file)
    try:
        schema = load_yaml(path)
    except FileNotFoundError:
        report.problem(SERIALIZATION_CONFIG_FILE_KEY, f"{path} not found")
        return None
    except OSError as error:
        reason = error.strerror or os.strerror(error.errno or 0)
        report.problem(SERIALIZATION_CONFIG_FILE_KEY, f"{path} could not be read: {reason}")
        return None
    except yaml.YAMLError as error:
        report.problem(SERIALIZATION_CONFIG_FILE_KEY, invalid_yaml_message(path, error))
        return None
    return path, schema or {}


def _venue_property_gap_report(path: str, schema, venue_config: VenueConfig) -> PreflightReport:
    report = PreflightReport()
    file_key = f"{SERIALIZATION_CONFIG_FILE_KEY} ({path})"
    try:
        gaps = venue_property_gaps(schema, venue_config.venue_types, venue_config.data_dir)
    except Exception as error:
        # Advisory check: a malformed schema or unreadable venue file must not
        # stop preflight, but the user is told the check did not run.
        report.warning(file_key, f"venue property check skipped: {error}")
        return report
    for venue_type, property_name, columns in gaps:
        report.warning(
            f"{file_key}: venues.types.{venue_type}.properties",
            f"{property_name!r} not in the venue files; they carry {columns}",
        )
    return report
