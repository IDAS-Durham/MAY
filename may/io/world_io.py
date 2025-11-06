"""
World I/O utilities for saving and loading World objects.

This module provides efficient serialization and deserialization of World objects
with compression options to minimize file size.
"""

import logging
import os
import time
from joblib import dump, load

logger = logging.getLogger("world_io")


def save_world(world, filename='world_state.joblib', compress=True, compression_level=3):
    """
    Save a World object to disk with optional compression.

    Args:
        world (World): The World object to save
        filename (str): Output filename (default: 'world_state.joblib')
        compress (bool): Whether to use compression (default: True)
        compression_level (int): Compression level 0-9, where:
            - 0: No compression (fastest, largest file)
            - 1-3: Light compression (good balance)
            - 4-6: Medium compression (default=3)
            - 7-9: Heavy compression (slowest, smallest file)

    Returns:
        dict: Dictionary with save statistics (time, file_size_mb, compression_ratio)

    Examples:
        >>> # Quick save with default compression
        >>> save_world(world, 'my_world.joblib')

        >>> # Maximum compression for storage
        >>> save_world(world, 'my_world.joblib', compress=True, compression_level=9)

        >>> # No compression for fastest save
        >>> save_world(world, 'my_world.joblib', compress=False)
    """
    logger.info(f"Saving world to {filename}...")
    save_start = time.perf_counter()

    # Set compression parameters
    if compress:
        compress_param = ('lzma', compression_level)  # lzma gives better compression than gzip
        logger.info(f"Using LZMA compression (level {compression_level})")
    else:
        compress_param = 0  # No compression
        logger.info("No compression")

    # Save the world object
    dump(world, filename, compress=compress_param)

    save_time = time.perf_counter() - save_start
    file_size = os.path.getsize(filename) / (1024**2)  # Convert to MB

    logger.info(f"World saved successfully in {save_time:.2f}s")
    logger.info(f"File size: {file_size:.1f} MB")

    # Calculate compression ratio if we have population info
    stats = {
        'save_time_seconds': save_time,
        'file_size_mb': file_size,
        'filename': filename
    }

    if world and world.population:
        num_people = len(world.population.get_all_people())
        bytes_per_person = (file_size * 1024 * 1024) / num_people
        stats['population'] = num_people
        stats['bytes_per_person'] = bytes_per_person
        logger.info(f"Storage efficiency: {bytes_per_person:.1f} bytes per person")

    return stats


def load_world(filename='world_state.joblib'):
    """
    Load a World object from disk.

    Args:
        filename (str): Input filename (default: 'world_state.joblib')

    Returns:
        World: The loaded World object with all references intact

    Raises:
        FileNotFoundError: If the file doesn't exist

    Examples:
        >>> world = load_world('my_world.joblib')
        >>> print(f"Loaded {len(world.population.get_all_people())} people")
    """
    if not os.path.exists(filename):
        raise FileNotFoundError(f"World file not found: {filename}")

    logger.info(f"Loading world from {filename}...")
    load_start = time.perf_counter()

    file_size = os.path.getsize(filename) / (1024**2)  # MB
    logger.info(f"File size: {file_size:.1f} MB")

    # Load the world object
    world = load(filename)

    load_time = time.perf_counter() - load_start
    logger.info(f"World loaded successfully in {load_time:.2f}s")

    # Print summary
    if world:
        logger.info(world)
        if world.geography:
            logger.info(f"  Geography: {len(world.geography.get_all_units())} units")
        if world.population:
            logger.info(f"  Population: {len(world.population.get_all_people()):,} people")
        if world.venues:
            logger.info(f"  Venues: {len(world.venues.get_all_venues())} venues")

    return world


def compare_compression_options(world, base_filename='world_test'):
    """
    Benchmark different compression options to help choose the best trade-off.

    This function saves the world with different compression levels and reports
    the time and file size for each option.

    Args:
        world (World): The World object to benchmark
        base_filename (str): Base name for test files (without extension)

    Returns:
        list: List of dicts with statistics for each compression option

    Examples:
        >>> results = compare_compression_options(world)
        >>> # Choose the best option based on your priorities
    """
    logger.info("=" * 60)
    logger.info("Comparing compression options...")
    logger.info("=" * 60)

    test_configs = [
        {'compress': False, 'level': 0, 'name': 'No compression'},
        {'compress': True, 'level': 1, 'name': 'Light compression (fast)'},
        {'compress': True, 'level': 3, 'name': 'Medium compression (balanced)'},
        {'compress': True, 'level': 6, 'name': 'High compression'},
        {'compress': True, 'level': 9, 'name': 'Maximum compression (slow)'},
    ]

    results = []

    for config in test_configs:
        filename = f"{base_filename}_lvl{config['level']}.joblib"
        logger.info(f"\nTesting: {config['name']}")

        stats = save_world(
            world,
            filename=filename,
            compress=config['compress'],
            compression_level=config['level']
        )

        stats['config'] = config['name']
        results.append(stats)

        # Clean up test file
        if os.path.exists(filename):
            os.remove(filename)

    # Print comparison table
    logger.info("\n" + "=" * 60)
    logger.info("COMPARISON RESULTS")
    logger.info("=" * 60)
    logger.info(f"{'Configuration':<30} {'Time (s)':<12} {'Size (MB)':<12} {'Bytes/person':<12}")
    logger.info("-" * 60)

    for result in results:
        config_name = result['config']
        save_time = result['save_time_seconds']
        file_size = result['file_size_mb']
        bytes_per = result.get('bytes_per_person', 0)
        logger.info(f"{config_name:<30} {save_time:<12.2f} {file_size:<12.1f} {bytes_per:<12.1f}")

    logger.info("=" * 60)
    logger.info("\nRecommendation:")
    logger.info("  - For frequent saves during development: level 1 (fast)")
    logger.info("  - For production/archival: level 3-6 (balanced)")
    logger.info("  - For long-term storage: level 9 (maximum compression)")
    logger.info("=" * 60)

    return results
