# workplace_assignment.yaml

Assigns `workplace_location` (LGU code) and `work_mode` to working-age agents by sampling from origin–destination commuting flow matrices.

**Topic:** [Attributes](index.md)  
**Path:** `configs/2021/attributes/workplace_assignment.yaml`

See [`attribute_assignment.yaml`](attribute-assignment.md) for the full attribute YAML schema. This page documents only the keys specific to O-D matrix commuting assignment.

---

## Key-specific Notes

```yaml
attribute:
  name: "workplace_location"
  data_type: "categorical"
  assignment_level: "person"

additional_attributes:
  - name: "work_mode"                 # assigned simultaneously with workplace_location
    data_type: "categorical"
    # values: "From_Home" | "Hybrid" | "Normal"

filters:
  age:
    attribute: "age"
    type: "numerical"
    numerical: {min: 18, max: 64}
  activities:
    exclude: ["primary_activity"]     # skip students etc. already assigned a primary activity

data_sources:
  commuting_flows:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW-work-destination-likelihood.csv"
        output_format: "origin_destination_matrix"
        origin_level: "LGU"           # hierarchy level to match person's residence
        destination_level: "LGU"      # hierarchy level of destination codes
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
          - "888888888"               # Offshore Installation
          - "999999999"               # Outside UK
    fallback: "local_work"            # name of fallback data source

  local_work:
    type: "constant"
    values:
      workplace_location: "person.geographical_unit.lgu"
      work_mode: "Normal"

assignment_rules:
  person:
    rules:
      - assignment:
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
