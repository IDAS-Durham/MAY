# Pickle/Joblib Serialization Fix

## Problem

When trying to save a World instance using `joblib.dump()`, the following error occurred:

```
_pickle.PicklingError: Can't pickle <function PopulationManager.load_demographics_from_csv.<locals>.<lambda>>:
it's not found as may.population.population.PopulationManager.load_demographics_from_csv.<locals>.<lambda>
```

## Root Cause

Python's pickle module (used by joblib) **cannot serialize lambda functions** that are stored as instance attributes. The codebase had two instances of this pattern:

1. **`may/population/population.py:81`**
   ```python
   self.precise_demographics = defaultdict(lambda: defaultdict(dict))
   ```

2. **`may/distributor/distributor_pop_to_venue.py:56`**
   ```python
   self._venue_has_membership_capacity_by_subset = defaultdict(lambda: [True]*self.subset_distributor.n_subsets)
   ```

Lambda functions defined inside methods cannot be pickled because pickle needs to be able to locate and import the function by its module path, which is impossible for anonymous lambda functions.

## Solution

Replace lambda functions with named methods that can be properly serialized:

### Fix 1: PopulationManager

**Before:**
```python
self.precise_demographics = defaultdict(lambda: defaultdict(dict))
```

**After:**
```python
@staticmethod
def _create_nested_defaultdict():
    """
    Create a nested defaultdict for demographics storage.

    This is a separate function (not a lambda) to make the object pickle-compatible.
    Returns a defaultdict(dict) for storing age -> sex -> count mappings.
    """
    return defaultdict(dict)

# In load_demographics_from_csv:
self.precise_demographics = defaultdict(self._create_nested_defaultdict)
```

### Fix 2: Distributor

**Before:**
```python
self._venue_has_membership_capacity_by_subset = defaultdict(lambda: [True]*self.subset_distributor.n_subsets)
```

**After:**
```python
def _create_capacity_list(self):
    """
    Create a capacity list for membership tracking.

    This is a separate function (not a lambda) to make the object pickle-compatible.
    Returns a list of True values with length equal to the number of subsets.
    """
    return [True] * self.subset_distributor.n_subsets

# In _assign_subsets:
self._venue_has_membership_capacity_by_subset = defaultdict(self._create_capacity_list)
```

## Verification

### Test Results

1. **Pickle Test**: ✓ Objects can be pickled and unpickled successfully
2. **Joblib Test**: ✓ Objects can be saved with `joblib.dump()` and loaded with `joblib.load()`
3. **Functionality Test**: ✓ Unpickled objects maintain full functionality
4. **Integration Test**: ✓ `create_world_households.py` successfully saves world to `my_world.joblib`

### Files Modified

- `may/population/population.py` - Added `_create_nested_defaultdict()` static method
- `may/distributor/distributor_pop_to_venue.py` - Added `_create_capacity_list()` instance method

### Test File Created

- `test_pickle_fix.py` - Comprehensive test suite for pickle compatibility

## Why This Works

1. **Named functions** can be pickled because pickle can reference them by their qualified name (e.g., `PopulationManager._create_nested_defaultdict`)
2. **Lambda functions** cannot be pickled because they have no qualified name - they're anonymous
3. **Static methods** are especially good for this use case as they don't depend on instance state and are easily serializable

## Best Practices Going Forward

When writing code that needs to be serializable:

1. ❌ **Avoid**: `defaultdict(lambda: ...)`
2. ✓ **Use**: Named helper functions/methods
3. ❌ **Avoid**: Storing lambda functions in instance attributes
4. ✓ **Use**: `lambda` only for temporary operations (sorting, filtering, etc.)

## Related Issues

This pattern should be avoided throughout the codebase. A search for `defaultdict(lambda` found no remaining instances after the fixes.

Lambda functions used in temporary operations (like `sort(key=lambda x: x.age)`) are fine and don't cause serialization issues because they're not stored.

## Testing

To test pickle compatibility of any object:

```python
import pickle
import joblib

# Test with pickle
try:
    pickled = pickle.dumps(your_object)
    unpickled = pickle.loads(pickled)
    print("✓ Pickle works")
except Exception as e:
    print(f"✗ Pickle failed: {e}")

# Test with joblib
try:
    joblib.dump(your_object, 'test.joblib')
    loaded = joblib.load('test.joblib')
    print("✓ Joblib works")
except Exception as e:
    print(f"✗ Joblib failed: {e}")
```

## Result

✅ World instances can now be successfully saved and loaded using `joblib.dump()` and `joblib.load()`
