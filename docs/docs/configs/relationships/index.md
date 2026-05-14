# Relationships

Builds agent networks after venue allocation is complete. Two separate pipelines are configured here: social networks (friendship/contact graphs) and romantic relationships (sexual orientation and partnerships).

| File | Purpose |
|---|---|
| [`social_networks.yaml`](social-networks.md) | Defines one or more social contact networks using a `networks:` list; each entry specifies pool type, algorithm, contact counts, and constraints |
| [`romantic_relationships.yaml`](romantic-relationships.md) | Sexual orientation assignment and partnership formation; supports ONS-derived per-MSOA probabilities or YAML-only fallback |
