# work_sector_assignment.yaml

Assigns `work_sector` — a single industry sector code (A–Q) — by sampling from LGU × sex stratified employment distributions.

**Topic:** [Attributes](index.md)  
**Path:** `configs/2021/attributes/work_sector_assignment.yaml`

See [`attribute_assignment.yaml`](attribute-assignment.md) for the full attribute YAML schema. This page documents only the keys specific to categorical sampler assignment.

---

## Key-specific Notes

```yaml
attribute:
  name: "work_sector"
  data_type: "categorical"
  assignment_level: "person"

filters:
  age:
    attribute: "age"
    type: "numerical"
    numerical: {min: 18, max: 64}

required_attributes:
  - name: "workplace_location"
    required: true
    error_if_missing: true
  - name: "workplace_sgu"
    required: true
    error_if_missing: true

data_sources:
  workplace_industry_by_sex:
    type: "csv_lookup"
    files:
      - path: "data/activities/work/EW_industry_sex_lad.csv"
        key_columns:
          LGU_name:
            attribute: "workplace_location"
            type: "direct"            # read from person.properties["workplace_location"]
          Sex:
            attribute: "sex"
            type: "direct"
        value_columns:
          A: "Agriculture; Forestry; Fishing"
          B: "Mining and Quarrying"
          C: "Manufacturing"
          # ... one entry per sector column
          P: "Education"
          Q: "Human Health and Social Work Activities"
          Other: "Other"
    fallback:
      A: 0.01
      C: 0.08
      G: 0.15
      # ... national approximation

assignment_rules:
  person:
    rules:
      - assignment:
          strategy: "categorical_sampler"
                                      # samples ONE sector from the probability distribution
          data_source: "workplace_industry_by_sex"

settings:
  normalize_probabilities: true
  error_handling:
    missing_geo_unit: "use_fallback"
    missing_filter_activity: "skip_person"
```
