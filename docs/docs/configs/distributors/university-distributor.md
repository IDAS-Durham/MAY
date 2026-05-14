# university_distributor.yaml

Assigns 18–24 year-olds to universities. Uses per-SGU probability files to reflect differential university attendance rates. Dorm residents are matched to their closest university as a special case.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/university_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "university_distributor"
venue_type: "university"
activity_map_key: "primary_activity"
subset_key: "student"

special_cases:
  - name: "student_dorms_students"
    condition:
      person_residence_type: "student_dorms"
      filters:
        - attribute: "age"
          type: "numerical"
          min: 18
    allocation_rule:
      strategy: "closest"
      if_no_match: "warn"

eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 18
      max: 24
    - attribute: "residence.type"
      type: "categorical"
      values: ["household", "student_dorms"]

  priority_allocation:
    enabled: true
    groups:
      - name: "highest_priority_young_adults_from_specific_households"
        priority: 1
        allow_overflow: false
        probability_config:
          type: "file"
          file_path: "data/activities/university/university_probabilities.csv"
          lookup_column: "geo_unit"
          lookup_attribute: "geographical_unit.name"
          probability_column: "prob_uni_18_22"
          default: 0.35
        filters:
          - attribute: "age"
            type: "numerical"
            min: 18
            max: 22
          - attribute: "residence.properties.original_pattern"
            type: "categorical"
            values: ["0 >=0 0 0"]       # young-adult-only households first

      - name: "high_priority_uni_age"
        priority: 2
        allow_overflow: false
        probability_config:
          type: "file"
          file_path: "data/activities/university/university_probabilities.csv"
          lookup_column: "geo_unit"
          lookup_attribute: "geographical_unit.name"
          probability_column: "prob_uni_18_22"
          default: 0.35
        filters:
          - attribute: "age"
            type: "numerical"
            min: 18
            max: 22

      - name: "second_priority_postgrads"
        priority: 3
        allow_overflow: false
        probability_config:
          type: "file"
          file_path: "data/activities/university/university_probabilities.csv"
          lookup_column: "geo_unit"
          lookup_attribute: "geographical_unit.name"
          probability_column: "prob_uni_23_24"
          default: 0.15
        filters:
          - attribute: "age"
            type: "numerical"
            min: 23
            max: 24

venue_selection:
  consider_by: "count"
  count: 5
  criteria: "distance"
  max_distance: 10
  max_distance_unit: "km"
  venue_geo_level: "SGU"
  distance_metric: "haversine"
  respect_capacity: true

allocation:
  strategy: "proportional"          # weight by inverse distance
  capacity_column: "n_students"
  capacity_handling:
    if_missing: "ignore"
    if_zero: "ignore"
  track_capacity: true
  when_full: "exclude"

fallback:
  strategy: "skip"
  relax_params:
    max_iterations: 3
    distance_multiplier: 2.0
```
