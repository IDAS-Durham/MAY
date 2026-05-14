# config.yaml

The master configuration file. Entry point for every simulation section — each top-level key either configures a subsystem directly or points to a subordinate YAML file.

**Topic:** [Configuration Reference](index.md)  
**Path:** `configs/2021/config.yaml` (or any path passed via `--config`)

---

## Overview

`config.yaml` is the single file passed to `create_world.py`. It wires together geography, population, venues, households, the timeline pipeline, relationship networks, and serialisation. Subsystems that need their own detailed schema (venues, households, distributors, etc.) are referenced by path and documented separately.

## Keys

| Key | Description |
|---|---|
| `geography` | Geography hierarchy and spatial filter |
| `population` | Population data source and mode |
| `venues` | Venue data directory and type catalogue |
| `households` | Household allocation configuration |
| `debug_outputs` | Optional auxiliary CSV exports |
| `timeline` | Ordered pipeline of attribute, distributor, and child-creator steps |
| `relationship_pipeline` | Social network construction |
| `romantic_relationships` | Sexual orientation and partnership assignment |
| `serialization` | HDF5 output path and field selection |

---

## `geography`

```yaml
geography:
  data_dir: "data/geography"
  levels: ["SGU", "MGU", "LGU"]
  load_all: false
  filter:
    level: LGU
    codes: ["Durham", "Gateshead"]
    file: "filters/my_codes.txt"
```

`data_dir` must contain `hierarchy.csv`, `coord_sgu.csv`, and `coord_mgu.csv`.

`levels` names the hierarchy from smallest to largest unit. Default is `["SGU", "MGU", "LGU"]`; any number of levels with any names are accepted (e.g. `["SGU", "MGU", "LGU", "XLGU"]` for a four-level hierarchy).

`load_all: true` loads every unit and ignores `filter`. When `false`, `filter` is applied.

`filter.level` must match one of the names in `levels`. `codes` is an inline list; `file` is a path to a text file with one code per line. When both are set, `file` takes precedence. If `level` is `null` or no codes are supplied, the filter is not applied and all units are loaded.

---

## `population`

Two modes are supported.

**Matrix mode** (default) — reads aggregated age–sex matrices:

```yaml
population:
  data_dir: "data/population"
  demographics_male_file: "demographics_male.csv"
  demographics_female_file: "demographics_female.csv"
```

Each CSV has rows indexed by geo unit and columns indexed by age (0–99).

**Explicit mode** — reads a pre-built individual-level CSV:

```yaml
population:
  type: "explicit"
  data_dir: "data/population"
  filename: "population.csv"
  column_mapping:
    age: "Age"
    sex: "Sex"
    Occode: "Occode"
```

**Explicit batch mode** — as above but reads multiple CSVs from `data_dir` rather than a single file:

```yaml
population:
  type: "explicit_batch"
  data_dir: "1911_data/population"
  column_mapping:
    age: "Age"
    sex: "Sex"
```

`column_mapping` maps engine attribute names to CSV column names. Any additional columns listed are loaded as per-person attributes. `filename` is required for `type: "explicit"` and ignored for `type: "explicit_batch"`.

---

## `venues`

```yaml
venues:
  data_dir: "data/venues"
  config_file: "configs/2021/venues/venues_config.yaml"
  export_file: "venue_allocations.csv"
```

`data_dir` is the root directory for all venue CSVs. `config_file` is the venue type catalogue — see [Venues Config](venues/venues-config.md). `export_file` is optional; when set, venue allocation results are written there.

---

## `households`

```yaml
households:
  enabled: true
  data_dir: "data/households"
  data_file: "households.csv"
  config_file: "configs/2021/households/households_config.yaml"
  strategy_file: "configs/2021/households/allocation_strategy.yaml"
  export_file: "household_allocations.csv"
```

`enabled: false` skips household allocation entirely.

`data_file` is a CSV of household composition counts per geo unit. `config_file` defines age categories and demotion/promotion rules — see [Households Config](households/households-config.md).

Three allocation modes are selected by which optional files are set:

| Mode | How to activate |
|---|---|
| Unified strategy (households + communal venues) | Set `strategy_file`; see [Allocation Strategy](households/allocation-strategy.md) |
| Household-only multi-round | Set `rounds_file`; set `strategy_file: null` |
| Single-pass (simple) | Set both `strategy_file` and `rounds_file` to `null` |

`export_file` is optional; when set, household allocation results are written there.

---

## `debug_outputs`

```yaml
debug_outputs:
  enabled: false
```

When `enabled: true`, the engine writes auxiliary CSVs during world creation: `household_allocations.csv`, `venue_allocations.csv`, `residence_venues.csv`, and `unallocated_people.csv`. These build large in-memory DataFrames — disable for country-scale runs.

---

## `timeline`

```yaml
timeline:
  enabled: true
  steps:
    - type: attribute
      config: "configs/2021/attributes/attribute_assignment.yaml"
    - type: distributor
      config: "configs/2021/distributors/school_distributor.yaml"
    - type: child_creator
      config: "configs/2021/venue_child_creators/school_classrooms.yaml"
```

`steps` is an ordered list executed top to bottom. Step `type` is one of:

| Type | Effect |
|---|---|
| `attribute` | Assigns a property to each eligible person |
| `distributor` | Places people into venues; writes to `activity_map` |
| `child_creator` | Sub-divides a parent venue into child venues |

Earlier steps get first pick of the population pool. Order is critical: education distributors must run before workplace assignment so the primary-activity filter works correctly.

See [Attribute Assignment](attributes/attribute-assignment.md), [Distributors](distributors/index.md), and [Venue Child Creators](venue-child-creators/index.md).

---

## `relationship_pipeline`

```yaml
relationship_pipeline:
  enabled: true
  relationships:
    - config: "configs/2021/relationships/social_networks.yaml"
```

Runs after venue assignment. Each entry in `relationships` builds one social network; multiple entries produce multiple independent networks. See [Social Networks](relationships/social-networks.md).

---

## `romantic_relationships`

```yaml
romantic_relationships:
  enabled: true
  config: "configs/2021/relationships/romantic_relationships.yaml"
```

Runs after household distribution and `relationship_pipeline`. Assigns sexual orientation and builds partnership networks. See [Romantic Relationships](relationships/romantic-relationships.md).

---

## `serialization`

```yaml
serialization:
  enabled: true
  config_file: "configs/2021/serialization_config.yaml"
  output_dir: "output/2021"
  filename: "world_state.h5"
  compression: "gzip"
  compression_level: 4
```

`config_file` controls which person and venue fields are written — see [Serialization Config](serialization/serialization-config.md). `output_dir` is created if absent. `filename` is overridden by `--filename` at the CLI.

`compression` is an HDF5 codec (`"gzip"` by default); omit to disable compression. `compression_level` controls gzip effort (default `4`).

---

## CLI Overrides

| Flag | Overrides |
|---|---|
| `--config PATH` | Path to this config file (default: `configs/2021/config.yaml`) |
| `--filename NAME` | `serialization.filename` |
| `--load-all` | Sets `geography.load_all: true` |
| `--lgu CODE[,CODE]` | `geography.filter` at LGU level |
| `--lgu-file PATH` | `geography.filter` at LGU level, codes from file |
| `--mgu CODE[,CODE]` | `geography.filter` at MGU level |
| `--mgu-file PATH` | `geography.filter` at MGU level, codes from file |
| `--sgu CODE[,CODE]` | `geography.filter` at SGU level |
| `--sgu-file PATH` | `geography.filter` at SGU level, codes from file |

CLI flags take precedence over config-file settings. `--lgu-file` takes precedence over `--lgu` when both are supplied.
