# university_uni_years.yaml

Creates year-group child venues within universities. Ages 18–22 each receive their own group; ages 23+ are merged into a single mature-student group.

**Topic:** [Venue Child Creators](index.md)  
**Path:** `configs/2021/venue_child_creators/university_uni_years.yaml`

See [`school_classrooms.yaml`](school-classrooms.md) for the full venue child creator schema. The key difference here is the `attribute_mapping` block.

---

## Key-specific Notes

```yaml
parent_venue_type: university
child_venue_type: uni_groups_by_year

group_by_attribute: age

attribute_mapping:                    # maps each age value to a group label
  18: "18"
  19: "19"
  20: "20"
  21: "21"
  22: "22"
  default: "23_and_over"             # all ages not listed above fall into this group

max_capacity: 25
min_capacity: 1
child_properties:
  capacity: 25
distribution_strategy: even

activity_map_key: "primary_activity"
subset_key: "student"
replace_parent_activity: true
remove_from_parent: false
```
