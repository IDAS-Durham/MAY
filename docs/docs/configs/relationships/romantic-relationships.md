# romantic_relationships.yaml

Controls sexual orientation assignment and romantic partnership formation. Orientation probabilities can be sourced from ONS-derived per-area CSV files (for UK worlds) or from YAML-only fallback values (for other worlds).

**Topic:** [Relationships](index.md)  
**Path:** `configs/2021/relationships/romantic_relationships.yaml`

---

## Full Schema

```yaml
name: "romantic_relationships"        # arbitrary label

min_age: 16                           # minimum age for orientation/partnership assignment
max_age: 120                          # maximum age


# ============================================================
# DATA SOURCES  (optional — omit for YAML-only fallback)
# ============================================================
# When present, orientation probabilities are raked:
#   P(o | sex, age, area) ∝ P_nat(o | sex, age) · P_area(o) / P_nat_marginal(o)
# Worlds without area-level orientation data should omit this section entirely
# and rely on the probabilities block below.

data_sources:
  prevalence_path: "data/.../orientation_prevalence_extended.csv"
                                      # national prevalence by sex × age
  msoa_marginal_path: "data/.../orientation_by_msoa_normalized.csv"
                                      # per-area orientation marginals
  geo_level: "MGU"                    # geography level of the area codes in the CSV


# ============================================================
# DIAGNOSTICS  (optional)
# ============================================================
diagnostics:
  verbose: false                      # true → log detailed national-vs-empirical comparisons
                                      # and MSOA quintile sweeps; disable for production runs


# ============================================================
# SEXUAL ORIENTATIONS
# ============================================================
sexual_orientations:

  types:                              # list of orientation labels; arbitrary strings
    - heterosexual
    - homosexual
    - bisexual

  probabilities:                      # fallback national-level probabilities by sex
    male:                             # sex value as stored on the person
      heterosexual: 0.90
      homosexual: 0.05
      bisexual: 0.05
    female:
      heterosexual: 0.85
      homosexual: 0.05
      bisexual: 0.10
    # Add further sex categories as needed

  age_adjustments:                    # optional — multiplicative adjustments by age band
    "16-25":                          # string key: "min-max" or "min+"
      bisexual: 1.3                   # probability × multiplier (result re-normalised)
    "65-74":
      homosexual: 0.7
      bisexual: 0.5

  compatibility:                      # which orientations can form a partnership
    heterosexual:
      male: [female]                  # list of compatible sex values
      female: [male]
    homosexual:
      male: [male]
      female: [female]
    bisexual:
      male: [male, female]
      female: [male, female]


# ============================================================
# STORAGE
# ============================================================
storage:
  orientation_key: "sexual_orientation"   # person property key for orientation
  status_key: "relationship_status"       # person property key for partnership status
```
