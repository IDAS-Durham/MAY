# school_distributor.yaml

Assigns school-age agents to schools. Applies age and gender constraints, handles boarding school residents as a special case, and processes age groups in priority order to guarantee places for 5–17 year-olds.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/school_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema. Key-specific notes below.

---

## Key Configuration Points

```yaml
distributor_name: "school_distributor"
venue_type: "school"
activity_map_key: "primary_activity"
subset_key: "student"

special_cases:
  - name: "boarding_school_students"
    condition:
      person_residence_type: "boarding_school"
    allocation_rule:
      match_by:
        - field: "name"
          source: "person.residence.name"
          target: "venue.name"
          match_type: "exact"           # must match school by name AND geo_unit
        - field: "geo_unit"
          source: "person.residence.geographical_unit.name"
          target: "venue.geographical_unit.name"
          match_type: "exact"
      mandatory: true
      if_no_match: "error"

eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 0
      max: 19
    - attribute: "residence.type"
      type: "categorical"
      values: ["household", "boarding_school"]
  exclude:
    households:
      original_pattern: "0 >=0 0 0"  # exclude young-adult-only households

  attributes:
    - name: "age"
      type: "numerical"
      venue_constraints:
        min_column: "StatutoryLowAge"
        max_column: "StatutoryHighAge"
      assume_if_missing: {min: 5, max: 18}

    - name: "sex"
      type: "categorical"
      venue_column: "Gender"
      matching_rules:
        "Mixed": ["male", "female"]
        "Boys": ["male"]
        "Girls": ["female"]
        "": ["male", "female"]
      assume_if_missing: "Mixed"
      case_sensitive: false

  priority_allocation:
    enabled: true
    priority_order: "age_desc"        # allocate oldest first
    groups:
      - name: "high_priority_school_age"
        priority: 1
        allow_overflow: true          # ages 5-17 guaranteed a place
        search_limits: [20, 70]
        filters:
          - attribute: "age"
            type: "numerical"
            min: 5
            max: 17
          - attribute: "residence.type"
            type: "categorical"
            values: ["household", "boarding_school"]

      - name: "second_priority_sixth_form"
        priority: 2
        allow_overflow: false         # ages 18-19 respect capacity
        search_limits: [15, 30]
        filters:
          - attribute: "age"
            type: "numerical"
            min: 18
            max: 19

      - name: "optional_early_childhood"
        priority: 3
        allow_overflow: false
        search_limits: [8, 10]        # nurseries very local — stop at 10
        filters:
          - attribute: "age"
            type: "numerical"
            min: 0
            max: 4

venue_selection:
  consider_by: "count"
  count: 10
  criteria: "closest"
  search_limits: [20, 50]
  venue_geo_level: "SGU"
  distance_metric: "haversine"
  respect_capacity: true

allocation:
  strategy: "random"
  capacity_column: "SchoolCapacity"
  capacity_handling:
    if_missing: "ignore"
    if_zero: "ignore"
  track_capacity: true
  when_full: "exclude"
  overflow_behavior:
    distribute_evenly: true
    max_overflow_per_venue: null

fallback:
  strategy: "skip"
```
