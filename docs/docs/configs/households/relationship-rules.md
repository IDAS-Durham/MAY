# relationship_rules.yaml

Defines named rules that govern the internal structure of households — who fills which role, and what constraints apply between them. Allocation steps reference rules by name via the `rule:` key.

**Topic:** [Households](index.md)  
**Path:** `configs/2021/households/relationship_rules.yaml`

---

## Keys

| Key | Description |
|---|---|
| `enabled` | Activates relationship rule processing |
| `same_category_sources` | Per-area data sources that override the scalar same-category probability on pair-matching constraints |
| `selection_strategy` | Controls how the engine searches for valid role combinations and handles failures |
| `track_statistics` | Enables allocation statistics collection |
| `rules` | List of named rules, each defining roles, patterns, and constraints |

---

## `enabled`

```yaml
enabled: true
```

Set `false` to disable all rule-based internal structure. Households are still formed but members are assigned without any age-gap or pairing constraints.

---

## `same_category_sources`

```yaml
same_category_sources:
  - attribute: "sex"
    csv_path: "data/population/sexual_orientation/orientation_by_msoa_normalized.csv"
    geo_code_column: "geo_unit"
    geo_level: "MGU"
    formula:
      - column: "homosexual"
        weight: 1.0
      - column: "bisexual"
        weight: 0.5
```

Provides per-area probabilities for same-category pairing, used by `pair_matching` constraints. Each source applies to one `attribute` (e.g. `"sex"`). The engine looks up the candidate's geography at `geo_level` in the CSV, then computes `P = Σ(column × weight)`, clamped to [0, 1]. This overrides the per-rule `same_category_probability_fallback` whenever the candidate's area is found in the CSV. When no source is configured, or the area is absent from the CSV, the scalar fallback applies.

Any number of sources may be listed; each applies only to `pair_matching` constraints whose `categorical_attribute.attribute` matches.

---

## `selection_strategy`

```yaml
selection_strategy:
  max_attempts: 10
  use_best_candidate: true
  penalty_mode: "squared"
  log_violations: true
  backtracking:
    enabled: true
    max_backtracks: 3
    strategy: "first_role"
    log_backtracks: true
    avoid_duplicates: true
```

Controls how the engine searches for valid role combinations. `max_attempts` sets how many candidate draws are tried per role before giving up and falling back to demotion. `use_best_candidate` — when `true` — picks the candidate with the lowest constraint penalty rather than the first valid one. `penalty_mode` sets the penalty scaling: `"squared"` penalises large violations more heavily than `"linear"`.

`backtracking` allows the engine to retry with a different first-role person when a later role cannot be filled, before resorting to demotion. `max_backtracks` caps the number of retry attempts. `strategy: "first_role"` always returns to the first role when backtracking. `avoid_duplicates` prevents retrying the same first-role person twice.

---

## `track_statistics`

```yaml
track_statistics: true
```

When `true`, the engine collects per-rule allocation statistics (success rates, demotion counts, backtrack counts) and writes them to the log at the end of household allocation.

---

## `rules`

```yaml
rules:
  - name: "Two-adult family with kids"
    patterns:
      - ">=2 >=0 2 0"
      - "1 >=0 2 0"
    roles:
      role_A:
        categories: ["Kids"]
        count: "any"
      role_B:
        categories: ["Adults"]
        count: 2
    selection_order:
      - role_A
      - role_B
    constraints:
      - type: "numerical_attribute_difference"
        ...
      - type: "pair_matching"
        ...
```

Each rule has a `name` referenced by `rule:` in `allocation_strategy.yaml`, a list of `patterns` the rule applies to, a set of named `roles`, and `constraints` between them.

`roles` maps an arbitrary role name to a `categories` list (category names from `households_config.yaml`) and a `count` — either an integer or `"any"`. `selection_order` lists roles in the order they are filled; roles filled first are drawn from a full pool, making them easier to satisfy. Roles filled later are constrained against already-selected members.

---

### Constraint type: `numerical_attribute_difference`

```yaml
- type: "numerical_attribute_difference"
  attribute: "age"
  role_1: "role_B"
  role_2: "role_A"
  min_difference: 16
  max_difference: 50
  max_difference_by_categorical_attribute:
    attribute: "sex"
    values:
      female: 50
      male: 55
  preferred_distribution:
    type: "normal"
    mean: 32
    std: 6
    tolerance: 9
```

Validates that `role_1[attribute] − role_2[attribute]` falls within `[min_difference, max_difference]`. When multiple people fill `role_2`, the check uses the minimum value for `min_difference` and the maximum for `max_difference`.

`max_difference_by_categorical_attribute` overrides `max_difference` per value of a categorical attribute on `role_1` — useful for sex-specific age-gap limits. `preferred_distribution` adds a soft preference: the engine samples a target difference from a normal distribution (with the given `mean`, `std`, and search `tolerance`) and prefers candidates close to it, while still accepting any candidate within the hard bounds.

---

### Constraint type: `pair_matching`

```yaml
- type: "pair_matching"
  role: "role_B"
  require_exact_count: 2
  categorical_attribute:
    attribute: "sex"
    same_category_probability_fallback: 0.05
  numerical_attribute:
    attribute: "age"
    mean_difference: 3.0
    std_difference: 5.0
    max_absolute_difference: 19
  creates_romantic_couple: true
```

Selects two people from a role to form a compatible pair. `require_exact_count` makes the constraint conditional — it only applies when the role contains exactly that many people; omit to always apply.

`categorical_attribute` controls same-category pairing probability. The engine draws from `same_category_sources` if the candidate's area is present; otherwise it uses `same_category_probability_fallback`. `numerical_attribute` sets a soft target for the numerical difference between the pair: `mean_difference` and `std_difference` define the preferred distribution, while `max_absolute_difference` is a hard ceiling on `|value_1 − value_2|`.

`creates_romantic_couple: true` flags the pair as a cohabiting couple; the `romantic_relationships` pipeline downstream picks them up automatically rather than re-pairing them.
