"""
Configuration and command-line argument handling for MAY.
"""

import os
import logging
import yaml
from may.geography import Geography
from may.utils import path_resolver as pr

logger = logging.getLogger("config_loader")


def load_config(config_path="config.yaml"):
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to the config file

    Returns:
        Dictionary with configuration
    """
    if not os.path.exists(config_path):
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return {}

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    logger.info(f"Loaded configuration from {config_path}")
    return config


def build_filters(config):
    """
    Build the geographical filter from config.

    A run either loads all units or filters to one level's codes, both declared
    under `geography:` in the config. Levels are referenced by their config label
    (no hardcoded SGU/MGU/LGU), so any level naming works.

    Args:
        config: Configuration dictionary

    Returns:
        Filter dictionary with 'level' and 'codes' keys, or None if no filter
    """
    geo_config = config.get('geography', {})

    if geo_config.get('load_all', False):
        return None

    filter_config = geo_config.get('filter', {})
    if not filter_config or not filter_config.get('level'):
        return None

    level = filter_config['level']
    codes = []

    # Load codes from file if specified
    if filter_config.get('file'):
        codes = list(Geography.load_codes_from_file(filter_config['file']))
    # Otherwise use inline codes
    elif filter_config.get('codes'):
        codes = filter_config['codes']

    # Only return filter if we have codes
    if codes:
        return {'level': level, 'codes': codes}

    return None


def setup_geography(config=None):
    """
    Set up geography from config.

    Args:
        config: Configuration dict (if None, loads the default config file)

    Returns:
        Tuple of (Geography object, filters dict)
    """
    if config is None:
        config = load_config()

    # Build filters from config
    filters = build_filters(config)

    if filters:
        logger.info(f"Using filter: {filters['level']} with {len(filters['codes'])} codes")
    else:
        logger.info("Loading all geographical units (no filters)")

    # Get data directory and levels from config
    geo_config = config.get('geography', {})
    data_dir = pr.resolve(geo_config.get('data_dir', 'data/geography'))
    levels = geo_config.get('levels')  # required; Geography fails loud if absent (adr/0002)

    # Create Geography object
    geo = Geography(data_dir=data_dir, filters=filters, levels=levels)

    return geo, filters
