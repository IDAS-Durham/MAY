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
  # Create and visualize an example world with OpenStreetMap
  python launch_world_map.py --example

  # Load a saved world
  python launch_world_map.py --world-file world_state.joblib

  # Use a custom background image (local file)
  python launch_world_map.py --world-file world.joblib \\
      --map-background image \\
      --map-image /path/to/medieval_map.png \\
      --map-bounds "50.0,-5.0,60.0,2.0" \\
      --map-attribution "Medieval England Map - 1200 AD"

  # Use a custom image from URL
  python launch_world_map.py --world-file world.joblib \\
      --map-background image \\
      --map-image "https://example.com/maps/england_1200.jpg" \\
      --map-bounds "50.0,-5.0,60.0,2.0"

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

    # Map configuration arguments
    parser.add_argument(
        '--map-background',
        type=str,
        choices=['osm', 'image'],
        default='osm',
        help='Background map type: osm (OpenStreetMap) or image (custom image)'
    )

    parser.add_argument(
        '--map-image',
        type=str,
        help='Path or URL to custom map background image (required if --map-background=image)'
    )

    parser.add_argument(
        '--map-bounds',
        type=str,
        help='Geographic bounds for custom image: "north,east,south,west" (required if --map-background=image). Example: "55.0,2.0,50.0,-5.0"'
    )

    parser.add_argument(
        '--map-attribution',
        type=str,
        help='Attribution text for custom map image'
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

    # Parse map configuration
    map_config = None

    if args.map_background == 'image':
        if not args.map_image:
            print("\nERROR: --map-image is required when --map-background=image\n")
            sys.exit(1)

        if not args.map_bounds:
            print("\nERROR: --map-bounds is required when --map-background=image\n")
            sys.exit(1)

        # Parse bounds
        try:
            bounds_values = [float(x.strip()) for x in args.map_bounds.split(',')]
            if len(bounds_values) != 4:
                raise ValueError("Expected 4 values")

            north, east, south, west = bounds_values

            # Validate bounds
            if not (-90 <= south < north <= 90):
                raise ValueError(f"Invalid latitude bounds: {south}, {north}")
            if not (-180 <= west < east <= 180):
                raise ValueError(f"Invalid longitude bounds: {west}, {east}")

            bounds = [[south, west], [north, east]]

        except Exception as e:
            print(f"\nERROR: Invalid bounds format: {e}")
            print("Expected format: 'north,east,south,west'")
            print("Example: '55.0,2.0,50.0,-5.0'\n")
            sys.exit(1)

        # Check if image file exists (if it's a local path)
        from pathlib import Path
        image_path = args.map_image

        # If it's a local file path, convert to URL
        if not image_path.startswith(('http://', 'https://')):
            image_file = Path(image_path)
            if not image_file.exists():
                print(f"\nERROR: Image file not found: {image_path}\n")
                sys.exit(1)

            # Copy image to static directory
            import shutil
            static_images_dir = Path(__file__).parent / 'static' / 'map_images'
            static_images_dir.mkdir(parents=True, exist_ok=True)

            dest_file = static_images_dir / image_file.name
            shutil.copy(image_file, dest_file)

            # Convert to URL path
            image_path = f'/static/map_images/{image_file.name}'
            print(f"Copied image to: {dest_file}")

        map_config = {
            'background_type': 'image',
            'image_url': image_path,
            'bounds': bounds,
            'attribution': args.map_attribution or 'Custom Map Image'
        }

        print("\nMap Configuration:")
        print(f"  Type: Custom Image")
        print(f"  Image: {args.map_image}")
        print(f"  URL: {image_path}")
        print(f"  Bounds: {bounds}")
        print(f"  Attribution: {map_config['attribution']}")

    else:
        # Default OSM configuration
        map_config = {
            'background_type': 'osm',
            'image_url': None,
            'bounds': None,
            'attribution': '© OpenStreetMap contributors'
        }
        print("\nMap Configuration: OpenStreetMap (default)")

    # Initialize and run the Flask app
    app = initialize_app(world, map_config=map_config)

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
