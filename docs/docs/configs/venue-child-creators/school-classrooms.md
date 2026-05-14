# school_classrooms.yaml

Creates classroom child venues within schools by grouping students by age, then splitting each age group into rooms of `max_capacity`.

**Topic:** [Venue Child Creators](index.md)  
**Path:** `configs/2021/venue_child_creators/school_classrooms.yaml`

---

## Full Schema

```yaml
parent_venue_type: school             # venue type to sub-divide
child_venue_type: classroom           # type name for created child venues

group_by_attribute: age               # optional — group members by this attribute before
                                      # creating children; null → all members together

# -- Custom attribute mapping (optional) --
# Maps attribute values to group labels. Values not listed use `default`.
attribute_mapping:
  18: "18"
  19: "19"
  default: "23_and_over"

max_capacity: 30                      # maximum members per child venue
                                      # if a group exceeds this, multiple children are created

min_capacity: 1                       # minimum members to justify creating a child venue
                                      # groups smaller than this are skipped

child_properties:                     # optional — properties written to each created child venue
  capacity: 30

distribution_strategy: even           # "even" — distribute members evenly across children
                                      # "fill" — fill each child to max before creating the next

# ============================================================
# ACTIVITY MANAGEMENT
# ============================================================
activity_map_key: "primary_activity"  # activity key updated on each member

subset_key: "student"                 # subset name the member is added to in the child venue

replace_parent_activity: true         # true  → replace the parent venue in the member's
                                      #          activity_map with the child venue
                                      # false → keep both parent and child in activity_map

remove_from_parent: false             # true  → remove member from parent venue's subset
                                      # false → keep member in parent subset for reference
```
