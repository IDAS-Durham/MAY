# Care Home Visits Distributor

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/care_home_visits_distributor.yaml`

---

## Overview

Links households of care home residents to the care home as a leisure venue, so that household members may visit. For each resident already placed in a care home, `multiplier` households in the same geographical area are linked to the venue under `activity_map["leisure"]`.

Identified by `distributor_type: "resident_linked"` — a distinct loader class (`ResidentLinkedDistributor`) from the standard venue distributor.

---

## Keys

| Key | Description |
|---|---|
| `distributor_name` | Arbitrary label used in logs |
| `distributor_type` | Must be `"resident_linked"` |
| `target_venue_type` | Venue type to link visitors to |
| `resident_subset` | Subset name identifying residents already in the venue |
| `subset_key` | Subset name assigned to visiting household members |
| `activity_map_key` | Key written to `person.activity_map` |
| `link_level` | Unit of linking: `"household"` or `"person"` |
| `multiplier` | Visitor units linked per resident |
| `geography_level` | Geography level used when batching venue–household matching |
| `visitor_eligibility` | Filters restricting which households are eligible to visit |
| `settings` | Logging and batch geography level |

---

## Core linking keys

```yaml
distributor_type: "resident_linked"
target_venue_type: "care_home"
resident_subset: "resident"
subset_key: "visitor"
activity_map_key: "leisure"
link_level: "household"
multiplier: 1
geography_level: "MGU"
```

The distributor iterates care homes, reads the `resident_subset` to count how many residents are present, then links `multiplier` visitor units per resident from households in the same `geography_level` area. `link_level: "household"` links the entire household — all members are added to the venue's `visitor` subset and receive the care home under `activity_map["leisure"]`. Setting `link_level: "person"` links individuals rather than households. `multiplier` may be a non-integer; fractional parts are applied probabilistically (e.g. `1.5` gives each resident a 50% chance of attracting a second household).

---

## `visitor_eligibility`

```yaml
visitor_eligibility:
  global_filters:
    - attribute: "residence.type"
      value: "household"
      type: "categorical"
    - attribute: "residence.properties.original_pattern"
      values:
        - ">=2 >=0 2 0"
        - "1 >=0 2 0"
        - "0 0 2 0"
        - "0 0 0 2"
        # ... (full list in config)
      type: "categorical"
```

Filters which households are eligible to be linked as visitors. `residence.type: "household"` excludes communal residence types. `residence.properties.original_pattern` restricts linking to household compositions that are likely to include family members of care home residents — families with children, households with young adults, and adult-only households. The pattern strings follow the household composition encoding defined in `allocation_strategy.yaml`.

---

## `settings`

```yaml
settings:
  verbose: true
  batch_geo_level: "MGU"
```

`batch_geo_level` controls the geographic unit at which venue–household pairing is batched. `"MGU"` (Middle Geographical Unit) is appropriate for care homes, which draw visitors from a broader area than a single small geo unit.
