# World Serialization Round-Trip Test

This document describes `test_world_serialization_roundtrip.py`, a script that validates the HDF5 serialization/deserialization process for World objects.

## Purpose

The script verifies that:
1. A World object can be saved to HDF5 format
2. The saved World can be loaded back from the file
3. The loaded World is **exactly equivalent** to the original World

This ensures that the serialization process doesn't lose or corrupt any data.

## What It Tests

The script uses the newly implemented `World.__eq__()` method to compare:
- **Geography**: All geographical units (id, name, level, coordinates, properties, parent relationships)
- **Population**: All people (id, age, sex, geographical_unit, activities, properties, activity_map)
- **Venues**: All venues (id, name, type, geographical_unit, coordinates, properties)

## Usage

### Basic Usage

```bash
# Test with Medieval world config
python test_world_serialization_roundtrip.py --config world_specific_code/MedievalYaml/config.yaml

# Test with another config
python test_world_serialization_roundtrip.py --config path/to/your/config.yaml
```

### Options

```
--config PATH         Path to world configuration YAML file
                      (default: world_specific_code/MedievalYaml/config.yaml)

--output PATH         Path for temporary HDF5 file
                      (default: test_world_roundtrip.h5)

--keep-file          Keep the HDF5 file after testing
                      (default: delete the file)
```

### Examples

```bash
# Test with default config
python test_world_serialization_roundtrip.py

# Test and keep the HDF5 file for inspection
python test_world_serialization_roundtrip.py --keep-file

# Test with custom output location
python test_world_serialization_roundtrip.py \
    --config world_specific_code/MedievalYaml/config.yaml \
    --output my_test_world.h5 \
    --keep-file
```

## Output

The script provides detailed output showing:

### 1. World Creation
```
================================================================================
CREATING WORLD
================================================================================
Loading configuration from: world_specific_code/MedievalYaml/config.yaml
Geography loaded: 1234 units
Venues loaded: 5678 venues
Population generated: 10,000 people
World created successfully:
  <World: 1234 units, 10,000 people, 5678 venues>
================================================================================
```

### 2. Serialization Round-Trip Test
```
================================================================================
TESTING SERIALIZATION ROUND-TRIP
================================================================================

Step 1: Exporting World to HDF5...
✓ Successfully saved to test_world_roundtrip.h5 (12.34 MB)

Step 2: Loading World from HDF5...
✓ Successfully loaded from test_world_roundtrip.h5
  <World: 1234 units, 10,000 people, 5678 venues>

Step 3: Comparing original and loaded worlds...
--------------------------------------------------------------------------------
✓ PASS: Original and loaded worlds are EQUAL
  All geographical units, people, and venues match!
```

### 3. Detailed Comparison
```
================================================================================
DETAILED COMPARISON
================================================================================

Geography:
  Original units: 1234
  Loaded units:   1234
  Match: ✓

Population:
  Original people: 10,000
  Loaded people:   10,000
  Match: ✓

  Sample people comparison:
    Person 0: ✓ Equal
    Person 1: ✓ Equal
    Person 2: ✓ Equal

Venues:
  Original venues: 5678
  Loaded venues:   5678
  Match: ✓

  Venues by type:
    household           :   5000 vs   5000 ✓
    school              :    500 vs    500 ✓
    hospital            :    178 vs    178 ✓
================================================================================
```

### 4. Final Result
```
================================================================================
✓✓✓ SERIALIZATION ROUND-TRIP TEST: PASSED ✓✓✓
The World object is correctly preserved through HDF5 save/load!
================================================================================
```

## Exit Codes

- **0**: Test passed - World objects are equal
- **1**: Test failed - World objects differ or error occurred

This makes the script suitable for use in automated testing:

```bash
python test_world_serialization_roundtrip.py && echo "Test passed!" || echo "Test failed!"
```

## Debugging Failed Tests

If the test fails, the script will output debug logs showing exactly what differs:

```
Step 3: Comparing original and loaded worlds...
--------------------------------------------------------------------------------
DEBUG:world:Population count mismatch: 10000 vs 9999
✗ FAIL: Original and loaded worlds are NOT EQUAL
  Check debug logs above for specific differences
```

Common issues that might cause failures:
- Missing data in HDF5 export
- Incorrect deserialization logic
- Loss of relationships (activity_map)
- Precision loss in numeric fields

## Integration with CI/CD

This script can be integrated into continuous integration pipelines:

```yaml
# Example GitHub Actions workflow
- name: Test World Serialization
  run: |
    python test_world_serialization_roundtrip.py \
      --config world_specific_code/MedievalYaml/config.yaml
```

## Requirements

- All dependencies from `requirements.txt`
- A valid world configuration YAML file
- Sufficient disk space for HDF5 file (typically 10-50 MB for small worlds)

## Related Files

- `may/world.py` - Contains `World.__eq__()` implementation
- `may/population/person.py` - Contains `Person.__eq__()` implementation
- `may/geography/geographical_unit.py` - Contains `GeographicalUnit.__eq__()` implementation
- `may/serialization/world_serializer.py` - Handles HDF5 export
- `may/serialization/world_loader.py` - Handles HDF5 import
