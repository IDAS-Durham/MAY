# Venue Child Creators

**Topic:** [Venue Child Creators](index.md)  
**Paths:** `configs/2021/venue_child_creators/school_classrooms.yaml`, `company_offices.yaml`, `university_uni_years.yaml`

---

## Motivation

Many venues contain far more agents than would realistically interact in a single day. A company of 1,000 employees does not mean every employee interacts with every other employee — most only interact with a small group sharing the same office. Venue child creators address this by sub-dividing a large parent venue into smaller child venues after agents have been distributed to it. Each child venue holds a subset of the parent's members, and agents interact only within their assigned child.

This pattern applies wherever natural sub-groupings exist: school pupils grouped into classrooms by year and age, university students grouped into cohort-year groups, office workers split into rooms by headcount. The same config schema covers all cases.

---

## Keys

| Key | Description |
|---|---|
| `parent_venue_type` | Venue type to sub-divide |
| `child_venue_type` | Type name assigned to created child venues |
| `group_by_attribute` | Person attribute used to form groups before splitting; `null` to pool all members together |
| `attribute_mapping` | Optional remapping of attribute values to group labels; supports a `default` key for unmapped values |
| `max_capacity` | Maximum members per child venue; default `30` |
| `min_capacity` | Minimum members required to create a child venue; default `1` |
| `child_properties` | Dict of properties written to each created child venue |
| `distribution_strategy` | How members are spread across children: `"even"` or `"fill"` |
| `activity_map_key` | Activity key updated on each member when moved to a child venue |
| `subset_key` | Subset name the member is added to within the child venue |
| `replace_parent_activity` | Whether to replace the parent venue in the member's `activity_map` with the child |
| `remove_from_parent` | Whether to remove the member from the parent venue's subset |

---

## `parent_venue_type` and `child_venue_type`

```yaml
parent_venue_type: school
child_venue_type: classroom
```

`parent_venue_type` must match a key in `venues_config.yaml`. The engine iterates every venue of that type and creates child venues within it. `child_venue_type` is the type name assigned to each created child; this name appears in serialisation config and can be used in distributor configs.

---

## `group_by_attribute` and `attribute_mapping`

```yaml
# Schools: group pupils by age, one classroom set per age
group_by_attribute: age

# Universities: group students by age with custom label mapping
group_by_attribute: age
attribute_mapping:
  18: "18"
  19: "19"
  20: "20"
  21: "21"
  22: "22"
  default: "23_and_over"

# Offices: no grouping — all employees in one pool
group_by_attribute: null
```

When `group_by_attribute` is set, members are sorted into groups by that attribute value before children are created. Each distinct value (or mapped label) receives its own set of child venues. Set to `null` to skip grouping — all members are pooled together and split purely by capacity.

`attribute_mapping` remaps raw attribute values to group labels. Values not listed fall into the `default` group. This is used in the university config to merge all ages above 22 into a single mature-student group, avoiding many near-empty venues for ages rarely seen in universities. Omit `attribute_mapping` to use raw attribute values as group keys.

---

## `max_capacity`, `min_capacity`, and `child_properties`

```yaml
max_capacity: 30
min_capacity: 1
child_properties:
  capacity: 30
```

`max_capacity` is the ceiling on members per child venue. If a group has more members than this, multiple child venues are created. `min_capacity` sets the floor: groups with fewer members are not given a child venue — those members remain in the parent. `child_properties` is a dict of properties written to every created child venue; typically used to record the capacity ceiling on the venue object.

---

## `distribution_strategy`

```yaml
distribution_strategy: even
```

Controls how members within a group are spread across child venues. `"even"` distributes members as equally as possible across all children for that group. `"fill"` fills the first child to `max_capacity` before creating and filling the next. Use `"even"` when all children should have similar sizes; use `"fill"` to minimise partially-filled venues.

---

## `activity_map_key`, `subset_key`, `replace_parent_activity`, `remove_from_parent`

```yaml
activity_map_key: "primary_activity"
subset_key: "student"
replace_parent_activity: true
remove_from_parent: false
```

After a child venue is created, the engine updates each member's `activity_map` and subset membership. `activity_map_key` names the activity entry to write; if `None`, the child venue type name is used. `subset_key` is the subset the member is added to within the child venue.

`replace_parent_activity` — when `true` — overwrites the parent venue's entry in `activity_map` with the child, so the member's primary activity now points to the classroom rather than the school. `remove_from_parent` — when `true` — removes the member from the parent venue's subset; when `false`, the member remains in both parent and child subsets, which allows queries such as "all students at this school" to still work after classroom assignment.

---

## Examples by venue type

| Config file | Parent → Child | `group_by_attribute` | `max_capacity` | `subset_key` |
|---|---|---|---|---|
| `school_classrooms.yaml` | school → classroom | `age` | 30 | `student` |
| `university_uni_years.yaml` | university → uni_groups_by_year | `age` (with mapping) | 25 | `student` |
| `company_offices.yaml` | company → office | `null` | 50 | `worker` |
