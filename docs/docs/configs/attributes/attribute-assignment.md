# attribute_assignment.yaml

Assigns a categorical attribute (e.g. ethnicity) to every agent using household-structure-aware rules, data-driven probability lookups, and optional inheritance between household members.

**Topic:** [Attributes](index.md)  
**Path:** `configs/2021/attributes/attribute_assignment.yaml`

---

## Full Schema

```yaml
# ============================================================
# ATTRIBUTE DECLARATION
# ============================================================
attribute:
  name: "ethnicity"                   # property key written to person
  description: "..."
  data_type: "categorical"            # "categorical" | "list"
  assignment_level: "person_by_residence"
                                      # "person_by_residence" — iterate households,
                                      #   assign members using structure rules
                                      # "person" — assign each person independently

  household_venue_types: ["household"]
                                      # venue types treated as households for
                                      # structure-based assignment;
                                      # other residence types use venue_assignment_rules


# ============================================================
# ADDITIONAL ATTRIBUTES  (optional)
# ============================================================
# Declare extra properties assigned as a side-effect of this YAML.
additional_attributes:
  - name: "work_mode"
    description: "..."
    data_type: "categorical"


# ============================================================
# REQUIRED ATTRIBUTES  (optional)
# ============================================================
# Attributes that must already be assigned before this one runs.
required_attributes:
  - name: "ethnicity"
    description: "Must be assigned first"
    required: true
    error_if_missing: true
    mapping:                          # optional — map internal codes to CSV codes
      W: "W"
      O: "CO"


# ============================================================
# AGE BAND CATEGORIES  (optional)
# ============================================================
# Define named age bands used in data-source lookups.
# Same structure as households_config.yaml categories.
categories:
  - name: "Adults (30-49)"
    symbol: "A3049"
    csv_value: "30-49"               # value used as key in lookup CSV
    attribute: "age"
    type: "numerical"
    numerical:
      min: 30
      max: 49


# ============================================================
# FILTERS  (optional)
# ============================================================
# Restrict assignment to a subset of the population.
filters:
  age:
    attribute: "age"
    type: "numerical"
    numerical:
      min: 18
      max: 64
  activities:
    exclude: ["primary_activity"]     # skip people who already have this activity key


# ============================================================
# REGION MAPPING  (optional)
# ============================================================
# Map geography unit names to CSV row keys when they differ.
region_mapping:
  "East of England": "East"
  "Yorkshire and The Humber": "Yorkshire and The Humber"


# ============================================================
# ROLES
# ============================================================
# Named roles map to household subsets (category names from households_config.yaml).
# Roles are declared globally and referenced in assignment_rules.
roles:
  primary_adult:
    type: primary                     # optional — "primary" | "secondary" | "extra"
    description: "First adult assigned"
    subsets: ["Adults"]               # category names this role draws from

  children:
    description: "Children in households"
    subsets: ["Kids", "Young Adults"]


# ============================================================
# HOUSEHOLD STRUCTURES
# ============================================================
# Named structural types matched against household composition patterns.
# Checked in declaration order — first match wins.
household_structures:

  Family:
    description: "..."
    inheritance: true                 # true → children inherit from adults

    matching_rules:
      - actual:                       # current household composition must match one of these
          - ">=1 >=0 >=0 >=0"
        description: "Any household with kids"

      - actual:                       # narrower actual pattern ...
          - "0 >=1 1 <=2"
        original:                    # ... only if original (pre-demotion) pattern matches
          - ">=2 >=0 1 0"
          - "1 >=0 2 0"
        description: "Young adult families (demoted or originally dependent)"

  Couple:
    description: "..."
    inheritance: false
    matching_rules:
      - actual: ["0 0 2 0"]
        original: ["0 0 2 0"]
        description: "Adult couple"

  Independents:
    description: "..."
    inheritance: false
    matching_rules:
      - actual: ["0 0 1 0", "0 0 0 1"]
        description: "Single person households"
      - actual: ["0 >=0 >=0 >=0"]    # catch-all — list last
        description: "Flexible households"


# ============================================================
# DATA SOURCES
# ============================================================
data_sources:
  geo_distribution:
    type: "csv_lookup"
    description: "..."

    files:
      - path: "data/population/ethnicity/ethnicity_5groups_by_OA.csv"

        key_column: "geo_unit"        # single key column
        # key_columns:                # alternative: multi-key lookup
        #   sex:
        #     attribute: "sex"
        #     type: "direct"
        #   age_band_min:
        #     attribute: "age"
        #     type: "category_lookup" # maps age → category symbol via `categories`
        #   region:
        #     attribute: "geographical_unit"
        #     type: "ancestor_lookup" # traverse hierarchy to a given level
        #     level: "XLGU"
        #     property: "name"
        #     mapping: "region_mapping"

        value_columns:                # maps internal key → CSV column name
          W: "W"
          A: "A"

        total_column: "total"         # optional — normalisation denominator

        output_format: "origin_destination_matrix"
                                      # optional — for O-D matrix loading;
                                      # requires destination_column, likelihood_column
        destination_column: "LGU_destination_name"
        likelihood_column: "Likelihood"
        metadata_columns:
          work_mode: "Place of work indicator"

        exclude_destinations:         # optional — filter out specific destination codes
          - "888888888"

        geographical_unit_column:     # optional — for geo-unit sampling strategies
          name: "SGU"
          level: "SGU"
        weight_column: "Total"

        exclude_rows:                 # optional — filter rows by column value
          - column: "SGU"
            values: ["ALL"]

    fallback:                         # used when CSV lookup yields no result
      W: 0.81
      A: 0.09
      # "uniform" — equal probability across all values
      # "local_work" — reference another data_source by name

  local_work:
    type: "constant"                  # constant fallback data source
    description: "..."
    values:
      workplace_location: "person.geographical_unit.lgu"
      work_mode: "Normal"


# ============================================================
# ASSIGNMENT RULES
# ============================================================
# Keyed by household structure name (or "person" for person-level assignment).

assignment_rules:

  Family:
    description: "..."
    rules:
      - role: "primary_adult"         # role name, or list of role names
        priority: 1                   # lower = assigned first
        description: "..."

        assignment:
          strategy: "probabilistic"   # "probabilistic"       — sample from distribution
                                      # "probabilistic_conditions" — independent Bernoulli per condition
                                      # "partnership"          — condition on partner's value
                                      # "inheritance"          — derive from parent roles
                                      # "reverse_inheritance"  — derive from child's value
                                      # "commuting_likelihood" — sample from O-D matrix
                                      # "geographical_unit_sampler" — sample a geo unit
                                      # "categorical_sampler"  — sample one category
                                      # "constant"             — assign a fixed value

          data_source: "geo_distribution"

          context: "household.geo_unit"
                                      # dot-path to the lookup key value
                                      # or list: ["household.geo_unit", "primary_adult.ethnicity"]

          partner_role: "primary_adult"   # for "partnership" strategy

          inherit_from:               # for "inheritance" / "reverse_inheritance"
            roles: ["primary_adult", "secondary_adult"]  # or role: "primary_adult"

          logic:                      # for inheritance strategies
            - when: "count(unique_values) == 1"
              then: "values[0]"
            - when: "count(unique_values) > 1"
              then: "M"

          selection_method: "independent_bernoulli"   # for probabilistic_conditions

          conditions:                 # for probabilistic_conditions
            - name: "cvd"
              label: "Cardiovascular Disease"

          outputs:                    # for commuting_likelihood — maps result fields to properties
            workplace_location: "destination"
            work_mode: "work_mode"

          exclude: ["primary_elder.ethnicity"]  # for probabilistic strategies — exclude values

          fallback:
            strategy: "probabilistic"
            data_source: "geo_distribution"
            context: "household.geo_unit"

  person:                             # for assignment_level: "person"
    description: "..."
    rules:
      - description: "..."
        priority: 1
        assignment:
          strategy: "categorical_sampler"
          data_source: "workplace_industry_by_sex"


# ============================================================
# VENUE ASSIGNMENT RULES  (optional)
# ============================================================
# Applied to residence venues NOT in household_venue_types.
venue_assignment_rules:
  - venue_types: ["care_home", "boarding_school"]
    description: "..."
    assignment:
      strategy: "probabilistic"
      data_source: "geo_distribution"
      context: "venue.geo_unit"


# ============================================================
# SETTINGS
# ============================================================
settings:
  random_seed: null                   # optional integer for reproducibility
  normalize_probabilities: true       # re-normalise distributions after filtering
  cache_lookups: true                 # cache CSV lookups in memory

  assignment_order:                   # optional — control intra-household ordering
    method: "category_priority"
    category_priorities:
      "Adults": 0
      "Young Adults": 1
      "Kids": 2
      "Old Adults": 3

  error_handling:
    missing_geo_unit: "use_fallback"    # "use_fallback" | "skip_person" | "error"
    missing_lookup_data: "use_fallback"
    missing_household_structure: "default_to_independents"
    missing_required_attribute: "skip_person"
    invalid_age: "skip_person"
    invalid_sex: "skip_person"
    person_without_work_sector: "skip_person"
    missing_filter_activity: "skip_person"

  logging:
    level: "INFO"                     # "DEBUG" | "INFO" | "WARNING"
    detailed_assignment_logging: false
    show_samples: true
    sample_size: 10
    show_attribute_distribution: true
```
