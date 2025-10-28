# Profiling Analysis - June Zero World Creation

**Total Runtime:** 4.772 seconds
**Total Function Calls:** 16,595,716 calls

---

## 🔥 TOP BOTTLENECKS (by cumulative time)

### 1. **Venue Assignment Loop** - 2.397s (50.2% of total time)
**File:** `may/distributor/distributor_pop_to_venue.py:83`
**Function:** `assign_people_venues()`
**Calls:** 1,058 calls

**Sub-bottlenecks:**
- `find_venues_for_person()` - 1.798s (37.7%)
  - Called 129,514 times
  - 0.593s internal time
- `_update_venue_membership_capacity()` - 0.826s (17.3%)
  - Called 189,165 times (household distributor)
  - 0.280s internal time

### 2. **Multi-Pass Assignment** - 1.900s (39.8% of total time)
**File:** `may/distributor/distribute_pop_to_venue_multipass.py:143`
**Function:** `assign_people_venues_multi_pass()`
**Calls:** 425 calls

### 3. **Demographics Loading** - 0.455s (9.5% of total time)
**File:** `may/population/population.py:43`
**Function:** `load_demographics_from_csv()`
**Calls:** 1 call
**Time:** 0.042s internal + 0.413s in pandas operations

### 4. **Household Loading** - 0.386s (8.1% of total time)
**File:** `world_specific_code/household_distributors/household_manager.py:24`
**Function:** `load_venue_type_from_df()`
**Calls:** 1 call
**Time:** 0.074s internal + 0.312s in pandas

### 5. **Population Generation** - 0.265s (5.6% of total time)
**File:** `may/population/population.py:130`
**Function:** `generate_population()`
**Calls:** 1 call
**Time:** 0.119s internal
- Creating 95,231 Person objects: 0.099s

---

## 📊 HOTSPOT FUNCTIONS (high call count)

| Function | Calls | Total Time | Per Call |
|----------|-------|------------|----------|
| `subset.num_members` (property) | 1,739,286 | 0.319s | 0.18 μs |
| `len()` builtin | 4,016,226 | 0.232s | 0.06 μs |
| `care_home_subset_distributor.find_subset_for_person()` | 163,400 | 0.360s | 2.2 μs |
| `household_subset_distributor.find_subset_for_person()` | 802,795 | 0.155s | 0.19 μs |
| `care_home_subset_distributor.person_in_age_range()` | 1,632,505 | 0.123s | 0.08 μs |
| `venue.num_members` (property) | 282,463 | 0.420s | 1.5 μs |
| `subset.__init__()` | 145,850 | 0.217s | 1.5 μs |
| `pandas Series.__getitem__()` | 123,242 | 0.369s | 3.0 μs |

---

## 🎯 OPTIMIZATION TARGETS (Priority Order)

### **Priority 1: Venue Assignment Loop**
**Target:** `find_venues_for_person()` and capacity checks
**Current:** 1.798s over 129,514 calls
**Potential Speedup:** 2-4x with Numba

**Optimization Strategy:**
```python
@njit
def _find_available_venue_numba(venue_capacities, venue_ids, max_iter):
    """Vectorized venue search.

    Args:
        venue_capacities: bool array[n_venues, 4] - capacity per subset
        venue_ids: int array - available venue indices
        max_iter: int - max iterations

    Returns:
        venue_index, subset_index (or -1, -1 if not found)
    """
    pass
```

### **Priority 2: Capacity Update Functions**
**Target:** `_update_venue_membership_capacity()`
**Current:** 0.826s over 189,165 calls
**Potential Speedup:** 3-5x with vectorization

**Key Issue:** Called once per person per venue trial
- Composition matching (match-case)
- Threshold calculations (189,165 calls to `get_threshold_for_pass()`: 0.071s)

**Optimization Strategy:**
```python
@njit
def _check_household_capacity_batch(
    member_counts,  # array[n_venues]
    thresholds,     # array[n_venues]
    compositions    # array[n_venues]
):
    """Batch capacity check for all venues."""
    return member_counts < thresholds
```

### **Priority 3: Subset Assignment Functions**
**Targets:**
- `care_home_subset_distributor.find_subset_for_person()` - 163,400 calls, 0.360s
- `household_subset_distributor.find_subset_for_person()` - 802,795 calls, 0.155s

**Combined:** 0.515s (10.8% of total)

**Optimization Strategy:**
```python
@njit
def _assign_subset_by_age_vectorized(ages, capacities_matrix):
    """Vectorize age-to-subset assignment for batch of people.

    Args:
        ages: array[n_people] - ages of people to assign
        capacities_matrix: bool array[n_subsets] - which subsets have capacity

    Returns:
        subset_indices: int array[n_people] - assigned subset per person
    """
    subset_indices = np.full(len(ages), -1, dtype=np.int32)

    # Kids (age < 18)
    mask = (ages < 18) & capacities_matrix[0]
    subset_indices[mask] = 0

    # Independent children (18 <= age < 25)
    mask = (ages >= 18) & (ages < 25) & capacities_matrix[1]
    subset_indices[mask] = 1

    # Adults (25 <= age < 60)
    mask = (ages >= 25) & (ages < 60) & capacities_matrix[2]
    subset_indices[mask] = 2

    # Elderly (age >= 60)
    mask = (ages >= 60) & capacities_matrix[3]
    subset_indices[mask] = 3

    return subset_indices
```

### **Priority 4: Property Access Optimization**
**Targets:**
- `subset.num_members` property - 1.74M calls, 0.319s
- `venue.num_members` property - 282K calls, 0.420s

**Issue:** Python properties have overhead. Consider caching or pre-computing.

**Optimization Strategy:**
```python
# Cache member counts in distributor
class Distributor:
    def __init__(self, ...):
        self._venue_member_counts = np.zeros(len(venues), dtype=np.int32)
        self._subset_member_counts = {}  # venue_id -> array[4]

    def _update_cached_counts(self, venue_idx):
        """Update cached counts after assignment."""
        self._venue_member_counts[venue_idx] += 1
```

### **Priority 5: Population Generation** (Lower Priority)
**Target:** `generate_population()`
**Current:** 0.265s total (0.119s internal + 0.099s Person creation)
**Potential Speedup:** 1.5-2x

**Note:** Person object creation can't be Numba-accelerated, but demographic array generation can be.

---

## 💡 IMPLEMENTATION RECOMMENDATIONS

### Phase 1: Quick Wins (1-2 hours)
1. **Cache property access** - Replace repeated `.num_members` calls with cached arrays
2. **Vectorize age-based subset assignment** - Replace per-person logic with batch operations
3. **Pre-compute venue capacities** - Build capacity matrices upfront

**Expected speedup:** 20-30% (0.6-0.9s saved)

### Phase 2: Medium Effort (4-6 hours)
1. **Numba-fy capacity checking** - Vectorize `_update_venue_membership_capacity()`
2. **Batch venue search** - Replace sequential find_venues loop with vectorized search
3. **Optimize threshold calculations** - Pre-compute thresholds for all passes

**Expected speedup:** 40-50% (1.5-2.0s saved)

### Phase 3: Major Refactor (1-2 days)
1. **Full NumPy-based assignment algorithm** - Rewrite core distributor logic
2. **Parallel geo-unit processing** - Use multiprocessing for independent geo units
3. **JIT-compiled matching logic** - Numba-compile composition matching

**Expected speedup:** 60-70% (2.5-3.0s saved)

---

## 📈 EXPECTED PERFORMANCE IMPROVEMENTS

| Phase | Time Saved | New Runtime | Speedup |
|-------|------------|-------------|---------|
| Baseline | - | 4.77s | 1.0x |
| Phase 1 (cache + vectorize) | 0.6-0.9s | 3.9-4.2s | 1.2-1.3x |
| Phase 2 (Numba core) | 1.5-2.0s | 2.3-2.8s | 1.7-2.1x |
| Phase 3 (full refactor) | 2.5-3.0s | 1.8-2.3s | 2.1-2.7x |

---

## 🔍 OTHER FINDINGS

### Import Time
- **Total import overhead:** 0.814s (17% of runtime!)
- Scipy imports: ~0.42s
- Pandas imports: ~0.15s
- **Note:** This is one-time cost, won't scale with population size

### Pandas Overhead
- DataFrame iteration (`iterrows()`): 0.058s across 1,148 calls
- Series indexing: 0.369s across 123,242 calls
- **Recommendation:** Convert to NumPy arrays early, avoid pandas in hot loops

### Function Call Overhead
- Total function calls: 16.6 million
- `hasattr()` calls: 15,138
- `isinstance()` calls: 790,551
- **Recommendation:** Reduce dynamic type checking in hot paths

---

## 🎬 NEXT STEPS

1. **Profile with larger population** (500K+ people) to confirm bottlenecks scale
2. **Implement Phase 1 optimizations** - Low risk, high reward
3. **Benchmark after each change** - Verify improvements
4. **Consider Cython alternative** - If Numba has limitations
