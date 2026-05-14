# Distributors

Each file assigns agents to a venue type by setting an entry in their `activity_map`. Distributors are run in the order specified in `timeline.steps`; order matters because `require_unassigned: true` skips people already placed.

| File | Venue type | Activity key | Notes |
|---|---|---|---|
| [`school_distributor.yaml`](school-distributor.md) | school | `primary_activity` | Age/gender constraints; boarding-school special case; priority groups |
| [`university_distributor.yaml`](university-distributor.md) | university | `primary_activity` | Per-SGU probability config; dorm special case; proportional distance allocation |
| [`company_distributor.yaml`](company-distributor.md) | company | `primary_activity` | Geo-unit matching on `workplace_sgu`; sector attribute matching |
| [`hospital_distributor.yaml`](hospital-distributor.md) | hospital | `medical_facility` | Closest hospital; no capacity tracking |
| [`multi_venue_distributor.yaml`](multi-venue-distributor.md) | cinema, grocery, gym, pub | `leisure` | Assigns N closest venues of each type; participation filter support |
| [`specific_workplace_hospitals_distributor.yaml`](specific-workplace-hospitals.md) | hospital | `primary_activity` | Q-sector workers → hospitals as workplace |
| [`specific_workplace_care_homes_distributor.yaml`](specific-workplace-care-homes.md) | care_home | `primary_activity` | Q-sector workers → care homes as workplace |
| [`specific_workplace_classrooms_distributor.yaml`](specific-workplace-classrooms.md) | classroom | `primary_activity` | P-sector workers → classrooms; fixed capacity 1 |
| [`care_home_visits_distributor.yaml`](care-home-visits.md) | care_home | `leisure` | Links households of care home residents as visitors |

---

## Generic Distributor Schema

The keys below apply to all standard distributors. Individual pages document only what differs.

```yaml
distributor_name: "..."             # arbitrary label for logging
venue_type: "..."                   # must match a key in venues_config.yaml
description: "..."
distributor_type: "..."             # optional — "multi_venue" | "resident_linked"
                                    # omit for standard single-venue distributor

activity_map_key: "primary_activity"  # key written to person.activity_map
subset_key: "student"               # subset name within the venue


# ============================================================
# SPECIAL CASES  (optional)
# ============================================================
special_cases:
  - name: "boarding_school_students"
    description: "..."
    priority: 1                     # lower = checked first

    condition:
      person_residence_type: "boarding_school"   # match by residence venue type
      filters:                      # optional additional filters
        - attribute: "age"
          type: "numerical"
          min: 18

    allocation_rule:
      strategy: "closest"           # "closest" | match_by
      match_by:                     # optional — match by field values
        - field: "name"
          source: "person.residence.name"
          target: "venue.name"
          match_type: "exact"
      mandatory: true
      if_no_match: "error"          # "error" | "warn" | "skip" | "fallback_to_normal"


# ============================================================
# ELIGIBILITY
# ============================================================
eligibility:
  require_unassigned: true          # skip people already holding this activity key

  global_filters:                   # applied to all phases
    - attribute: "age"
      type: "numerical"             # "numerical" | "categorical"
      min: 0
      max: 19
    - attribute: "properties.work_sector"
      type: "categorical"
      values: ["Q"]                 # optional — restrict to listed values
    - attribute: "residence.type"
      type: "categorical"
      values: ["household"]
    - attribute: "residence.properties.original_pattern"
      type: "categorical"
      values: ["0 0 2 0"]

  exclude:                          # optional — exclude by household properties
    households:
      original_pattern: "0 >=0 0 0"

  require_residence: true           # optional — person must have a residence assigned

  attributes:                       # venue-level attribute matching
    - name: "sex"
      type: "categorical"
      venue_column: "Gender"        # CSV column on the venue
      matching_rules:
        "Mixed": ["male", "female"]
        "Boys": ["male"]
      assume_if_missing: "Mixed"
      case_sensitive: false
    - name: "age"
      type: "numerical"
      venue_constraints:
        min_column: "StatutoryLowAge"
        max_column: "StatutoryHighAge"
      assume_if_missing:
        min: 5
        max: 18

  priority_allocation:              # optional — process subgroups in priority order
    enabled: true
    priority_order: "age_desc"      # optional — "age_desc" | "age_asc"
    groups:
      - name: "high_priority_school_age"
        description: "..."
        priority: 1
        allow_overflow: false       # true → can exceed venue capacity

        search_limits: [20, 70]     # [first_try, max_try] — stops after max_try

        probability_config:         # optional — probabilistic inclusion
          type: "file"
          file_path: "data/.../probabilities.csv"
          lookup_column: "geo_unit"
          lookup_attribute: "geographical_unit.name"
          probability_column: "prob_uni_18_22"
          default: 0.35

        filters:
          - attribute: "age"
            type: "numerical"
            min: 5
            max: 17


# ============================================================
# VENUE SELECTION
# ============================================================
venue_selection:
  consider_by: "count"              # "count" | "distance" | "geo_unit"

  count: 10                         # venues to consider (when consider_by = "count")
  criteria: "closest"               # "closest" | "random" | "largest_capacity" | "distance"

  max_distance: 100                 # optional — km limit (when consider_by = "distance" or as soft cap)
  max_distance_unit: "km"           # "km" | "miles" | "meters"

  search_limits: [20, 50]           # global fallback [first_try, max_try]

  venue_geo_level: "SGU"            # "SGU" | "MGU" | "LGU" | "XLGU"
  batch_geo_level: "SGU"            # optional — override batch level

  person_location_source: "geographical_unit.coordinates"
                                    # or "properties.workplace_sgu"
  person_location_attribute: "properties.workplace_sgu"
                                    # alternative form for specific_workplace distributors

  venue_location_source: "coordinates"   # "coordinates" | "geo_unit.coordinates"

  distance_metric: "haversine"      # "haversine" | "euclidean"

  filter_by_geography: true
  respect_capacity: true


# ============================================================
# ALLOCATION
# ============================================================
allocation:
  strategy: "random"                # "random" | "closest" | "proportional" | "closest_balanced"

  capacity_column: "SchoolCapacity" # optional — CSV column to read capacity from
  fixed_capacity: 1                 # optional — fixed integer capacity (overrides CSV column)

  capacity_handling:
    if_missing: "ignore"            # "ignore" | "skip" | "default"
    default_capacity: 1000
    if_zero: "ignore"               # "ignore" | "skip"

  track_capacity: true
  when_full: "exclude"              # "exclude" | "overflow"

  overflow_behavior:
    distribute_evenly: true
    max_overflow_per_venue: null

  batch_by: "geo_unit"              # "geo_unit" | "none"
  batch_location_source: "centroid"


# ============================================================
# SETTINGS
# ============================================================
settings:
  priority: 10                      # execution order; higher = earlier
  max_allocations: null             # optional integer cap
  verbose: true
  log_summary: true
  use_spatial_index: true


# ============================================================
# FALLBACK
# ============================================================
fallback:
  strategy: "skip"                  # "skip" | "relax_distance" | "relax_capacity" | "assign_closest"
  relax_params:
    max_iterations: 3
    distance_multiplier: 2.0


# ============================================================
# VALIDATION
# ============================================================
validation:
  required_person_attributes:
    - "age"
    - "geographical_unit"
  required_venue_columns:
    - "geo_unit"
    - "Latitude"
    - "Longitude"
  optional_venue_columns:
    - "SchoolCapacity"
```
