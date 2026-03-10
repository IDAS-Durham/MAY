import pytest
import copy

from may.residence.composition_pattern import CompositionPattern

# 1. Parsing & Construction
def test_parse_real_patterns():
    # 15 real patterns from production
    patterns = [
        ">=2 >=0 2 0", "1 >=0 2 0", ">=2 >=0 1 0", "1 >=0 1 0",
        ">=2 >=0 >=0 >=0", "1 >=0 >=0 >=0", "0 >=1 2 0", "0 >=1 1 0",
        "0 0 0 2", "0 0 0 1", "0 0 2 0", "0 0 1 0",
        "0 >=0 0 0", "0 0 0 >=3", "0 >=0 >=0 >=0"
    ]
    for p in patterns:
        cp = CompositionPattern.from_string(p)
        assert cp.to_string() == p

def test_parse_operators_and_counts():
    cp = CompositionPattern.from_string(">=2 <=3 4 0")
    assert cp.requirements == [
        ("gte", 2),
        ("lte", 3),
        ("exact", 4),
        ("exact", 0)
    ]

def test_whitespace_handling():
    cp1 = CompositionPattern.from_string("  >=2    <=3   4   0  ")
    assert cp1.requirements == [("gte", 2), ("lte", 3), ("exact", 4), ("exact", 0)]
    assert cp1.to_string() == ">=2 <=3 4 0"

def test_instance_caching():
    # Calling from_string twice should return the identical object
    cp1 = CompositionPattern.from_string(">=2 >=0 2 0")
    cp2 = CompositionPattern.from_string(">=2 >=0 2 0")
    assert cp1 is cp2

def test_to_string_round_trip():
    cp = CompositionPattern(original_pattern="custom", requirements=[("exact", 1), ("gte", 0)])
    assert cp.to_string() == "1 >=0"

# 2. get_min_count / get_max_count
def test_get_min_count():
    cp = CompositionPattern.from_string(">=2 <=3 4 0")
    assert cp.get_min_count(0) == 2  # gte 2
    assert cp.get_min_count(1) == 0  # lte 3 -> min 0
    assert cp.get_min_count(2) == 4  # exact 4
    assert cp.get_min_count(3) == 0  # exact 0
    
def test_get_max_count():
    cp = CompositionPattern.from_string(">=2 <=3 4 0")
    assert cp.get_max_count(0) is None  # gte 2 -> no limit
    assert cp.get_max_count(1) == 3     # lte 3
    assert cp.get_max_count(2) == 4     # exact 4
    assert cp.get_max_count(3) == 0     # exact 0

def test_out_of_bounds_index():
    cp = CompositionPattern.from_string("2 3")
    assert cp.get_min_count(5) == 0
    assert cp.get_max_count(5) is None

# 3. is_flexible
def test_is_flexible():
    cp = CompositionPattern.from_string(">=2 <=3 4 0")
    assert cp.is_flexible(0) is True
    assert cp.is_flexible(1) is True
    assert cp.is_flexible(2) is False
    assert cp.is_flexible(3) is False
    assert cp.is_flexible(4) is True # out of bounds

# 4. min_household_size
def test_min_household_size():
    assert CompositionPattern.from_string(">=2 >=0 2 0").min_household_size() == 4
    assert CompositionPattern.from_string("0 0 0 1").min_household_size() == 1
    assert CompositionPattern.from_string("0 >=0 >=0 >=0").min_household_size() == 0
    assert CompositionPattern.from_string("0 0 0 >=3").min_household_size() == 3
    assert CompositionPattern.from_string(">=2 <=3 4 0").min_household_size() == 6 # 2+0+4+0

# 5. demote_once (Priority: 0=Kids, 1=YA, 3=OA, 2=Adults -> [0, 1, 3, 2])
@pytest.fixture
def priority_order():
    return [0, 1, 3, 2] # Kids, YA, OA, Adults

def test_demote_once_chain(priority_order):
    cp = CompositionPattern.from_string(">=2 >=0 2 0")  # size 4
    
    # 1. Demote Kids (idx 0): >=2 -> >=1
    cp1 = cp.demote_once(priority_order)
    assert cp1 is not None and cp1.to_string() == ">=1 >=0 2 0"
    
    # 2. Demote Kids again: >=1 -> >=0
    cp2 = cp1.demote_once(priority_order)
    assert cp2 is not None and cp2.to_string() == ">=0 >=0 2 0"

    # 3. Kids is >=0 (cannot be demoted further based on demote_once logic).
    # Next is YA (idx 1). It is >=0, so it skips.
    # Next is OA (idx 3). It is exact 0, so it skips.
    # Next is Adults (idx 2). It is exact 2. 2 -> exact 1.
    cp3 = cp2.demote_once(priority_order)
    assert cp3 is not None and cp3.to_string() == ">=0 >=0 1 0"

    # 4. Demote Adults again: 1 -> exact 0.
    cp4 = cp3.demote_once(priority_order)
    assert cp4 is not None and cp4.to_string() == ">=0 >=0 0 0"

    # 5. Nothing left to demote
    cp5 = cp4.demote_once(priority_order)
    assert cp5 is None

def test_demote_exact_count(priority_order):
    cp = CompositionPattern.from_string("1 >=0 2 0")
    # First priority is Kids (idx 0), exact 1 -> exact 0
    cp1 = cp.demote_once(priority_order)
    assert cp1.to_string() == "0 >=0 2 0"

def test_demote_adults_only(priority_order):
    cp = CompositionPattern.from_string("0 0 2 0")
    # Kids, YA, OA all 0. Adults goes 2 -> 1
    cp1 = cp.demote_once(priority_order)
    assert cp1.to_string() == "0 0 1 0"

    # Adults 1 -> 0
    cp2 = cp1.demote_once(priority_order)
    assert cp2.to_string() == "0 0 0 0"
    
    # Can't demote
    cp3 = cp2.demote_once(priority_order)
    assert cp3 is None

def test_demote_keeps_original_pattern(priority_order):
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    cp1 = cp.demote_once(priority_order)
    assert cp1.original_pattern == ">=2 >=0 2 0"

# 6. demote_to_count
def test_demote_to_count_gte():
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    # Target < current
    cp1 = cp.demote_to_count(0, 1)
    assert cp1.to_string() == ">=1 >=0 2 0"
    
    # Target == current (code says "target_count < current_count", returns None)
    cp2 = cp.demote_to_count(0, 2)
    assert cp2 is None

    # Target 0
    cp3 = cp.demote_to_count(0, 0)
    assert cp3.to_string() == ">=0 >=0 2 0"

def test_demote_to_count_exact():
    cp = CompositionPattern.from_string("2 >=0 2 0")
    cp1 = cp.demote_to_count(2, 1) # Demote Adults
    assert cp1.to_string() == "2 >=0 1 0"

def test_demote_to_count_out_of_bounds():
    cp = CompositionPattern.from_string("2 >=0 2 0")
    assert cp.demote_to_count(5, 0) is None

# 7. promote_once
@pytest.fixture
def promotion_priority():
    return [1, 2, 3, 0] # YA, Adults, OA, Kids

def test_promote_once_chain(promotion_priority):
    cp = CompositionPattern.from_string("0 0 2 0")
    
    # YA (idx 1) is 0 -> >=0
    cp1 = cp.promote_once(promotion_priority)
    assert cp1.to_string() == "0 >=0 2 0"
    
    # Adults (idx 2) is 2 -> >=2
    cp2 = cp1.promote_once(promotion_priority)
    assert cp2.to_string() == "0 >=0 >=2 0"
    
    # OA (idx 3) is 0 -> >=0
    cp3 = cp2.promote_once(promotion_priority)
    assert cp3.to_string() == "0 >=0 >=2 >=0"

    # Kids (idx 0) is 0 -> >=0
    cp4 = cp3.promote_once(promotion_priority)
    assert cp4.to_string() == ">=0 >=0 >=2 >=0"

    # Everything is flexible (>=) -> None
    cp5 = cp4.promote_once(promotion_priority)
    assert cp5 is None

def test_promote_all_exact(promotion_priority):
    cp = CompositionPattern.from_string("2 1 2 1")
    # Priority YA(1) -> Adults(2) -> OA(3) -> Kids(0)
    assert cp.promote_once(promotion_priority).to_string() == "2 >=1 2 1"

# 8. validate_against_rules
@pytest.fixture
def validation_rules():
    return [
        {
            "name": "Kids require adult supervision",
            "condition": {
                "category": "Kids",
                "operator": ">=",
                "value": 1
            },
            "requirement": {
                "category": "Adults",
                "operator": ">=",
                "value": 1
            }
        }
    ]

@pytest.fixture
def cat_map():
    return {"Kids": 0, "Young Adults": 1, "Adults": 2, "Old Adults": 3}

def test_validate_passes(validation_rules, cat_map):
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    assert cp.validate_against_rules(validation_rules, cat_map) is True

def test_validate_condition_not_met(validation_rules, cat_map):
    cp = CompositionPattern.from_string("0 0 2 0")
    # Zero kids, rule is not triggered
    assert cp.validate_against_rules(validation_rules, cat_map) is True

def test_validate_fails(validation_rules, cat_map):
    cp = CompositionPattern.from_string(">=2 >=0 0 0")
    # Kids >= 1 but Adults = 0 -> Fails
    assert cp.validate_against_rules(validation_rules, cat_map) is False

    cp2 = CompositionPattern.from_string("1 >=0 0 0")
    assert cp2.validate_against_rules(validation_rules, cat_map) is False

def test_validate_multiple_requirements_or(cat_map):
    # Rule with multiple requirements (list acts as OR)
    rule = [{
        "name": "Kids need Adult OR OA",
        "condition": {"category": "Kids", "operator": ">=", "value": 1},
        "requirement": [
            {"category": "Adults", "operator": ">=", "value": 1},
            {"category": "Old Adults", "operator": ">=", "value": 1}
        ]
    }]
    
    assert CompositionPattern.from_string("1 0 1 0").validate_against_rules(rule, cat_map) is True
    assert CompositionPattern.from_string("1 0 0 1").validate_against_rules(rule, cat_map) is True
    assert CompositionPattern.from_string("1 0 0 0").validate_against_rules(rule, cat_map) is False

def test_validate_unknown_category(validation_rules, cat_map):
    # Log warning but continue
    rules = copy.deepcopy(validation_rules)
    rules[0]["condition"]["category"] = "Aliens"
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    assert cp.validate_against_rules(rules, cat_map) is True

# 9. operator evaluation internals
def test_evaluate_operator():
    cp = CompositionPattern.from_string("0")
    assert cp._evaluate_operator(5, ">=", 3) is True
    assert cp._evaluate_operator(5, ">", 3) is True
    assert cp._evaluate_operator(5, "==", 5) is True
    assert cp._evaluate_operator(5, "<=", 5) is True
    assert cp._evaluate_operator(5, "<", 10) is True
    assert cp._evaluate_operator(5, "foo", 5) is False

# 10. Edge cases
def test_empty_pattern():
    # Should not crash, just empty requirements
    cp = CompositionPattern.from_string("")
    assert cp.requirements == []
    assert cp.to_string() == ""
    assert cp.min_household_size() == 0

def test_single_category():
    cp = CompositionPattern.from_string(">=5")
    assert cp.requirements == [("gte", 5)]
    assert cp.to_string() == ">=5"

# 11. Tests added after audit — filling gaps

def test_demote_lte_operator_is_skipped(priority_order):
    """lte operators should NOT be demotable by demote_once — only gte and exact are."""
    cp = CompositionPattern(
        original_pattern="test",
        requirements=[("lte", 3), ("exact", 0), ("exact", 0), ("exact", 0)]
    )
    # lte with count=3 is NOT demoted (code checks for "gte" and "exact" only)
    # All exact counts are 0, so nothing to demote
    result = cp.demote_once(priority_order)
    assert result is None  # lte is skipped, all others at 0

def test_demote_with_out_of_bounds_priority():
    """Priority list containing indices beyond the pattern length should be safely skipped."""
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    result = cp.demote_once([10, 20, 0])  # first two are OOB, third is valid
    assert result is not None
    assert result.to_string() == ">=1 >=0 2 0"

def test_demotion_then_validation_pipeline(validation_rules, cat_map):
    """
    Critical real-world scenario: demoting ">=2 >=0 2 0" should eventually produce
    ">=0 >=0 0 0" which has kids>=0 but adults=0. If kids were present, validation
    should reject it. But since kids is >=0 (min_count=0), condition is NOT met.
    """
    priority_order = [0, 1, 3, 2]
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    
    # Walk the full demotion chain and validate each step
    results = []
    current = cp
    while current is not None:
        is_valid = current.validate_against_rules(validation_rules, cat_map)
        results.append((current.to_string(), is_valid))
        current = current.demote_once(priority_order)
    
    # Verify the chain
    assert results == [
        (">=2 >=0 2 0", True),   # kids>=2, adults=2: valid
        (">=1 >=0 2 0", True),   # kids>=1, adults=2: valid
        (">=0 >=0 2 0", True),   # kids>=0 (condition not met), valid
        (">=0 >=0 1 0", True),   # kids>=0 (condition not met), valid
        (">=0 >=0 0 0", True),   # kids>=0 (min_count=0, condition not met), valid
    ]

def test_demotion_validation_rejects_kids_without_adults(validation_rules, cat_map):
    """
    Pattern "1 0 0 0" should FAIL validation: kids=1 (condition met) but adults=0.
    This is a pattern that could emerge from aggressive demotion of "1 >=0 2 0".
    """
    priority_order = [0, 1, 3, 2]
    cp = CompositionPattern.from_string("1 >=0 2 0")
    
    results = []
    current = cp
    while current is not None:
        is_valid = current.validate_against_rules(validation_rules, cat_map)
        results.append((current.to_string(), is_valid))
        current = current.demote_once(priority_order)
    
    # After kids demotes to 0, we no longer trigger the rule
    # But the critical step is "0 >=0 1 0" -> "0 >=0 0 0" which is fine.
    # The interesting step is if we had "1 0 0 0" — let's test that directly.
    bad_pattern = CompositionPattern(
        original_pattern="test", requirements=[("exact", 1), ("exact", 0), ("exact", 0), ("exact", 0)]
    )
    assert bad_pattern.validate_against_rules(validation_rules, cat_map) is False

def test_demote_to_count_lte_skipped():
    """demote_to_count should return None for lte operators (not handled)."""
    cp = CompositionPattern(
        original_pattern="test",
        requirements=[("lte", 5), ("exact", 2)]
    )
    result = cp.demote_to_count(0, 3)
    assert result is None  # lte not in the code's if/elif

def test_demote_to_count_target_greater_than_current():
    """demote_to_count with target > current should return None (no demotion needed)."""
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    result = cp.demote_to_count(0, 5)  # target=5 > current=2
    assert result is None

def test_original_pattern_immutable_after_demotion(priority_order):
    """Demoting should NOT modify the original pattern's requirements list."""
    cp = CompositionPattern.from_string(">=2 >=0 2 0")
    original_reqs = list(cp.requirements)  # copy
    
    cp1 = cp.demote_once(priority_order)
    # Original should be unchanged
    assert cp.requirements == original_reqs
    # Demoted should be different
    assert cp1.requirements != original_reqs

def test_promote_lte_is_not_promoted(promotion_priority):
    """lte operators should NOT be promoted — only exact operators are."""
    cp = CompositionPattern(
        original_pattern="test",
        requirements=[("gte", 0), ("lte", 3), ("gte", 2), ("gte", 0)]
    )
    # All are already gte/lte (non-exact), so nothing to promote
    result = cp.promote_once(promotion_priority)
    assert result is None

def test_full_demotion_chain_real_pattern_1_gte0_2_0(priority_order):
    """
    Walk the complete demotion chain for production pattern "1 >=0 2 0"
    (single-kid families) with real priority [Kids, YA, OA, Adults].
    """
    cp = CompositionPattern.from_string("1 >=0 2 0")
    chain = [cp.to_string()]
    current = cp
    while True:
        demoted = current.demote_once(priority_order)
        if demoted is None:
            break
        chain.append(demoted.to_string())
        current = demoted
    
    assert chain == [
        "1 >=0 2 0",    # original
        "0 >=0 2 0",    # Kids 1->0 (exact)
        "0 >=0 1 0",    # Adults 2->1 (all higher-priority at 0/>=0)
        "0 >=0 0 0",    # Adults 1->0
    ]
