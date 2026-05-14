# company_distributor.yaml

Assigns working-age agents to companies, matching on `workplace_sgu` (not residence) and industry sector.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/company_distributor.yaml`

See [Distributors overview](index.md) for the full generic schema.

---

## Key Configuration Points

```yaml
distributor_name: "company_distributor"
venue_type: "company"
activity_map_key: "primary_activity"

eligibility:
  require_unassigned: true
  global_filters:
    - attribute: "age"
      type: "numerical"
      min: 18
      max: 64
    - attribute: "properties.workplace_sgu"
      type: "categorical"           # must have a workplace_sgu assigned
    - attribute: "properties.work_sector"
      type: "categorical"           # must have a work_sector assigned
    - attribute: "residence.type"
      type: "categorical"
      values: ["household"]         # exclude communal residents

  attributes:
    - name: "properties.work_sector"
      type: "categorical"
      venue_column: "industry_code"  # company CSV column
      matching_rules:               # each sector maps to its own industry code
        "A": ["A"]
        "B": ["B"]
        # ... all sectors mapped 1-to-1
        "Q": ["Q"]
      case_sensitive: false

venue_selection:
  consider_by: "geo_unit"           # match on workplace_sgu → parent MGU
  venue_geo_level: "MGU"
  person_location_source: "properties.workplace_sgu"
                                    # use work location, not home
  batch_geo_level: "SGU"
  filter_by_geography: true
  respect_capacity: true

allocation:
  strategy: "random"
  capacity_column: "employee_count"
  capacity_handling:
    if_missing: "skip"
    if_zero: "skip"
  track_capacity: true
  when_full: "exclude"
  batch_by: "geo_unit"

settings:
  priority: 5                       # runs after school (10) and university (1)

fallback:
  strategy: "skip"
```
