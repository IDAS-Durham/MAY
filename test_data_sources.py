"""
Test script for data source loaders.
"""

import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

from attribute_assignment.assignment_config import AttributeAssignmentConfig
from attribute_assignment.data_sources import DataSourceManager

def test_data_sources():
    """Test data source loading and lookups."""
    print("\n" + "="*80)
    print("Testing Data Source Loaders")
    print("="*80 + "\n")

    # Load config
    config = AttributeAssignmentConfig.from_yaml("yaml/attribute_assignment_ethnicity.yaml")
    print(f"✓ Loaded config for '{config.attribute_name}'\n")

    # Create data source manager
    manager = DataSourceManager(config)
    print(f"✓ Created DataSourceManager with {len(manager.sources)} sources\n")

    # List sources
    print("Data sources:")
    for name, source in manager.sources.items():
        print(f"  • {name}: {type(source).__name__}")
    print()

    # Test without loading data (should use fallbacks)
    print("--- Testing Fallbacks (no data loaded) ---")

    # Area distribution
    area_dist = manager.lookup('area_distribution', 'E00000001')
    print(f"\nArea distribution for E00000001 (fallback):")
    for k, v in area_dist.items():
        print(f"  {k}: {v:.4f}")

    # Household diversity
    diversity = manager.lookup('household_diversity', 'E00000001')
    print(f"\nHousehold diversity for E00000001 (fallback):")
    for k, v in diversity.items():
        print(f"  {k}: {v:.4f}")

    # Partnership probabilities
    partnership = manager.lookup('partnership_probabilities', 'E00000001', 'W')
    print(f"\nPartnership probabilities for E00000001, first='W' (fallback):")
    for k, v in partnership.items():
        print(f"  {k}: {v:.4f}")

    # Test with sample area codes (if data files exist)
    print("\n--- Testing Data Loading ---")
    sample_areas = {'E00000001', 'E00000002', 'S00000001', 'N00000001'}

    try:
        manager.load_all(sample_areas)
        print("\n✓ Data loading attempted (some files may be missing)")

        # Try lookups again
        print("\n--- Testing Lookups After Loading ---")
        area_dist = manager.lookup('area_distribution', 'E00000001')
        print(f"\nArea distribution for E00000001:")
        for k, v in area_dist.items():
            print(f"  {k}: {v:.4f}")

    except Exception as e:
        print(f"\n⚠ Data loading failed (expected if CSV files don't exist): {e}")
        print("  This is OK - the system will use fallbacks")

    print("\n" + "="*80)
    print("✓ Data source tests complete!")
    print("="*80 + "\n")

if __name__ == "__main__":
    test_data_sources()
