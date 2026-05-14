# Multi-Venue Distributor

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/multi_venue_distributor.yaml`

---

## Overview

Assigns each eligible agent a set of candidate venues across multiple venue types in a single pass. Unlike the standard venue distributor — which assigns one venue per agent — this distributor stores a *list* of N closest venues per type in a nested dict on `activity_map`:

```
person.activity_map["leisure"] = {
    "cinema": [subset_a, subset_b, ...],
    "gym":    [subset_c],
    "pub":    [subset_d, subset_e, ...],
}
```

Use this for optional activities (leisure, social, services) where agents should have a pool of nearby options rather than a single assigned venue.

Identified by `distributor_type: "multi_venue"` — this field tells the loader to instantiate `MultiVenueDistributor` rather than the standard `VenueDistributor`.

---

## Keys

| Key | Description |
|---|---|
| `distributor_name` | Arbitrary label used in logs |
| `distributor_type` | Must be `"multi_venue"` |
| `activity_map_key` | Top-level key written to `person.activity_map` |
| `subset_key` | Subset name added to each venue |
| `venue_types` | List of venue type names to include |
| `venue_type_config` | Per-type overrides: `count` and `participation_filter` |
| `eligibility` | Age, residence, and other filters |
| `venue_selection` | Distance method and candidate count |
| `allocation` | Capacity tracking (usually disabled) |
| `settings` | Execution priority and logging |
| `validation` | Required person and venue attributes |

---

## `venue_types` and `venue_type_config`

```yaml
venue_types:
  - cinema
  - grocery
  - gym
  - pub

venue_type_config:
  gym:
    count: 1
    participation_filter:
      data_file: "data/population/leisure_participation/gym_attendance.csv"
      row_filters:
        - person_attribute: "age"
          csv_column: "age_band"
          match_type: "age_range"         # parses "16-24" format
      probability_column:
        person_attribute: "sex"
        column_template: "pct_{value}"    # e.g. "pct_male", "pct_female"
        # alternative: column_name: "participation_rate"
```

`venue_types` lists every venue type to include; all must be defined in `venues_config.yaml`. The global `venue_selection.count` applies to all types by default. `venue_type_config` allows per-type overrides:

`count` overrides the number of candidate venues assigned for that type.

`participation_filter` applies stochastic inclusion before assigning venues — only agents passing the filter receive venues of that type. `row_filters` match the agent's attributes against CSV rows to select the correct probability row. `match_type` may be `"age_range"` (parses `"16-24"`-style strings), `"exact"`, or `"numerical_range"`. `probability_column` resolves the probability column either dynamically via `column_template` (where `{value}` is substituted with the agent's attribute value) or statically via `column_name`.

---

## `eligibility`

```yaml
eligibility:
  require_unassigned: false
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 18
      max: 120
    - attribute: "residence.type"
      type: "categorical"
      values: ["household", "student_dorms"]
  require_residence: true
```

`require_unassigned: false` — leisure assignment is independent of other activities; an agent may hold this key alongside `primary_activity`. `require_residence: true` skips agents without a residence assigned. Filters follow the same rules as the standard distributor (see [Venue Distributors](venue-distributor.md)).

---

## `venue_selection`

```yaml
venue_selection:
  consider_by: "count"
  count: 5
  criteria: "closest"
  venue_geo_level: "MGU"
  batch_geo_level: "SGU"
  person_location_source: "geographical_unit.coordinates"
  venue_location_source: "coordinates"
  distance_metric: "haversine"
  filter_by_geography: true
  respect_capacity: false
```

`count` is the default number of candidate venues per type. `respect_capacity: false` is standard for optional activities — there is no meaningful capacity limit on how many agents may list a cinema as a leisure option.

---

## `allocation` and `settings`

```yaml
allocation:
  track_capacity: false
  batch_by: "geo_unit"

settings:
  priority: 1
  max_allocations: null
  verbose: true
  log_summary: true
  use_spatial_index: true
```

Capacity tracking is typically disabled for leisure venues. `batch_by: "geo_unit"` groups agents sharing a geo unit to share the spatial query, reducing computation significantly at population scale. `use_spatial_index` builds a KD-tree per venue type for fast nearest-neighbour queries.
