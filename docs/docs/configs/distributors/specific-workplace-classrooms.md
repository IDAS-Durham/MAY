# specific_workplace_classrooms_distributor.yaml

Assigns P-sector (Education) workers to classrooms as their workplace. Each classroom has a fixed capacity of 1 teacher.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/specific_workplace_classrooms_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "specific_workplace_classrooms_distributor"
venue_type: "classroom"              # child venues created by school_classrooms.yaml
activity_map_key: "primary_activity"
subset_key: "worker"

eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "properties.work_sector"
      type: "categorical"
      values: ["P"]                  # only P (Education) sector

venue_selection:
  consider_by: "geo_unit"
  venue_geo_level: "LGU"
  person_location_attribute: "properties.workplace_sgu"

allocation:
  strategy: "random"
  fixed_capacity: 1                  # one teacher per classroom; no CSV column needed
  track_capacity: true
  when_full: "exclude"

settings:
  priority: 3

fallback:
  strategy: "skip"
```
