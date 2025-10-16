# Multi-Round Household Allocation Guide

## Overview

The multi-round household allocation system allows you to distribute people into households across multiple rounds, with the ability to perform other operations (like venue allocation, school enrollment, etc.) between rounds.

## Key Features

1. **Pattern Filtering**: Allocate specific household types in each round
2. **State Preservation**: Person pools maintain state between rounds
3. **Pool Refreshing**: Update pools to exclude already-allocated people
4. **Flexible Control**: Limit number of households per round
5. **Statistics Tracking**: Detailed stats for each round

## Basic Usage

### Method 1: Single Call (Original)

```python
# Allocate all households at once
households.distribute_households()
```

### Method 2: Multi-Round with Filtering

```python
# Round 1: Allocate elderly couples
households.distribute_households_round(
    pattern_filter=["0 0 0 2"],
    round_name="Elderly Couples"
)

# Round 2: Allocate families with kids
households.distribute_households_round(
    pattern_filter=[">=2 >=0 2 0", "1 >=0 2 0"],
    round_name="Families with Children"
)

# Round 3: Allocate everyone else
households.distribute_households_round(
    pattern_filter=None,  # All remaining patterns
    refresh_pools=True,   # Important!
    round_name="Remaining"
)
```

## API Reference

### `distribute_households_round()`

Allocate households in a single round with filtering and limits.

**Parameters:**

- `pattern_filter` (List[str], optional):
  - List of patterns to allocate in this round
  - If `None`, allocates all patterns
  - Example: `["0 0 2 0", "0 0 0 2"]`

- `max_households` (int, optional):
  - Maximum number of households to create this round
  - If `None`, no limit
  - Useful for gradual allocation

- `refresh_pools` (bool, default=False):
  - If `True`, refresh person pools to exclude already-allocated people
  - **Important**: Set to `True` when returning to allocation after other operations

- `round_name` (str, optional):
  - Name for this round (used in logging)
  - If `None`, defaults to "Round N"

**Returns:**
- `dict`: Statistics about the round including:
  - `round_name`: Name of the round
  - `round_number`: Sequential round number
  - `households_created`: Number created this round
  - `households_requested`: Number requested (with filter)
  - `households_with_demotion`: Number that used demotion
  - `people_allocated_this_round`: People allocated in this round
  - `total_households`: Total households so far
  - `total_people_allocated`: Total people allocated so far
  - `total_people_remaining`: Unallocated people remaining

### `get_available_people_count()`

Get the number of people currently available (not allocated).

**Returns:**
- `int`: Count of unallocated people

### `get_available_people_by_category()`

Get counts of available people by age category.

**Returns:**
- `dict`: Category name → count mapping

**Example:**
```python
available = households.get_available_people_by_category()
# {'Kids': 5234, 'Young Adults': 12453, 'Adults': 15432, 'Old Adults': 3421}
```

### `reset_allocation()`

Reset all household allocations. **Warning**: This clears all households!

Use this if you need to completely restart allocation.

## Usage Patterns

### Pattern 1: Priority-Based Allocation

Allocate households in order of priority (e.g., vulnerable populations first):

```python
# Round 1: Elderly first
households.distribute_households_round(
    pattern_filter=["0 0 0 2", "0 0 0 >=3"],  # Elderly couples and groups
    round_name="Elderly Priority"
)

# Round 2: Families with children
households.distribute_households_round(
    pattern_filter=[">=2 >=0 2 0", "1 >=0 2 0", ">=2 >=0 1 0", "1 >=0 1 0"],
    round_name="Families"
)

# Round 3: Adult-only households
households.distribute_households_round(
    pattern_filter=["0 0 2 0", "0 0 1 0"],
    round_name="Adult Households"
)

# Round 4: Everything else
households.distribute_households_round(
    pattern_filter=None,
    refresh_pools=True,
    round_name="Remaining"
)
```

### Pattern 2: Interleaved with Other Allocations

Allocate to households, then to venues, then back to households:

```python
# Round 1: Families with kids
households.distribute_households_round(
    pattern_filter=[">=2 >=0 2 0", "1 >=0 2 0"],
    round_name="Families"
)

# Now allocate some people to care homes
# (your code to allocate elderly to care homes)
care_homes.allocate_residents(...)

# Now allocate students to university dorms
# (your code to allocate students)
dorms.allocate_students(...)

# Round 2: Allocate remaining people to households
# IMPORTANT: Use refresh_pools=True!
households.distribute_households_round(
    pattern_filter=None,
    refresh_pools=True,  # Excludes people allocated to venues
    round_name="Post-Venue Allocation"
)
```

### Pattern 3: Gradual Allocation with Limits

Allocate a limited number of households per round:

```python
# Allocate in batches of 1000 households
for i in range(10):
    stats = households.distribute_households_round(
        max_households=1000,
        round_name=f"Batch {i+1}"
    )

    # Check if we allocated fewer than requested
    if stats['households_created'] < 1000:
        print("Ran out of compatible people/patterns")
        break

    # Do something between batches
    # ...
```

### Pattern 4: Conditional Allocation

Check available people before each round:

```python
available = households.get_available_people_by_category()

if available['Kids'] >= 1000:
    # Enough kids for family allocation
    households.distribute_households_round(
        pattern_filter=[">=2 >=0 2 0", "1 >=0 2 0"],
        round_name="Families with Kids"
    )

if available['Old Adults'] >= 500:
    # Enough elderly for couple allocation
    households.distribute_households_round(
        pattern_filter=["0 0 0 2"],
        round_name="Elderly Couples"
    )
```

## Important Notes

### When to Use `refresh_pools=True`

You **must** use `refresh_pools=True` when:
- Returning to household allocation after allocating people elsewhere
- You've manually modified `allocated_people` set
- You want to ensure pools only contain truly available people

You can skip it (use `False`) when:
- Running consecutive rounds with no other operations in between
- The distributor is the only thing modifying allocations

### Pattern Syntax

Patterns follow the format: `"<kids> <young_adults> <adults> <old_adults>"`

- Exact count: `"2"` means exactly 2 people
- Flexible: `">=2"` means 2 or more people
- Zero: `"0"` means zero people

Age categories are defined in `households_config.yaml`:
- Kids: 0-17
- Young Adults: 18-24
- Adults: 25-64
- Old Adults: 65+

### Performance Considerations

- Each round prepares/refreshes pools, which can be expensive for large populations
- Filter to specific patterns to speed up rounds
- Use `max_households` to limit work per round
- Person pool preparation is O(N) where N is population size

### State Management

The distributor maintains state across rounds:
- `self.households`: List of all created households
- `self.allocated_people`: Set of person IDs that have been allocated
- `self.person_pool_by_area`: Available people by area and category
- `self.current_round`: Current round number

This state persists until:
- You call `reset_allocation()` (clears everything)
- You create a new HouseholdDistributor instance

## Testing Results

Using `example_multiround_households.py` with the test data:

| Round | Patterns | Households | People Allocated |
|-------|----------|------------|------------------|
| 1: Elderly Couples | `0 0 0 2` | 929 | 1,858 |
| 2: Families | `>=2 >=0 2 0`, `1 >=0 2 0`, etc. | 9,319 | 29,676 |
| 3: Remaining | All patterns | 27,305 | 48,961 |
| **Total** | - | **37,553** | **80,495** |

Starting population: 95,231
Final unallocated: 14,736 (15.5%)

## Example Script

See `example_multiround_households.py` for a complete working example demonstrating:
- 3-round allocation
- Pattern filtering
- Pool refreshing
- Statistics tracking
- Export of final results
