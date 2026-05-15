# Venue Distributors

**Topic:** [Distributors](index.md)  
**Paths:** `configs/2021/distributors/school_distributor.yaml`, `university_distributor.yaml`, `company_distributor.yaml`, `hospital_distributor.yaml`

---

## Overview

A venue distributor allocates agents to venues and records the assignment on the agent's `activity_map`. Each YAML file targets one `venue_type` (school, university, company, hospital). All share the same top-level schema; only the values differ.

Allocation proceeds in phases:

1. **Special cases** — mandatory overrides handled before anything else (e.g. boarding-school students matched to their named school).
2. **Priority groups** — defined sub-populations allocated in order, optionally with per-area probabilities. Each group may permit overflow.
3. **Normal allocation** — remaining eligible agents allocated by the configured strategy and distance rules.
4. **Fallback** — agents still unallocated after all phases are handled according to `fallback.strategy`.

---

## Keys

| Key | Description |
|---|---|
| `distributor_name` | Arbitrary label used in logs |
| `venue_type` | Must match a key in `venues_config.yaml` |
| `activity_map_key` | Key written to `person.activity_map` on assignment |
| `subset_key` | Subset the agent is added to within the venue |
| `special_cases` | Priority overrides applied before eligibility filters |
| `eligibility` | Who is eligible and how they are prioritised |
| `venue_selection` | How candidate venues are found for each agent |
| `allocation` | How a venue is chosen from candidates and capacity managed |
| `settings` | Execution order, logging, performance |
| `fallback` | Behaviour when no eligible venue is found |
| `validation` | Required attributes checked before allocation |
| `exports` | Optional CSV reports written after allocation |

---

## `distributor_name`, `venue_type`, `activity_map_key`, `subset_key`

```yaml
distributor_name: "school_distributor"
venue_type: "school"
activity_map_key: "primary_activity"
subset_key: "student"
```

`venue_type` determines which loaded venues are candidates. `activity_map_key` is the key under which the assigned venue is stored on `person.activity_map`; the hospital distributor uses `"medical_facility"` rather than `"primary_activity"`. `subset_key` is the subset name added to the venue; omit to skip subset assignment.

---

## `special_cases`

```yaml
special_cases:
  - name: "boarding_school_students"
    priority: 1
    condition:
      person_residence_type: "boarding_school"
    allocation_rule:
      match_by:
        - field: "name"
          source: "person.residence.name"
          target: "venue.name"
          match_type: "exact"
      mandatory: true
      if_no_match: "error"   # "error" | "warn" | "skip" | "fallback_to_normal"
```

Special cases are checked before any eligibility filter. A matched agent bypasses the normal pipeline entirely. `mandatory: true` means the match must succeed; `if_no_match` controls what happens when no venue matches the rule — `"error"` halts, `"warn"` logs and continues, `"skip"` silently leaves the agent unassigned, `"fallback_to_normal"` re-enters the agent into normal allocation.

---

## `eligibility`

```yaml
eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 5
      max: 19
    - attribute: "residence.type"
      type: "categorical"
      values: ["household", "boarding_school"]
  exclude:
    households:
      original_pattern: "0 >=0 0 0"
  attributes:
    - name: "sex"
      type: "categorical"
      venue_column: "Gender"
      matching_rules:
        "Mixed": ["male", "female"]
        "Boys": ["male"]
        "Girls": ["female"]
      assume_if_missing: "Mixed"
      case_sensitive: false
  priority_allocation:
    enabled: true
    priority_order: "age_desc"
    groups:
      - name: "high_priority_school_age"
        priority: 1
        allow_overflow: true
        search_limits: [20, 70]
        filters:
          - attribute: "age"
            type: "numerical"
            min: 5
            max: 17
        probability_config:
          type: "file"
          file_path: "data/activities/university/university_probabilities.csv"
          lookup_column: "geo_unit"
          lookup_attribute: "geographical_unit.name"
          probability_column: "prob_uni_18_22"
          default: 0.35
```

`require_unassigned` — when `true`, skips anyone who already has `activity_map_key` assigned.

`global_filters` apply to all phases. Each filter has an `attribute` path, a `type` (`"numerical"` or `"categorical"`), and type-specific bounds (`min`/`max`) or allowed `values`. Filters are checked in order; list more restrictive filters first for efficiency. Attribute paths may traverse nested objects using dot notation (e.g. `residence.type`, `properties.workplace_sgu`).

`exclude.households.original_pattern` removes agents from households whose `original_pattern` property matches the given string.

`attributes` matches agent properties against venue CSV columns. Each entry names a `venue_column` and a `matching_rules` dict mapping CSV values to lists of valid agent values. `assume_if_missing` supplies a default if the column is absent from the venue data.

`priority_allocation.groups` are processed in `priority` order before normal allocation. `allow_overflow: true` permits the group to exceed venue capacity whilst still respecting `attributes` constraints. `search_limits` is a list of candidate counts tried in sequence (e.g. `[20, 70]` — try 20 closest, then 70). `probability_config` optionally samples agents stochastically: `type: "file"` loads a CSV, matching rows by `lookup_column` against the agent attribute named by `lookup_attribute`, and reads allocation probability from `probability_column`; `default` is used when the agent's geo unit is not found in the file. `priority_order: "age_desc"` processes older agents first within each group.

---

## `venue_selection`

```yaml
venue_selection:
  consider_by: "count"       # "count" | "distance" | "geo_unit"
  count: 10
  criteria: "closest"        # "closest" | "random" | "largest_capacity"
  search_limits: [20, 50]
  max_distance: 10
  max_distance_unit: "km"    # "km" | "miles" | "meters"
  venue_geo_level: "SGU"     # "SGU" | "MGU" | "LGU"
  person_location_source: "geographical_unit.coordinates"
  venue_location_source: "coordinates"
  distance_metric: "haversine"  # "haversine" | "euclidean"
  filter_by_geography: true
  respect_capacity: true
```

`consider_by` controls how candidate venues are identified. `"count"` selects the `count` closest venues matching `criteria`. `"distance"` selects all venues within `max_distance`. `"geo_unit"` restricts to venues sharing the agent's geo unit (used by the company distributor, which matches by `workplace_sgu` rather than residence).

`venue_geo_level` declares the geography level at which venue coordinates are stored; the engine traverses the hierarchy when agent and venue levels differ.

`person_location_source` is the attribute path used to read the agent's location. The company distributor sets this to `"properties.workplace_sgu"` to match agents to companies near their work location rather than their home.

`distance_metric: "haversine"` computes great-circle distance from (latitude, longitude) pairs; `"euclidean"` uses projected coordinates.

`search_limits` gives a fallback candidate sequence for the global pipeline (individual priority groups may specify their own).

---

## `allocation`

```yaml
allocation:
  strategy: "random"        # "random" | "closest" | "proportional"
  capacity_column: "SchoolCapacity"
  capacity_handling:
    if_missing: "ignore"    # "ignore" | "skip" | "default"
    default_capacity: 1000
    if_zero: "ignore"       # "ignore" | "skip"
  track_capacity: true
  when_full: "exclude"      # "exclude" | "overflow"
  overflow_behavior:
    distribute_evenly: true
    max_overflow_per_venue: null
  enforce_no_empty_venues: false
  batch_by: "geo_unit"      # "geo_unit" | "none"
  batch_location_source: "centroid"
```

`strategy` selects from the candidate set: `"random"` picks uniformly; `"closest"` always picks the nearest; `"proportional"` weights by inverse distance.

`capacity_column` names the CSV column holding venue capacity. `capacity_handling` controls what happens when the column is absent or zero. `track_capacity` enables runtime tracking so full venues are excluded from subsequent candidates. `when_full: "exclude"` removes a full venue from the candidate set; `"overflow"` allows over-capacity assignment (always applies to priority groups with `allow_overflow: true`).

`enforce_no_empty_venues` — when `true`, post-allocation step that moves one agent from the most-populated venue to each empty venue, minimising the number of venues with zero occupancy.

`batch_by: "geo_unit"` groups agents sharing a geo unit and performs a single spatial query for the batch, reducing the number of distance calculations significantly.

---

## `settings`

```yaml
settings:
  priority: 10
  max_allocations: null
  verbose: true
  log_summary: true
  use_spatial_index: true
```

`priority` controls execution order across all distributors; higher runs first. `use_spatial_index` builds a KD-tree over venue coordinates for fast nearest-neighbour queries — disable only for very small venue sets or debugging.

---

## `fallback`

```yaml
fallback:
  strategy: "skip"    # "skip" | "relax_distance" | "relax_capacity" | "assign_closest"
  relax_params:
    max_iterations: 3
    distance_multiplier: 2.0
```

Applied to any agent still unassigned after all phases. `"skip"` leaves the agent unassigned. `"relax_distance"` retries with an expanded search radius, doubling it each iteration up to `max_iterations`. `"relax_capacity"` retries ignoring capacity limits. `"assign_closest"` assigns the nearest venue regardless of all constraints.

The hospital distributor uses `"assign_closest"` — every agent must be assigned a medical facility.

---

## `validation`

```yaml
validation:
  required_person_attributes:
    - "age"
    - "geographical_unit"
  required_venue_columns:
    - "geo_unit"
    - "Latitude"
    - "Longitude"
  optional_venue_columns:
    - "StatutoryLowAge"
    - "StatutoryHighAge"
```

`required_person_attributes` — agents missing any of these are skipped before allocation. `required_venue_columns` — venues missing these raise an error. `optional_venue_columns` — missing values trigger a warning only.

---

## `exports`

```yaml
exports:
  venue_summary: "output/school_summary.csv"
  unallocated_report: "output/school_unallocated.csv"
```

Optional post-allocation CSV reports. `venue_summary` writes per-venue occupancy statistics. `unallocated_report` lists agents that remained unassigned after fallback.

---

## Key differences by venue type

| Config | `consider_by` | `allocation.strategy` | `fallback.strategy` | Notes |
|---|---|---|---|---|
| `school_distributor` | `count` | `random` | `skip` | Age + gender constraints; boarding-school special case; priority groups by age band |
| `university_distributor` | `count` | `proportional` | `skip` | Stochastic priority groups with per-SGU probability file |
| `company_distributor` | `geo_unit` | `random` | `skip` | Matches by `workplace_sgu`; `work_sector` must match `industry_code` |
| `hospital_distributor` | `count` (1) | `closest` | `assign_closest` | No eligibility filters; `respect_capacity: false`; everyone assigned |
