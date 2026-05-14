# comorbidity_assignment.yaml

Assigns a list of health conditions to each agent using independent Bernoulli sampling stratified by sex, age band, ethnicity, and region.

**Topic:** [Attributes](index.md)  
**Path:** `configs/2021/attributes/comorbidity_assignment.yaml`

See [`attribute_assignment.yaml`](attribute-assignment.md) for the full attribute YAML schema. This page documents only the keys specific to person-level probabilistic condition assignment.

---

## Key-specific Notes

```yaml
attribute:
  name: "comorbidities"
  data_type: "list"                   # assigned value is a list of condition names
  assignment_level: "person"          # each person assigned independently

required_attributes:
  - name: "ethnicity"
    mapping:
      W: "W"
      O: "CO"                         # remap internal code to CSV code

region_mapping:                       # maps XLGU names to CSV region labels
  "East of England": "East"
  # ...

categories:                           # age bands used as lookup keys
  - name: "Children (0-9)"
    csv_value: "0-9"                  # string used in the CSV row key
    attribute: "age"
    type: "numerical"
    numerical: {min: 0, max: 9}

data_sources:
  comorbidity_probabilities:
    type: "csv_lookup"
    files:
      - path: "data/population/comorbidities/comorbidities_by_region.csv"
        key_columns:
          sex:
            attribute: "sex"
            type: "direct"
          age_band_min:
            attribute: "age"
            type: "category_lookup"   # maps age value → category symbol via `categories`
          combined_ethnicity_less:
            attribute: "ethnicity"
          region:
            attribute: "geographical_unit"
            type: "ancestor_lookup"
            level: "XLGU"
            property: "name"
            mapping: "region_mapping"
        value_columns:
          cvd: "has_had_cvd_diagnosis_count_midpoint_rounded"
          crd: "has_had_crd_diagnosis_count_midpoint_rounded"
          # ... one entry per condition column

assignment_rules:
  person:
    rules:
      - assignment:
          strategy: "probabilistic_conditions"
          data_source: "comorbidity_probabilities"
          selection_method: "independent_bernoulli"
                                      # each condition sampled independently
          conditions:
            - name: "cvd"             # internal key; must match value_columns key
              label: "Cardiovascular Disease"
            - name: "crd"
              label: "Chronic Respiratory Disease"
            # add/remove conditions here

settings:
  normalize_probabilities: false      # conditions are independent — do not normalise
  error_handling:
    missing_required_attribute: "skip_person"
    invalid_age: "skip_person"
    invalid_sex: "skip_person"
```
