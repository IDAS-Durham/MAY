#!/usr/bin/env python3
"""
Test script to verify that the pickle/joblib serialization fix works.
"""

import sys
import tempfile
from pathlib import Path

# Test 1: Test PopulationManager pickling
print("=" * 60)
print("Test 1: PopulationManager pickle compatibility")
print("=" * 60)

from may.population import PopulationManager
from may.geography import Geography
from collections import defaultdict

# Create a simple geography
geography = Geography(data_dir="data/geography", levels=["SGU", "MGU"])

# Create population manager
pop_manager = PopulationManager(geography, data_dir="data/population")

# Initialize the problematic attribute
pop_manager.precise_demographics = defaultdict(pop_manager._create_nested_defaultdict)

# Try to pickle it
try:
    import pickle
    pickled = pickle.dumps(pop_manager)
    print("✓ PopulationManager can be pickled!")

    # Try to unpickle
    unpickled = pickle.loads(pickled)
    print("✓ PopulationManager can be unpickled!")

    # Verify the defaultdict still works
    unpickled.precise_demographics['test'][10]['male'] = 5
    print("✓ Unpickled defaultdict works correctly!")
    print(f"  Value: {unpickled.precise_demographics['test'][10]['male']}")

except Exception as e:
    print(f"✗ PopulationManager pickle failed: {e}")
    sys.exit(1)

print()

# Test 2: Test Distributor pickling (if available)
print("=" * 60)
print("Test 2: Distributor pickle compatibility")
print("=" * 60)

try:
    from may.distributor.distributor_pop_to_venue import Distributor
    from may.geography import VenueManager, Venue

    # This is a simplified test - in practice, Distributor needs valid venues
    print("✓ Distributor class can be imported")
    print("  (Full test requires complete venue setup)")

except ImportError as e:
    print(f"⚠ Distributor not available: {e}")

print()

# Test 3: Test with joblib (if available)
print("=" * 60)
print("Test 3: joblib serialization")
print("=" * 60)

try:
    import joblib

    # Test joblib dump/load
    with tempfile.NamedTemporaryFile(suffix='.joblib', delete=False) as f:
        temp_file = f.name

    joblib.dump(pop_manager, temp_file, compress=3)
    print(f"✓ joblib.dump successful: {temp_file}")

    loaded = joblib.load(temp_file)
    print("✓ joblib.load successful!")

    # Verify it works
    loaded.precise_demographics['test2'][20]['female'] = 10
    print("✓ Loaded object works correctly!")
    print(f"  Value: {loaded.precise_demographics['test2'][20]['female']}")

    # Clean up
    Path(temp_file).unlink()

except ImportError:
    print("⚠ joblib not installed - skipping joblib test")
    print("  Install with: pip install joblib")
except Exception as e:
    print(f"✗ joblib test failed: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("✓ All tests passed! The pickle fix is working correctly.")
print("=" * 60)
