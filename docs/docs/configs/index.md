# Configuration Reference

This reference documents every available key across all MAY configuration YAML files. It is engine-agnostic: keys are described as the engine supports them, independent of any specific world configuration.

For a narrative walkthrough of how to use these files together, see the [User Guide](../USER_GUIDE.md).

## Structure

Configuration files are grouped by topic. Each topic has an overview page listing the relevant files, and a dedicated page per YAML file containing a full annotated schema.

| Section | Purpose |
|---|---|
| [Master Config](master-config.md) | Top-level `config.yaml` — entry point for all sections |
| [Venues](venues/index.md) | Venue type catalogue and capacity configuration |
| [Households](households/index.md) | Household composition, allocation strategy, internal relationship rules |
| [Attributes](attributes/index.md) | Per-person attribute assignment (ethnicity, comorbidities, workplace, etc.) |
| [Distributors](distributors/index.md) | Venue distribution — who goes where |
| [Venue Child Creators](venue-child-creators/index.md) | Sub-division of parent venues into child venues |
| [Relationships](relationships/index.md) | Social networks and romantic relationships |
| [Serialization](serialization/index.md) | HDF5 export — what gets written and where |

## Conventions Used in This Reference

```yaml
key: value             # Required key
key: value             # optional — key may be omitted
key: "a" | "b" | "c"  # Enumerated: one of the listed values
key: true | false      # Boolean
key: ~                 # null / not set
```
