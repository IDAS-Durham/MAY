# romantic_relationships.yaml

Controls sexual orientation assignment and romantic partnership formation. Two modes are available: data-driven (ONS-derived per-area probabilities, recommended for UK worlds) and YAML-only fallback (hand-tuned national probabilities, used when area-level data is unavailable).

**Topic:** [Relationships](index.md)  
**Path:** `configs/2021/relationships/romantic_relationships.yaml`

---

## Keys

| Key | Description |
|---|---|
| `name` | Arbitrary label for this relationship config |
| `min_age` / `max_age` | Age bounds for orientation and partnership assignment |
| `data_sources` | Paths to ONS-derived prevalence and per-area CSV files; omit to use YAML fallback |
| `diagnostics` | Logging options for verification runs |
| `sexual_orientations` | Orientation types, probabilities, age adjustments, and compatibility rules |
| `storage` | Keys written to `person.properties` for orientation and relationship status |

---

## `name`, `min_age`, `max_age`

```yaml
name: "romantic_relationships"
min_age: 16
max_age: 120
```

`name` is used only for logging. `min_age` and `max_age` define the age window for assignment; people outside this range are skipped entirely for both orientation and partnership steps.

---

## `data_sources`

```yaml
data_sources:
  prevalence_path: "data/population/sexual_orientation/orientation_prevalence_extended.csv"
  msoa_marginal_path: "data/population/sexual_orientation/orientation_by_msoa_normalized.csv"
  geo_level: "MGU"
```

When present, the engine uses raked probabilities: national prevalence by sex × age is combined with per-area orientation marginals to produce `P(orientation | sex, age, area)`. `prevalence_path` points to the national-level file; `msoa_marginal_path` to the per-area file; `geo_level` names the geography level at which area codes in that file are expressed.

Omit this entire block for worlds without area-level orientation data — the engine falls back to the `sexual_orientations.probabilities` values below.

---

## `diagnostics`

```yaml
diagnostics:
  verbose: false
```

`verbose: true` enables detailed per-run logging: a national-vs-empirical orientation comparison, MSOA quintile sweep, and assignment diagnostics. This walks the full population multiple times — leave `false` for production runs, enable only when verifying a code change.

---

## `sexual_orientations`

```yaml
sexual_orientations:
  types:
    - heterosexual
    - homosexual
    - bisexual
  probabilities:
    male:
      heterosexual: 0.90
      homosexual: 0.05
      bisexual: 0.05
  age_adjustments:
    "16-25":
      bisexual: 1.3
    "75+":
      homosexual: 0.7
  compatibility:
    heterosexual:
      male: [female]
      female: [male]
    bisexual:
      male: [male, female]
      female: [male, female]
```

`types` lists the orientation labels in the order they will be processed. Any string is valid; the labels must be consistent with `probabilities`, `age_adjustments`, and `compatibility`.

`probabilities` provides fallback national-level probabilities keyed by sex then orientation. Used when `data_sources` is absent or when an area is missing from the marginals CSV. Values need not sum to 1.0 — the engine re-normalises after any age adjustments.

`age_adjustments` applies multiplicative adjustments to the base probabilities for a given age band. Keys are age-range strings in the format `"min-max"` or `"min+"`. Each adjustment is applied as a multiplier to the named orientation's probability before re-normalisation. This allows, for example, higher bisexual rates among younger cohorts or lower rates for specific orientations in older age groups.

`compatibility` maps each orientation and sex to the list of partner sexes that are considered compatible. The engine uses this when searching for a partner: a candidate is eligible only if their sex appears in the compatibility list for the person's orientation and sex. Any sex values defined in the population may be listed; there is no restriction to `male`/`female`.

---

## `storage`

```yaml
storage:
  orientation_key: "sexual_orientation"
  status_key: "relationship_status"
```

`orientation_key` is the key written to `person.properties` for the assigned orientation string. `status_key` is the key written for partnership status. Both keys must also be listed in `serialization_config.yaml` under `population.properties` to appear in the HDF5 output.
