# multi_venue_distributor.yaml

Assigns agents a set of N closest venues of each listed type, stored as a nested dict under a single activity key. Used for leisure venues (cinema, grocery, gym, pub). Supports per-venue-type participation filters.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/multi_venue_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "multi_venue_distributor"
distributor_type: "multi_venue"       # activates the multi-venue loader class

activity_map_key: "leisure"           # top-level key: person.activity_map["leisure"]
subset_key: "patron"

venue_types:                          # list of venue types to assign
  - cinema
  - grocery
  - gym
  - pub

# Per-type overrides (optional)
venue_type_config:
  gym:
    count: 1                          # override default count for this type
    participation_filter:
      data_file: "data/population/leisure_participation/gym_attendance.csv"
      row_filters:
        - person_attribute: "age"
          csv_column: "age_band"
          match_type: "age_range"     # "age_range" | "exact" | "numerical_range"
      probability_column:
        person_attribute: "sex"
        column_template: "pct_{value}"  # {value} replaced with person.sex
        # alternative: column_name: "participation_rate"  # fixed column

eligibility:
  require_unassigned: false           # leisure is independent of primary_activity
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 18
      max: 120
    - attribute: "residence.type"
      type: "categorical"
      values: ["household", "student_dorms"]
  require_residence: true

venue_selection:
  consider_by: "count"
  count: 5                            # 5 venues of each type per person
  criteria: "closest"
  venue_geo_level: "MGU"              # leisure venues at MGU level
  batch_geo_level: "SGU"
  distance_metric: "haversine"
  respect_capacity: false

allocation:
  track_capacity: false
  batch_by: "geo_unit"

# Result structure:
# person.activity_map["leisure"] = {
#     "cinema": [subset1, subset2, ...],
#     "grocery": [...],
#     "gym": [...],
#     "pub": [...],
# }
```
