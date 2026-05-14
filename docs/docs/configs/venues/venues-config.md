# venues_config.yaml

Catalogue of all venue types the engine will load. Each named entry under `venue_types` defines one type; the name is the key used throughout distributor and serialisation configs.

**Topic:** [Venues](index.md)  
**Path:** `configs/2021/venues/venues_config.yaml`

---

## Keys

| Key | Description |
|---|---|
| `settings` | Global loading options applied to all venue types |
| `venue_types` | Dict of venue type definitions, keyed by venue type name |

---

## `settings`

```yaml
settings:
  filter_by_geography: true
```

`filter_by_geography` — when `true`, only venues whose `geo_unit` column matches a unit in the loaded geographical hierarchy are created. Set `false` to load all venues in the CSV regardless of geography. Defaults to `true`.

---

## `venue_types`

Each entry under `venue_types` uses the venue type name as its key. That name is referenced throughout distributor configs (`venue_type:`), serialisation config, and allocation strategy venue steps. The following sub-keys are available on each entry.

---

### Core keys

```yaml
venue_types:
  hospital:
    enabled: true
    filename: "medical/hospitals.csv"
    description: "Healthcare facilities"
    is_residence: false
```

`enabled` — set `false` to skip loading this venue type entirely; the type still exists in the registry but contains no venues. `filename` is the path to the CSV under `venues.data_dir`; if omitted, the engine defaults to `{venue_type_name}s.csv` in `data_dir`. `description` is a human-readable label for logging. `is_residence` marks whether agents live here; this affects how the household pipeline treats residents and is stored on each venue object.

---

### Batch mode loading

```yaml
venue_types:
  church:
    enabled: true
    batch_mode: true
    filter_column: "BTCode"
    filter_values: ["CH"]
    is_residence: false
    subset_key: "priest"
```

When `batch_mode: true`, venues of this type are loaded from a shared CSV (the same file used by other batch-mode types in the same config) rather than from a type-specific file. `filter_column` names the CSV column used to distinguish types; `filter_values` is the list of values in that column that belong to this venue type. Rows not matching any listed value are ignored for this type.

`subset_key` is an optional default subset name attached to the venue. For residence types, this becomes the subset that residents are placed into during allocation. `subset_categories` (less common) defines named age-band slots directly on the venue — used in the 1911 configs where household composition is encoded in the venue CSV rather than derived from a separate file.

---

### Capacity config — total capacity

```yaml
venue_types:
  school:
    capacity_config:
      total_capacity_column: "SchoolCapacity"
```

`total_capacity_column` names the CSV column holding the venue's total capacity. When a distributor has `track_capacity: true`, the engine reads this column and prevents allocation once the count is reached. If the column is missing or zero on a given venue, the distributor's `capacity_handling` settings determine what happens (ignore, skip, or use a default).

---

### Capacity config — attribute-aware slots

```yaml
venue_types:
  care_home:
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

Attribute-aware capacity breaks the total into demographic slots, each mapped to a CSV column. The engine reads `total_capacity_column` as an overall ceiling, then uses `column_mappings` to direct people into specific slots. Each mapping entry names a CSV column and specifies the attribute criteria (`age_band` with inclusive `[min, max]` bounds, and/or a `categorical` attribute value) that a person must match to fill that slot.

`filter_attributes` declares which person attributes the engine inspects when matching slots — typically `age` with type `"age_band"` and `sex` with type `"categorical"`. This block is only needed for slot matching; it does not filter eligibility.

`fallback_strategy` controls what happens when a specific slot is full:
- `"flexible"` — overflow into other age/sex slots as long as total capacity allows.
- `"strict"` — reject the person if their exact slot is full.
- `"total_capacity"` — ignore per-slot limits entirely and use only the total capacity ceiling.

---

### Capacity config — attribute constraints

```yaml
venue_types:
  boarding_school:
    capacity_config:
      attribute_constraints:
        age:
          min_column: "StatutoryLowAge"
          max_column: "StatutoryHighAge"
```

Attribute constraints prevent a person being placed in a venue if their attribute value falls outside the range defined by per-venue CSV columns. Unlike slot capacity (which limits *how many* people of a given type), constraints control *who is eligible at all*. `min_column` and `max_column` name CSV columns on the venue; the engine reads those values from the venue's properties and checks the person's attribute against them. Both bounds are inclusive. Either `min_column` or `max_column` may be omitted to apply only a one-sided constraint.
