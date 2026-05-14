# households_config.yaml

Defines the age categories used in household composition patterns, and the global demotion and promotion rules applied when census household counts and demographic counts disagree.

**Topic:** [Households](index.md)  
**Path:** `configs/2021/households/households_config.yaml`

---

## Keys

| Key | Description |
|---|---|
| `categories` | Named age (or attribute) bands used in composition pattern slots |
| `demotion` | Rules for relaxing household patterns when the population is too small to fill them |
| `promotion` | Rules for loosening household patterns when surplus people remain after allocation |

---

## `categories`

```yaml
categories:
  - name: "Kids"
    symbol: "K"
    attribute: "age"
    type: "numerical"
    numerical:
      min: 0
      max: 17
```

Each entry defines one slot in a composition pattern. The order of entries here determines the slot order in pattern strings — so four categories produce patterns of the form `"K YA A OA"`. The `symbol` is what appears in those strings. `attribute` is any person property (most commonly `"age"`); `type` is `"numerical"` or `"categorical"`. For numerical types, `min` and `max` are inclusive bounds; `null` means no upper limit. For categorical types, `allowed_values` lists the accepted values.

Adding, removing, or reordering categories changes the meaning of every pattern string in `allocation_strategy.yaml` and `relationship_rules.yaml`, so both files must be updated in step.

---

## `demotion`

```yaml
demotion:
  enabled: true
  max_attempts: 10
  min_household_size: 1
  priority:
    Kids: 1
    Young Adults: 2
    Old Adults: 3
    Adults: 4
  validation_rules:
    - name: "Kids require adult supervision"
      condition:
        category: "Kids"
        operator: ">="
        value: 1
      requirement:
        category: "Adults"
        operator: ">="
        value: 1
```

Demotion fires when a geo-unit lacks enough people in a given category to satisfy a household pattern. The engine relaxes the pattern step by step — reducing `>=N` bounds downward, then reducing exact counts — until either a viable pattern is found or `max_attempts` is exhausted. Patterns that would produce fewer than `min_household_size` members are discarded rather than demoted further.

`priority` controls which category is relaxed first. Lower number means demoted first — `Kids` are relaxed before `Adults` because the engine prioritises preserving at least one supervising adult. `validation_rules` gate every demotion step: if a relaxed pattern would violate a rule (e.g. kids without an adult), that pattern is rejected and demotion continues. Any number of rules may be added; each rule specifies a `condition` and a `requirement` using the operators `>=`, `>`, `==`, `<=`, `<`.

---

## `promotion`

```yaml
promotion:
  enabled: true
  max_attempts: 4
  priority:
    Young Adults: 1
    Adults: 2
    Old Adults: 3
    Kids: 4
  validation_rules:
    - name: "Kids require adult supervision"
      condition:
        category: "Kids"
        operator: ">="
        value: 1
      requirement:
        category: "Adults"
        operator: ">="
        value: 1
```

Promotion fires when leftover people remain after all allocation steps. The engine loosens existing households by converting fixed slots (`0` or `N`) to flexible slots (`>=0` or `>=N`), allowing them to absorb surplus people. `max_attempts` caps how many times any single household can be loosened.

`priority` controls which category is promoted into first. `validation_rules` use the same format as demotion and are enforced after every promotion step. Kids are promoted last (priority 4) to avoid creating households where children lack an adult.
