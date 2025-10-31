"""
Configuration and command-line argument handling for June Zero.
"""

import os
import logging
import argparse
import yaml
from may.geography import Geography

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


def parse_arguments():
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="June Zero - Geographical Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load all units using config.yaml
  python create_world.py

  # Load all units (override config)
  python create_world.py --load-all

  # Filter by LGU
  python create_world.py --lgu London

  # Filter by MGU codes (comma-separated)
  python create_world.py --mgu E02000173,E02000187

  # Filter by MGU from file
  python create_world.py --mgu-file filters/my_mgus.txt

  # Filter by SGU codes
  python create_world.py --sgu E00004320,E00004321

  # Use custom config file
  python create_world.py --config my_config.yaml
        """
    )

    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )

    parser.add_argument(
        '--load-all',
        action='store_true',
        help='Load all geographical units (ignores all filters)'
    )

    # LGU filters
    parser.add_argument(
        '--lgu',
        type=str,
        help='Filter by LGU codes (comma-separated)'
    )
    parser.add_argument(
        '--lgu-file',
        type=str,
        help='Filter by LGU codes from file'
    )

    # MGU filters
    parser.add_argument(
        '--mgu',
        type=str,
        help='Filter by MGU codes (comma-separated)'
    )
    parser.add_argument(
        '--mgu-file',
        type=str,
        help='Filter by MGU codes from file'
    )

    # SGU filters
    parser.add_argument(
        '--sgu',
        type=str,
        help='Filter by SGU codes (comma-separated)'
    )
    parser.add_argument(
        '--sgu-file',
        type=str,
        help='Filter by SGU codes from file'
    )

    return parser.parse_args()


def build_filters(args, config):
    """
    Build filter dictionary from arguments and config.
    Command-line arguments take precedence over config file.

    Args:
        args: Parsed command-line arguments
        config: Configuration dictionary

    Returns:
        Filter dictionary with 'level' and 'codes' keys, or None if no filter
    """
    # Check if --load-all is specified
    if args.load_all:
        return None

    # Check command-line arguments first (highest priority)
    if args.lgu or args.lgu_file:
        codes = []
        if args.lgu_file:
            codes = list(Geography.load_codes_from_file(args.lgu_file))
        elif args.lgu:
            codes = [c.strip() for c in args.lgu.split(',')]
        return {'level': 'LGU', 'codes': codes}

    if args.mgu or args.mgu_file:
        codes = []
        if args.mgu_file:
            codes = list(Geography.load_codes_from_file(args.mgu_file))
        elif args.mgu:
            codes = [c.strip() for c in args.mgu.split(',')]
        return {'level': 'MGU', 'codes': codes}

    if args.sgu or args.sgu_file:
        codes = []
        if args.sgu_file:
            codes = list(Geography.load_codes_from_file(args.sgu_file))
        elif args.sgu:
            codes = [c.strip() for c in args.sgu.split(',')]
        return {'level': 'SGU', 'codes': codes}

    # Check config file (lower priority)
    geo_config = config.get('geography', {})

    if geo_config.get('load_all', False):
        return None

    # Check filter in config
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


def setup_geography(args=None, config=None):
    """
    Setup geography based on arguments and config.
    Convenience function that handles all the configuration loading.

    Args:
        args: Parsed arguments (if None, will parse from command line)
        config: Configuration dict (if None, will load from file)

    Returns:
        Tuple of (Geography object, filters dict)
    """
    # Parse arguments if not provided
    if args is None:
        args = parse_arguments()

    # Load configuration if not provided
    if config is None:
        config = load_config(args.config)

    # Build filters from args and config
    filters = build_filters(args, config)

    if filters:
        logger.info(f"Using filter: {filters['level']} with {len(filters['codes'])} codes")
    else:
        logger.info("Loading all geographical units (no filters)")

    # Get data directory from config
    geo_config = config.get('geography', {})
    data_dir = geo_config.get('data_dir', 'data/geography')

    # Create Geography object
    geo = Geography(data_dir=data_dir, filters=filters)

    return geo, filters
