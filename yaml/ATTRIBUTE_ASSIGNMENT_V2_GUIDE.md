# Attribute Assignment V2 - Streamlined System Guide

## Overview

Version 2 simplifies the attribute assignment system with three core concepts:

1. **Roles**: Map person roles to household subsets (age categories)
2. **Household Structures**: Define household types with flexible pattern matching
3. **Assignment Rules**: Simple rules organized by household structure

## Key Improvements

- **User-configurable roles** mapped to existing subsets from `household_config.yaml`
- **Flexible pattern matching** supporting operators (`>=`, `<=`, exact values)
- **Conditional structure matching** (actual pattern + original pattern conditions)
- **Three clear household types**: Family (with inheritance), Couple (with partnership), Independents (independent assignment)

---

## 1. Role Definitions

Roles map to the household subsets defined in `household_config.yaml`:
- **Kids** (age 0-17)
- **Young Adults** (age 18-24)
- **Adults** (age 25-64)
- **Old Adults** (age 65+)

### Example Roles

```yaml
roles:
  primary_adult:
    description: "First adult assigned in any household"
    subsets: ["Adults"]

  children:
    description: "Children and dependent young adults in families"
    subsets: ["Kids", "Young Adults"]
```

**How it works:**
- When assigning a person to a role, the system checks if their household subset matches any of the role's subsets
- A person in the "Adults" subset can be assigned to `primary_adult`, `secondary_adult`, or `extra_adult`
- Order matters: roles are checked in priority order

---

## 2. Household Structure Definitions

Define three household types with flexible pattern matching rules.

### Pattern Format

Patterns follow the format: `"Kids Young_Adults Adults Old_Adults"`

**Supported operators:**
- `N` - Exact count (e.g., `2` = exactly 2)
- `>=N` - N or more (e.g., `>=1` = at least 1)
- `<=N` - N or fewer (e.g., `<=2` = at most 2)
- `>=0` - Any count (0 or more)

### Matching Rules

Each structure has one or more matching rules:

```yaml
Family:
  matching_rules:
    # Simple rule: match actual pattern only
    - actual:
        - ">=1 >=0 >=0 >=0"  # At least 1 kid
      description: "Any household with kids"

    # Conditional rule: match actual AND original patterns
    - actual:
        - "0 >=1 1 <=2"      # No kids, 1+ young adults, 1-2 adults
        - "0 >=1 2 <=2"
      original:
        - ">=2 >=0 1 0"      # Must have originally been a family
        - ">=2 >=0 2 0"
      description: "Young adult families (kids demoted)"
```

**How it works:**
1. System checks each rule in order
2. If `actual` patterns match the household's actual pattern:
   - If `original` is specified, also check if original pattern matches
   - If both match (or only `actual` required), household gets this structure
3. First matching structure wins

### The Three Structures

#### Family
- **Inheritance**: YES (children inherit from parents)
- **Matching**: Has kids OR was originally intended as a family
- **Examples**:
  - `2 0 2 0` - Family with 2 kids and 2 adults
  - `0 2 1 0` - Young adults living with parent (if originally `>=2 >=0 1 0`)

#### Couple
- **Inheritance**: NO
- **Matching**: Exactly 2 adults/elders, must have been originally intended as couple (not demoted family)
- **Examples**:
  - `0 0 2 0` with original `0 0 2 0` - Adult couple
  - `0 0 0 2` with original `0 0 0 2` - Elderly couple

#### Independents
- **Inheritance**: NO
- **Matching**: Everything else (default catch-all)
- **Examples**:
  - `0 0 1 0` - Single adult
  - `0 3 0 0` - Young adult roommates
  - `0 0 3 0` - Adult roommates
  - `0 0 2 0` with original `0 >=0 >=0 >=0` - Flexible household

---

## 3. Assignment Rules by Structure

Each household structure has its own set of assignment rules.

### Family Structure

```yaml
Family:
  rules:
    - role: "primary_adult"
      priority: 1
      assignment:
        type: "probabilistic"
        data_source: "geo_distribution"
        context: "household.geo_unit"
```

**Assignment Flow:**
1. **primary_adult**: Geographic distribution
2. **secondary_adult**: Partnership rules (diversity check + pair probabilities)
3. **extra_adult**: Independent geographic distribution
4. **children**: **INHERITANCE** from primary + secondary adults
5. **primary_elder** / **secondary_elder**: Geographic distribution (or reverse inheritance)

### Couple Structure

```yaml
Couple:
  rules:
    - role: ["primary_adult", "primary_elder"]
      priority: 1
      assignment:
        type: "probabilistic"
```

**Assignment Flow:**
1. **primary_adult/elder**: Geographic distribution
2. **secondary_adult/elder**: Partnership rules (diversity check + pair probabilities)

### Independents Structure

```yaml
Independents:
  rules:
    - role: ["primary_adult", "secondary_adult", "extra_adult", ...]
      priority: 1
      assignment:
        type: "probabilistic"
```

**Assignment Flow:**
- **Everyone**: Independent geographic distribution (no relationships assumed)

---

## 4. Pattern Matching Examples

### Example 1: Family with Kids

**Household:**
- Original pattern: `2 0 2 0` (2 kids, 2 adults)
- Actual pattern: `2 0 2 0` (no demotion)

**Matching:**
- Checks Family rule 1: `actual >= ">=1 >=0 >=0 >=0"` ✅
- **Structure**: Family

**Assignment:**
- Adult 1 → `primary_adult` → Geographic distribution
- Adult 2 → `secondary_adult` → Partnership rules
- Kid 1 → `children` → Inherit from adults
- Kid 2 → `children` → Inherit from adults

### Example 2: Demoted Family (Young Adults)

**Household:**
- Original pattern: `>=2 >=0 2 0` (family intended to have kids)
- Actual pattern: `0 1 2 0` (kids demoted, 1 young adult remains)

**Matching:**
- Checks Family rule 1: `actual >= ">=1 >=0 >=0 >=0"` ❌ (no kids)
- Checks Family rule 2:
  - `actual` matches `"0 >=1 2 <=2"` ✅
  - `original` matches `">=2 >=0 2 0"` ✅
- **Structure**: Family

**Assignment:**
- Adult 1 → `primary_adult` → Geographic distribution
- Adult 2 → `secondary_adult` → Partnership rules
- Young Adult → `children` → Inherit from adults (dependent)

### Example 3: Couple

**Household:**
- Original pattern: `0 0 2 0`
- Actual pattern: `0 0 2 0`

**Matching:**
- Checks Family rules: None match
- Checks Couple rule 1:
  - `actual` matches `"0 0 2 0"` ✅
  - `original` matches `"0 0 2 0"` ✅
- **Structure**: Couple

**Assignment:**
- Adult 1 → `primary_adult` → Geographic distribution
- Adult 2 → `secondary_adult` → Partnership rules

### Example 4: Independent Roommates

**Household:**
- Original pattern: `0 >=0 >=0 >=0` (flexible household)
- Actual pattern: `0 0 3 0` (3 adults)

**Matching:**
- Checks Family rules: None match
- Checks Couple rules: None match
- **Structure**: Independents (default)

**Assignment:**
- Adult 1 → `primary_adult` → Geographic distribution
- Adult 2 → `extra_adult` → Geographic distribution (independent)
- Adult 3 → `extra_adult` → Geographic distribution (independent)

---

## 5. Extending the System

### Adding New Roles

```yaml
roles:
  my_custom_role:
    description: "Description of role"
    subsets: ["Adults", "Young Adults"]  # Which age categories
```

### Adding New Structure Matching Rules

```yaml
Family:
  matching_rules:
    # ... existing rules ...

    # New rule: Multi-generational families
    - actual:
        - ">=1 >=0 >=1 >=1"  # Kids + adults + elderly
      description: "Multi-generational family"
```

### Customizing Assignment Logic

Each structure can have completely different assignment rules:

```yaml
MyCustomStructure:
  rules:
    - role: "my_custom_role"
      priority: 1
      assignment:
        type: "probabilistic"
        data_source: "my_custom_data"
        context: "my_custom_context"
```

---

## 6. Migration from V1

### Key Changes

1. **Household structures**: Now defined with flexible pattern matching instead of exact string matches
2. **Person roles**: Now explicitly mapped to subsets instead of using complex conditions
3. **Assignment rules**: Organized by structure type instead of priority-based global list
4. **Simpler logic**: Three clear types (Family/Couple/Independents) instead of 8+ structure types

### V1 → V2 Mapping

| V1 Structure | V2 Structure |
|--------------|--------------|
| `family_with_kids` | `Family` |
| `family_with_young_adults` | `Family` |
| `couple_household` | `Couple` |
| `elderly_couple` | `Couple` |
| `flexible_household` | `Independents` |
| `young_adult_group` | `Independents` |
| `single_person` | `Independents` |

| V1 Role | V2 Role |
|---------|---------|
| `primary_adult` | `primary_adult` |
| `secondary_adult_partner` | `secondary_adult` |
| `additional_adult_independent` | `extra_adult` |
| `dependent_child` | `children` |
| `elderly_couple_member` | `primary_elder` / `secondary_elder` |

---

## Summary

The V2 system provides:

✅ **Flexibility**: Easy to add new roles and structures
✅ **Clarity**: Three clear household types with obvious behavior
✅ **Power**: Pattern matching with operators for complex rules
✅ **Simplicity**: Less configuration, cleaner logic

You can now configure the entire assignment system by editing just three sections:
1. `roles` - Define what roles exist and which age groups they apply to
2. `household_structures` - Define how to classify households
3. `assignment_rules` - Define how to assign attributes for each structure type
