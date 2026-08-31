# User guide: building a world with `create_world.py`

This guide is for anyone who wants to generate a synthetic population world
(England 2021, say) by editing configuration files and input data, without
touching Python.

Three things drive the whole pipeline:

1. YAML config files in `configs/` control what the simulation does and how.
2. CSV data files in `data/` provide the raw inputs: geography, demographics, venues and so on.
3. One command, `python create_world.py`, runs everything end to end and writes `world_state.h5`.

---

## 1. Environment setup

Run this project in an isolated Python environment, so its dependencies (numba, numpy, pandas, scipy, h5py, PyYAML) stay clear of anything else on your machine. You only need to set this up once.

The project requires Python 3.13+. Pick whichever environment manager you already use.

### Option A: Conda (recommended)

```bash
# Create the environment
conda create -n MayEnv python=3.13 -y

# Activate it (do this every time you open a new terminal)
conda activate MayEnv

# Install dependencies
pip install -r requirements.txt
```

### Option B: `venv` (built into Python)

```bash
# Create the environment in a local .venv folder
python3.13 -m venv .venv

# Activate it (every new terminal)
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows PowerShell

# Install dependencies
pip install -r requirements.txt
```

### Verifying the environment

After activation, run:

```bash
python --version          # should report 3.13.x
pip list | grep -E "numba|numpy|pandas|scipy|h5py|PyYAML"
```

All six packages should appear at the versions pinned in `requirements.txt`. If anything is missing or mismatched, re-run `pip install -r requirements.txt`.

> Activate the environment in every new terminal session before running `python create_world.py`. Forget, and you get either the wrong Python version or a `ModuleNotFoundError`.

### Downloading the input data

The repository ships with code and configs, but not the bulky census and venue CSVs that live under `data/`. Fetch them with:

```bash
python scripts/get_data.py
```

This downloads `data_may.zip` from the project's data server, unpacks it into
`data/`, and cleans up after itself. You only need to do this once (or whenever
the upstream dataset is refreshed).

It uses only the standard library, so it runs the same way on Windows, macOS and
Linux. If `data/` already exists and is not empty the script stops, so pass
`--force` when you want it replaced.

On macOS and Linux, `bash scripts/get_data.sh` does the same thing.

---

## 2. Quick start

Once the environment is active you can run the model. The shipped default builds
County Durham and Darlington, two local authorities in North East England sized
to run on a laptop, rather than the whole country. §10 shows how to widen it.

```bash
# Run with the default config (configs/2021/config.yaml)
python create_world.py

# Or point at a custom config
python create_world.py --config configs/2021/config.yaml

# Override the output filename
python create_world.py --filename my_world.h5
```

CLI arguments:

| Flag | Default | Description |
|---|---|---|
| `--config` | `configs/2021/config.yaml` | Path to the master config file. |
| `--filename` | *(see below)* | Output HDF5 filename. Overrides `serialization.filename` in config. Falls back to `world_state.h5` if neither is set. |

### Output path

The output location is controlled by two keys in the `serialization:` section of `config.yaml`:

```yaml
serialization:
  enabled: true
  config_file: "${config_root}/serialization_config.yaml"
  output_dir: "${output_root}/2021"   # directory; created automatically if absent
  filename: "world_state.h5"          # filename within that directory
```

`${config_root}` and `${output_root}` are path variables, described in §4.0. The
default 2021 config writes to `output/2021/world_state.h5`. Passing `--filename`
on the command line takes precedence over `serialization.filename` in the config,
while `output_dir` always comes from the config.

When the run finishes you will have:

- `output/2021/world_state.h5`, holding the serialized world: people, geography, venues and relationships. Everything else is derived from this file.

---

## 3. The two folders you edit

```
MAY/
├── configs/   ← edit YAMLs to change behaviour, scope, scenarios
└── data/      ← edit CSVs to change the input statistics / locations
```

Everything else (`may/`, `create_world.py`) is the engine, and you should not need to touch any Python code.

The `configs/` folder contains a subdirectory for each world scenario, and you can edit any file under it. The rest of this guide focuses on `configs/2021/`, the modern-day UK world. §5 describes what else lives in `configs/`.

---

## 4. The master config: `configs/2021/config.yaml`

`configs/2021/config.yaml` is the single entry point. It points to all the other YAMLs and tells the engine which steps to run. Open it and edit in place.

The shipped file builds County Durham and Darlington from the England+Wales data
files, and everything below describes that config as it ships.

### 4.0 Path variables: `${data_root}`, `${config_root}`, `${output_root}`

Paths in the configs are not written out in full. Three variables are declared at
the top of `config.yaml` and substituted everywhere:

```yaml
# config_root: /absolute/path/to/configs/2021   # optional; defaults to this file's directory
data_root: data                                  # set to an absolute path for collaboration
# output_root: /absolute/path/to/output          # optional; defaults to {CWD}/output
```

| Variable | Default | Used for |
|---|---|---|
| `${config_root}` | the directory holding `config.yaml` | Pointers to the other YAMLs (`${config_root}/venues/venues_config.yaml`). |
| `${data_root}` | `data` | Every CSV path (`${data_root}/geography`). |
| `${output_root}` | `{CWD}/output` | Where the HDF5 and debug files land. |

Set `data_root` to an absolute path when several people share one data directory.
Every example below shows the real form used in the shipped configs, so what you
read here matches what you see when you open the file.

The rest of `config.yaml` divides into the sections that follow.

### 4.1 `geography:` sets which area to build

| Key | What it does |
|---|---|
| `data_dir` | Base folder the file paths below resolve against. |
| `hierarchy_file` | The hierarchy CSV. Takes a single path, or a list of paths that the engine stacks into one table (the UK build lists one file per nation). |
| `coord_files` | Mapping of level → coordinate CSV(s), same path-or-list rule. Omit a level to load it without coordinates. |
| `levels` | Names of the geographical hierarchy levels, smallest → largest. The UK build uses `["SGU", "MGU", "LGU", "XLGU"]` (Output Area → MSOA → Local Authority → Region/Nation). |
| `load_all` | `true` to build the entire dataset, `false` to use the filter below. |
| `filter.level` | Which level the filter applies to (`SGU`, `MGU`, `LGU`, `XLGU`). |
| `filter.codes` | Inline list of codes to include (small lists). |
| `filter.file` | Path to a text file with one code per line (large lists). |

When several files are listed, they must all exist and share the same columns, and no
unit may appear in two files. Any violation stops the run with a message naming the
offending files. A filter can span files freely (e.g. one English and one Scottish LAD).

**What ships: County Durham and Darlington.** Only the England+Wales files are
listed; the Scotland (`SCT_*`) and Northern Ireland (`NI_*`) files sit beside
them in `data/geography/` and are simply not loaded.

```yaml
geography:
  data_dir: "${data_root}/geography"
  levels: ["SGU", "MGU", "LGU", "XLGU"]   # OA -> MSOA -> LAD -> Region
  hierarchy_file: EW_hierarchy.csv
  coord_files:
    SGU: EW_coord_sgu.csv
    MGU: EW_coord_mgu.csv
  load_all: false
  filter:
    level: LGU
    codes: ["County Durham", "Darlington"]
```

**Building the whole UK.** Add the other two nations' files to each key:

```yaml
geography:
  data_dir: "${data_root}/geography"
  levels: ["SGU", "MGU", "LGU", "XLGU"]
  hierarchy_file: [EW_hierarchy.csv, SCT_hierarchy.csv, NI_hierarchy.csv]
  coord_files:
    SGU: [EW_coord_sgu.csv, SCT_coord_sgu.csv, NI_coord_sgu.csv]
    MGU: [EW_coord_mgu.csv, SCT_coord_mgu.csv, NI_coord_mgu.csv]
  load_all: true
```

**Building only London:**
```yaml
geography:
  load_all: false
  filter:
    level: XLGU
    codes: ["London"]
```
London sits in `EW_hierarchy.csv`, which the default `hierarchy_file` already
lists. The filter selects from the geography those files hold, so the files
listed set the ceiling and the filter chooses within it.

### 4.2 `population:` supplies the demographics

What ships (England+Wales only, matching the geography above):

```yaml
population:
  data_dir: "${data_root}/population"
  demographics_male_file: EW_demographics_male.csv
  demographics_female_file: EW_demographics_female.csv
```

For a UK build, list all three per nation:

```yaml
  demographics_male_file: [EW_demographics_male.csv, SCT_demographics_male.csv, NI_demographics_male.csv]
  demographics_female_file: [EW_demographics_female.csv, SCT_demographics_female.csv, NI_demographics_female.csv]
```

The CSVs are matrices: rows = SGU codes, columns = ages 0-99. Each key takes a single
file or a list to stack (same columns, disjoint SGUs). Every SGU in the loaded
geography must have a row in the stacked data, or the run stops naming the gaps.

### 4.3 `venues:` lists the places people go

```yaml
venues:
  data_dir: "${data_root}/venues"
  config_file: "${config_root}/venues/venues_config.yaml"   # which venue types to load
```
See **§5.1** to enable/disable venue types and §6 for the CSVs they read.

### 4.4 `households:` decides where people live

What ships:

```yaml
households:
  data_dir: "${data_root}/households"
  data_file: EW_households.csv
  config_file: "${config_root}/households/households_config.yaml"   # age categories + demotion rules
  rules_file: "${config_root}/households/relationship_rules.yaml"   # couple/family pair matching
```

For a UK build, stack all three and set the column policy:

```yaml
  data_file: [EW_households.csv, SCT_households.csv, NI_households.csv]
  # NI's composition columns differ from EW/SCT; union them, absent = zero.
  column_policy: union_zero_fill
```

`data_file` takes a single file or a list to stack. By default all files must share
the same composition-pattern columns; `column_policy: union_zero_fill` lets files
with different vocabularies combine, so a pattern absent from a file counts as zero
households of that shape in its areas, and each fill is logged as a warning.

> **Set `rules_file` whenever you want relationship rules.** The key switches them
> on: with it, every parent-child age gap and couple-compatibility rule in
> `relationship_rules.yaml` applies; without it they are disabled and households
> are built on composition patterns alone.

**Where the allocation strategy is configured.** In the timeline. Which strategy
runs, and *where in the run* it runs, is owned by the `residence_allocation` step
(§4.5), whose `config:` points at `allocation_strategy.yaml`. That keeps one
source of truth for allocation ordering.

### 4.5 `timeline:` fixes the order things happen

The `timeline.steps` list is the **execution order** of the entire simulation. Each step is one of:

- `type: residence_allocation` runs the household allocation strategy, placing everyone into households and communal residences (care homes, boarding schools, dorms). Its `config:` points at `households/allocation_strategy.yaml`.
- `type: attribute` assigns a property to people, such as ethnicity, comorbidities or work sector.
- `type: distributor` places people into venues: school, hospital, company, leisure.
- `type: child_creator` subdivides a venue, turning a school into classrooms or a company into offices.

Each step references a YAML in `configs/2021/households/`, `configs/2021/attributes/`, `configs/2021/distributors/`, or `configs/2021/venue_child_creators/`.

**Every config must include a `residence_allocation` step.** It is the only way
households get built; a timeline without one aborts the run with an explicit
error rather than producing a world with no homes. In the shipped config it is
step 0:

```yaml
timeline:
  enabled: true
  steps:
    - type: residence_allocation
      config: "${config_root}/households/allocation_strategy.yaml"
    - type: attribute
      config: "${config_root}/attributes/attribute_assignment.yaml"
    # ...
```

Move it later only if a residence allocation needs an attribute assigned by an
earlier step.

**To skip a step**, comment it out. **To reorder**, move the YAML block. Order matters. In the default pipeline, schools and universities are assigned before workplaces, because workplace assignment skips anyone who already has a `primary_activity`. That is how things are wired right now. With enough tinkering across the related YAMLs (eligibility filters, attribute dependencies, `require_unassigned` and so on) the steps can in principle be reordered to suit a different scenario, but the order documented here is what ships.

### 4.6 `relationship_pipeline:`, `romantic_relationships:`, and `serialization:`

**`relationship_pipeline:`** builds social networks after venues are assigned. It takes a `relationships:` list; each entry points to a network config YAML. Set `enabled: false` to skip all networks.

```yaml
relationship_pipeline:
  enabled: true
  relationships:
    - config: "${config_root}/relationships/social_networks.yaml"
    # add further network configs here
```

**`romantic_relationships:`** builds sexual orientation and partnership networks. Set `enabled: false` to skip.

```yaml
romantic_relationships:
  enabled: true
  config: "${config_root}/relationships/romantic_relationships.yaml"
```

**`serialization:`** controls where the output HDF5 is written and which serialization config to use.

```yaml
serialization:
  enabled: true
  config_file: "${config_root}/serialization_config.yaml"
  output_dir: "${output_root}/2021"
  filename: "world_state.h5"
```

---

## 5. The other YAMLs, and what each folder controls

```
configs/
├── 2021/                             # modern-day UK world (this guide)
│   ├── config.yaml                       # master config (above)
│   ├── serialization_config.yaml         # what gets exported to world_state.h5
│   ├── venues/venues_config.yaml         # venue types catalogue
│   ├── households/
│   │   ├── households_config.yaml        # age categories + demotion/promotion rules
│   │   ├── allocation_strategy.yaml      # household allocation order
│   │   └── relationship_rules.yaml       # how people inside a household relate
│   ├── attributes/                       # one YAML per attribute to assign
│   ├── distributors/                     # one YAML per venue distributor
│   ├── venue_child_creators/             # rules to break venues into sub-venues
│   └── relationships/
│       ├── social_networks.yaml
│       └── romantic_relationships.yaml
└── 1911/                             # example configs for building a portion of the UK in 1911
    └── *.yaml                            # flat layout, no subfolders
```

`configs/2021/` also holds two alternative master configs beside `config.yaml`:
`config_uk_test.yaml` (four-nation build, stacking all three per-nation files
under each key) and `config_commute_test.yaml`. Point `--config` at either to run
them.

`configs/1911/` is a separate world. Its structure and keys differ from
`configs/2021/`; it is provided as an example and is not covered further in this
guide.

The rest of this section documents each file under `configs/2021/`.

### 5.1 `configs/2021/venues/venues_config.yaml`

Catalogue of all venue types. Every entry sits under a single top-level
`venue_types:` key. Miss it out and nothing loads.

```yaml
venue_types:
  hospital:
    enabled: true                     # set false to skip this venue type entirely
    filename:                         # one path, or a list to stack; under data/venues/
      - medical/hospitals/EW_hospitals.csv
      - medical/hospitals/SCT_hospitals.csv
      - medical/hospitals/NI_hospitals.csv
    is_residence: false               # true => people live here
    capacity_config:                  # optional: how to read capacity
      total_capacity_column: "n_beds"
```

`filename` follows the same path-or-list rule as the geography and population
keys, and the shipped config lists all three nations for most venue types. Rows
outside the loaded geography are filtered out on load, so listing Scotland and
Northern Ireland in an England-only build costs read time and nothing else.

Some venues (care homes, boarding schools, dorms) include `attribute_capacities` that map CSV columns to age/sex slots. Keep these aligned with your CSV columns.

A few types ship with `enabled: false` because they are created at runtime rather
than loaded from CSV: `household` (built by the household distributor) and the
`*_line` transport venues (built by the route distributor, §5.4.1).

### 5.2 Household allocation, and the three YAMLs that cooperate

Household allocation has more moving parts than anything else in the pipeline, so it gets its own walkthrough. Three files cooperate:

| File | Role |
|---|---|
| `configs/2021/households/households_config.yaml` | Defines **what** people are (age categories) and the global **demotion/promotion** safety nets. |
| `configs/2021/households/allocation_strategy.yaml` | Defines **the ordered list of steps** that places people into households (and into communal residences). |
| `configs/2021/households/relationship_rules.yaml` | Defines **how members of a household relate to each other** (parent-child age gaps, couple compatibility, multi-generational structure). |

#### Why is the pipeline so elaborate?

The short answer: **census data is heavily obfuscated at the smallest geographical level**, and the two inputs we rely on don't have to be self-consistent.

For disclosure-control reasons, the ONS perturbs counts in OA-level (SGU-level) tables before publication. The age-by-sex demographics in the `*_demographics_male.csv` / `*_demographics_female.csv` files are obfuscated independently of the household-composition counts in the `*_households.csv` files, and there is no constraint that the two add up. So in any given Output Area you can get mismatches like:

> The demographics for OA `E00000123` say there are 5 kids living there.
> But the household table for the same OA lists 5 households whose composition pattern is `">=2 >=0 2 0"`, meaning at least 2 kids each, so ≥10 kids.

A naive allocator handed those two files would either error out, leave 5 households empty, or invent 5 phantom kids. We don't want any of those: we want the resulting world to honour the **demographics** (the population we have is what we have) while staying as close as possible to the **household structure** (most kids really do live in two-adult households, etc.).

That's exactly what the pipeline is built to do, and it's why it has so many phases:

- **Demotion** (§5.2.1) handles the "household table demands more people than we've got" direction. If the OA only has 5 kids and demands ≥10, the engine relaxes patterns (`">=2 >=0 2 0"` → `"1 >=0 2 0"` → `"0 >=0 2 0"`) until what's asked for matches what's available.
- **Promotion + `household_excess` + `household_overflow`** (§5.2.2 phases D-F) handle the opposite direction. If the OA has people left over (the household table didn't account for them), existing households are loosened (`"0 0 2 0"` → `">=0 >=0 2 0"`) and topped up via probabilistic excess steps, with the final overflow rounds guaranteeing every person ends up housed.
- **Relationship rules + backtracking** (§5.2.3) make sure that even after demotion/promotion, the resulting households stay demographically plausible, so kids end up with adults of a parent-aged spread and couples have realistic age and sex compatibility.

The order matters: structurally constrained households (families with kids, multi-generational) are formed **first**, while there's a full population to choose from. Looser, flexible patterns are formed **last** so they can absorb whatever's left without breaking realism elsewhere. The phases below are arranged accordingly.

Composition patterns appear throughout. They use the format **`Kids YoungAdults Adults OldAdults`**, where each slot is either an exact count (`2`) or a flexible bound (`>=2`, `>=0`). Examples:

- `">=2 >=0 2 0"` means 2 or more kids, any young adults, exactly 2 adults and no elderly, the classic two-adult family.
- `"0 0 0 2"` means 2 elderly and nothing else, an elderly couple.
- `"0 >=0 >=0 >=0"` is the flexible adult-only household used as a catch-all.

#### 5.2.1 `households_config.yaml` holds categories and global rules

Defaults shipped with the project:

- **Age categories.** `Kids` 0-17, `Young Adults` 18-24, `Adults` 25-64, `Old Adults` 65+. These are the four slots in every composition pattern. Editing the `categories` list changes the age boundaries everywhere downstream.
- **Demotion** (`demotion.enabled: true`, `max_attempts: 10`): if the population can't fill the requested pattern (e.g. not enough kids in this OA), the engine relaxes the pattern by reducing slots in priority order **Kids → Young Adults → Old Adults → Adults**. Adults are demoted last because the engine wants to preserve at least one adult for child supervision.
- **Promotion** (`max_attempts: 4`): when there are *leftover* people, fixed slots like `0` are promoted to `>=0` / `>=1` so existing households can absorb them. Priority: **Young Adults → Adults → Old Adults → Kids** (kids are promoted last, again to keep supervision realistic). The engine reads `priority`, `validation_rules` and `max_attempts` from this block. To stop promotion, remove the steps that use it from `allocation_strategy.yaml`.
- **Validation rule.** Both demotion and promotion are gated by *"if Kids ≥ 1, then Adults ≥ 1"*, so any pattern that would leave children unsupervised is rejected.

You'll typically only edit this file if you want different age bands or a new validation rule (e.g. "Old Adults ≥ 2 must have at least one Adult").

#### 5.2.2 `allocation_strategy.yaml` is the ordered pipeline

`enabled: true` plus a `steps:` list. The engine walks the list **top to bottom**; earlier steps get first pick of the population pool. There are **five step types** in use today:

| `type:` | What it does |
|---|---|
| `household` | Create new households matching a pattern, optionally invoking a `rule:` from `relationship_rules.yaml` to enforce internal structure. |
| `household_excess` | Add extra members of a given category into *existing* households matching `target_patterns`, with a probabilistic `add_distribution` (poisson / weighted / normal) and `constraints` capping size. |
| `household_promotion` | Loosen an existing household's pattern (e.g. `"0 0 2 0"` → `">=0 >=0 2 0"`) so it can accept new categories. |
| `household_overflow` | The final desperation round. Distributes *all* remaining people across the listed `target_patterns`, weighted by `pattern_bias`. |
| `venue` | Send eligible people to communal residences (boarding schools, care homes, student dorms). Uses `attribute_aware` allocation that respects the age/sex slot capacities defined in `venues_config.yaml`. |

Three per-step settings show up repeatedly:
- `refresh_pools: true` re-scans the population for who is still unallocated before this step runs. Almost every shipped step leaves it `false`, and one late `household_excess` step turns it on.
- `assumption:` sits on a pattern. When that pattern is open-ended (`">=2 >=0 >=0 >=0"`), the engine assumes a concrete shape such as `"2 0 1 1"` for sizing purposes.
- `demotion_rules:` switches to a different relationship rule when a step's pattern demotes mid-allocation, so a two-adult family rule can demote to a single-adult family rule.

**The default sequence ships in seven broad phases. This is what currently runs:**

| Phase | Steps (in order) | Purpose |
|---|---|---|
| **A. Core families** | 1a Two-adult families w/ kids · 1b Single-parent families w/ kids · 2 Multi-generational households · 3a/3b Families w/ young adults (no kids) | Build the most structurally-constrained households first, while there's a full population to choose from. |
| **B. Care homes** | Elderly (50+) → Care homes (`age_weighted`) | Runs before the elderly household steps, for the reason given below. |
| **C. Couples / singles** | 4a Elderly couples · 4b Elderly singles · 5a Adult couples · 5b Adult singles · 6 Young-adult pairs | Pair off and place remaining adults / elderly. |
| **D. Other communal residences** | Kids → Boarding schools · Young adults (16+) → Student dorms · 10 Multi-elderly households | These `venue` steps move people *out* of the household pool. |
| **E. Top up existing households** (`household_excess`) | 11 Extra kids → kid-families · 11 More YA → YA households · 12a/12b YA → adult families w/o kids · 13 YA → families w/ kids · 14 YA → multi-gen · 15 Old Adults → multi-gen · 16 More elderly → multi-elderly · 17 More adults → multi-gen | Inflate already-built households using poisson-distributed counts to mop up surplus people while respecting size constraints (`category_sum max: ...`). |
| **F. Flexible households** | 18 Flexible households (`pattern: "0 >=0 >=0 >=0"`, `max_household_size: 10`) · then add Adults / Old Adults / YA to them | A general-purpose adult-only household pattern that absorbs whoever's left. |
| **G. Final cleanup** | `household_promotion` (couples accept young adults; singles become multi-adult; elderly singles → couples) · `household_overflow` for remaining YA / Adults / Old Adults · final `Promote and allocate all remaining` | Last-ditch passes that *will* place everyone, even if it means stretching existing patterns. |

If a population is balanced, very few steps in Phase G need to fire. If it's unbalanced, the demotion/promotion logic in §5.2.1 plus these final steps make sure no person goes unallocated.

**Why care homes run before the elderly household steps.** The two draws are not
symmetric. The care-home step is age-selective, because it needs the oldest tail. The
elderly household patterns are age-blind above 65: `"0 0 0 2"` asks for two old
adults, not *which* two. Run the age-blind steps first and they strip a little
over half the 65+ population uniformly, including half the 85-year-olds, and no
weighting can recover a tail that has already gone. Running care homes first
takes the tail it needs and hands back a residual the household steps are, by
their own definition, indifferent to. **If you reorder these steps, this is the
one to leave alone.**

The care-home step uses `strategy: "age_weighted"` with a table of bands under
`strategy_config.bands`. Each weight is that band's care-home **residence rate**
(residents ÷ population), so someone's chance of being drawn early rises steeply
with age, so that by rate age 90 outweighs age 65 by about 24×. It has to be a rate
rather than a share of residents, because the pool already carries the local age structure and
weighting by share would count that structure twice and under-place the very old
by roughly sevenfold.

To **change the order**, reorder the `steps:` list. To **drop a step**, comment its block. To **tighten** allocations, lower `max_household_size`, lower `category_sum max`, or narrow `add_distribution.max`.

#### 5.2.3 `relationship_rules.yaml` shapes each household internally

Steps that say `rule: "..."` look up that rule here. The shipped rules:

| Rule | Used by | Constraints enforced |
|---|---|---|
| `Two-adult family with kids` | Step 1a | Kids vs. Adults age gap 16-50 (preferred normal(μ=32, σ=6)); 2 Adults form a romantic pair (≈3-yr age diff, std 5, max 19). |
| `Single-adult family with kids` | Step 1b + demoted 1a | Same parent-child age gap; no pair constraint (single parent). |
| `Two-adult family with young adults` | Step 3a | Same as 1a but Adults vs. Young Adults. |
| `Single-adult family with young adults` | Step 3b + demoted 3a | Single-parent variant. |
| `Adult pair` | Step 5a | Two compatible adults; flagged as romantic couple. |
| `Elderly pair` | Step 4a | Two compatible elderly; flagged as romantic couple. |
| `Add young adults to existing family` | Steps 12a/12b/13/14 | New YA must be 16-50 yrs younger than existing adults. |
| `Multi-generational household` | Steps 2, 15, 17 | Three age tiers: Kids ↔ Adults gap (μ=32, σ=6), Adults ↔ Old Adults gap (μ=30, σ=7), 2-Adult pair sex/age compatibility. |

**Two important data-driven mechanisms:**

1. **Same-sex pairing per area.** The `same_category_sources:` block at the top of `relationship_rules.yaml` reads the per-nation census marginals under `data/population/sexual_orientation/` (`EW_`, `SCT_` and `NI_orientation_by_mgu.csv`, stacked into one table) and computes `P(same-sex couple) = homosexual + 0.5 * bisexual` per area. Couple-forming rules use this live, falling back to `same_category_probability_fallback: 0.05` only when an area isn't in the table.
2. **`creates_romantic_couple: true`.** Rules with this flag mark pairs as cohabiting couples; the romantic relationships step downstream picks them up automatically (rather than re-pairing them).

The selection engine uses **backtracking** (`max_backtracks: 3`) before resorting to demotion: if a later role can't be filled, it retries with a different first-role person, then if all backtracks fail it falls back on the demotion ladder from §5.2.1.

#### 5.2.4 What you'll typically edit

| If you want to… | File / key |
|---|---|
| Change age band cut-offs | `households_config.yaml` → `categories` |
| Allow children alone | `households_config.yaml` → remove the `Kids require adult supervision` validation rule |
| Re-order the allocation pipeline | `allocation_strategy.yaml` → reorder `steps` |
| Skip a phase entirely | comment out the relevant blocks in `allocation_strategy.yaml` |
| Cap household sizes more tightly | `allocation_strategy.yaml` → `max_household_size` and per-step `constraints` |
| Tweak parent-child age realism | `relationship_rules.yaml` → `preferred_distribution` on the relevant rule |
| Change couple age gap | `relationship_rules.yaml` → the `type: pair_matching` constraint → `numerical_attribute` |
| Change who ends up in care homes | `allocation_strategy.yaml` → the care-home step's `strategy_config.bands`, and its `eligibility` age floor |
| Change same-sex couple probability | `relationship_rules.yaml` → `same_category_sources` formula, or the per-rule `same_category_probability_fallback` if you have no per-area data |

### 5.3 `configs/2021/attributes/*.yaml`

One file per attribute the simulation assigns:

| File | Assigns | Property set |
|---|---|---|
| `attribute_assignment.yaml` | Ethnicity (with parent → child inheritance rules). | `ethnicity` |
| `comorbidity_assignment.yaml` | Health comorbidities, by age × sex × ethnicity × region. | comorbidity flags |
| `economic_activity_assignment.yaml` | The employment gate. Only the employed go on to get a workplace, sector and company. | `economic_activity` |
| `commutes_assignment.yaml` | Commute / no-commute split, drawn at output-area resolution. | `commutes` |
| `workplace_assignment.yaml` | Workplace **LGU** + work mode (Home / Hybrid / Normal). | `workplace_location`, `work_mode` |
| `workplace_mgu_assignment.yaml` | Workplace **MGU** within the chosen LGU, weighted by job supply. | `workplace_mgu` |
| `work_sector_assignment.yaml` | Industry sector (A, Q, P …). | `work_sector` |
| `work_mode_correction.yaml` | Forces on-site sectors (hospital / care home / classroom) back to `Normal`, overriding the area-level draw. | `work_mode` |
| `commute_mode_assignment.yaml` | Travel mode for commuters (train, tube, bus, car_solo …). | `commute_mode` |

The workplace destination is an **MGU**, set by `workplace_mgu_assignment.yaml`
under the property name `workplace_mgu`. The route distributor keys off it
(§5.4.1).

Each YAML declares its **dependencies** (e.g. comorbidities require ethnicity), **filters** (who is eligible), and **data sources** (which CSV provides the probabilities).

### 5.4 `configs/2021/distributors/*.yaml`

One file per venue distribution step. Each tells the engine:

- which venue type to fill (`venue_type`),
- which `activity_map_key` to set on the person (`primary_activity`, `medical`, `leisure`, …),
- eligibility filters,
- selection logic (distance, capacity, attribute matching),
- subset assignment (e.g. school → "student" subset).

Common distributors:

| File | Purpose |
|---|---|
| `school_distributor.yaml` | Assigns children to schools. |
| `university_distributor.yaml` | Assigns students to universities. |
| `company_distributor.yaml` | Assigns working-age adults to companies. |
| `hospital_distributor.yaml` | Assigns people to a registered hospital (non-resident). |
| `multi_venue_distributor.yaml` | Assigns leisure venues (cinemas, gyms, pubs, etc.). |
| `specific_workplace_hospitals_distributor.yaml` | Q-sector workers → hospitals as workplace. |
| `specific_workplace_care_homes_distributor.yaml` | Q-sector workers → care homes as workplace. |
| `specific_workplace_classrooms_distributor.yaml` | P-sector workers → schools as workplace. |
| `care_home_visits_distributor.yaml` | Links households of care home residents to visit that care home as a leisure activity. |
| `route_commute_train.yaml` / `_tube` / `_bus` | Put commuters on shared transport lines (§5.4.1). |

#### 5.4.1 The `route` distributor, for transit lines and commuting

The `route` distributor (`distributor_type: "route"`) is how MAY puts people onto
**shared transport lines** (train / tube / bus) and, more generally, onto any
origin→destination journey made of one or more **legs**. Commuting is the built-in
use-case, but the distributor is generic: school buses, ferries, or freight routes
plug in the same way, and only the YAML and the input CSV change.

**The distributor is a lookup, not a router.** It does no pathfinding
at world-build time. For each eligible person it forms a key `(origin, destination,
mode)` and looks that key up in a **precomputed routing table** you supply. If the
key is found, the person is placed as a rider on **every leg already listed** for
that journey; if not, a fallback property is applied (a "miss"). This is what lets
it scale to tens of millions of agents, since all the route-finding happens once,
offline, before the run.

##### What you must provide

| File | Required? | Role |
|---|---|---|
| `route_legs.csv` | Yes, the distributor reads this | The itinerary table: one row per leg, keyed by `(origin, destination, mode)`. |
| A line→stops mapping | Only if you want geometry | Ordered stops per line. **Not used by the distributor**, but needed downstream (e.g. to draw the lines on a map). See note at the end. |

Put the CSVs anywhere under `data/` and point the YAML at them via `${data_root}`.
The conventional location is `data/activities/commute/`, where the shipped
`route_legs.csv` lives alongside the two viewer-geometry files in
`for-visualisation/`.

> **Bus derives its pools at runtime.** `route_commute_bus.yaml` uses a
> `pool_rule` block instead of a table: riders crossing the same ordered pair of
> LGUs share a pool, same-LGU journeys pool on their origin MGU, and travel time
> comes from centroid distance at an urban-bus average. Train and tube are the
> two distributors that read `route_legs.csv`.

##### `route_legs.csv` format (the file the distributor consumes)

One row per leg. **Required columns** (the distributor errors if any are missing):

| Column | Meaning |
|---|---|
| `origin_mgu` | Journey origin, an **MGU** name/code. Must match `GeographicalUnit.name`. |
| `dest_mgu` | Journey destination, an **MGU** name/code. |
| `mode_class` | The transport class (`train`, `tube`, `bus`, …). Matched against the person's mode (see `class_source`/`class_map`). |
| `leg_idx` | 0-based leg order within the journey. Rows are sorted by this. |
| `line_id` | Stable identifier of the line ridden on this leg. **Becomes the venue name** (`/metadata/names/venues`), so one venue is materialised per distinct `line_id`. |
| `board_mgu` | Where the rider boards this leg (an MGU). |
| `alight_mgu` | Where the rider alights this leg. |

Plus any **per-leg metadata columns** you reference in the YAML's `leg_metadata`
(the commute configs use `t_board_min` and `t_alight_min`, both minutes from start of day):

```csv
origin_mgu,dest_mgu,mode_class,leg_idx,line_id,board_mgu,alight_mgu,t_board_min,t_alight_min
E02000001,E02000016,train,0,three_bridges_west_hampstead_thameslink_0911,E02000001,E02000575,63,65
E02000001,E02000016,train,1,reading_abbey_wood_el_0739,E02000575,E02000878,58,60
```

A journey with two rows like the above (`leg_idx` 0 and 1) is a **two-leg trip with
one interchange**. The keying is only `(origin_mgu, dest_mgu, mode_class)`, so
every person travelling that O→D by that mode rides an identical leg sequence with
no per-person variation. Origin and destination sit at MGU granularity even though
people live and work at finer SGU units, because the distributor rolls each up to its
MGU ancestor before the lookup (see `origin_source`/`destination_source` below).

##### How to build `route_legs.csv` (the algorithm)

You produce this table however you like; the distributor only cares about the
columns above. The reference approach used to generate the shipped commute tables is
a standard **shortest-path over a transit graph**, and you can reproduce it with any
graph library (e.g. `scipy.sparse.csgraph` or `networkx`):

1. **Define lines.** For each line, list its stops in order, map each stop to an MGU,
   and record a cumulative time offset per stop (from a timetable, or estimated from
   inter-stop distance).
2. **Build a graph.** Create *stop-nodes* `(line, stop)` and one *hub-node* per MGU.
   Add **ride edges** between consecutive stops on a line (weight = travel time) and
   **transfer edges** between a stop-node and its MGU hub (weight = a transfer
   penalty). The hub-per-MGU keeps transfers cheap to model (O(lines), not O(lines²)).
3. **Shortest path per (origin, mode).** For each origin MGU, run a multi-source
   Dijkstra from *all* that MGU's stop-nodes at once (so the **first boarding is
   free** and only **transfers pay the penalty**). Every destination MGU is reached
   at its hub; walk the predecessor tree back and **split the node path into legs at
   hub crossings**, where a leg is a maximal run of stops on one line.
4. **Cap and emit.** Drop journeys over a max time or max leg count (the shipped
   tables use ≤120 min, ≤4 legs), then write one `route_legs.csv` row per leg.

Run this **once per mode class** (keep `train`/`tube`/`bus` graphs separate) and
concatenate the results into a single `route_legs.csv` with the right `mode_class`.

##### The distributor YAML

One file per mode class (so each instance filters to one `class_filter`). Annotated
example (`configs/2021/distributors/route_commute_train.yaml`):

```yaml
distributor_type: "route"
distributor_name: "route_commute_train"

activity_map_key: "commute"      # activity bucket set on the person
leg_venue_type:   "train_line"   # venue type created per line_id (must be a known venue type)
leg_subset_key:   "rider"        # subset each rider is added to on every leg venue

legs_table:   "${data_root}/activities/commute/route_legs.csv"  # REQUIRED, the table read above

# How to form the routing-table key from each person:
origin_source:        # -> origin_mgu
  type: "ancestor"
  from: "geographical_unit"          # the person's residence unit (an SGU)...
  level: "MGU"                        # ...rolled up to its MGU ancestor
destination_source:   # -> dest_mgu
  type: "ancestor"
  from: "properties.workplace_mgu"   # set by workplace_mgu_assignment.yaml
  level: "MGU"

# How to form mode_class, and which class this instance handles:
class_source: "properties.commute_mode"  # person property holding the mode
class_filter: "train"                     # only act on people with commute_mode == "train"
class_map: { train: "train" }             # person value -> mode_class in the CSV (identity here)

require_properties:                       # skip people missing any of these
  - "commute_mode"
  - "workplace_mgu"

# Station catchment: endpoints snap to the nearest MGU the table serves.
catchment:
  max_access_km: 10
  access_speed_kmh: 30

# Per-leg CSV columns to store on Subset.member_metadata, keyed by field name:
leg_metadata:
  t_board_min:  "t_board_min"
  t_alight_min: "t_alight_min"

on_miss:                 # applied when (origin,dest,mode) isn't in the table
  set:
    commute_mode: "bus"  # hands them to the generic shared pool; see below
```

Three details in that example carry weight:

**`destination_source` reads `properties.workplace_mgu`.** That is the property
`workplace_mgu_assignment.yaml` sets, and it is what the routing table is keyed
on. A `destination_source` pointing anywhere else misses on every lookup, and
`on_miss` then rewrites the whole population without raising anything.

**`require_properties` lists `workplace_mgu` as well as `commute_mode`.** Someone
with a travel mode but no assigned workplace has no journey to route. Skipping
them keeps the miss rate honest and leaves the mode of a non-commuter alone.

**Train and tube miss to `bus`.** What is preserved is *exposure*, not the mode
label. The census recorded this person sharing enclosed air with strangers, and
bus is the model's generic bounded pool, so the mode is approximate while the
exposure stays roughly right. `route_commute_bus.yaml` is the last rung and falls back to
`car_solo`, by which point the journey is over 50 km and beyond a daily bus.

Field reference:

| Key | What it does |
|---|---|
| `distributor_type` | Must be `"route"`. |
| `leg_venue_type` | Venue type materialised once per `line_id`. Must be a venue type the world knows (e.g. `train_line`, `tube_line`, `bus_line`). The line venue is attached to a rider's residence MGU purely for stable HDF5 partitioning, so its `geo_unit` is not the line's location. |
| `leg_subset_key` | Subset every rider is added to on each leg venue (e.g. `rider`). |
| `origin_source` / `destination_source` | Recipe to derive the O/D key. `type: ancestor` reads a unit (`from: geographical_unit` or `from: properties.<name>`) and rolls it up to `level`. `type: property` uses a raw property string. |
| `class_source` | Person attribute/property giving the transport class. |
| `class_filter` | Run this instance only for people whose class equals this. Run one distributor per class. |
| `class_map` | Maps the person's class value to the `mode_class` string in the CSV (identity if omitted). |
| `require_properties` | People missing any of these are skipped entirely (not even counted as misses). Commute configs list `commute_mode` **and** `workplace_mgu`. |
| `catchment` | Optional. Riders need not live in an MGU containing a station; each endpoint snaps to the nearest MGU the table serves, up to `max_access_km` at `access_speed_kmh`. The rail configs use 10 km at 30 km/h, a road speed, since the assumption is park-and-ride rather than walking. Beyond that the rider is a real miss. |
| `leg_metadata` | `{ field_name: csv_column }`. Per-leg numbers copied onto `Subset.member_metadata[person.id]`. |
| `on_miss.set` | Property overrides applied when the key isn't found. Train and tube set `commute_mode: bus`; bus sets `car_solo`. |
| `pool_rule` | Bus only, and mutually exclusive with `legs_table`. Derives pools at runtime instead of reading a table: `pool_id_prefix`, `corridor_level`, `max_distance_km`, `speed_kmh`, `min_duration_min`, `max_duration_min`. |

##### Prerequisites & ordering

The `route` distributor only works if, by the time it runs, each eligible person
already has the properties its key needs. For commuting that means the timeline must
run, **in order**:

1. **Workplace assignment.** `workplace_assignment.yaml` picks the destination
   LGU, then `workplace_mgu_assignment.yaml` sets `workplace_mgu` inside it.
2. **All workplace distributors**, so the next step can gate on a venue that was
   actually assigned.
3. **Commute-mode assignment** (`attributes/commute_mode_assignment.yaml`), which
   sets `commute_mode`, the class.
4. **The `route` distributors**, one `type: distributor` step per mode class.

In `config.yaml` the commute block looks like:

```yaml
    - type: attribute
      config: "${config_root}/attributes/commute_mode_assignment.yaml"
    - type: distributor
      config: "${config_root}/distributors/route_commute_train.yaml"
    - type: distributor
      config: "${config_root}/distributors/route_commute_tube.yaml"
    - type: distributor
      config: "${config_root}/distributors/route_commute_bus.yaml"
```

**Bus must stay last.** Train and tube rewrite riders the network cannot serve to
`bus` rather than taking them off shared transport, and only a distributor
running *after* them picks those riders up. Move bus earlier and everyone rail
could not route stops being placed at all, with nothing in the run output to say so.

##### Serialization & downstream geometry

Each line venue is serialized with its `line_id` as the venue **name**, and the
per-leg `t_board_min`/`t_alight_min` land on the membership metadata side-table in
`world_state.h5`. To know *who rides each line*, read the line venue's `rider`
subset; to reconstruct a person's full journey, order their legs by `t_board_min`.

The distributor stores **board/alight MGUs**, not the stops in between. If you need
the drawable shape of a line (a polyline through its stations), keep your line→stops
mapping (`line_id, position, node_mgu, name, …`) alongside the world and join on
`line_id` at render time. Slicing each line's stop sequence between a rider's
`board_mgu` and `alight_mgu` gives exactly the segment they travel.

The shipped data does this in `data/activities/commute/for-visualisation/`, which
holds `line_stops.csv` (ordered stops per line) and `coord_mgu.csv` (a UK-wide
MGU centroid file, since the geography ships one file per nation). MAY opens
neither, as both are there for the map viewer. That folder's README covers how to
refresh them and how to check the pair is current.

### 5.5 `configs/2021/venue_child_creators/*.yaml`

Break a parent venue into children. Examples: `school_classrooms.yaml` (school → classrooms by age), `university_uni_years.yaml` (university → year groups), `company_offices.yaml` (company → offices by sizeband).

### 5.6 `configs/2021/relationships/*.yaml`

#### `social_networks.yaml`

Defines one or more social networks to build. The file contains a top-level `networks:` list; each entry is one network. The 2021 config builds three networks that all write into the same `friendships` storage key, so contacts across networks are automatically deduplicated:

```yaml
networks:
  - name: activity_peers
    network_type: activity_peers      # same venue, similar age
    pool_type: activity
    pool:
      activity: primary_activity
    algorithm: random
    mean_count: 3                     # mean contacts per person from this network
    degree_variants:
      - probability: 0.10
        count: 6                      # 10% of people get double contacts
    storage_key: friendships
    constraints:
      - type: numerical_attribute_difference
        attribute: age
        max_difference: 5

  - name: geographic_local
    network_type: intra_geo_unit      # same SGU (Output Area)
    pool_type: geographic
    pool:
      level: SGU
    algorithm: random
    mean_count: 2
    storage_key: friendships
    constraints:
      - type: numerical_attribute_difference
        attribute: age
        max_difference: 10

  - name: geographic_community
    network_type: intra_geo_unit      # same MGU (MSOA)
    pool_type: geographic
    pool:
      level: MGU
    algorithm: random
    mean_count: 1
    storage_key: friendships
    constraints:
      - type: numerical_attribute_difference
        attribute: age
        max_difference: 15
```

Key settings per network entry:

| Key | What it does |
|---|---|
| `network_type` | Pool selection strategy. `activity_peers`: same venue. `intra_geo_unit`: same geographic unit. Other types (e.g. `spatial_social_network`, `local_social_network` with Watts-Strogatz) exist for other world configs. |
| `algorithm` | Contact-sampling algorithm. `random`: uniform random draw. `watts_strogatz`: clustered small-world graph (used in other configs). |
| `mean_count` | Mean number of contacts per person from this network. |
| `degree_variants` | Optional list of `{probability, count}` overrides, giving a subset of people a different contact count. |
| `storage_key` | Where contacts are stored on the person. Multiple networks sharing the same key are merged (deduplicated). |
| `constraints` | List of filters on who can be paired. `numerical_attribute_difference` enforces a max gap on a numeric attribute (e.g. age). |

To **add a new network**, append a new entry to `networks:`. To **change total contacts**, adjust `mean_count` across entries. To **skip social networks entirely**, set `relationship_pipeline.enabled: false` in `config.yaml`.

#### `romantic_relationships.yaml`

Controls sexual orientation assignment and partnership formation. Key sections:

- `data_sources:` reads ONS-derived prevalence and per-MSOA orientation marginals for UK runs, and computes orientation probabilities from them. Worlds without UK MSOA codes should omit this block and fall back on `probabilities:` below.
- `sexual_orientations.probabilities:` holds national-level orientation probabilities by sex, used when `data_sources` is absent or an MSOA isn't in the table.
- `sexual_orientations.age_adjustments:` applies multiplicative tweaks to those probabilities by age band.
- `sexual_orientations.compatibility:` says which orientations can pair with which.
- `storage:` names the keys under which orientation and relationship status are stored on the person.
- `diagnostics.verbose:` set to `true` logs detailed national against empirical orientation comparisons. Leave it `false` for production runs.

### 5.7 `configs/2021/serialization_config.yaml`

Controls **what is written to `world_state.h5`**. Edit to:

- Add/remove fields under `population.properties` (e.g. enable `work_sector`).
- Add/remove fields under each `venues.types.*.properties`.
- Toggle coordinates, hierarchy export, compression level.

If you add a new property (e.g. `income`) to people via attribute YAMLs, you must also list it here for it to appear in the HDF5 file.

---

## 6. The `data/` folder and its input CSVs

Nation prefixes are `EW` (England+Wales), `SCT` (Scotland) and `NI`, and they
come **first** in every filename.

```
data/
├── geography/                 # one file per nation, stacked by the engine
│   ├── EW_hierarchy.csv       # SGU,MGU,LGU,XLGU (England+Wales)
│   ├── SCT_hierarchy.csv      #   "  (Scotland)
│   ├── NI_hierarchy.csv       #   "  (Northern Ireland)
│   ├── {EW,SCT,NI}_coord_sgu.csv
│   └── {EW,SCT,NI}_coord_mgu.csv
├── population/
│   ├── {EW,SCT,NI}_demographics_male.csv     # rows=SGU, cols=ages 0-99
│   ├── {EW,SCT,NI}_demographics_female.csv
│   ├── comorbidities/
│   ├── ethnicity/
│   ├── leisure_participation/
│   └── sexual_orientation/    # {EW,SCT,NI}_orientation_by_mgu.csv
├── households/
│   ├── EW_households.csv      # geo_unit + columns of composition patterns
│   ├── SCT_households.csv
│   └── NI_households.csv      # NI's pattern columns differ; see column_policy
├── venues/
│   ├── primary_activities/    # schools/, companies/, universities/
│   ├── medical/               # hospitals/
│   ├── residences/            # care_homes/, boarding_schools/, student_dorms/
│   └── leisure/               # cinemas/, groceries/, gyms/, pubs/
└── activities/
    ├── work/                  # commuting flows + sex × industry × LAD
    ├── university/            # university-attendance probabilities
    └── commute/               # commute mode/split by SGU + route_legs.csv
        └── for-visualisation/ # map-viewer geometry; MAY never opens these
```

Every venue subfolder holds one file per nation on the same pattern
(`EW_hospitals.csv`, `SCT_hospitals.csv`, `NI_hospitals.csv`).

A run writes nothing under `data/`, since all outputs land in `output_dir` (§2).

### 6.1 Required column conventions

Every venue CSV must include **one geographical column**: either `geo_unit`, or a
column named after one of the hierarchy levels (`SGU`, `MGU`, `LGU`, `XLGU`). A
file with neither aborts the load.

Two further columns are optional:

- `name` becomes the venue name when present, and the engine generates one when it is absent. `EW_pubs.csv` ships without it.
- `latitude` and `longitude` are matched case-insensitively and used by distance-based distributors. Venues lacking them still load.

Beyond that, columns must match what the relevant YAML expects. For example:

| File | Required by | Required columns |
|---|---|---|
| `schools/EW_Schools.csv` | `school_distributor.yaml` | `StatutoryLowAge`, `StatutoryHighAge`, `Gender`, `SchoolCapacity` |
| `universities/EW_universities.csv` | `university_distributor.yaml` | `n_students` |
| `companies/EW_companies.csv` | `company_distributor.yaml` | `industry_code`, `sizeband`, `employee_count` |
| `hospitals/EW_hospitals.csv` | `hospital_distributor.yaml` | `n_beds`, `estimated_staff` |
| `care_homes/EW_care_homes.csv` | `venues_config.yaml` (care_home) | `n_50_64`, `n_65_plus`, `number_staff` |
| `boarding_schools/EW_boarding_schools.csv` | `venues_config.yaml` (boarding_school) | `Gender`, `StatutoryLowAge`, `StatutoryHighAge`, `n_total`, `n_male`, `n_female` |
| `student_dorms/EW_student_dorms.csv` | `venues_config.yaml` (student_dorms) | `n_total`, `n_16_24`, `n_25_plus` |

The care-home file carries just the two resident columns. No UK nation publishes
care-home age detail finer than that which survives across all three, so the
capacity slots stop there and the `age_weighted` fill strategy (§5.2.2) carries
the age structure instead.

### 6.2 Household file format (`EW_households.csv` and friends)

```
geo_unit, "0 0 0 2", "0 0 2 0", "0 0 0 1", "1 >=0 2 0", ...
E00000001, 16,        22,        16,        6, ...
```
Each non-`geo_unit` column header is a household composition pattern using the categories defined in `households_config.yaml`. The cell value is the **count of households** of that pattern in that area. Patterns can be exact (`2`) or open (`>=2`).

### 6.3 Adding a new area / new census year

For an England-2021 build:

1. Replace the files under `data/geography/` with 2021 OA → MSOA → LAD → Region hierarchy and centroids.
2. Replace `data/population/EW_demographics_{male,female}.csv` with 2021 census age × sex per OA.
3. Replace `data/households/EW_households.csv` with 2021 household composition counts per OA.
4. Update venue CSVs (`schools/EW_Schools.csv`, `universities/EW_universities.csv`, `companies/EW_companies.csv`, `hospitals/EW_hospitals.csv`, …) with 2021 inventories.
5. Update region-keyed reference files: `data/population/comorbidities/`, `data/population/ethnicity/`, `data/population/sexual_orientation/`.
6. Update commuting flow / industry tables under `data/activities/work/`, and the mode-share and routing tables under `data/activities/commute/`.

You do **not** need to change YAML structure unless you change column names or category boundaries.

---

## 7. Common customisations

| You want to… | Edit |
|---|---|
| Build only one region | `configs/2021/config.yaml` → `geography.filter` |
| Skip leisure venues | In `configs/2021/config.yaml` timeline, comment out the `multi_venue_distributor` step |
| Disable a venue type | `configs/2021/venues/venues_config.yaml` → `venue_types.<type>.enabled: false` |
| Add a nation to the build | `configs/2021/config.yaml` → add the `SCT_`/`NI_` files to `hierarchy_file`, `coord_files`, `demographics_*_file` and `data_file`, or start from `config_uk_test.yaml` |
| Turn commuting off | In `configs/2021/config.yaml` timeline, comment out `commute_mode_assignment` and all three `route_commute_*` steps |
| Change age categories | `configs/2021/households/households_config.yaml` → `categories` |
| Change household allocation order | `configs/2021/households/allocation_strategy.yaml` → reorder `steps` |
| Add a new attribute to HDF5 export | `configs/2021/serialization_config.yaml` → `population.properties` |
| Turn off romantic relationships | `configs/2021/config.yaml` → `romantic_relationships.enabled: false` |
| Turn off friendships | `configs/2021/config.yaml` → `relationship_pipeline.enabled: false` |
| Change number of friend connections | `configs/2021/relationships/social_networks.yaml` → `mean_count` on the relevant network entry |
| Filter who can go to leisure venues | `configs/2021/distributors/multi_venue_distributor.yaml` → `eligibility.global_filters` |

---

## 8. Validating a run

After `python create_world.py` finishes, sanity-check:

1. The console summary, where the script logs counts of people, venues and allocations, including the household allocation rate and the number left unallocated.
2. `output/2021/world_state.h5`, which you can open in Python with `h5py` to inspect the exported groups: `population`, `geography`, `venues`, `relationships`. A default run produces this file and nothing else.
3. The specialised world viewers, using the generated `world_state.h5`.

A run writes everything into `output_dir` and leaves `data/` untouched.

Tests live in `tests/`. Run `pytest` to verify nothing is broken before/after a change.

---

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `KeyError` on a CSV column | A YAML references a column name the CSV does not have. Align the two. |
| Many people unallocated to households | Population doesn't match the household-file totals; check demotion/promotion settings in `households_config.yaml`. |
| No households at all, run aborts | The timeline has no `residence_allocation` step (§4.5). |
| Household couples and parent-child age gaps look random | Add `rules_file` to the `households:` block to switch relationship rules on (§4.4). |
| Everyone commutes by car, no train or tube riders | A `route` distributor's `destination_source` must read `properties.workplace_mgu` (§5.4.1); pointed elsewhere, every lookup misses and `on_miss` rewrites the population. |
| Route misses far higher than expected | Put bus last in the timeline so it picks up the riders train and tube hand to it (§5.4.1). |
| `if_no_match: error` from school distributor | Boarding-school name in residences CSV doesn't match a school in `schools/EW_Schools.csv`. |
| Workplace step assigns no one | Education steps haven't been run before workplace assignment, or `primary_activity` filter is excluding everyone. |
| Property missing from `world_state.h5` | Add it to `configs/2021/serialization_config.yaml`. |
| Geography filter returns 0 areas | `filter.level` doesn't match the level the codes belong to (e.g. LAD codes with `level: MGU`). |

---

## 10. Example: building England 2021

The shipped config builds County Durham + Darlington. To widen it to **England**,
keep the same England+Wales files and change only the filter: move from the `LGU`
level to `XLGU` (region) and list every English region explicitly.
`EW_hierarchy.csv` covers England *and* Wales, so naming the nine English regions
is what excludes Wales.

```yaml
geography:
  data_dir: "${data_root}/geography"
  levels: ["SGU", "MGU", "LGU", "XLGU"]   # OA -> MSOA -> LAD -> Region
  hierarchy_file: EW_hierarchy.csv        # unchanged
  coord_files:                            # unchanged
    SGU: EW_coord_sgu.csv
    MGU: EW_coord_mgu.csv
  load_all: false                         # use the filter below
  filter:
    level: XLGU
    codes: ["East Midlands", "East of England", "London", "North East", "North West", "South East", "South West", "West Midlands", "Yorkshire and The Humber"]

population:
  data_dir: "${data_root}/population"
  demographics_male_file: EW_demographics_male.csv     # unchanged
  demographics_female_file: EW_demographics_female.csv # unchanged

# Leave venues, households, timeline, relationship_pipeline, romantic_relationships
# at their defaults, since they already point at the modern UK YAMLs.
```

> **Tip.** Omitting any of the nine regions narrows the build further (drop
> everything except `London` and `South East` for a London-region run).
>
> The filter selects from whatever the listed files hold, so with the England+Wales
> files above, `load_all: true` gives you England and Wales. A four-nation build
> also lists `SCT_hierarchy.csv` and `NI_hierarchy.csv` under `hierarchy_file`,
> their coordinate files under `coord_files`, the Scottish and NI demographics
> under `population`, and the two other household files with
> `column_policy: union_zero_fill`. `configs/2021/config_uk_test.yaml` has all
> that stacking in place, so start from it and set its `filter` block (or
> `load_all: true`) to choose your scope.

Then ensure all CSVs under `data/` reflect 2021 inputs (see §6.3) and run:

```bash
python create_world.py --config configs/2021/config.yaml --filename england_2021.h5
```
