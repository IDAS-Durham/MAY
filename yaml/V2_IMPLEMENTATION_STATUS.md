# V2 Attribute Assignment - Implementation Status

**Date**: November 5, 2025
**Branch**: `Martha_Branch`
**Last Commit**: `b59c42a` - "Implement v2 attribute assignment configuration system (Part 1)"

---

## 📋 Project Goal

Overhaul the attribute assignment system to be simpler and more user-friendly with:
- **Roles** mapped to household subsets (Kids, Young Adults, Adults, Old Adults)
- **Three household types**: Family (with inheritance), Couple (with partnership), Independents (independent assignment)
- **Flexible pattern matching** supporting `>=`, `<=`, and exact values
- **Ethnicity inheritance rules**: W+W=W, W+A=M, M→parents must differ, etc.

---

## ✅ Completed

### 1. V2 Configuration File
**File**: `yaml/attribute_assignment_v2.yaml` (477 lines)
- Defines 8 roles: `primary_adult`, `secondary_adult`, `extra_adult`, `primary_elder`, `secondary_elder`, `extra_elder`, `independent_young`, `children`
- Each role maps to subsets from `household_config.yaml`
- Three household structures with ordered matching (Family → Couple → Independents)
- Complete inheritance rules documented in comments
- Structure-based assignment rules organized by household type

**Key Configuration Details**:
- **Family matching**:
  - Rule 1: `>=1 >=0 >=0 >=0` (any household with kids)
  - Rule 2: `0 >=1 1 <=2` or `0 >=1 2 <=2` ONLY IF original was a family pattern
- **Couple matching**: Exactly `0 0 2 0` or `0 0 0 2` with matching original pattern
- **Independents matching**: Singles, young adult roommates, multi-elderly, flexible households

### 2. V2 Configuration Documentation
**File**: `yaml/ATTRIBUTE_ASSIGNMENT_V2_GUIDE.md` (328 lines)
- Complete guide to v2 system
- Pattern matching examples
- Household structure classification examples
- How to extend the system
- Migration notes from v1

### 3. Extended CompositionPattern
**File**: `may/residence/composition_pattern.py` (modified)
- **Added `<=` operator support** (previously only had `>=` and exact)
- Updated `from_string()` to parse `<=N` patterns
- Updated `get_min_count()`, `get_max_count()`, `is_flexible()` to handle `<=`
- Updated `_requirements_to_string()` to output `<=N`
- Pattern examples: `">=1 >=0 2 <=2"` means 1+ kids, any young adults, 2 adults, ≤2 elderly

### 4. V2 Configuration Loader
**File**: `attribute_assignment/assignment_config_v2.py` (441 lines)
- **Clean, simple configuration system** (no complex v1 conditions)
- `RoleV2`: Maps roles to subsets (e.g., `primary_adult` → `["Adults"]`)
- `HouseholdStructureV2`: Flexible matching with `MatchingRule`
- `MatchingRule`: Supports conditional matching (actual + original patterns)
- Pattern matching uses `CompositionPattern` for consistency
- Automatic primary/secondary/extra role assignment based on naming conventions

**Key Classes**:
- `MatchingRule`: Checks if household matches actual/original pattern conditions
- `HouseholdStructureV2`: Contains list of matching rules
- `RoleV2`: Simple subset mapping (no conditions!)
- `AssignmentRuleV2`: Simpler than v1, organized by structure
- `AttributeAssignmentConfigV2`: Main config loader

### 5. Git Commits
- `a22a2af`: Add streamlined attribute assignment v2 configuration system
- `b59c42a`: Implement v2 attribute assignment configuration system (Part 1)

---

## 🚧 In Progress / Not Started

### 1. Assignment Strategies (V2)
**File to create**: `attribute_assignment/strategies_v2.py`

**Strategies needed**:
1. ✅ **ProbabilisticStrategy**: Simple geo-based assignment (already exists in v1, can adapt)
2. ❌ **PartnershipStrategy** (NEW):
   - Uses `pair_probabilities` data source
   - Given first person's ethnicity, samples second person's ethnicity
   - Used by Couples and Family secondary_adult
3. ❌ **InheritanceStrategy**: Parent→child inheritance (exists in v1, can adapt)
   - Same + Same = Same (W+W=W)
   - Different = Mixed (W+A=M)
4. ❌ **ReverseInheritanceStrategy** (NEW):
   - Child→parent reverse mapping
   - Child is W → Both parents W
   - Child is M → Parents must differ

**Reference**: Look at existing `attribute_assignment/strategies.py` for structure, but simplify!

### 2. Assignment Orchestrator (V2)
**File to create**: `attribute_assignment/assigner_v2.py`

**Main flow**:
1. Load v2 configuration from YAML
2. Load data sources (ethnicity distributions, pair probabilities, etc.)
3. For each household:
   a. Classify structure (Family/Couple/Independents) - ORDERED matching
   b. Get assignment rules for that structure
   c. Sort people by age category (Adults first, then children, etc.)
   d. For each person:
      - Determine role based on subset + already-assigned roles
      - Get assignment rule for that role
      - Execute strategy
      - Track assigned roles
4. Report statistics

**Key differences from v1**:
- NO complex role conditions - just subset matching + counting
- Structure-based rule lookup (simpler!)
- Role assignment tracks primary/secondary/extra automatically

### 3. Data Source Manager
**Status**: Existing `attribute_assignment/data_sources.py` might work as-is, but review needed

Check if it can load:
- `geo_distribution` (CSV with ethnicity by geo_unit)
- `pair_probabilities` (CSV with conditional probabilities)
- `diversity` (single vs mixed ethnicity households)

### 4. End-to-End Testing
**Test script location**: Could be in `attribute_assignment/` or create `tests/test_v2_assignment.py`

**Test cases needed**:
1. Pattern matching with `<=` operator
2. Structure classification (Family/Couple/Independents)
3. Role assignment (primary/secondary/extra)
4. Partnership strategy (W+A=M, etc.)
5. Reverse inheritance (child M → parents differ)
6. Full assignment flow with small test dataset

---

## 🎯 Next Steps - Start Here in New Conversation

### Step 1: Create `strategies_v2.py`
```bash
# Look at existing strategies for reference
cat attribute_assignment/strategies.py | head -100
```

**Create these strategies**:
1. `ProbabilisticStrategyV2` - Copy from v1, simplify
2. `PartnershipStrategyV2` - NEW
   - Load pair probabilities data source
   - Given `primary_adult.ethnicity`, sample partner ethnicity
   - Context: `["household.geo_unit", "primary_adult.ethnicity"]`
3. `InheritanceStrategyV2` - Copy from v1, simplify
   - Collect parent ethnicities
   - Apply combination rules (same→same, diff→M)
4. `ReverseInheritanceStrategyV2` - NEW
   - Given child ethnicity, infer parent ethnicities
   - If child is W/A/B/O → both parents same
   - If child is M → parents different

### Step 2: Create `assigner_v2.py`
**Copy structure from**: `attribute_assignment/assigner.py` but simplify heavily

**Main changes**:
- Use `AttributeAssignmentConfigV2` instead of v1 config
- Simpler role detection (no conditions!)
- Structure-based rule lookup
- Track assigned roles for primary/secondary/extra logic

### Step 3: Create Test Script
```python
# Quick test script outline
from attribute_assignment.assignment_config_v2 import AttributeAssignmentConfigV2

config = AttributeAssignmentConfigV2.from_yaml('yaml/attribute_assignment_v2.yaml')

# Test pattern matching
# Test structure classification
# Test role assignment
# Test strategies
```

### Step 4: Integration Test with Real Data
```python
# Test with actual household data
from may.geography.venue_manager import VenueManager
# Load households that were already allocated
# Run v2 assignment
# Check results make sense
```

---

## 📚 Key Files Reference

### Configuration
- `yaml/attribute_assignment_v2.yaml` - V2 configuration (THE SOURCE OF TRUTH)
- `yaml/ATTRIBUTE_ASSIGNMENT_V2_GUIDE.md` - Complete documentation
- `yaml/households/households_config.yaml` - Defines subsets (Kids, Young Adults, Adults, Old Adults)

### V2 Implementation
- `attribute_assignment/assignment_config_v2.py` - Config loader ✅ DONE
- `attribute_assignment/strategies_v2.py` - Strategies ❌ TODO
- `attribute_assignment/assigner_v2.py` - Orchestrator ❌ TODO

### Existing Code (Reference)
- `may/residence/composition_pattern.py` - Pattern matching (UPDATED with `<=`)
- `attribute_assignment/data_sources.py` - Data loading (might work as-is)
- `attribute_assignment/strategies.py` - V1 strategies (reference for structure)
- `attribute_assignment/assigner.py` - V1 orchestrator (reference for flow)

### Data Files
- `data/population/ethnicity/ethnicity_5groups_by_OA.csv` - Ethnicity by geo unit
- `data/population/ethnicity/precomputed_area_partnerships.csv` - Pair probabilities
- `data/population/ethnicity/combination_ethnicities_in_households_standardized.csv` - Diversity data

---

## ⚠️ Important Notes

### Pattern Matching Order
**CRITICAL**: Structures MUST be checked in order: Family → Couple → Independents
The `0 >=0 >=0 >=0` pattern in Independents will match everything, so it must be last!

### Role Assignment Logic
- First person with subset "Adults" → `primary_adult`
- Second person with subset "Adults" → `secondary_adult`
- Third+ person with subset "Adults" → `extra_adult`
- Same for `primary_elder`, `secondary_elder`, `extra_elder`
- Non-primary/secondary/extra roles (like `children`, `independent_young`) assigned to all matching people

### Inheritance Rules (CRITICAL)
```
FORWARD (Parent → Child):
  W+W=W, A+A=A, B+B=B, O+O=O, M+M=M
  W+A=M, W+B=M, W+O=M, A+B=M, A+O=M, B+O=M, M+X=M

REVERSE (Child → Parent):
  Child is W → Both parents W
  Child is A → Both parents A
  Child is B → Both parents B
  Child is O → Both parents O
  Child is M → Parents different (sample two different ethnicities)
```

### Partnership Strategy
Uses `pair_probabilities` data source:
- Key: `[geo_unit, first_ethnicity]`
- Returns: Probability distribution for second person's ethnicity
- Fallback: Geographic distribution if pair data not found

---

## 🐛 Potential Issues to Watch For

1. **Role assignment**: Make sure primary/secondary/extra logic works correctly when there are multiple people with same subset
2. **Pattern matching**: Test `<=` operator thoroughly (new feature)
3. **Structure ordering**: Ensure Independents is always checked last
4. **Reverse inheritance**: When child is M, ensure parents get DIFFERENT ethnicities
5. **Data loading**: Verify existing `data_sources.py` can load pair_probabilities with compound keys

---

## 💡 Design Philosophy

**V2 is all about simplicity**:
- ✅ Roles map to subsets (not complex conditions)
- ✅ Pattern matching uses existing CompositionPattern
- ✅ Structure-based rules (organized, clean)
- ✅ Primary/secondary/extra by naming convention (automatic!)
- ❌ No complex condition evaluation
- ❌ No priority-based global rule lists
- ❌ No role-to-role dependencies in config

**If it feels complicated, it's probably wrong!**

---

## 🚀 Quick Start Command for Next Session

```bash
# Check current status
git log -3 --oneline
git status

# Review what's done
ls -lh attribute_assignment/assignment_config_v2.py
head -50 yaml/attribute_assignment_v2.yaml

# Start implementing strategies
code attribute_assignment/strategies_v2.py

# Reference v1 for structure
head -200 attribute_assignment/strategies.py
```

Good luck! The hard design work is done - now it's just implementation! 🎉
