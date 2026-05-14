# specific_workplace_care_homes_distributor.yaml

Assigns Q-sector workers not already placed by `specific_workplace_hospitals_distributor` to care homes as their workplace. Runs after hospitals, before `company_distributor`.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/specific_workplace_care_homes_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema. Configuration is identical to [`specific_workplace_hospitals_distributor.yaml`](specific-workplace-hospitals.md) except for venue type and capacity column.

---

## Key Configuration Points

```yaml
distributor_name: "specific_workplace_care_homes_distributor"
venue_type: "care_home"
activity_map_key: "primary_activity"
subset_key: "worker"

eligibility:
  require_unassigned: true           # only picks up Q workers not sent to hospitals
  global_filters:
    - attribute: "properties.work_sector"
      type: "categorical"
      values: ["Q"]

venue_selection:
  consider_by: "geo_unit"
  venue_geo_level: "LGU"
  person_location_attribute: "properties.workplace_sgu"

allocation:
  strategy: "random"
  capacity_column: "number_staff"    # differs from hospital distributor
  capacity_handling:
    if_missing: "skip"
    if_zero: "skip"
  track_capacity: true
  when_full: "exclude"

settings:
  priority: 3                        # after hospitals (4), before company (5)

fallback:
  strategy: "skip"
```
