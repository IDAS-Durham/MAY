# Attribute Assignment

Assigns categorical or list-type properties to agents using probabilistic strategies driven by data files.

**Topic:** [Attributes](index.md)  
**Paths:** `configs/2021/attributes/attribute_assignment.yaml`, `comorbidity_assignment.yaml`

---

## Overview

The attribute assigner runs against every agent in the population. It supports two assignment modes controlled by `attribute.assignment_level`:

- `person_by_residence` — processes each residence venue, classifies it by household structure, assigns roles to members, then applies per-role strategies. Used by `attribute_assignment.yaml` (ethnicity).
- `person` — processes each person independently with no household context. Used by `comorbidity_assignment.yaml` (comorbidities).

All keys are parsed by the same `AttributeAssignmentConfig` class; keys irrelevant to the chosen mode are ignored.

## Keys

| Key | Description |
|---|---|
| `attribute` | Attribute name, data type, and assignment mode |
| `required_attributes` | Attributes that must already be assigned before this runs |
| `region_mapping` | Maps geo unit names to names used in data files |
| `categories` | Value bands (e.g. age ranges) used for data lookups |
| `roles` | Household roles mapped to residence subsets |
| `household_structures` | Composition patterns that classify each household |
| `data_sources` | Probability tables loaded from CSV |
| `assignment_rules` | Per-structure or per-person assignment strategies |
| `venue_assignment_rules` | Fallback rules for non-household residence venues |
| `settings` | Execution options, error handling, logging |

---

## `attribute`

```yaml
# Person-by-residence mode (attribute_assignment.yaml)
attribute:
  name: "ethnicity"
  data_type: "categorical"
  assignment_level: "person_by_residence"
  household_venue_types: ["household"]

# Person mode (comorbidity_assignment.yaml)
attribute:
  name: "comorbidities"
  data_type: "list"
  assignment_level: "person"
```

`name` is the key written to `person.properties`. `data_type` is `"categorical"` for a single value or `"list"` for multiple conditions assigned simultaneously.

`assignment_level: "person_by_residence"` enables the household structure and role pipeline. `household_venue_types` lists which residence venue types are processed through that pipeline; residents of other venue types (e.g. `care_home`, `boarding_school`) are handled by `venue_assignment_rules` instead.

`assignment_level: "person"` bypasses household context entirely — every person is processed individually.

---

## `required_attributes`

```yaml
required_attributes:
  - name: "ethnicity"
    required: true
    error_if_missing: true
    mapping:
      W: "W"
      O: "CO"
```

Lists attributes that must already be present on the person before this assigner runs. `error_if_missing: true` halts on any person lacking the attribute; `false` skips them. `mapping` translates internal attribute values to the codes used in data file columns (e.g. internal `"O"` → CSV column `"CO"`).

Accepts both list and dict formats.

---

## `region_mapping`

```yaml
region_mapping:
  "East of England": "East"
  "Yorkshire and The Humber": "Yorkshire and The Humber"
```

Maps geo unit names (as stored on the `GeographicalUnit`) to the names used in data file rows or columns. Referenced by a data source entry with `mapping: "region_mapping"`. Omit if data files use the same names as the geography.

---

## `categories`

```yaml
categories:
  - name: "Adults (30-49)"
    symbol: "A3049"
    csv_value: "30-49"
    attribute: "age"
    type: "numerical"
    numerical:
      min: 30
      max: 49
```

Defines value bands used when a data source maps a continuous person attribute (e.g. age) to a discrete CSV row. `csv_value` is the string looked up in the data file. `max: null` means no upper bound. `type: "categorical"` is also supported, with `categorical.allowed_values: [...]` listing matching values.

Categories are matched in definition order; the first match wins.

---

## `roles`

```yaml
roles:
  primary_adult:
    type: primary
    subsets: ["Adults"]

  secondary_adult:
    type: secondary
    subsets: ["Adults"]

  children:
    subsets: ["Kids", "Young Adults"]
```

Roles map household subsets (defined in `households_config.yaml`) to assignment order and inheritance behaviour. `type` controls when a role is assigned:

| Type | Condition |
|---|---|
| `primary` | First person in the subset |
| `secondary` | After a `primary` exists for the same subset |
| `extra` | After both `primary` and `secondary` exist |
| `general` | Any matching person, regardless of count |

A role may list multiple `subsets`. Roles are defined globally and referenced by name in `assignment_rules`.

---

## `household_structures`

```yaml
household_structures:
  Family:
    description: "Households with children"
    inheritance: true
    matching_rules:
      - actual:
          - ">=1 >=0 >=0 >=0"
        description: "Any household with kids"
      - actual:
          - "0 >=1 1 <=2"
        original:
          - ">=2 >=0 1 0"
        description: "Demoted family"

  Independents:
    inheritance: false
    matching_rules:
      - actual:
          - "0 >=0 >=0 >=0"
        description: "Catch-all for no-kid households"
```

Each named structure is tested in definition order; the first match wins. `inheritance: true` enables child-inherits-from-parent logic in the `inheritance` and `reverse_inheritance` strategies.

Pattern format is `"Kids YoungAdults Adults OldAdults"` with operators `N` (exact), `>=N`, `<=N`. When a rule specifies both `actual` and `original`, both must match. When only one is given, only that is checked.

---

## `data_sources`

```yaml
data_sources:
  geo_distribution:
    type: "csv_lookup"
    files:
      - path: "data/population/ethnicity/ethnicity_5groups_by_OA.csv"
        key_column: "geo_unit"
        value_columns:
          W: "W"
          A: "A"
        total_column: "total"
    fallback:
      W: 0.81
      A: 0.09

  comorbidity_probabilities:
    type: "csv_lookup"
    files:
      - path: "data/population/comorbidities/comorbidities_by_region.csv"
        key_columns:
          sex:
            attribute: "sex"
          age_band_min:
            attribute: "age"
            type: "category_lookup"
          region:
            attribute: "geographical_unit"
            type: "ancestor_lookup"
            level: "XLGU"
            property: "name"
            mapping: "region_mapping"
        value_columns:
          cvd: "has_had_cvd_diagnosis_count_midpoint_rounded"
          crd: "has_had_crd_diagnosis_count_midpoint_rounded"
    fallback:
      cvd: 0.01
      crd: 0.01
```

`key_column` (single string) or `key_columns` (dict) defines the lookup key. In `key_columns`, each entry maps a column name to a person attribute path plus an optional lookup `type`:

| Lookup type | Behaviour |
|---|---|
| _(omitted)_ | Direct value from `person.attribute` |
| `"category_lookup"` | Maps continuous value to a category `csv_value` via `categories` |
| `"ancestor_lookup"` | Traverses the geo hierarchy to the named `level` and reads `property` |

`mapping` references a top-level `region_mapping` dict to translate the looked-up value before matching.

`value_columns` maps internal names to CSV column names. `fallback` supplies defaults when the key is not found; use `fallback: "uniform"` to draw uniformly, or name another data source to chain.

---

## `assignment_rules`

**Person-by-residence mode** (`attribute_assignment.yaml`) — rules keyed by structure name:

```yaml
assignment_rules:
  Family:
    rules:
      - role: "primary_adult"
        priority: 1
        assignment:
          strategy: "probabilistic"
          data_source: "geo_distribution"
          context: "household.geo_unit"

      - role: "secondary_adult"
        priority: 2
        assignment:
          strategy: "partnership"
          data_source: "pair_probabilities"
          partner_role: "primary_adult"
          context: ["household.geo_unit", "primary_adult.ethnicity"]
          fallback:
            strategy: "probabilistic"
            data_source: "geo_distribution"
            context: "household.geo_unit"

      - role: "children"
        priority: 4
        assignment:
          strategy: "inheritance"
          inherit_from:
            roles: ["primary_adult", "secondary_adult"]
          logic:
            - when: "count(unique_values) == 1"
              then: "values[0]"
            - when: "count(unique_values) > 1"
              then: "M"
          fallback:
            strategy: "probabilistic"
            data_source: "geo_distribution"
            context: "household.geo_unit"

      - role: "primary_elder"
        priority: 5
        assignment:
          strategy: "reverse_inheritance"
          inherit_from:
            role: "primary_adult"
          logic:
            - when: "primary_adult.ethnicity in ['W', 'A', 'B', 'O']"
              then: "primary_adult.ethnicity"
            - when: "primary_adult.ethnicity == 'M'"
              then:
                strategy: "probabilistic"
                data_source: "geo_distribution"
```

`role` may be a string or a list (all listed roles receive the same rule). `priority` controls order within a structure; lower runs first.

Assignment strategies:

| Strategy | Behaviour |
|---|---|
| `probabilistic` | Sample from `data_source` keyed by `context` |
| `partnership` | Sample conditional on `partner_role`'s already-assigned value |
| `inheritance` | Derive value from parent roles using `logic` conditions |
| `reverse_inheritance` | Infer parent value from an already-assigned child role |
| `constant` | Assign a fixed `value` |

`logic` is a list of `when`/`then` pairs evaluated in order. `inherit_from.roles` collects values from multiple roles (forward); `inherit_from.role` names a single role (reverse).

**Person mode** (`comorbidity_assignment.yaml`) — rules keyed by the literal string `person`:

```yaml
assignment_rules:
  person:
    rules:
      - priority: 1
        assignment:
          strategy: "probabilistic_conditions"
          data_source: "comorbidity_probabilities"
          selection_method: "independent_bernoulli"
          conditions:
            - name: "cvd"
              label: "Cardiovascular Disease"
            - name: "crd"
              label: "Chronic Respiratory Disease"
```

`probabilistic_conditions` assigns a list of conditions independently. `independent_bernoulli` samples each condition as a separate Bernoulli trial. Each entry in `conditions` must correspond to a key in `data_source.value_columns`.

---

## `venue_assignment_rules`

```yaml
venue_assignment_rules:
  - venue_types: ["care_home", "boarding_school"]
    assignment:
      strategy: "probabilistic"
      data_source: "geo_distribution"
      context: "venue.geo_unit"
```

Applied to persons residing in venue types not listed in `attribute.household_venue_types`. Uses the same `assignment` block as household rules. Omit if all residence types are covered by `household_venue_types`.

---

## `settings`

```yaml
settings:
  random_seed: null
  normalize_probabilities: true
  cache_lookups: true

  assignment_order:
    method: "category_priority"
    category_priorities:
      "Adults": 0
      "Young Adults": 1
      "Kids": 2
      "Old Adults": 3

  error_handling:
    missing_geo_unit: "use_fallback"
    missing_lookup_data: "use_fallback"
    missing_household_structure: "default_to_independents"
    missing_required_attribute: "skip_person"
    invalid_age: "skip_person"

  logging:
    level: "INFO"
    detailed_assignment_logging: false
    show_samples: true
    sample_size: 10
    show_attribute_distribution: false
```

`normalize_probabilities: true` normalises distributions to sum to 1 before sampling. Set `false` for `probabilistic_conditions` where each condition is independent.

`assignment_order.category_priority` controls which household subset is processed first within a structure. Lower numbers run first.

`error_handling` values: `"use_fallback"`, `"skip_person"`, or `"default_to_independents"`.
