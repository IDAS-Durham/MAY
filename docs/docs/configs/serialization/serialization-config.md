# serialization_config.yaml

Specifies which fields are written to `world_state.h5`. Core attributes (agent id, age, sex, geo unit; venue id, name, type, geo unit) are always included. All other fields are opt-in.

**Topic:** [Serialization](index.md)  
**Path:** `configs/2021/serialization_config.yaml`

---

## Full Schema

```yaml
# ============================================================
# POPULATION
# ============================================================
# Core attributes always written: id, age, sex, geographical_unit

population:
  properties:               # additional keys from person.properties to include
    - ethnicity
    - comorbidities
    - work_mode
    - friendships
    - sexual_orientation
    - cohabiting_couple
    - romantic_partners
    - relationship_status
    # Any property assigned via attribute YAMLs may be listed here.
    # Dict/list values are serialised as JSON strings.


# ============================================================
# GEOGRAPHY
# ============================================================
# Core attributes always written: id, name, level, parent/child relationships

geography:
  include_coordinates: true     # true → write latitude/longitude for each geo unit
  properties: []                # additional keys from geographical_unit.properties


# ============================================================
# VENUES
# ============================================================
# Core attributes always written for ALL venues:
#   id, name, type, geographical_unit, parent/child relationships

venues:
  global:
    include_coordinates: true       # true → write lat/lon for venues that have them
    include_is_residence: true      # true → write is_residence flag

  types:                            # per venue-type property lists
    {venue_type_name}:              # must match a key in venues_config.yaml
      properties:
        - column_name               # CSV column or venue property to include
        # Any column loaded from the venue CSV may be listed here.


# ============================================================
# SUBSETS
# ============================================================
# Core attributes always written: venue reference, subset_index,
# subset_name, members list

subsets:
  properties: []                # additional subset properties (rarely needed)


# ============================================================
# RELATIONSHIPS
# ============================================================
relationships:
  include_activity_map: true        # write person → venue activity_map entries
  include_venue_hierarchy: true     # write venue parent → child links
  include_geography_hierarchy: true # write geography parent → child links


# ============================================================
# OUTPUT SETTINGS
# ============================================================
output:
  compression: "gzip"               # optional — HDF5 compression codec; omit for none
  compression_level: 4              # optional — 0 (none) to 9 (maximum); default 4

  include_metadata: true            # optional — write a metadata group to the HDF5

  metadata:                         # optional — which metadata fields to write
    - random_seed
    - creation_timestamp
    - config_files_used
    - num_people
    - num_venues
    - num_geo_units
```
