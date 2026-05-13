# User Guide — Building a World with `create_world.py`

This guide is for users who want to **generate a synthetic population world** (e.g. England 2021) by editing configuration files and input data only — no Python edits required.

The whole pipeline is driven by:

1. **YAML config files** in `configs/` — control *what* the simulation does and *how*.
2. **CSV data files** in `data/` — provide the *raw inputs* (geography, demographics, venues, etc.).
3. **One command** — `python create_world.py` — runs everything end-to-end and writes `world_state.h5`.

---

## 1. Environment Setup

We strongly recommend running this project in an **isolated Python environment** so its dependencies (numba, numpy, pandas, scipy, h5py, PyYAML) don't conflict with anything else on your machine. You only need to do this once.

The project requires **Python 3.13+**. Pick whichever environment manager you already use:

### Option A — Conda (recommended)

```bash
# Create the environment
conda create -n MayEnv python=3.13 -y

# Activate it (do this every time you open a new terminal)
conda activate MayEnv

# Install dependencies
pip install -r requirements.txt
```

### Option B — `venv` (built into Python)

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

> **Reminder:** activate the environment in every new terminal session **before** running `python create_world.py`. If you forget, you'll either get the wrong Python version or `ModuleNotFoundError`.

### Downloading the input data

The repository ships with code and configs but **not** the bulky census/venue CSVs that live under `data/`. Fetch them with:

```bash
bash scripts/get_data.sh
```

This downloads `data_may.zip` from the project's data server, unpacks it into `data/`, and removes the zip. You only need to do this once (or whenever the upstream dataset is refreshed).

---

## 2. Quick Start

Once the environment is active:

```bash
# Run with the default config (configs/2021/config.yaml)
python create_world.py

# Or point at a custom config / output file
python create_world.py --config configs/2021/config.yaml --filename world_state.h5
```

CLI arguments:

| Flag | Default | Description |
|---|---|---|
| `--config` | `yaml/config.yaml` | Path to the master config file. |
| `--filename` | `world_state.h5` | Output HDF5 file containing the built world. |

When the run finishes you will have:

- `world_state.h5` — the serialized world (people, geography, venues, relationships). **This is the canonical output.**
- *(opt-in)* debug CSVs — `household_allocations.csv`, `venue_allocations.csv`, `residence_venues.csv`, `unallocated_people.csv`. These are **off by default** because each one builds a DataFrame the size of the population/venue set, which can blow memory on country-scale runs. Enable them only for small worlds via `debug_outputs.enabled: true` in `yaml/config.yaml`.

---

## 3. The Two Folders You Edit

```
MAY/
├── yaml/   ← edit YAMLs to change behaviour, scope, scenarios
└── data/   ← edit CSVs to change the input statistics / locations
```

Everything else (`may/`, `world_specific_code/`, `create_world.py`) is the engine. **You do not need to touch Python code.**

---

## 4. The Master Config — `yaml/config.yaml`

`yaml/config.yaml` is the single entry point. It points to all the other YAMLs and tells the engine which steps to run. Open it and edit in place.

It has six top-level sections:

### 4.1 `geography:` — which area to build

| Key | What it does |
|---|---|
| `data_dir` | Folder with `hierarchy.csv`, `coord_sgu.csv`, `coord_mgu.csv`. |
| `levels` | Names of the geographical hierarchy levels, smallest → largest. The default for England is `["SGU", "MGU", "LGU", "XLGU"]` (Output Area → MSOA → Local Authority → Region). |
| `load_all` | `true` to build the entire dataset, `false` to use the filter below. |
| `filter.level` | Which level the filter applies to (`SGU`, `MGU`, `LGU`, `XLGU`). |
| `filter.codes` | Inline list of codes to include (small lists). |
| `filter.file` | Path to a text file with one code per line (large lists). |

**Example — build all of England:**
```yaml
geography:
  data_dir: "data/geography"
  levels: ["SGU", "MGU", "LGU", "XLGU"]
  load_all: true
```

**Example — build only London:**
```yaml
geography:
  load_all: false
  filter:
    level: XLGU
    codes: ["London"]
```

### 4.2 `population:` — demographics

```yaml
population:
  data_dir: "data/population"
  demographics_male_file: "demographics_male.csv"
  demographics_female_file: "demographics_female.csv"
```
The two CSVs are matrices: rows = SGU codes, columns = ages 0–99.

### 4.3 `venues:` — places people go

```yaml
venues:
  data_dir: "data/venues"
  config_file: "yaml/venues/venues_config.yaml"   # which venue types to load
  export_file: "venue_allocations.csv"
```
See **§5.1** to enable/disable venue types and §6 for the CSVs they read.

### 4.4 `households:` — where people live

```yaml
households:
  data_dir: "data/households"
  data_file: "households.csv"
  config_file: "yaml/households/households_config.yaml"
  strategy_file: "yaml/households/allocation_strategy.yaml"
  export_file: "household_allocations.csv"
```

### 4.5 `timeline:` — the order things happen

The `timeline.steps` list is the **execution order** of the entire simulation. Each step is one of:

- `type: attribute` — assign a property to people (e.g. ethnicity, comorbidities, work sector).
- `type: distributor` — place people into venues (school, hospital, company, leisure).
- `type: child_creator` — sub-divide a venue (school → classrooms; company → offices).

Each step references a YAML in `yaml/attributes/`, `yaml/distributors/`, or `yaml/venue_child_creators/`.

**To skip a step**, comment it out. **To reorder**, move the YAML block. Order matters — for example, in the **default** pipeline, schools/universities are assigned **before** workplaces, because workplace assignment skips anyone who already has a `primary_activity`. This is just how things are wired right now; with enough tinkering across the related YAMLs (eligibility filters, attribute dependencies, `require_unassigned`, etc.) the steps can in principle be reordered to suit a different scenario — but the order documented here is what currently ships.

### 4.6 `relationship_pipeline:` and `romantic_relationships:`

Build social and romantic networks **after** venues are assigned. Set `enabled: false` on either to skip.

---

## 5. The Other YAMLs — what each folder controls

```
yaml/
├── config.yaml                       # master config (above)
├── serialization_config.yaml         # what gets exported to world_state.h5
├── venues/venues_config.yaml         # venue types catalogue
├── households/
│   ├── households_config.yaml        # age categories + demotion/promotion rules
│   ├── allocation_strategy.yaml      # household allocation order
│   └── relationship_rules.yaml       # how people inside a household relate
├── attributes/                       # one YAML per attribute to assign
├── distributors/                     # one YAML per venue distributor
├── venue_child_creators/             # rules to break venues into sub-venues
├── relationships/
│   ├── friendships.yaml
│   └── romantic_relationships.yaml
└── 1911/                             # alternative configs (1911 census world)
```

### 5.1 `yaml/venues/venues_config.yaml`

Catalogue of all venue types. For each one:

```yaml
hospital:
  enabled: true                       # set false to skip this venue type entirely
  filename: medical/hospitals.csv     # path under data/venues/
  is_residence: false                 # true => people live here
  capacity_config:                    # optional: how to read capacity
    total_capacity_column: "n_beds"
```
Some venues (care homes, boarding schools, dorms) include `attribute_capacities` that map CSV columns to age/sex slots — keep these aligned with your CSV columns.

### 5.2 Household allocation — the three cooperating YAMLs

Household allocation is the most intricate part of the pipeline, so it gets its own walkthrough. Three files cooperate:

| File | Role |
|---|---|
| `yaml/households/households_config.yaml` | Defines **what** people are (age categories) and the global **demotion/promotion** safety nets. |
| `yaml/households/allocation_strategy.yaml` | Defines **the ordered list of steps** that places people into households (and into communal residences). |
| `yaml/households/relationship_rules.yaml` | Defines **how members of a household relate to each other** (parent–child age gaps, couple compatibility, multi-generational structure). |

#### Why is the pipeline so elaborate?

The short answer: **census data is heavily obfuscated at the smallest geographical level**, and the two inputs we rely on don't have to be self-consistent.

For disclosure-control reasons, the ONS perturbs counts in OA-level (SGU-level) tables before publication. The age-by-sex demographics in `demographics_male.csv` / `demographics_female.csv` are obfuscated independently of the household-composition counts in `households.csv`, and there is no constraint that the two add up. So in any given Output Area you can get mismatches like:

> The demographics for OA `E00000123` say there are 5 kids living there.
> But the household table for the same OA lists 5 households whose composition pattern is `">=2 >=0 2 0"` — at least 2 kids each, i.e. ≥10 kids.

A naive allocator handed those two files would either error out, leave 5 households empty, or invent 5 phantom kids. We don't want any of those: we want the resulting world to honour the **demographics** (the population we have is what we have) while staying as close as possible to the **household structure** (most kids really do live in two-adult households, etc.).

That's exactly what the pipeline is built to do, and it's why it has so many phases:

- **Demotion** (§5.2.1) handles the "household table demands more people than we've got" direction. If the OA only has 5 kids and demands ≥10, the engine relaxes patterns (`">=2 >=0 2 0"` → `"1 >=0 2 0"` → `"0 >=0 2 0"`) until what's asked for matches what's available.
- **Promotion + `household_excess` + `household_overflow`** (§5.2.2 phases D–F) handle the opposite direction. If the OA has people left over (the household table didn't account for them), existing households are loosened (`"0 0 2 0"` → `">=0 >=0 2 0"`) and topped up via probabilistic excess steps, with the final overflow rounds guaranteeing every person ends up housed.
- **Relationship rules + backtracking** (§5.2.3) make sure that even after demotion/promotion, the resulting households remain demographically plausible — kids end up with adults of a parent-aged spread, couples have realistic age and sex compatibility, etc.

The order matters: structurally constrained households (families with kids, multi-generational) are formed **first**, while there's a full population to choose from. Looser, flexible patterns are formed **last** so they can absorb whatever's left without breaking realism elsewhere. The phases below are arranged accordingly.

Composition patterns appear throughout. They use the format **`Kids YoungAdults Adults OldAdults`**, where each slot is either an exact count (`2`) or a flexible bound (`>=2`, `>=0`). Examples:

- `">=2 >=0 2 0"` — 2 + kids, any young adults, exactly 2 adults, no elderly (a classic two-adult family).
- `"0 0 0 2"` — 2 elderly, nothing else (an elderly couple).
- `"0 >=0 >=0 >=0"` — flexible adult-only household used as a catch-all.

#### 5.2.1 `households_config.yaml` — categories + global rules

Defaults shipped with the project:

- **Age categories.** `Kids` 0–17, `Young Adults` 18–24, `Adults` 25–64, `Old Adults` 65+. These are the four slots in every composition pattern. Editing the `categories` list changes the age boundaries everywhere downstream.
- **Demotion** (`demotion.enabled: true`, `max_attempts: 10`): if the population can't fill the requested pattern (e.g. not enough kids in this OA), the engine relaxes the pattern by reducing slots in priority order **Kids → Young Adults → Old Adults → Adults**. Adults are demoted last because the engine wants to preserve at least one adult for child supervision.
- **Promotion** (`promotion.enabled: true`, `max_attempts: 4`): when there are *leftover* people, fixed slots like `0` are promoted to `>=0` / `>=1` so existing households can absorb them. Priority: **Young Adults → Adults → Old Adults → Kids** (kids are promoted last, again to keep supervision realistic).
- **Validation rule.** Both demotion and promotion are gated by *"if Kids ≥ 1, then Adults ≥ 1"* — patterns that would leave children unsupervised are rejected.

You'll typically only edit this file if you want different age bands or a new validation rule (e.g. "Old Adults ≥ 2 must have at least one Adult").

#### 5.2.2 `allocation_strategy.yaml` — the ordered pipeline

`enabled: true` plus a `steps:` list. The engine walks the list **top to bottom**; earlier steps get first pick of the population pool. There are **five step types** in use today:

| `type:` | What it does |
|---|---|
| `household` | Create new households matching a pattern, optionally invoking a `rule:` from `relationship_rules.yaml` to enforce internal structure. |
| `household_excess` | Add extra members of a given category into *existing* households matching `target_patterns`, with a probabilistic `add_distribution` (poisson / weighted / normal) and `constraints` capping size. |
| `household_promotion` | Loosen an existing household's pattern (e.g. `"0 0 2 0"` → `">=0 >=0 2 0"`) so it can accept new categories. |
| `household_overflow` | "Final desperation" round — distribute *all* remaining people across listed `target_patterns` weighted by `pattern_bias`. |
| `venue` | Send eligible people to communal residences (boarding schools, care homes, student dorms). Uses `attribute_aware` allocation that respects the age/sex slot capacities defined in `venues_config.yaml`. |

Some useful per-step knobs you'll see repeatedly:
- `refresh_pools: true` — re-scan the population for who is still unallocated before this step. Used after venue steps so household steps don't try to place residents who are now in a care home.
- `assumption:` (on a pattern) — when a pattern is open-ended (`">=2 >=0 >=0 >=0"`), the engine assumes a concrete shape for sizing purposes (`"2 0 1 1"`).
- `demotion_rules:` — if a step's pattern demotes mid-allocation, switch to a different relationship rule (e.g. a two-adult family rule demotes to a single-adult family rule).

**The default sequence ships in six broad phases. This is what currently runs:**

| Phase | Steps (in order) | Purpose |
|---|---|---|
| **A. Core families** | 1a Two-adult families w/ kids · 1b Single-parent families w/ kids · 2 Multi-generational households · 3a/3b Families w/ young adults (no kids) | Build the most structurally-constrained households first, while there's a full population to choose from. |
| **B. Couples / singles** | 4a Elderly couples · 4b Elderly singles · 5a Adult couples · 5b Adult singles · 6 Young-adult pairs | Pair off and place remaining adults / elderly. |
| **C. Communal residences** | Kids → Boarding schools · Elderly (50+) → Care homes (`oldest_first`) · Young adults (16+) → Student dorms · 10 Multi-elderly households (`refresh_pools: true`) | These `venue` steps move people *out* of the household pool. The multi-elderly step refreshes pools afterwards so we don't try to re-place care-home residents. |
| **D. Top up existing households** (`household_excess`) | 11 Extra kids → kid-families · 11 More YA → YA households · 12a/12b YA → adult families w/o kids · 13 YA → families w/ kids · 14 YA → multi-gen · 15 Old Adults → multi-gen · 16 More elderly → multi-elderly · 17 More adults → multi-gen | Inflate already-built households using poisson-distributed counts to mop up surplus people while respecting size constraints (`category_sum max: ...`). |
| **E. Flexible households** | 18 Flexible households (`pattern: "0 >=0 >=0 >=0"`, `max_household_size: 10`) · then add Adults / Old Adults / YA to them | A general-purpose adult-only household pattern that absorbs whoever's left. |
| **F. Final cleanup** | `household_promotion` (couples accept young adults; singles become multi-adult; elderly singles → couples) · `household_overflow` for remaining YA / Adults / Old Adults · final `Promote and allocate all remaining` | Last-ditch passes that *will* place everyone, even if it means stretching existing patterns. |

If a population is balanced, very few steps in Phase F need to fire. If it's unbalanced, the demotion/promotion logic in §5.2.1 plus these final steps make sure no person goes unallocated.

To **change the order**, reorder the `steps:` list. To **drop a step**, comment its block. To **tighten** allocations, lower `max_household_size`, lower `category_sum max`, or narrow `add_distribution.max`.

#### 5.2.3 `relationship_rules.yaml` — internal household structure

Steps that say `rule: "..."` look up that rule here. The shipped rules:

| Rule | Used by | Constraints enforced |
|---|---|---|
| `Two-adult family with kids` | Step 1a | Kids vs. Adults age gap 16–50 (preferred normal(μ=32, σ=6)); 2 Adults form a romantic pair (≈3-yr age diff, std 5, max 19). |
| `Single-adult family with kids` | Step 1b + demoted 1a | Same parent–child age gap; no pair constraint (single parent). |
| `Two-adult family with young adults` | Step 3a | Same as 1a but Adults vs. Young Adults. |
| `Single-adult family with young adults` | Step 3b + demoted 3a | Single-parent variant. |
| `Adult pair` | Step 5a | Two compatible adults; flagged as romantic couple. |
| `Elderly pair` | Step 4a | Two compatible elderly; flagged as romantic couple. |
| `Add young adults to existing family` | Steps 12a/12b/13/14 | New YA must be 16–50 yrs younger than existing adults. |
| `Multi-generational household` | Steps 2, 15, 17 | Three age tiers: Kids ↔ Adults gap (μ=32, σ=6), Adults ↔ Old Adults gap (μ=30, σ=7), 2-Adult pair sex/age compatibility. |

**Two important data-driven mechanisms:**

1. **Same-sex pairing per area.** The `same_category_sources:` block at the top of `relationship_rules.yaml` reads `data/population/sexual_orientation/orientation_by_msoa_normalized.csv` (per-MSOA ONS marginals) and computes `P(same-sex couple) = homosexual + 0.5 * bisexual` per MSOA. Couple-forming rules use this live, falling back to `same_category_probability_fallback: 0.05` only when an MSOA isn't in the table.
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
| Tweak parent–child age realism | `relationship_rules.yaml` → `preferred_distribution` on the relevant rule |
| Change couple age gap | `relationship_rules.yaml` → `pair_matching.numerical_attribute` |
| Change same-sex couple probability | `relationship_rules.yaml` → `same_category_sources` formula, or the per-rule `same_category_probability_fallback` if you have no per-area data |

### 5.3 `yaml/attributes/*.yaml`

One file per attribute the simulation assigns:

| File | Assigns |
|---|---|
| `attribute_assignment.yaml` | Ethnicity (with parent → child inheritance rules). |
| `comorbidity_assignment.yaml` | Health comorbidities, by age × sex × ethnicity × region. |
| `workplace_assignment.yaml` | Workplace LGU + work mode (Home / Hybrid / Normal). |
| `workplace_sgu_assignment.yaml` | Workplace SGU within the chosen LGU. |
| `work_sector_assignment.yaml` | Industry sector (A, Q, P …). |

Each YAML declares its **dependencies** (e.g. comorbidities require ethnicity), **filters** (who is eligible), and **data sources** (which CSV provides the probabilities).

### 5.4 `yaml/distributors/*.yaml`

One file per venue distribution step. Each tells the engine:

- which venue type to fill (`venue_type`),
- which `activity_map_key` to set on the person (`primary_activity`, `medical`, `leisure`, …),
- eligibility filters,
- selection logic (distance, capacity, attribute matching),
- subset assignment (e.g. school → "student" subset).

Common distributors: `school_distributor.yaml`, `university_distributor.yaml`, `company_distributor.yaml`, `hospital_distributor.yaml`, `multi_venue_distributor.yaml` (leisure), `specific_workplace_*` (Q-sector → hospitals/care homes, P-sector → schools).

### 5.5 `yaml/venue_child_creators/*.yaml`

Break a parent venue into children. Examples: `school_classrooms.yaml` (school → classrooms by age), `university_uni_years.yaml` (university → year groups), `company_offices.yaml` (company → offices by sizeband).

### 5.6 `yaml/relationships/*.yaml`

- **`friendships.yaml`** — generic peer network. Configurable: connections per person, source mix (activity peers, neighbours), filters (same role, age range).
- **`romantic_relationships.yaml`** — sexual orientation + partnership probabilities. For UK runs, leaves the `data_sources` block enabled to use ONS-derived MSOA-level orientation data.

### 5.7 `yaml/serialization_config.yaml`

Controls **what is written to `world_state.h5`**. Edit to:

- Add/remove fields under `population.properties` (e.g. enable `work_sector`).
- Add/remove fields under each `venues.types.*.properties`.
- Toggle coordinates, hierarchy export, compression level.

If you add a new property (e.g. `income`) to people via attribute YAMLs, you must also list it here for it to appear in the HDF5 file.

---

## 6. The `data/` Folder — input CSVs

```
data/
├── geography/
│   ├── hierarchy.csv          # SGU,MGU,LGU,XLGU
│   ├── coord_sgu.csv
│   └── coord_mgu.csv
├── population/
│   ├── demographics_male.csv  # rows=SGU, cols=ages 0–99
│   ├── demographics_female.csv
│   ├── comorbidities/
│   ├── ethnicity/
│   ├── leisure_participation/
│   └── sexual_orientation/
├── households/
│   ├── households.csv         # geo_unit + columns of composition patterns
│   └── household_allocations.csv  (output)
├── venues/
│   ├── primary_activities/    # Schools_EW.csv, uk_universities.csv, companies.csv
│   ├── medical/hospitals.csv
│   ├── residences/            # care_homes.csv, boarding_schools.csv, student_dorms.csv
│   ├── leisure/               # cinemas.csv, groceries.csv, gyms.csv, pubs.csv
│   └── venue_allocations.csv  (output)
└── activities/
    └── work/                  # commuting flows + sex × industry × LAD
```

### 6.1 Required column conventions

Every venue CSV must include:

- `geo_unit` — geographical code matching one of the levels in `hierarchy.csv`.
- `name` — unique within the file.
- `latitude`, `longitude` — optional but used by distance-based distributors.

Beyond that, columns must match what the relevant YAML expects. For example:

| File | Required by | Required columns |
|---|---|---|
| `Schools_EW.csv` | `school_distributor.yaml` | `StatutoryLowAge`, `StatutoryHighAge`, `Gender`, `SchoolCapacity` |
| `uk_universities.csv` | `university_distributor.yaml` | `n_students` |
| `companies.csv` | `company_distributor.yaml` | `industry_code`, `sizeband`, `employee_count` |
| `hospitals.csv` | `hospital_distributor.yaml` | `n_beds`, `estimated_staff` |
| `care_homes.csv` | `venues_config.yaml` (care_home) | `capacity`, `age_50_64_male`, … `age_95_plus_female` |
| `boarding_schools.csv` | `venues_config.yaml` (boarding_school) | `n_total`, `n_0_15_male`, `n_16_24_female`, … |
| `student_dorms.csv` | `venues_config.yaml` (student_dorms) | `n_total`, `n_16_24`, … `n_65_99` |

### 6.2 `households.csv` format

```
geo_unit, "0 0 0 2", "0 0 2 0", "0 0 0 1", "1 >=0 2 0", ...
E00000001, 16,        22,        16,        6, ...
```
Each non-`geo_unit` column header is a household composition pattern using the categories defined in `households_config.yaml`. The cell value is the **count of households** of that pattern in that area. Patterns can be exact (`2`) or open (`>=2`).

### 6.3 Adding a new area / new census year

For an England-2021 build:

1. Replace the files under `data/geography/` with 2021 OA → MSOA → LAD → Region hierarchy and centroids.
2. Replace `data/population/demographics_{male,female}.csv` with 2021 census age × sex per OA.
3. Replace `data/households/households.csv` with 2021 household composition counts per OA.
4. Update venue CSVs (`Schools_EW.csv`, `uk_universities.csv`, `companies.csv`, `hospitals.csv`, …) with 2021 inventories.
5. Update region-keyed reference files: `data/population/comorbidities/`, `data/population/ethnicity/`, `data/population/sexual_orientation/`.
6. Update commuting flow / industry tables under `data/activities/work/`.

You do **not** need to change YAML structure unless you change column names or category boundaries.

---

## 7. Common Customisations

| You want to… | Edit |
|---|---|
| Build only one region | `yaml/config.yaml` → `geography.filter` |
| Skip leisure venues | In `yaml/config.yaml` timeline, comment out the `multi_venue_distributor` step |
| Disable a venue type | `yaml/venues/venues_config.yaml` → set `enabled: false` |
| Change age categories | `yaml/households/households_config.yaml` → `categories` |
| Change household allocation order | `yaml/households/allocation_strategy.yaml` → reorder `steps` |
| Add a new attribute to HDF5 export | `yaml/serialization_config.yaml` → `population.properties` |
| Turn off romantic relationships | `yaml/config.yaml` → `romantic_relationships.enabled: false` |
| Turn off friendships | `yaml/config.yaml` → `relationship_pipeline.enabled: false` |
| Re-enable the debug CSV outputs (small worlds only) | `yaml/config.yaml` → `debug_outputs.enabled: true` |
| Change number of friend connections | `yaml/relationships/friendships.yaml` → `connections.default` |
| Filter who can go to leisure venues | `yaml/distributors/multi_venue_distributor.yaml` → `eligibility.global_filters` |

---

## 8. Validating a Run

After `python create_world.py` finishes, sanity-check:

1. **Console summary** — the script logs counts of people, venues, and allocations.
2. **`world_state.h5`** — open in Python with `h5py` to inspect the exported groups (`population`, `geography`, `venues`, `relationships`).
3. **`data/venues/venue_allocations.csv`** and **`data/households/household_allocations.csv`** — quick CSV-level checks (totals, distribution).
4. **Detailed romantic CSVs** (if enabled) — `romantic_relationships_detailed.csv`, `cheating_network_detailed.csv`.

Tests live in `tests/`. Run `pytest` to verify nothing is broken before/after a change.

---

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `KeyError` on a CSV column | A YAML references a column name that doesn't exist in the CSV — align them. |
| Many people unallocated to households | Population doesn't match `households.csv` totals; check demotion/promotion settings in `households_config.yaml`. |
| `if_no_match: error` from school distributor | Boarding-school name in residences CSV doesn't match a school in `Schools_EW.csv`. |
| Workplace step assigns no one | Education steps haven't been run before workplace assignment, or `primary_activity` filter is excluding everyone. |
| Property missing from `world_state.h5` | Add it to `yaml/serialization_config.yaml`. |
| Geography filter returns 0 areas | `filter.level` doesn't match the level the codes belong to (e.g. LAD codes with `level: MGU`). |

---

## 10. Example: building England 2021

A minimal `yaml/config.yaml` change for an England-wide 2021 run:

The shipped geography data covers the whole UK (England + Scotland + Wales + Northern Ireland), so to restrict the build to **England only** filter on the `XLGU` (region) level and list every English region explicitly:

```yaml
geography:
  data_dir: "data/geography"
  levels: ["SGU", "MGU", "LGU", "XLGU"]   # OA -> MSOA -> LAD -> Region
  load_all: false                         # use the filter below
  filter:
    level: XLGU
    codes: ["East Midlands", "East of England", "London", "North East", "North West", "South East", "South West", "West Midlands", "Yorkshire and The Humber"]

population:
  data_dir: "data/population"
  demographics_male_file: "demographics_male.csv"
  demographics_female_file: "demographics_female.csv"

# Leave venues, households, timeline, relationship_pipeline, romantic_relationships
# at their defaults — they already point at the modern UK YAMLs.
```

> Tip: omitting any of the nine regions narrows the build to the listed subset (e.g. drop everything except `London` and `South East` for a London-region run). Setting `load_all: true` instead would include Scotland, Wales, and Northern Ireland.

Then ensure all CSVs under `data/` reflect 2021 inputs (see §6.3) and run:

```bash
python create_world.py --config yaml/config.yaml --filename england_2021.h5
```
