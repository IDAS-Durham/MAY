# config.yaml

The master configuration file. Entry point for all simulation sections — each top-level key either configures a subsystem directly or points to a subordinate YAML file.

**Path:** `configs/2021/config.yaml` (or any path passed via `--config`)

---

## Full Schema

```yaml
# ============================================================
# GEOGRAPHY
# ============================================================
geography:
  data_dir: "data/geography"          # directory containing hierarchy.csv,
                                      # coord_sgu.csv, coord_mgu.csv
  levels: ["SGU", "MGU", "LGU"]      # hierarchy level names, smallest → largest
                                      # any number of levels; names are arbitrary
                                      # example 4-level: ["SGU","MGU","LGU","XLGU"]

  load_all: false                     # true  → load every unit, ignore filter below
                                      # false → apply filter

  filter:                             # optional — omit entirely if load_all: true
    level: LGU                        # which level the filter codes belong to
                                      # must match one of the names in `levels`
    codes: ["Durham", "Gateshead"]    # optional — inline list of codes
    file: "filters/my_codes.txt"      # optional — path to file, one code per line
                                      # if both codes and file are set, file wins


# ============================================================
# POPULATION
# ============================================================
population:
  # --- Standard matrix mode (default) ---
  data_dir: "data/population"
  demographics_male_file: "demographics_male.csv"    # rows=geo_unit, cols=ages 0-99
  demographics_female_file: "demographics_female.csv"

  # --- Explicit batch mode (alternative) ---
  # Use when the population is supplied as an individual-level CSV
  # rather than aggregated age-sex matrices.
  type: "explicit_batch"              # optional — omit for standard matrix mode
  filename: "population.csv"          # optional — path to individual-level CSV
  column_mapping:                     # optional — map engine attribute names to CSV columns
    age: "Age"
    sex: "Sex"
    Occode: "Occode"                  # any additional per-person attributes to load


# ============================================================
# VENUES
# ============================================================
venues:
  data_dir: "data/venues"             # root directory for all venue CSVs
  config_file: "configs/2021/venues/venues_config.yaml"  # venue type catalogue
  export_file: "venue_allocations.csv"                   # optional — debug output path


# ============================================================
# HOUSEHOLDS
# ============================================================
households:
  enabled: true                       # false → skip household allocation entirely

  data_dir: "data/households"
  data_file: "households.csv"         # composition counts per geo_unit

  config_file: "configs/2021/households/households_config.yaml"
                                      # age categories + demotion/promotion rules

  # Choose one allocation mode:
  strategy_file: "configs/2021/households/allocation_strategy.yaml"
                                      # unified strategy (households + communal venues)
  # rounds_file: "allocation_rounds.yaml"
                                      # optional — household-only multi-round mode
                                      # set strategy_file to null to activate

  export_file: "household_allocations.csv"  # optional — debug output path


# ============================================================
# DEBUG OUTPUTS
# ============================================================
debug_outputs:
  enabled: false                      # true → write auxiliary CSVs during world creation
                                      # files: household_allocations.csv,
                                      #        venue_allocations.csv,
                                      #        residence_venues.csv,
                                      #        unallocated_people.csv
                                      # disable for large (country-scale) runs


# ============================================================
# TIMELINE
# ============================================================
timeline:
  enabled: true

  steps:                              # ordered list — executed top to bottom
    - type: attribute                 # assign a property to people
      config: "configs/2021/attributes/attribute_assignment.yaml"

    - type: distributor               # place people into venues
      config: "configs/2021/distributors/school_distributor.yaml"

    - type: child_creator             # sub-divide a venue into child venues
      config: "configs/2021/venue_child_creators/school_classrooms.yaml"

    # Add, remove, or reorder steps freely.
    # Earlier steps get first pick of the population pool.


# ============================================================
# RELATIONSHIP PIPELINE
# ============================================================
relationship_pipeline:
  enabled: true                       # false → skip all social network building

  relationships:                      # list of network configs to build, in order
    - config: "configs/2021/relationships/social_networks.yaml"
    # - config: "configs/other_network.yaml"


# ============================================================
# ROMANTIC RELATIONSHIPS
# ============================================================
romantic_relationships:
  enabled: true                       # false → skip orientation + partnership assignment
  config: "configs/2021/relationships/romantic_relationships.yaml"


# ============================================================
# SERIALIZATION
# ============================================================
serialization:
  enabled: true

  config_file: "configs/2021/serialization_config.yaml"
                                      # controls which fields are written to HDF5

  output_dir: "output/2021"           # directory for output file; created if absent
                                      # use "." for project root
  filename: "world_state.h5"          # HDF5 output filename
                                      # overridden by --filename CLI flag if supplied

  compression: "gzip"                 # optional — HDF5 compression codec
                                      # omit for no compression
```

---

## CLI Overrides

The following flags override config-file settings when passed to `create_world.py`:

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
