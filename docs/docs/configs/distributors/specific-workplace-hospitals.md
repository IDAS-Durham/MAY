# specific_workplace_hospitals_distributor.yaml

Assigns Q-sector (Health) workers to hospitals as their workplace (`primary_activity`). Runs before `company_distributor` so that Q workers are directed to hospitals rather than generic companies.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/specific_workplace_hospitals_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "specific_workplace_hospitals_distributor"
venue_type: "hospital"
activity_map_key: "primary_activity"
subset_key: "worker"

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
      values: ["Q"]                  # only Q (Health) sector
    - attribute: "residence.type"
      type: "categorical"
      values: ["household"]

venue_selection:
  consider_by: "geo_unit"
  venue_geo_level: "LGU"
  person_location_attribute: "properties.workplace_sgu"
  batch_geo_level: "SGU"
  respect_capacity: true

allocation:
  strategy: "random"
  capacity_column: "estimated_staff"
  capacity_handling:
    if_missing: "skip"
    if_zero: "skip"
  track_capacity: true
  when_full: "exclude"

settings:
  priority: 4                        # after university (1), before company (5)

fallback:
  strategy: "skip"                   # unassigned Q workers fall through to care_homes then company
```
