# company_offices.yaml

Creates office child venues within companies. All employees are grouped together (no attribute grouping) and split into offices of `max_capacity`.

**Topic:** [Venue Child Creators](index.md)  
**Path:** `configs/2021/venue_child_creators/company_offices.yaml`

See [`school_classrooms.yaml`](school-classrooms.md) for the full venue child creator schema.

---

## Key-specific Notes

```yaml
parent_venue_type: company
child_venue_type: office

group_by_attribute: null              # no grouping — all employees in same pool

max_capacity: 50
min_capacity: 1
child_properties:
  capacity: 50
distribution_strategy: even

activity_map_key: "primary_activity"
subset_key: "worker"
replace_parent_activity: true
remove_from_parent: false
```
