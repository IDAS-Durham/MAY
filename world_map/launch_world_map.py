#!/usr/bin/env python3
"""
Launcher script for World Map visualization.

This script demonstrates how to launch the interactive map with a World instance.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import 'may' module
sys.path.insert(0, str(Path(__file__).parent.parent))

from may.world import World
from may.geography import Geography
from may.population import PopulationManager
from may.geography import VenueManager

# Import the Flask app
from app import initialize_app


def create_example_world():
    """
    Create an example World instance.

    This is a placeholder - replace with your actual world loading logic.
    In practice, you would load your world from saved data or generate it.
    """
    print("Creating example world...")

    # Create geography
    geography = Geography(
        data_dir="data/geography",
        levels=["SGU", "MGU", "LGU"]  # Customize to your levels
    )

    # Load geography data (CSV files)
    # geography.load_from_csv()

    # Create population
    population = PopulationManager(geography, data_dir="data/population")

    # Load demographics and generate population
    # population.load_demographics_from_csv()
    # population.generate_population()

    # Create venues (optional)
    venues = None
    # venues = VenueManager(geography, data_dir="data/venues")
    # venues.load_from_csv()

    # Create world
    world = World(
        geography=geography,
        population=population,
        venues=venues
    )

    print(f"World created: {world}")
    return world


def load_world_from_file(filepath):
    """
    Load a World instance from a saved file.

    Args:
        filepath: Path to the saved world file (e.g., world.joblib, world.hdf5)

    Returns:
        World instance
    """
    # TODO: Implement loading from your saved format
    # Example with joblib:
    import joblib
    return joblib.load(filepath)

    # raise NotImplementedError(
    #     "Implement this function to load your World instance from a file. "
    #     "The file might be world.joblib, world.hdf5, or another format."
    # )


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Launch World Map visualization',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create and visualize an example world
  python launch_world_map.py --example

  # Load and visualize a saved world
  python launch_world_map.py --world-file world_state.joblib

  # Custom host and port
  python launch_world_map.py --example --host 0.0.0.0 --port 8080
        """
    )

    parser.add_argument(
        '--example',
        action='store_true',
        help='Create and use an example world'
    )

    parser.add_argument(
        '--world-file',
        type=str,
        help='Path to saved World instance file'
    )

    parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='Host to run the server on (default: 127.0.0.1)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Port to run the server on (default: 5000)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Run in debug mode'
    )

    args = parser.parse_args()

    # Load or create world
    world = None

    if args.world_file:
        print(f"Loading world from: {args.world_file}")
        try:
            world = load_world_from_file(args.world_file)
        except NotImplementedError as e:
            print(f"\nERROR: {e}")
            print("\nPlease implement the load_world_from_file() function")
            print("in launch_world_map.py to load your World instance.\n")
            sys.exit(1)
        except Exception as e:
            print(f"\nERROR: Failed to load world: {e}\n")
            sys.exit(1)

    elif args.example:
        world = create_example_world()

    else:
        parser.print_help()
        print("\n\nERROR: You must specify either --example or --world-file\n")
        sys.exit(1)

    # Verify world has required components
    if not world:
        print("ERROR: No world instance created")
        sys.exit(1)

    if not world.geography:
        print("WARNING: World has no geography data")

    if not world.population:
        print("WARNING: World has no population data")

    # Initialize and run the Flask app
    app = initialize_app(world)

    print("\n" + "=" * 60)
    print("🗺️  World Map Visualization")
    print("=" * 60)
    print(f"\nStarting server at http://{args.host}:{args.port}")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped by user\n")


if __name__ == '__main__':
    main()
