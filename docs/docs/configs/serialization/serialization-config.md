# serialization_config.yaml

Controls which fields are written to the HDF5 world-state file. Several fields are always written regardless of this config (see below). Everything else is opt-in.

**Always written — population:** `id`, `age`, `sex`, `geographical_unit`  
**Always written — venues:** `id`, `name`, `type`, `geographical_unit`, parent/child relationships  
**Always written — subsets:** `venue_id`, `subset_index`, `subset_name`, member list

**Topic:** [Serialisation](index.md)  
**Path:** `configs/2021/serialization_config.yaml`

---

## Keys

| Key | Description |
|---|---|
| `population` | Additional `person.properties` keys to include |
| `geography` | Coordinate export and additional `geographical_unit.properties` keys |
| `venues` | Global venue flags and per-type property lists |
| `subsets` | Additional subset properties (rarely needed) |
| `relationships` | Flags for activity map and hierarchy exports |
| `output` | HDF5 compression and metadata settings |

---

## `population`

```yaml
population:
  properties:
    - ethnicity
    - comorbidities
    - friendships
    - sexual_orientation
    - relationship_status
```

A list of keys from `person.properties` to include in the export. Any property assigned by an attribute YAML or social network builder may be listed here. Properties whose values are dicts or lists are serialised as JSON strings. Omitting a property from this list does not delete it from the world at runtime — it simply is not written to disk.

---

## `geography`

```yaml
geography:
  include_coordinates: true
  properties: []
```

`include_coordinates` — when `true`, writes `latitude` and `longitude` for each geographical unit. `properties` lists any additional keys from `geographical_unit.properties` to include; typically empty.

---

## `venues`

```yaml
venues:
  global:
    include_coordinates: true
    include_is_residence: true
  types:
    school:
      properties:
        - Gender
    company:
      properties:
        - work_sector
    classroom:
      properties:
        - capacity
```

`global` sets flags applied to all venue types: `include_coordinates` writes latitude/longitude where available; `include_is_residence` writes the `is_residence` flag.

`types` maps venue type names (matching keys in `venues_config.yaml`) to lists of CSV column names or venue properties to include. Any column loaded from the venue CSV may be listed. Child venue types (e.g. `classroom`, `office`) may also have entries here.

---

## `subsets`

```yaml
subsets:
  properties: []
```

Additional properties to write for each venue subset. Core attributes (venue reference, subset index, subset name, member list) are always written. This list is almost always empty.

---

## `relationships`

```yaml
relationships:
  include_activity_map: true
  include_venue_hierarchy: true
  include_geography_hierarchy: true
```

`include_activity_map` — writes each person's `activity_map` entries (person → venue links for each activity key). `include_venue_hierarchy` — writes parent → child venue links. `include_geography_hierarchy` — writes parent → child geography links. All three default to `true`; set `false` to reduce output size.

---

## `output`

```yaml
output:
  compression: "gzip"
  compression_level: 4
  include_metadata: true
  metadata:
    - random_seed
    - creation_timestamp
    - config_files_used
    - num_people
    - num_venues
    - num_geo_units
```

`compression` names the HDF5 compression codec; `"gzip"` is the standard choice. Omit for no compression. `compression_level` ranges from `0` (no compression) to `9` (maximum); `4` is a reasonable default balancing size and speed.

`include_metadata` — when `true`, writes a metadata group to the HDF5 file. `metadata` lists which fields to include; the available fields are `random_seed`, `creation_timestamp`, `config_files_used`, `num_people`, `num_venues`, and `num_geo_units`.
