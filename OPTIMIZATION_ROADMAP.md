# Numba Optimization Roadmap

## Key Findings from Profiling

**Total Runtime:** 4.772s
**Venue Assignment:** 2.397s (50.2%)
**Multi-Pass Logic:** 1.900s (39.8%)

---

## Phase 1: Quick Wins (Target: 20-30% speedup)

### 1.1 Cache Property Access
**Problem:** `subset.num_members` called 1.74M times (0.319s)

**Location:** `may/population/subset.py:159`
```python
@property
def num_members(self):
    return len(self.members)  # Called 1.74M times!
```

**Solution:** Add cached counts to Distributor
```python
class Distributor:
    def __init__(self, ...):
        self._subset_member_cache = {}  # {(venue_id, subset_name): count}

    def _get_subset_size(self, venue_id, subset_name):
        return self._subset_member_cache.get((venue_id, subset_name), 0)

    def _increment_subset_size(self, venue_id, subset_name):
        key = (venue_id, subset_name)
        self._subset_member_cache[key] = self._subset_member_cache.get(key, 0) + 1
```

### 1.2 Vectorize Age-Based Subset Assignment
**Problem:** 966K calls to `find_subset_for_person()` (0.515s total)

**Locations:**
- `world_specific_code/household_distributors/household_subset_distributor.py:6` (803K calls, 0.155s)
- `world_specific_code/care_home_distributor/care_home_subset_distributor.py:23` (163K calls, 0.360s)

**Current Code:**
```python
def find_subset_for_person(self, activity, venue_has_capacity, person):
    if person.age < 18 and venue_has_capacity[0]:
        return 0, 'kids'
    elif 18 <= person.age < 25 and venue_has_capacity[1]:
        return 1, 'independent children'
    # ... etc
```

**Numba Solution:**
```python
from numba import njit
import numpy as np

@njit
def _find_subset_by_age_numba(age, capacities):
    """Fast age-to-subset mapping.

    Args:
        age: float
        capacities: bool[4] array

    Returns:
        subset_index (int): 0-3 or -1 if no capacity
    """
    if age < 18 and capacities[0]:
        return 0
    elif 18 <= age < 25 and capacities[1]:
        return 1
    elif 25 <= age < 60 and capacities[2]:
        return 2
    elif 60 <= age and capacities[3]:
        return 3
    else:
        return -1

class HouseholdSubsetDistributor:
    def find_subset_for_person(self, activity, venue_has_capacity, person):
        idx = _find_subset_by_age_numba(person.age, np.array(venue_has_capacity))
        if idx >= 0:
            return idx, self.subset_names[idx]
        return -1, 'No subset available'
```

---

## Phase 2: Numba Core (Target: 40-50% total speedup)

### 2.1 Vectorize Venue Search
**Problem:** `find_venues_for_person()` called 129,514 times (1.798s)

**Location:** `may/distributor/distributor_pop_to_venue.py:139`

**Current Approach:** Sequential random sampling
```python
def find_venues_for_person(self, person, activity):
    # Lines 154-197
    for _ in range(self.maxiter):
        venue_idx = random.choice(self.available_venue_indices)
        # Try to assign to venue
```

**Numba Solution:**
```python
@njit
def _find_venue_fast(
    available_indices,
    capacity_matrix,  # bool[n_venues, n_subsets]
    subset_idx,
    max_iter,
    random_seed
):
    """Fast venue search with Numba.

    Returns:
        venue_index or -1 if none found
    """
    np.random.seed(random_seed)
    n_available = len(available_indices)

    for _ in range(max_iter):
        idx = np.random.randint(0, n_available)
        venue_idx = available_indices[idx]

        if capacity_matrix[venue_idx, subset_idx]:
            return venue_idx

    return -1
```

### 2.2 Batch Capacity Checks
**Problem:** `_update_venue_membership_capacity()` called 189,165 times (0.826s)

**Location:** `world_specific_code/household_distributors/household_distributor.py:123`

**Current:** Per-venue capacity check with match-case logic

**Numba Solution:**
```python
@njit
def _update_capacities_batch(
    member_counts,    # int[n_venues, 4] - counts per subset
    thresholds,       # int[n_venues, 4] - thresholds per subset
    composition_ids   # int[n_venues] - composition type ID
):
    """Vectorized capacity update.

    Returns:
        capacity_matrix: bool[n_venues, 4]
    """
    n_venues = len(member_counts)
    capacity = np.ones((n_venues, 4), dtype=np.bool_)

    for v in range(n_venues):
        for s in range(4):
            if member_counts[v, s] >= thresholds[v, s]:
                capacity[v, s] = False

    return capacity
```

### 2.3 Pre-compute Thresholds
**Problem:** `get_threshold_for_pass()` called 189,165 times (0.071s)

**Location:** `household_distributor.py:97`

**Solution:** Pre-compute threshold matrix for all passes
```python
class HouseholdDistributor:
    def __init__(self, ...):
        self._precompute_thresholds()

    def _precompute_thresholds(self):
        """Pre-compute thresholds for all venues x passes."""
        n_venues = len(self.potential_venues)
        self.threshold_matrix = np.zeros((n_venues, self.num_passes), dtype=np.int32)

        for v_idx, venue in enumerate(self.potential_venues):
            comp = venue.properties['composition']
            base_threshold = self.composition_thresholds.get(comp, 2)

            for pass_num in range(self.num_passes):
                increment = self.threshold_increment_per_pass.get(comp, 1)
                self.threshold_matrix[v_idx, pass_num] = base_threshold + (pass_num * increment)
```

---

## Phase 3: Major Refactor (Target: 60-70% total speedup)

### 3.1 Full NumPy-Based Assignment
Convert entire assignment loop to operate on NumPy arrays:
- Person ages/properties → NumPy arrays
- Venue capacities → NumPy matrices
- Assignment decisions → Vectorized operations

### 3.2 Parallel Geo-Unit Processing
**Location:** `create_world_households.py:291`

```python
from multiprocessing import Pool

def process_geo_unit(geo_unit_data):
    """Process one geo unit independently."""
    # Current loop body
    pass

with Pool(processes=4) as pool:
    results = pool.map(process_geo_unit, geo_unit_list)
```

**Expected:** 3-4x speedup on 4+ cores (geo units are independent)

### 3.3 JIT-Compiled Composition Matching
Replace Python match-case with Numba lookup table for household composition logic.

---

## Implementation Order

1. **Week 1:** Phase 1 optimizations
   - Cache property access (1-2 hours)
   - Vectorize subset assignment (2-3 hours)
   - Benchmark and validate

2. **Week 2:** Phase 2 core optimizations
   - Vectorize venue search (4-6 hours)
   - Batch capacity checks (3-4 hours)
   - Pre-compute thresholds (1-2 hours)

3. **Week 3+:** Phase 3 (if needed)
   - Assess if Phase 1+2 gains are sufficient
   - Plan major refactor if targeting 2-3x total speedup

---

## Benchmarking Strategy

```python
import time

def benchmark_function(func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()
    print(f"{func.__name__}: {end - start:.4f}s")
    return result

# Before optimization
baseline = benchmark_function(create_world_households.main)

# After optimization
optimized = benchmark_function(create_world_households.main)

speedup = baseline / optimized
print(f"Speedup: {speedup:.2f}x")
```

---

## Notes

- **Numba Compatibility:** Most code is compatible, but Person object creation can't be JIT-compiled
- **Incremental Approach:** Optimize one function at a time, benchmark each change
- **Validation:** Ensure results match before/after optimization (same person assignments)
- **Scaling:** Profile with 500K+ population to see if bottlenecks shift
