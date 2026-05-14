# households_config.yaml

Defines population age categories and the global demotion/promotion rules applied when census household counts and demographic counts do not agree.

**Topic:** [Households](index.md)  
**Path:** `configs/2021/households/households_config.yaml`

---

## Full Schema

```yaml
# ============================================================
# CATEGORIES
# ============================================================
# Named age (or attribute) bands used in composition patterns.
# The order here defines the slot order in patterns:
#   e.g. four categories → patterns of the form "K YA A OA"
# Any number of categories may be defined; names are arbitrary.

categories:
  - name: "Kids"            # human-readable label; used in rules and distribution keys
    symbol: "K"             # short symbol used in composition pattern strings
    attribute: "age"        # person attribute to categorise

    type: "numerical"       # "numerical" | "categorical"

    numerical:              # required when type is "numerical"
      min: 0                # inclusive lower bound
      max: 17               # inclusive upper bound; null → no upper limit

    # categorical:          # required when type is "categorical"
    #   allowed_values: ["male", "m", "M"]


# ============================================================
# DEMOTION
# ============================================================
# When a geo-unit lacks enough people to fill a household pattern,
# the engine relaxes the pattern (e.g. ">=2" → ">=1" → ">=0")
# until a viable composition is found or attempts are exhausted.

demotion:
  enabled: true             # false → skip demotion; unresolvable patterns are discarded

  max_attempts: 10          # maximum demotion iterations per pattern

  min_household_size: 1     # discard patterns that would produce fewer members than this

  priority:                 # which category to demote first; lower number = first
    Kids: 1
    Young Adults: 2
    Old Adults: 3
    Adults: 4               # demote Adults last — essential for supervision

  validation_rules:         # constraints enforced after every demotion step
    - name: "Kids require adult supervision"
      condition:
        category: "Kids"    # category name from the list above
        operator: ">="      # ">=" | ">" | "==" | "<=" | "<"
        value: 1
      requirement:
        category: "Adults"
        operator: ">="
        value: 1
    # Add further rules as needed


# ============================================================
# PROMOTION
# ============================================================
# When leftover people remain after all allocation steps,
# the engine loosens existing households (e.g. "0" → ">=0")
# to absorb the surplus.

promotion:
  enabled: true             # false → skip promotion

  max_attempts: 4           # maximum promotion iterations per household

  priority:                 # which category to promote first; lower number = first
    Young Adults: 1
    Adults: 2
    Old Adults: 3
    Kids: 4                 # promote Kids last — need adult supervision

  validation_rules:         # same format as demotion.validation_rules
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

---

## Composition Pattern Format

Patterns appear in `allocation_strategy.yaml` and throughout relationship rules. Each slot corresponds to one category in the order defined above:

```
"K YA A OA"        exact counts: 2 adults, 0 others → "0 0 2 0"
">=2 >=0 2 0"      2+ kids, any young adults, exactly 2 adults, 0 elderly
"1 >=0 >=0 >=0"    1 kid, flexible adults of any kind
```
