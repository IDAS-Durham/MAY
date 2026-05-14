# relationship_rules.yaml

Defines named rules that govern the internal structure of households. Rules specify roles, how many people fill each role, and constraints on their attributes. Allocation steps in `allocation_strategy.yaml` reference rules by name via the `rule:` key.

**Topic:** [Households](index.md)  
**Path:** `configs/2021/households/relationship_rules.yaml`

---

## Full Schema

```yaml
enabled: true


# ============================================================
# PER-AREA SAME-CATEGORY PROBABILITY SOURCES
# ============================================================
# Overrides the scalar same_category_probability_fallback on a per-area basis
# for pair_matching constraints. When a candidate's geography is found in the
# source CSV the live probability is used; the scalar fallback applies otherwise.

same_category_sources:                  # optional — omit to use scalar fallbacks only
  - attribute: "sex"                    # which categorical_attribute this source applies to
    csv_path: "data/.../file.csv"       # one row per area
    geo_code_column: "geo_unit"         # column holding the area code
    geo_level: "MGU"                    # geography level of those codes (SGU/MGU/LGU/XLGU)
    formula:                            # linear combination of CSV columns → probability
      - column: "homosexual"
        weight: 1.0
      - column: "bisexual"
        weight: 0.5
    # result is clamped to [0, 1]


# ============================================================
# SELECTION STRATEGY
# ============================================================
selection_strategy:
  max_attempts: 10                      # attempts per role before demotion
  use_best_candidate: true              # pick candidate with lowest constraint penalty
  penalty_mode: "squared"               # "squared" | "linear" — penalty scaling
  log_violations: true                  # optional — log constraint violations

  backtracking:
    enabled: true                       # retry with a different first-role person
                                        # before falling back to demotion
    max_backtracks: 3
    strategy: "first_role"              # always backtrack to the first role
    log_backtracks: true                # optional
    avoid_duplicates: true              # don't retry the same first-role person


# ============================================================
# STATISTICS
# ============================================================
track_statistics: true                  # optional — collect allocation statistics


# ============================================================
# RULES
# ============================================================
rules:
  - name: "Two-adult family with kids"  # referenced by rule: in allocation_strategy.yaml

    patterns:                           # household patterns this rule applies to
      - ">=2 >=0 2 0"
      - "1 >=0 2 0"

    roles:
      role_A:                           # arbitrary role name
        categories: ["Kids"]            # one or more category names from households_config.yaml
        count: "any"                    # "any" | integer

      role_B:
        categories: ["Adults"]
        count: 2

    selection_order:                    # roles are filled in this order
      - role_A
      - role_B

    constraints:

      # -- numerical_attribute_difference --
      # Validates: (role_1[attribute] - role_2[attribute]) ∈ [min_difference, max_difference]
      - type: "numerical_attribute_difference"
        attribute: "age"
        role_1: "role_B"
        role_2: "role_A"
        min_difference: 16
        max_difference: 50

        max_difference_by_categorical_attribute:   # optional — per-category override of max_difference
          attribute: "sex"
          values:
            female: 50
            male: 55

        preferred_distribution:                    # optional — soft target for the difference
          type: "normal"                           # "normal" (only supported type currently)
          mean: 32
          std: 6
          tolerance: 9                             # search window: ±tolerance around sampled target

      # -- pair_matching --
      # Selects two people from a role to form a compatible pair.
      - type: "pair_matching"
        role: "role_B"

        require_exact_count: 2                     # optional — only apply when role has exactly N people

        categorical_attribute:                     # optional
          attribute: "sex"
          same_category_probability_fallback: 0.05
          # Probability that both members share the same category value.
          # Overridden per-area by same_category_sources if configured.

        numerical_attribute:                       # optional
          attribute: "age"
          mean_difference: 3.0                     # target mean |age_1 - age_2|
          std_difference: 5.0
          max_absolute_difference: 19              # hard cap on |age_1 - age_2|

        creates_romantic_couple: true              # optional — flag pair as cohabiting couple;
                                                   # picked up automatically by romantic_relationships
```
