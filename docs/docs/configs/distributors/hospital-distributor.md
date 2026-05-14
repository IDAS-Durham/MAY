# hospital_distributor.yaml

Assigns every agent to their nearest hospital as a registered medical facility (`medical_facility` activity key). No capacity tracking — all agents receive an assignment.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/hospital_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "hospital_distributor"
venue_type: "hospital"
activity_map_key: "medical_facility"   # written to medical_facility, not primary_activity
subset_key: "patient"

eligibility:
  require_unassigned: true             # skips people already holding medical_facility

venue_selection:
  consider_by: "count"
  count: 1                             # consider only the single closest hospital
  criteria: "closest"
  max_distance: 100
  max_distance_unit: "km"
  venue_geo_level: "SGU"
  distance_metric: "haversine"
  respect_capacity: false              # no capacity limit for hospital registration

allocation:
  strategy: "closest"
  track_capacity: false
  when_full: "overflow"                # always assigns, never blocked
  batch_by: "geo_unit"

settings:
  priority: 1

fallback:
  strategy: "assign_closest"           # always assigns even when constraints would exclude
```
