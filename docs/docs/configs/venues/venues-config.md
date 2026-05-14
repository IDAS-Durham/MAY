# venues_config.yaml

Catalogue of all venue types the engine will load. Each entry under `venue_types` defines one type; the name is the key used throughout distributor and serialization configs.

**Topic:** [Venues](index.md)  
**Path:** `configs/2021/venues/venues_config.yaml`

---

## Full Schema

```yaml
# ============================================================
# GLOBAL SETTINGS
# ============================================================
settings:
  filter_by_geography: true     # true  → only load venues whose geo_unit is in the
                                #          loaded geographical hierarchy
                                # false → load all venues regardless of geography


# ============================================================
# VENUE TYPES
# ============================================================
venue_types:

  {venue_type_name}:            # arbitrary key; used as venue_type in distributors

    enabled: true | false       # false → skip loading this type entirely

    description: "..."          # optional — human-readable label

    is_residence: false         # true → agents live here (affects household pipeline)

    # ----------------------------------------------------------
    # Standard CSV loading (default mode)
    # ----------------------------------------------------------
    filename: "path/to/file.csv"   # optional — path under venues.data_dir
                                   # default: {venue_type_name}s.csv

    # ----------------------------------------------------------
    # Batch mode loading (alternative)
    # Used when all venue types share a single CSV, distinguished by a column value.
    # ----------------------------------------------------------
    batch_mode: true               # optional — enables batch loading
    filter_column: "BTCode"        # column in the shared CSV to filter on
    filter_values: ["C", "D"]      # rows whose filter_column matches any of these
                                   # values are loaded as this venue type

    subset_key: "resident"         # optional — default subset name assigned to
                                   # residents of this venue (used by distributors)

    subset_categories:             # optional — define named age/attribute subsets
      - name: "Kids"               # subset label
        attribute: "age"           # person attribute to filter on
        type: "numerical"          # "numerical" | "categorical"
        numerical:
          min: 0
          max: 17                  # null → no upper bound

    # ----------------------------------------------------------
    # Capacity configuration
    # ----------------------------------------------------------
    capacity_config:

      total_capacity_column: "capacity"
                                   # CSV column holding total capacity for this venue
                                   # used as hard ceiling when track_capacity is true

      # -- Attribute-aware capacity (optional) --
      # Breaks total capacity into age/sex slots defined in the CSV.
      attribute_capacities:

        filter_attributes:         # attributes used to match a person to a slot
          - name: "age"
            type: "age_band"       # "age_band" | "categorical"
          - name: "sex"
            type: "categorical"

        column_mappings:           # maps CSV column → attribute values for that slot
          age_50_64_male:
            age_band: [50, 64]     # inclusive [min, max]
            sex: "male"
          age_50_64_female:
            age_band: [50, 64]
            sex: "female"
          # ... one entry per CSV capacity column

      # -- Hard per-person attribute constraints (optional) --
      # Prevents a person being placed here unless their attribute falls
      # within the range defined by CSV columns on the venue.
      attribute_constraints:
        age:
          min_column: "StatutoryLowAge"   # CSV column holding per-venue minimum
          max_column: "StatutoryHighAge"  # CSV column holding per-venue maximum
                                          # both bounds are inclusive

      fallback_strategy: "flexible" | "strict" | "total_capacity"
                                   # behaviour when a specific age/sex slot is full:
                                   # "flexible"       → overflow into other slots
                                   # "strict"         → reject person if slot full
                                   # "total_capacity" → use total_capacity_column only,
                                   #                    ignore per-slot breakdowns
```

---

## Minimal Examples

**Simple venue (no capacity tracking):**
```yaml
venue_types:
  pub:
    enabled: true
    filename: leisure/pubs.csv
    is_residence: false
```

**Venue with total capacity only:**
```yaml
venue_types:
  school:
    enabled: true
    filename: primary_activities/Schools_EW.csv
    capacity_config:
      total_capacity_column: "SchoolCapacity"
```

**Residence with attribute-aware slots:**
```yaml
venue_types:
  care_home:
    enabled: true
    filename: residences/care_homes.csv
    is_residence: true
    capacity_config:
      total_capacity_column: "capacity"
      attribute_capacities:
        filter_attributes:
          - name: "age"
            type: "age_band"
          - name: "sex"
            type: "categorical"
        column_mappings:
          age_65_74_male:
            age_band: [65, 74]
            sex: "male"
          age_65_74_female:
            age_band: [65, 74]
            sex: "female"
      fallback_strategy: "total_capacity"
```

**Batch-mode venue (shared CSV, filter by column):**
```yaml
venue_types:
  church:
    enabled: true
    batch_mode: true
    filter_column: "BTCode"
    filter_values: ["CH"]
    is_residence: false
```
