# Venue Distributors

This directory contains YAML configuration files for the VenueDistributor system. Distributors allocate people to venues based on flexible, configurable rules.

## Overview

The VenueDistributor system provides a **generic, YAML-driven approach** to allocating people to venues. Each distributor:

1. **Filters eligible people** based on attributes (age, gender, employment status, etc.)
2. **Finds eligible venues** based on distance, geo_unit, or other criteria
3. **Allocates people to venues** using various strategies (random, closest, proportional, etc.)
4. **Sets activity_map** on each person: `person.activity_map[key] = venue`

## Usage

### In `config.yaml`:

```yaml
distributors:
  enabled: true
  configs:
    - "yaml/distributors/school_distributor.yaml"
    - "yaml/distributors/workplace_distributor.yaml"
    # Add more as needed
```

### Execution Order

Distributors run **after attribute assignment** in `create_world.py`:

1. Geography loaded
2. Venues loaded
3. Population generated
4. Households allocated
5. **Attributes assigned** (age, sex, ethnicity, etc.)
6. **→ Distributors executed** (allocate people to venues)

### In Code:

```python
from may.venue_distributor import VenueDistributor

# Load and execute distributor
distributor = VenueDistributor.from_yaml("yaml/distributors/school_distributor.yaml")
distributor.allocate(world)

# Access allocated venue
for person in world.people:
    if 'primary_activity' in person.activity_map:
        school = person.activity_map['primary_activity']
        print(f"{person} attends {school.name}")
```

## Creating a New Distributor

### Basic Structure:

```yaml
distributor_name: "my_distributor"
venue_type: "gym"  # Must match venue CSV type
activity_map_key: "leisure"  # person.activity_map['leisure'] = gym

# Who can be allocated?
eligibility:
  require_unassigned: true
  participation_rate: 0.20  # Optional: only 20% participate
  attributes:
    - name: "age"
      type: "numerical"
      person_constraints:
        min: 16
        max: 75

# How to find venues?
venue_selection:
  consider_by: "distance"  # or "count", "geo_unit"
  max_distance: 5
  max_distance_unit: "km"

# How to pick from eligible venues?
allocation:
  strategy: "random"  # or "closest", "proportional"
  batch_by: "geo_unit"  # For performance

settings:
  priority: 5
  use_spatial_index: true
```

## Available Distributors

### `school_distributor.yaml`
- **Venue type**: `school`
- **Activity key**: `primary_activity`
- **Eligibility**: Age (StatutoryLowAge to StatutoryHighAge), Gender matching
- **Selection**: Random from 5 closest schools
- **Special cases**: Boarding school students matched by name + geo_unit

## Key Features

### 1. Special Case Handling

Handle exceptions before normal allocation:

```yaml
special_cases:
  - name: "boarding_school_students"
    condition:
      person_residence_type: "boarding_school"
    allocation_rule:
      match_by:
        - field: "name"
          source: "person.residence.name"
          target: "venue.name"
```

### 2. Attribute Filtering

Filter people and venues by attributes:

```yaml
eligibility:
  attributes:
    # Numerical (age, income, etc.)
    - name: "age"
      type: "numerical"
      venue_constraints:
        min_column: "MinAge"
        max_column: "MaxAge"

    # Categorical (gender, employment, etc.)
    - name: "sex"
      type: "categorical"
      venue_column: "Gender"
      matching_rules:
        "Mixed": ["male", "female"]
        "Boys": ["male"]
        "Girls": ["female"]
```

### 3. Distance-Based Selection

Find venues by distance or count:

```yaml
venue_selection:
  # Option 1: N closest
  consider_by: "count"
  count: 5
  criteria: "closest"

  # Option 2: Within radius
  consider_by: "distance"
  max_distance: 10
  max_distance_unit: "km"

  # Option 3: Same geo_unit only
  consider_by: "geo_unit"
```

### 4. Allocation Strategies

Choose how to select final venue:

- **`random`**: Equal probability among eligible venues
- **`closest`**: Always pick nearest venue
- **`proportional`**: Weight by inverse distance (closer = higher chance)
- **`capacity_weighted`**: Weight by available capacity
- **`greedy_fill`**: Fill venues sequentially

### 5. Capacity Management

Track and respect venue capacity:

```yaml
allocation:
  capacity_column: "SchoolCapacity"
  capacity_handling:
    if_missing: "default"
    default_capacity: 500
  track_capacity: true
  when_full: "exclude"  # Remove from options
```

### 6. Performance Optimization

For millions of people:

```yaml
allocation:
  batch_by: "geo_unit"  # Process by geo_unit (huge speedup)

settings:
  use_spatial_index: true  # Use KDTree for O(log n) queries
  cache_venue_pools: true  # Cache eligible venues
```

## Examples

### Example 1: School Allocation
See `school_distributor.yaml` - demonstrates:
- Special case handling (boarding schools)
- Age and gender filtering
- Distance-based selection
- Random from N closest

### Example 2: Workplace Allocation
(Create `workplace_distributor.yaml`)
- Larger search radius (50km for commuting)
- Employment status filtering
- Proportional by distance (realistic commuting patterns)

### Example 3: Hospital Assignment
(Create `hospital_distributor.yaml`)
- Everyone assigned to nearest hospital
- No capacity limits (emergency care)
- Deterministic (always closest)

## Performance Notes

For **10 million people** and **30,000 schools**:

- **Without batching**: ~30 minutes (10M distance queries)
- **With batching**: ~1-2 minutes (30K distance queries)
- **Spatial indexing**: 100x faster distance lookups (O(log n) vs O(n))

## Best Practices

1. **Order matters**: Run distributors with stricter requirements first
2. **Batch by geo_unit**: Essential for large populations
3. **Use spatial indexing**: Enable `use_spatial_index: true`
4. **Handle special cases**: Define edge cases explicitly
5. **Test with small data**: Use filtered geography for development
6. **Log and monitor**: Enable verbose logging to debug

## File Naming Convention

Use descriptive names:
- `school_distributor.yaml`
- `workplace_distributor.yaml`
- `hospital_distributor.yaml`
- `gym_distributor.yaml`

## Troubleshooting

### No people allocated
- Check eligibility criteria (age ranges, attributes)
- Verify venue_type matches loaded venues
- Enable verbose logging: `settings.verbose: true`

### Slow performance
- Enable batching: `batch_by: "geo_unit"`
- Enable spatial index: `use_spatial_index: true`
- Reduce search radius or count

### Allocation errors
- Check required attributes exist on people
- Verify venue CSV has required columns
- Check special case matching conditions

## Additional Resources

- **VenueDistributor source**: `may/venue_distributor/venue_distributor.py`
- **Example usage**: `may/venue_distributor/example_usage.py`
- **Integration**: See `create_world.py` lines 262-285
