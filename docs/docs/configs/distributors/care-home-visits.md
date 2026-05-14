# care_home_visits_distributor.yaml

Links households of care home residents to the care home as a leisure venue. One household is linked per resident. Uses `distributor_type: "resident_linked"` — a different loader class from standard distributors.

**Topic:** [Distributors](index.md)  
**Path:** `configs/2021/distributors/care_home_visits_distributor.yaml`

---

## Full Schema

```yaml
distributor_name: "care_home_visits_distributor"
distributor_type: "resident_linked"  # uses the resident-linked loader class

target_venue_type: "care_home"       # venue type to link visitors to
resident_subset: "resident"          # subset name identifying residents in the venue
subset_key: "visitor"                # subset name assigned to the visitor household

activity_map_key: "leisure"          # key written to person.activity_map

link_level: "household"              # "household" — link the resident's household as visitor
multiplier: 1                        # number of households linked per resident

geography_level: "MGU"               # geography level used when searching for households


# ============================================================
# VISITOR ELIGIBILITY
# ============================================================
visitor_eligibility:
  global_filters:
    - attribute: "residence.type"
      value: "household"             # note: single value form (not values list)
      type: "categorical"

    - attribute: "residence.properties.original_pattern"
      values:                        # list of household composition patterns eligible to visit
        - ">=2 >=0 2 0"
        - "1 >=0 2 0"
        - ">=2 >=0 1 0"
        - "1 >=0 1 0"
        - "0 >=1 2 0"
        - "0 >=1 1 0"
        - "0 0 2 0"
        - "0 0 0 2"
      type: "categorical"


# ============================================================
# SETTINGS
# ============================================================
settings:
  verbose: true
  batch_geo_level: "MGU"
```
