# allocation_strategy.yaml

Ordered list of allocation steps executed sequentially during world creation. Each step is one of five types: `household`, `venue`, `household_excess`, `household_promotion`, or `household_overflow`. Earlier steps get first pick of the unallocated population.

**Topic:** [Households](index.md)  
**Path:** `configs/2021/households/allocation_strategy.yaml`

---

## Full Schema

```yaml
enabled: true               # false → skip household allocation entirely

steps:

  # ============================================================
  # TYPE: household
  # Creates new households matching given composition patterns.
  # ============================================================
  - name: "Two-Adult Families with Children"   # arbitrary label for logging
    type: "household"

    patterns:               # list of composition patterns to match
      - ">=2 >=0 2 0"       # simple string form
      - pattern: ">=2 >=0 >=0 >=0"
        assumption: "2 0 1 1"  # concrete shape assumed for sizing when pattern is open-ended

    rule: "Two-adult family with kids"
                            # optional — name of a rule in relationship_rules.yaml
                            # enforces internal age/pairing constraints

    max_households: null    # optional — cap on households created by this step (null = no limit)
    max_household_size: 10  # optional — maximum members per household
    allocate_flexible: true # optional — randomly fill flexible (>=) slots when true

    refresh_pools: false    # true → rebuild unallocated-person pools before this step
                            # use after venue steps to exclude residents from household pool

    enable_demotion: null   # optional — override global demotion setting for this step
                            # null = use global; true/false = force on/off

    demotion_rules:         # optional — when a pattern demotes, switch to a different rule
      ">=2 >=0 1 0": "Single-adult family with kids"


  # ============================================================
  # TYPE: venue
  # Sends eligible people to a communal residence venue.
  # ============================================================
  - name: "Elderly to Care Homes"
    type: "venue"

    venue_type: "care_home"              # must match a key in venues_config.yaml

    allocation_mode: "attribute_aware"   # optional — enables age/sex slot matching
    use_attribute_capacities: true       # optional — use capacity_config.attribute_capacities

    subset_key: "resident"               # optional — subset name assigned within the venue

    eligibility:                         # optional — pre-filter before slot matching
      - attribute: "age"
        min: 50                          # inclusive; omit for no lower bound
        max: 100                         # optional inclusive upper bound
      # - attribute: "sex"
      #   value: "female"               # exact categorical match

    strategy: "random" | "oldest_first" | "youngest_first"
                                         # selection order within eligible pool

    max_allocations: null                # optional — cap on total allocations (null = fill capacity)


  # ============================================================
  # TYPE: household_excess
  # Adds more members of one category to existing households.
  # ============================================================
  - name: "Add Excess Kids to Families"
    type: "household_excess"

    target_patterns:           # existing households whose current pattern matches one of these
      - ">=2 >=0 2 0"

    add_category: "Kids"       # category name to draw new members from

    rule: "Add young adults to existing family"
                               # optional — relationship rule to enforce during addition

    constraints:               # optional — cap size after addition
      - category_sum: ["Kids", "Young Adults"]
        max: 8                 # combined count of these categories must not exceed max

      - category: "Kids"       # optional — single-category cap
        max: 4

      - household_size: true   # optional — cap on total household size
        max: 10

    add_distribution:          # optional — how many members to add per household
      type: "poisson"          # "poisson" | "weighted" | "normal"
      mean: 2                  # poisson lambda
      min: 0                   # clamp minimum (default 0)
      max: 4                   # clamp maximum

      # weighted form:
      # type: "weighted"
      # probabilities: {0: 0.4, 1: 0.35, 2: 0.20, 3: 0.05}

      # normal form:
      # type: "normal"
      # mean: 1.5
      # std: 0.7

    max_per_household: null    # optional — hard cap on additions per household (null = no limit)
    refresh_pools: false


  # ============================================================
  # TYPE: household_promotion
  # Loosens existing household patterns to accept new members.
  # ============================================================
  - name: "Promote households for specific categories"
    type: "household_promotion"

    promotion_rules:           # explicit source → target pattern transformations
      - source_pattern: "0 0 2 0"
        target_pattern: ">=0 >=0 2 0"
        accept_categories: ["Kids", "Young Adults"]   # categories allowed into the promoted slot
        max_to_add: 3          # maximum new members added via this rule

    target_categories:         # alternative form: promote ALL households to accept these categories
      - "Young Adults"         # (used in the final "catch-all" promotion step)
      - "Adults"

    refresh_pools: false


  # ============================================================
  # TYPE: household_overflow
  # Last-resort: distributes ALL remaining members of one category
  # across existing households, weighted by pattern.
  # ============================================================
  - name: "Overflow remaining Young Adults"
    type: "household_overflow"

    target_patterns:           # households eligible to receive overflow members
      - "0 >=0 >=0 >=0"
      - "0 >=0 0 0"

    add_category: "Young Adults"

    pattern_bias:              # optional — relative weight for each target pattern
      "0 >=0 >=0 >=0": 2.0     # higher weight → more likely to receive overflow
      "0 >=0 0 0": 5.0

    refresh_pools: false
```
