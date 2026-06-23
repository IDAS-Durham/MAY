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
  config_file: "configs/2021/serialization_config.yaml"
  output_dir: "output/2021"   # directory; created automatically if absent
  filename: "world_state.h5"  # filename within that directory
```

The default 2021 config writes to **`output/2021/world_state.h5`**. If you pass `--filename` on the command line it takes precedence over `serialization.filename` in the config; `output_dir` is always taken from the config.

When the run finishes you will have:

- `output/2021/world_state.h5` — the serialized world (people, geography, venues, relationships). **This is the canonical output.**
- *(opt-in)* debug CSVs — `household_allocations.csv`, `venue_allocations.csv`, `residence_venues.csv`, `unallocated_people.csv`. These are **off by default** because each one builds a DataFrame the size of the population/venue set, which can blow memory on country-scale runs. Enable them only for small worlds via `debug_outputs.enabled: true` in `configs/2021/config.yaml`.

---

## 3. The Two Folders You Edit

```
MAY/
├── configs/   ← edit YAMLs to change behaviour, scope, scenarios
└── data/      ← edit CSVs to change the input statistics / locations
```

Everything else (`may/`, `world_specific_code/`, `create_world.py`) is the engine. **You do not need to touch Python code.**

The `configs/` folder contains subdirectories for each world scenario. You can edit any files under `configs/`. The rest of this guide focuses on `configs/2021/` (modern-day UK). See §5 for a description of what else is in `configs/`.

---

## 4. The Master Config — `configs/2021/config.yaml`

`configs/2021/config.yaml` is the single entry point. It points to all the other YAMLs and tells the engine which steps to run. Open it and edit in place.

It has seven top-level sections:

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
  config_file: "configs/2021/venues/venues_config.yaml"   # which venue types to load
  export_file: "venue_allocations.csv"
```
See **§5.1** to enable/disable venue types and §6 for the CSVs they read.

### 4.4 `households:` — where people live

```yaml
households:
  data_dir: "data/households"
  data_file: "households.csv"
  config_file: "configs/2021/households/households_config.yaml"
  strategy_file: "configs/2021/households/allocation_strategy.yaml"
  export_file: "household_allocations.csv"
```

### 4.5 `timeline:` — the order things happen

The `timeline.steps` list is the **execution order** of the entire simulation. Each step is one of:

- `type: attribute` — assign a property to people (e.g. ethnicity, comorbidities, work sector).
- `type: distributor` — place people into venues (school, hospital, company, leisure).
- `type: child_creator` — sub-divide a venue (school → classrooms; company → offices).

Each step references a YAML in `configs/2021/attributes/`, `configs/2021/distributors/`, or `configs/2021/venue_child_creators/`.

**To skip a step**, comment it out. **To reorder**, move the YAML block. Order matters — for example, in the **default** pipeline, schools/universities are assigned **before** workplaces, because workplace assignment skips anyone who already has a `primary_activity`. This is just how things are wired right now; with enough tinkering across the related YAMLs (eligibility filters, attribute dependencies, `require_unassigned`, etc.) the steps can in principle be reordered to suit a different scenario — but the order documented here is what currently ships.

### 4.6 `relationship_pipeline:`, `romantic_relationships:`, and `serialization:`

**`relationship_pipeline:`** builds social networks after venues are assigned. It takes a `relationships:` list; each entry points to a network config YAML. Set `enabled: false` to skip all networks.

```yaml
relationship_pipeline:
  enabled: true
  relationships:
    - config: "configs/2021/relationships/social_networks.yaml"
    # add further network configs here
```

**`romantic_relationships:`** builds sexual orientation and partnership networks. Set `enabled: false` to skip.

```yaml
romantic_relationships:
  enabled: true
  config: "configs/2021/relationships/romantic_relationships.yaml"
```

**`serialization:`** controls where the output HDF5 is written and which serialization config to use.

```yaml
serialization:
  enabled: true
  config_file: "configs/2021/serialization_config.yaml"
  output_dir: "output/2021"
  filename: "world_state.h5"
```

---

## 5. The Other YAMLs — what each folder controls

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
    └── *.yaml                            # flat layout — no subfolders
```

`configs/1911/` contains a flat set of YAML files for building a historical 1911 UK world. Its structure and keys differ from `configs/2021/`; it is provided as an example and is not covered further in this guide.

The rest of this section documents each file under `configs/2021/`.

### 5.1 `configs/2021/venues/venues_config.yaml`

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
| `configs/2021/households/households_config.yaml` | Defines **what** people are (age categories) and the global **demotion/promotion** safety nets. |
| `configs/2021/households/allocation_strategy.yaml` | Defines **the ordered list of steps** that places people into households (and into communal residences). |
| `configs/2021/households/relationship_rules.yaml` | Defines **how members of a household relate to each other** (parent–child age gaps, couple compatibility, multi-generational structure). |

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

### 5.3 `configs/2021/attributes/*.yaml`

One file per attribute the simulation assigns:

| File | Assigns |
|---|---|
| `attribute_assignment.yaml` | Ethnicity (with parent → child inheritance rules). |
| `comorbidity_assignment.yaml` | Health comorbidities, by age × sex × ethnicity × region. |
| `workplace_assignment.yaml` | Workplace LGU + work mode (Home / Hybrid / Normal). |
| `workplace_sgu_assignment.yaml` | Workplace SGU within the chosen LGU. |
| `work_sector_assignment.yaml` | Industry sector (A, Q, P …). |

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

#### 5.4.1 The `route` distributor — transit lines & commuting

The `route` distributor (`distributor_type: "route"`) is how MAY puts people onto
**shared transport lines** (train / tube / bus) and, more generally, onto any
origin→destination journey made of one or more **legs**. Commuting is the built-in
use-case, but the distributor is generic: school buses, ferries, or freight routes
plug in the same way — only the YAML and the input CSV change.

**Key idea — it is a lookup, not a router.** The distributor does **no** pathfinding
at world-build time. For each eligible person it forms a key `(origin, destination,
mode)` and looks that key up in a **precomputed routing table** you supply. If the
key is found, the person is placed as a rider on **every leg already listed** for
that journey; if not, a fallback property is applied (a "miss"). This is what lets
it scale to tens of millions of agents — all the route-finding happens once,
offline, before the run.

##### What you must provide

| File | Required? | Role |
|---|---|---|
| `route_legs.csv` | **Yes** — the distributor reads this | The itinerary table: one row per leg, keyed by `(origin, destination, mode)`. |
| `routes.csv` | Optional | A human-readable per-journey summary. **Not read by the distributor** — keep it for your own QA if you like. |
| A line→stops mapping | Only if you want geometry | Ordered stops per line. **Not used by the distributor**, but needed downstream (e.g. to draw the lines on a map). See note at the end. |

Put the CSVs anywhere under `data/` and point the YAML at them (paths are resolved
relative to the project root). The conventional location is `data/activities/commute/`.

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
(the commute configs use `t_board_min`, `t_alight_min` — minutes from start of day):

```csv
origin_mgu,dest_mgu,mode_class,leg_idx,line_id,board_mgu,alight_mgu,t_board_min,t_alight_min
E02000001,E02000016,train,0,three_bridges_west_hampstead_thameslink_0911,E02000001,E02000192,63,65
E02000001,E02000016,train,1,reading_abbey_wood_el_0739,E02000192,E02000878,58,60
```

A journey with two rows like the above (`leg_idx` 0 and 1) is a **two-leg trip with
one interchange**. The keying is **only** `(origin_mgu, dest_mgu, mode_class)` — so
every person travelling that O→D by that mode rides the **identical** leg sequence
(no per-person variation). Origin/destination are at **MGU** granularity, even though
people live and work at finer (SGU) units — the distributor rolls each up to its MGU
ancestor before the lookup (see `origin_source`/`destination_source` below).

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
   hub crossings** — a leg is a maximal run of stops on one line.
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

routes_table: "data/activities/commute/routes.csv"      # optional summary (unused at runtime)
legs_table:   "data/activities/commute/route_legs.csv"  # REQUIRED — the table read above

# How to form the routing-table key from each person:
origin_source:        # -> origin_mgu
  type: "ancestor"
  from: "geographical_unit"          # the person's residence unit (an SGU)...
  level: "MGU"                        # ...rolled up to its MGU ancestor
destination_source:   # -> dest_mgu
  type: "ancestor"
  from: "properties.workplace_sgu"   # the workplace unit set by workplace assignment...
  level: "MGU"                        # ...rolled up to MGU

# How to form mode_class, and which class this instance handles:
class_source: "properties.commute_mode"  # person property holding the mode
class_filter: "train"                     # only act on people with commute_mode == "train"
class_map: { train: "train" }             # person value -> mode_class in the CSV (identity here)

require_properties: ["commute_mode"]      # skip people missing these properties

# Per-leg CSV columns to store on Subset.member_metadata, keyed by field name:
leg_metadata:
  t_board_min:  "t_board_min"
  t_alight_min: "t_alight_min"

on_miss:                 # applied when (origin,dest,mode) isn't in the table
  set:
    commute_mode: "car_solo"
```

Field reference:

| Key | What it does |
|---|---|
| `distributor_type` | Must be `"route"`. |
| `leg_venue_type` | Venue type materialised once per `line_id`. Must be a venue type the world knows (e.g. `train_line`, `tube_line`, `bus_line`). The line venue is attached to a rider's residence MGU purely for stable HDF5 partitioning — its `geo_unit` is **not** the line's location. |
| `leg_subset_key` | Subset every rider is added to on each leg venue (e.g. `rider`). |
| `origin_source` / `destination_source` | Recipe to derive the O/D key. `type: ancestor` reads a unit (`from: geographical_unit` or `from: properties.<name>`) and rolls it up to `level`. `type: property` uses a raw property string. |
| `class_source` | Person attribute/property giving the transport class. |
| `class_filter` | Run this instance only for people whose class equals this. Run one distributor per class. |
| `class_map` | Maps the person's class value to the `mode_class` string in the CSV (identity if omitted). |
| `require_properties` | People missing any of these are skipped entirely (not even counted as misses). |
| `leg_metadata` | `{ field_name: csv_column }` — per-leg numbers copied onto `Subset.member_metadata[person.id]`. |
| `on_miss.set` | Property overrides applied when the key isn't found (the fallback, e.g. send unrouted commuters to `car_solo`). |

##### Prerequisites & ordering

The `route` distributor only works if, by the time it runs, each eligible person
already has the properties its key needs. For commuting that means the timeline must
run, **in order**:

1. **Workplace assignment** — sets `workplace_sgu` (the destination unit).
2. **Commute-mode assignment** (`attributes/commute_mode_assignment.yaml`) — sets
   `commute_mode` (the class).
3. **The `route` distributors** — one `type: distributor` step per mode class.

In `config.yaml` the commute block looks like:

```yaml
    - type: attribute
      config: "configs/2021/attributes/commute_mode_assignment.yaml"
    - type: distributor
      config: "configs/2021/distributors/route_commute_train.yaml"
    - type: distributor
      config: "configs/2021/distributors/route_commute_tube.yaml"
    - type: distributor
      config: "configs/2021/distributors/route_commute_bus.yaml"
```

##### Serialization & downstream geometry

Each line venue is serialized with its `line_id` as the venue **name**, and the
per-leg `t_board_min`/`t_alight_min` land on the membership metadata side-table in
`world_state.h5`. To know *who rides each line*, read the line venue's `rider`
subset; to reconstruct a person's full journey, order their legs by `t_board_min`.

The distributor stores **board/alight MGUs**, not the stops in between. If you need
the drawable shape of a line (a polyline through its stations), keep your line→stops
mapping (`line_id, position, node_mgu, name, …`) alongside the world and join on
`line_id` at render time — slicing each line's stop sequence between a rider's
`board_mgu` and `alight_mgu` gives exactly the segment they travel.

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

Key knobs per network entry:

| Key | What it does |
|---|---|
| `network_type` | Pool selection strategy. `activity_peers`: same venue. `intra_geo_unit`: same geographic unit. Other types (e.g. `spatial_social_network`, `local_social_network` with Watts-Strogatz) exist for other world configs. |
| `algorithm` | Contact-sampling algorithm. `random`: uniform random draw. `watts_strogatz`: clustered small-world graph (used in other configs). |
| `mean_count` | Mean number of contacts per person from this network. |
| `degree_variants` | Optional list of `{probability, count}` overrides — gives a subset of people a different contact count. |
| `storage_key` | Where contacts are stored on the person. Multiple networks sharing the same key are merged (deduplicated). |
| `constraints` | List of filters on who can be paired. `numerical_attribute_difference` enforces a max gap on a numeric attribute (e.g. age). |

To **add a new network**, append a new entry to `networks:`. To **change total contacts**, adjust `mean_count` across entries. To **skip social networks entirely**, set `relationship_pipeline.enabled: false` in `config.yaml`.

#### `romantic_relationships.yaml`

Controls sexual orientation assignment and partnership formation. Key sections:

- `data_sources:` — for UK runs, reads ONS-derived prevalence and per-MSOA orientation marginals to compute orientation probabilities. Worlds without UK MSOA codes should omit this block and use the `probabilities:` fallback below.
- `sexual_orientations.probabilities:` — fallback national-level orientation probabilities by sex, used when `data_sources` is absent or an MSOA isn't in the table.
- `sexual_orientations.age_adjustments:` — multiplicative tweaks to orientation probabilities by age band.
- `sexual_orientations.compatibility:` — which orientations can pair with which.
- `storage:` — keys under which orientation and relationship status are stored on the person.
- `diagnostics.verbose:` — set `true` to log detailed national vs. empirical orientation comparisons. Leave `false` for production runs.

### 5.7 `configs/2021/serialization_config.yaml`

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
| Build only one region | `configs/2021/config.yaml` → `geography.filter` |
| Skip leisure venues | In `configs/2021/config.yaml` timeline, comment out the `multi_venue_distributor` step |
| Disable a venue type | `configs/2021/venues/venues_config.yaml` → set `enabled: false` |
| Change age categories | `configs/2021/households/households_config.yaml` → `categories` |
| Change household allocation order | `configs/2021/households/allocation_strategy.yaml` → reorder `steps` |
| Add a new attribute to HDF5 export | `configs/2021/serialization_config.yaml` → `population.properties` |
| Turn off romantic relationships | `configs/2021/config.yaml` → `romantic_relationships.enabled: false` |
| Turn off friendships | `configs/2021/config.yaml` → `relationship_pipeline.enabled: false` |
| Re-enable the debug CSV outputs (small worlds only) | `configs/2021/config.yaml` → `debug_outputs.enabled: true` |
| Change number of friend connections | `configs/2021/relationships/social_networks.yaml` → `mean_count` on the relevant network entry |
| Filter who can go to leisure venues | `configs/2021/distributors/multi_venue_distributor.yaml` → `eligibility.global_filters` |

---

## 8. Validating a Run

After `python create_world.py` finishes, sanity-check:

1. **Console summary** — the script logs counts of people, venues, and allocations.
2. **`output/2021/world_state.h5`** — open in Python with `h5py` to inspect the exported groups (`population`, `geography`, `venues`, `relationships`).
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
| Property missing from `world_state.h5` | Add it to `configs/2021/serialization_config.yaml`. |
| Geography filter returns 0 areas | `filter.level` doesn't match the level the codes belong to (e.g. LAD codes with `level: MGU`). |

---

## 10. Example: building England 2021

A minimal `configs/2021/config.yaml` change for an England-wide 2021 run:

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
python create_world.py --config configs/2021/config.yaml --filename england_2021.h5
```
