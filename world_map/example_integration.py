#!/usr/bin/env python3
"""
Example: How to integrate World Map with your actual World instance.

This shows different ways to launch the visualization with real data.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import initialize_app


# ============================================================================
# Example 1: Load from joblib file
# ============================================================================

def example_load_from_joblib():
    """Load a World instance saved with joblib."""
    import joblib

    print("Loading world from world_state.joblib...")
    world = joblib.load("../world_state.joblib")

    print(f"Loaded: {world}")

    # Initialize and run the visualization
    app = initialize_app(world)
    app.run(host='127.0.0.1', port=5000, debug=True)


# ============================================================================
# Example 2: Create world from existing data
# ============================================================================

def example_create_from_data():
    """Create a World instance from your data files."""
    from may.world import World
    from may.geography import Geography
    from may.population import PopulationManager
    from may.geography import VenueManager

    print("Creating world from data files...")

    # 1. Load geography
    geography = Geography(
        data_dir="../data/geography",
        levels=["SGU", "MGU", "LGU"]
    )
    geography.load_from_csv()

    # 2. Load and generate population
    population = PopulationManager(geography, data_dir="../data/population")
    population.load_demographics_from_csv(
        male_file="demographics_male.csv",
        female_file="demographics_female.csv"
    )
    population.generate_population()

    # 3. Load venues (optional)
    venues = VenueManager(geography, data_dir="../data/venues")
    venues.load_from_csv()

    # 4. Create world
    world = World(
        geography=geography,
        population=population,
        venues=venues
    )

    print(f"Created: {world}")

    # Initialize and run the visualization
    app = initialize_app(world)
    app.run(host='127.0.0.1', port=5000, debug=True)


# ============================================================================
# Example 3: Load from custom format
# ============================================================================

def example_load_from_custom():
    """Load a World instance from your custom format."""
    # TODO: Implement your custom loading logic
    # For example, if you use HDF5, pickle, or a database

    # Example with custom loader:
    # world = load_world_from_hdf5("world.hdf5")
    # world = load_world_from_database("postgresql://...")
    # world = load_world_from_pickle("world.pkl")

    raise NotImplementedError("Implement your custom world loading here")


# ============================================================================
# Example 4: Run with filtered geography
# ============================================================================

def example_with_filtered_geography():
    """Create a world with filtered geography (e.g., specific regions)."""
    from may.world import World
    from may.geography import Geography
    from may.population import PopulationManager

    print("Creating world with filtered geography...")

    # Load only specific geographical units
    geography = Geography(
        data_dir="../data/geography",
        levels=["SGU", "MGU", "LGU"],
        filters={
            'level': 'MGU',
            'codes': ['E02000173', 'E02000187', 'E02000188']  # Specific MSOAs
        }
    )
    geography.load_from_csv()

    # Generate population only for filtered geography
    population = PopulationManager(geography, data_dir="../data/population")
    population.load_demographics_from_csv()
    population.generate_population()

    world = World(geography=geography, population=population)

    print(f"Created filtered world: {world}")

    # Initialize and run the visualization
    app = initialize_app(world)
    app.run(host='127.0.0.1', port=5000, debug=True)


# ============================================================================
# Example 5: Add custom properties to geographical units
# ============================================================================

def example_with_custom_properties():
    """Add custom properties to geographical units for visualization."""
    from may.world import World
    from may.geography import Geography
    from may.population import PopulationManager

    print("Creating world with custom properties...")

    # Create world
    geography = Geography(data_dir="../data/geography", levels=["SGU", "MGU"])
    geography.load_from_csv()

    population = PopulationManager(geography, data_dir="../data/population")
    population.load_demographics_from_csv()
    population.generate_population()

    # Add custom properties to geographical units
    for unit in geography.get_all_units().values():
        # Example: Add deprivation index
        unit.properties['deprivation_index'] = calculate_deprivation(unit)

        # Example: Add risk score
        unit.properties['risk_score'] = calculate_risk_score(unit)

        # Example: Add custom category
        if len(unit.people) > 5000:
            unit.properties['size_category'] = 'large'
        elif len(unit.people) > 1000:
            unit.properties['size_category'] = 'medium'
        else:
            unit.properties['size_category'] = 'small'

    world = World(geography=geography, population=population)

    # Initialize and run the visualization
    app = initialize_app(world)
    app.run(host='127.0.0.1', port=5000, debug=True)


def calculate_deprivation(unit):
    """Example: Calculate deprivation index for a unit."""
    # Your custom calculation here
    return 0.5


def calculate_risk_score(unit):
    """Example: Calculate risk score for a unit."""
    # Your custom calculation here
    return 0.3


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("World Map Visualization - Integration Examples")
    print("="*60 + "\n")

    print("Choose an example:")
    print("1. Load from joblib file")
    print("2. Create from data files")
    print("3. Load from custom format")
    print("4. Filtered geography")
    print("5. Custom properties")
    print()

    choice = input("Enter choice (1-5): ").strip()

    try:
        if choice == '1':
            example_load_from_joblib()
        elif choice == '2':
            example_create_from_data()
        elif choice == '3':
            example_load_from_custom()
        elif choice == '4':
            example_with_filtered_geography()
        elif choice == '5':
            example_with_custom_properties()
        else:
            print("Invalid choice. Please run again and choose 1-5.")
    except FileNotFoundError as e:
        print(f"\nERROR: File not found - {e}")
        print("Make sure your data files are in the correct location.\n")
    except NotImplementedError as e:
        print(f"\nINFO: {e}\n")
    except KeyboardInterrupt:
        print("\n\nServer stopped by user\n")
    except Exception as e:
        print(f"\nERROR: {e}\n")
        import traceback
        traceback.print_exc()
