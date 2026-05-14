# Workplace Assignment

Assigns workplace location, fine-grained spatial unit, and industry sector to working-age agents.

**Topic:** [Attributes](index.md)  
**Paths:** `configs/2021/attributes/workplace_assignment.yaml`, `workplace_sgu_assignment.yaml`, `work_sector_assignment.yaml`

---

## Overview

Three attribute configs build up a layered workplace picture, each depending on the previous:

1. `workplace_assignment.yaml` — samples a destination LGU and work mode from commuting flow matrices, assigning `workplace_location` and `work_mode`.
2. `workplace_sgu_assignment.yaml` — samples a specific SGU within the workplace LGU weighted by employment density, assigning `workplace_sgu`.
3. `work_sector_assignment.yaml` — samples an industry sector (A–Q) from LGU × sex distributions, assigning `work_sector`.

All three use `assignment_level: "person"` and are processed by the same `AttributeAssignmentConfig` class.

## Keys

| Key | Description |
|---|---|
| `attribute` | Attribute name and assignment mode |
| `filters` | Age and activity filters controlling eligibility |
| `required_attributes` | Dependencies from earlier assignments |
| `data_sources` | Lookup tables for commuting, employment, or sector distributions |
| `assignment_rules` | Person-level sampling strategy |
| `settings` | Execution options, error handling, logging |

---

## `attribute`

```yaml
# workplace_assignment.yaml
attribute:
  name: "workplace_location"
  data_type: "categorical"
  assignment_level: "person"

# workplace_sgu_assignment.yaml
attribute:
  name: "workplace_sgu"
  data_type: "categorical"
  assignment_level: "person"

# work_sector_assignment.yaml
attribute:
  name: "work_sector"
  data_type: "categorical"
  assignment_level: "person"
```

`name` is the key written to `person.properties`. All three use `assignment_level: "person"` — each agent is processed independently with no household context.

---

## `filters`

```yaml
filters:
  age:
    attribute: "age"
    type: "numerical"
    numerical:
      min: 18
      max: 64

  activities:
    exclude: ["primary_activity"]
```

`filters` restricts which persons the assigner processes. Each named filter entry is either a numerical range (`type: "numerical"`) or an activity exclusion.

`activities.exclude` skips persons who already have any of the listed keys in `activity_map` — used by `workplace_assignment.yaml` to avoid assigning a workplace location to students and others with a primary activity already set.

---

## `required_attributes`

```yaml
# workplace_sgu_assignment.yaml
required_attributes:
  workplace_location:
    description: "Workplace LGU must be assigned first"
    required: true
    error_if_missing: true

# work_sector_assignment.yaml
required_attributes:
  - name: "workplace_location"
    required: true
    error_if_missing: true
  - name: "workplace_sgu"
    required: true
    error_if_missing: true
```

Lists attributes that must already be set on the person before this assigner runs. `error_if_missing: true` causes the engine to halt; `false` skips the person silently. Accepts both dict and list formats.

`workplace_assignment.yaml` has no `required_attributes` — it runs first in the chain.

---

## `data_sources`

All three files use `type: "csv_lookup"` but with different lookup structures.

**Origin–destination matrix** (`workplace_assignment.yaml`):

```yaml
data_sources:
  commuting_flows:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW-work-destination-likelihood.csv"
        output_format: "origin_destination_matrix"
        origin_level: "LGU"
        destination_level: "LGU"
        key_columns:
          LGU_origin_name:
            attribute: "geographical_unit"
            type: "ancestor_lookup"
            level: "LGU"
            property: "name"
        destination_column: "LGU_destination_name"
        likelihood_column: "Likelihood"
        metadata_columns:
          work_mode: "Place of work indicator"
          destination_code: "LGU_destination_code"
          count: "Count"
        exclude_destinations:
          - "888888888"
          - "999999999"
    fallback: "local_work"

  local_work:
    type: "constant"
    values:
      workplace_location: "person.geographical_unit.lgu"
      work_mode: "Normal"
```

`output_format: "origin_destination_matrix"` tells the loader to treat the file as an OD matrix. `origin_level` and `destination_level` set the geo hierarchy levels used for matching. `key_columns` uses `type: "ancestor_lookup"` to traverse the hierarchy to the person's LGU.

`exclude_destinations` filters rows by destination code before sampling (e.g. removes offshore and outside-UK codes).

`metadata_columns` loads additional columns alongside the `likelihood_column` — these are returned with the sampled row and mapped to outputs in `assignment_rules`.

`type: "constant"` is a fallback source that returns fixed values. `values` may reference person attribute paths.

**Geographical unit sampler** (`workplace_sgu_assignment.yaml`):

```yaml
data_sources:
  sgu_employment_distribution:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW_workers_by_industry_by_OA.csv"
        key_column: "LGU"
        geographical_unit_column:
          name: "SGU"
          level: "SGU"
        weight_column: "Total"
        exclude_rows:
          - column: "SGU"
            values: ["ALL"]
```

`geographical_unit_column` tells the loader to build a weighted probability distribution over geo units. `name` is the CSV column containing geo unit codes; `level` is the hierarchy level those codes belong to. `weight_column` provides the sampling weights. `exclude_rows` filters out aggregate rows before building the distribution.

**Multi-key lookup** (`work_sector_assignment.yaml`):

```yaml
data_sources:
  workplace_industry_by_sex:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW_industry_sex_lad.csv"
        key_columns:
          LGU_name:
            attribute: "workplace_location"
            type: "direct"
          Sex:
            attribute: "sex"
            type: "direct"
        value_columns:
          A: "Agriculture; Forestry; Fishing"
          P: "Education"
          Q: "Human Health and Social Work Activities"
    fallback:
      A: 0.01
      P: 0.09
      Q: 0.13
```

`type: "direct"` reads the attribute value from `person.properties` without any hierarchy traversal or category mapping.

---

## `assignment_rules`

All three configs use `assignment_level: "person"`, so rules are keyed by the literal string `person`.

**Commuting likelihood** (`workplace_assignment.yaml`):

```yaml
assignment_rules:
  person:
    rules:
      - priority: 1
        assignment:
          strategy: "commuting_likelihood"
          data_source: "commuting_flows"
          outputs:
            workplace_location: "destination"
            work_mode: "work_mode"
          context:
            origin: "person.geographical_unit"
          fallback:
            strategy: "constant"
            data_source: "local_work"
```

`strategy: "commuting_likelihood"` samples a `(destination, work_mode)` pair from the OD matrix weighted by `Likelihood`. `outputs` maps the sampled fields to person property names — this config assigns two attributes (`workplace_location` and `work_mode`) in a single step.

**Geographical unit sampler** (`workplace_sgu_assignment.yaml`):

```yaml
assignment_rules:
  person:
    rules:
      - priority: 1
        assignment:
          strategy: "geographical_unit_sampler"
          data_source: "sgu_employment_distribution"
```

`geographical_unit_sampler` draws an SGU from the weighted distribution built for the person's `workplace_location` (LGU). The sampled SGU code is written to `person.properties["workplace_sgu"]`.

**Categorical sampler** (`work_sector_assignment.yaml`):

```yaml
assignment_rules:
  person:
    rules:
      - priority: 1
        assignment:
          strategy: "categorical_sampler"
          data_source: "workplace_industry_by_sex"
```

`categorical_sampler` draws one category from the probability distribution keyed by the person's `workplace_location` and `sex`.

---

## `settings`

```yaml
settings:
  random_seed: null
  normalize_probabilities: true
  cache_lookups: true

  error_handling:
    missing_geo_unit: "use_fallback"
    missing_lookup_data: "use_fallback"
    missing_workplace_location: "skip_person"
    person_without_work_activity: "skip_person"
    missing_filter_activity: "skip_person"

  logging:
    level: "INFO"
    detailed_assignment_logging: false
    show_samples: true
    sample_size: 10
    show_attribute_distribution: false
```

`normalize_probabilities: true` normalises distributions to sum to 1 before sampling.

`show_attribute_distribution: false` suppresses per-value output — recommended for SGU assignment where the distribution spans tens of thousands of codes.

`error_handling` values: `"use_fallback"` or `"skip_person"`.
