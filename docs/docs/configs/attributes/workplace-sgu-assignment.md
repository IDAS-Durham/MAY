# workplace_sgu_assignment.yaml

Assigns `workplace_sgu` — the specific SGU (Output Area) within the agent's `workplace_location` LGU — by sampling proportionally to employment density.

**Topic:** [Attributes](index.md)  
**Path:** `configs/2021/attributes/workplace_sgu_assignment.yaml`

See [`attribute_assignment.yaml`](attribute-assignment.md) for the full attribute YAML schema. This page documents only the keys specific to geo-unit sampler assignment.

---

## Key-specific Notes

```yaml
attribute:
  name: "workplace_sgu"
  data_type: "categorical"
  assignment_level: "person"

filters:
  age:
    attribute: "age"
    type: "numerical"
    numerical: {min: 18, max: 64}

required_attributes:
  workplace_location:
    required: true
    error_if_missing: true

data_sources:
  sgu_employment_distribution:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW_workers_by_industry_by_OA.csv"
        key_column: "LGU"             # match person's workplace_location LGU name
        geographical_unit_column:
          name: "SGU"                 # CSV column holding the SGU code
          level: "SGU"               # geo level; controls which geography object is sampled
        weight_column: "Total"        # rows weighted by total employment count
        exclude_rows:
          - column: "SGU"
            values: ["ALL"]           # exclude aggregate rows

assignment_rules:
  person:
    rules:
      - assignment:
          strategy: "geographical_unit_sampler"
                                      # samples a geo unit object from the loaded hierarchy,
                                      # weighted by weight_column
          data_source: "sgu_employment_distribution"

settings:
  error_handling:
    missing_workplace_location: "skip_person"
    missing_lookup_data: "skip_person"
```
