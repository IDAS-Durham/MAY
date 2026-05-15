# Specific Workplace Distributors

**Topic:** [Distributors](index.md)  
**Paths:** `configs/2021/distributors/specific_workplace_hospitals_distributor.yaml`, `specific_workplace_care_homes_distributor.yaml`, `specific_workplace_classrooms_distributor.yaml`

---

## Overview

These distributors route sector-coded workers directly to specific venue types rather than to generic companies. They run before `company_distributor` so that, for example, health-sector workers are assigned to a hospital or care home before the company distributor processes the remaining workforce.

All three share an identical schema. The only meaningful differences are the target `venue_type`, the `work_sector` filter value, and the capacity column (or fixed capacity). Within the health sector (Q), the execution order ensures hospitals are filled first; unassigned Q workers then fall through to care homes.

---

## Keys

| Key | Description |
|---|---|
| `distributor_name` | Arbitrary label used in logs |
| `venue_type` | Venue type to assign workers to |
| `activity_map_key` | Key written to `person.activity_map`; `"primary_activity"` for all three |
| `subset_key` | Subset within the venue; `"worker"` for all three |
| `eligibility` | Age, sector, and residence filters |
| `venue_selection` | Geo-unit matching using workplace location |
| `allocation` | Strategy and capacity column |
| `settings` | Execution priority and logging |
| `fallback` | Behaviour when no eligible venue found |

---

## `eligibility`

```yaml
eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 18
      max: 64
    - attribute: "properties.workplace_sgu"
      type: "categorical"
    - attribute: "properties.work_sector"
      type: "categorical"
      values: ["Q"]           # "Q" for health; "P" for education
    - attribute: "residence.type"
      type: "categorical"
      values: ["household"]
  attributes:
    - name: "properties.work_sector"
      type: "categorical"
      matching_rules:
        "Q": ["Q"]
      case_sensitive: false
```

`require_unassigned: true` ensures workers already placed (e.g. by the hospital distributor before the care home distributor) are skipped. The `properties.workplace_sgu` filter requires that a workplace geography unit has already been assigned to the agent — agents without this attribute are excluded. `residence.type: ["household"]` excludes agents living in communal residences from workplace allocation.

The `attributes` block re-checks `work_sector` against the venue's own data as a second-pass constraint; in practice the `global_filters` already enforce sector exclusivity.

---

## `venue_selection`

```yaml
venue_selection:
  consider_by: "geo_unit"
  venue_geo_level: "LGU"
  person_location_attribute: "properties.workplace_sgu"
  batch_geo_level: "SGU"
  filter_by_geography: true
  respect_capacity: true
```

`consider_by: "geo_unit"` restricts candidates to venues within the same geo unit as the worker's assigned workplace area. `person_location_attribute: "properties.workplace_sgu"` uses the workplace geography rather than the agent's home geography — workers are matched to venues near where they work, not where they live. The engine traverses the geography hierarchy from the SGU workplace code up to `venue_geo_level` when resolving venue candidates.

---

## `allocation`

```yaml
# Hospitals — capacity from CSV column
allocation:
  strategy: "random"
  capacity_column: "estimated_staff"
  capacity_handling:
    if_missing: "skip"
    if_zero: "skip"
  track_capacity: true
  when_full: "exclude"
  batch_by: "geo_unit"

# Classrooms — fixed capacity of 1 teacher per room
allocation:
  strategy: "random"
  fixed_capacity: 1
  track_capacity: true
  when_full: "exclude"
  batch_by: "geo_unit"
```

`strategy: "random"` picks uniformly from eligible venues in the worker's geo unit. `capacity_column` names the CSV column holding venue capacity; `capacity_handling.if_missing: "skip"` excludes venues that lack a capacity value. The classroom distributor uses `fixed_capacity: 1` instead, enforcing exactly one teacher per classroom regardless of any CSV data.

---

## Key differences by config

| Config | `venue_type` | `work_sector` | Capacity source | `settings.priority` |
|---|---|---|---|---|
| `specific_workplace_hospitals_distributor` | `hospital` | `Q` | `estimated_staff` column | 4 |
| `specific_workplace_care_homes_distributor` | `care_home` | `Q` | `number_staff` column | 3 |
| `specific_workplace_classrooms_distributor` | `classroom` | `P` | `fixed_capacity: 1` | 3 |

The hospital distributor runs at priority 4 (before care homes at 3), so Q-sector workers are offered hospital placements first; those not assigned then become eligible for care home allocation. Both run before `company_distributor` (priority 5), which handles all remaining unassigned workers.
