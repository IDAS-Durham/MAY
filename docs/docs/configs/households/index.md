# Households

Controls how agents are placed into domestic units. Three co-operating files define: what age categories exist, the ordered sequence of allocation steps, and the structural rules that govern relationships within each household.

| File | Purpose |
|---|---|
| [`households_config.yaml`](households-config.md) | Age category definitions; demotion and promotion rules when population and household data are mismatched |
| [`allocation_strategy.yaml`](allocation-strategy.md) | Ordered list of allocation steps — households, communal venues, excess fill, overflow, and promotion |
| [`relationship_rules.yaml`](relationship-rules.md) | Internal household structure rules: role definitions, age-gap constraints, pair-matching for couples |
