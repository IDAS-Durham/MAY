import pytest
import numpy as np
from dataclasses import dataclass, field
from may.residence.relationship_rules import RelationshipRulesValidator

@dataclass
class MockPerson:
    id: int
    age: int
    sex: str
    properties: dict = field(default_factory=dict)

@pytest.fixture
def validator():
    # Empty categories list since we just need the validator instance methods
    v = RelationshipRulesValidator(categories=[])
    # Setup standard selection strategy from configs
    v.selection_strategy = {
        'max_attempts': 10,
        'use_best_candidate': True,
        'penalty_mode': "squared",
        'log_violations': False
    }
    return v

# 1. validate_numerical_attribute_difference_constraint
def test_validate_numerical_attribute_difference_pass(validator):
    p1 = MockPerson(1, age=40, sex='male')
    p2_list = [MockPerson(2, age=10, sex='female')]
    
    constraint = {
        'type': 'numerical_attribute_difference',
        'attribute': 'age',
        'min_difference': 16,
        'max_difference': 50
    }
    
    is_valid, penalty = validator.validate_numerical_attribute_difference_constraint(
        p1, p2_list, constraint
    )
    
    assert is_valid is True
    assert penalty == 0.0

def test_validate_numerical_attribute_difference_too_young(validator):
    p1 = MockPerson(1, age=20, sex='male') # Parent
    p2_list = [MockPerson(2, age=10, sex='female')] # Child
    
    constraint = {
        'attribute': 'age',
        'min_difference': 16, # Parent must be at least 16 years older
        'max_difference': 50
    }
    
    is_valid, penalty = validator.validate_numerical_attribute_difference_constraint(
        p1, p2_list, constraint
    )
    
    assert is_valid is False
    assert penalty == 6 # Diff is 10, min is 16 -> penalty = 6

def test_validate_numerical_attribute_difference_too_old(validator):
    p1 = MockPerson(1, age=70, sex='male') # Parent
    p2_list = [MockPerson(2, age=10, sex='female')] # Child
    
    constraint = {
        'attribute': 'age',
        'min_difference': 16,
        'max_difference': 50
    }
    
    is_valid, penalty = validator.validate_numerical_attribute_difference_constraint(
        p1, p2_list, constraint
    )
    
    assert is_valid is False
    assert penalty == 10 # Diff is 60, max is 50 -> penalty = 10

def test_validate_numerical_attribute_difference_categorical_override(validator):
    p1_male = MockPerson(1, age=65, sex='male') # Male parent
    p1_female = MockPerson(2, age=65, sex='female') # Female parent
    p2_list = [MockPerson(3, age=10, sex='female')]
    
    constraint = {
        'attribute': 'age',
        'min_difference': 16,
        'max_difference': 50,
        'max_difference_by_categorical_attribute': {
            'attribute': 'sex',
            'values': {
                'female': 50,
                'male': 55  # Males allowed to be 55 years older
            }
        }
    }
    
    # Male is 55 years older -> allowed
    is_valid_m, _ = validator.validate_numerical_attribute_difference_constraint(
        p1_male, p2_list, constraint
    )
    assert is_valid_m is True
    
    # Female is 55 years older -> fails (max 50)
    is_valid_f, _ = validator.validate_numerical_attribute_difference_constraint(
        p1_female, p2_list, constraint
    )
    assert is_valid_f is False

def test_validate_numerical_attribute_difference_empty_p2(validator):
    # Empty people2 list immediately returns True
    p1 = MockPerson(1, age=40, sex='male')
    is_valid, penalty = validator.validate_numerical_attribute_difference_constraint(
        p1, [], {}
    )
    assert is_valid is True

# 2. validate_pair_numerical_attribute_difference
def test_validate_pair_numerical_attribute_difference(validator):
    p1 = MockPerson(1, age=30, sex='male')
    p2 = MockPerson(2, age=55, sex='female') # diff = 25
    
    constraint = {
        'numerical_attribute': {
            'attribute': 'age',
            'max_absolute_difference': 19
        }
    }
    
    is_valid, penalty = validator.validate_pair_numerical_attribute_difference(
        p1, p2, constraint
    )
    
    assert is_valid is False
    assert penalty == 6 # 25 - 19

def test_calculate_pair_numerical_attribute_penalty(validator):
    p1 = MockPerson(1, age=30, sex='male')
    p2 = MockPerson(2, age=40, sex='female') # diff = 10
    
    constraint = {
        'numerical_attribute': {
            'attribute': 'age',
            'mean_difference': 3.0,
            'std_difference': 5.0
        }
    }
    
    penalty = validator.calculate_pair_numerical_attribute_penalty(p1, p2, constraint)
    # diff = 10. target = 3. z_score = abs(10-3)/5 = 7/5 = 1.4
    # penalty_mode is "squared" -> 1.4^2 = 1.96
    assert np.isclose(penalty, 1.96)

# 3. select_pair
def test_select_pair_basic(validator, monkeypatch):
    # 4 candidates
    candidates = [
        MockPerson(1, age=30, sex='male'),
        MockPerson(2, age=30, sex='male'),
        MockPerson(3, age=28, sex='female'),
        MockPerson(4, age=29, sex='female')
    ]
    
    constraint = {
        'categorical_attribute': {
            'attribute': 'sex',
            'same_category_probability': 0.0 # Force heterosexual
        },
        'numerical_attribute': {
            'max_absolute_difference': 19
        }
    }
    
    # Set random seed for predictability (or just verify it returns a valid diff-sex pair)
    pair = validator.select_pair(candidates, constraint)
    
    assert pair is not None
    p_a, p_b = pair
    assert p_a.sex != p_b.sex
    assert p_a.id != p_b.id

def test_select_pair_same_category(validator):
    candidates = [
        MockPerson(1, age=30, sex='male'),
        MockPerson(2, age=31, sex='male'),
        MockPerson(3, age=28, sex='female'),
        MockPerson(4, age=29, sex='female')
    ]
    
    constraint = {
        'categorical_attribute': {
            'attribute': 'sex',
            'same_category_probability': 1.0 # Force homosexual
        }
    }
    
    pair = validator.select_pair(candidates, constraint)
    assert pair is not None
    p_a, p_b = pair
    assert p_a.sex == p_b.sex

def test_select_pair_no_candidates(validator):
    assert validator.select_pair([], {}) is None
    assert validator.select_pair([MockPerson(1, age=30, sex='male')], {}) is None

# 4. validate_composition
def test_validate_composition(validator):
    composition = {"Kids": 3, "Adults": 2}
    
    # Valid
    assert validator.validate_composition(composition, [
        {"category_sum": ["Kids"], "max": 4},
        {"category": "Adults", "max": 2},
        {"household_size": True, "max": 8}
    ])[0] is True
    
    # Fails sum
    assert validator.validate_composition(composition, [
        {"category_sum": ["Kids"], "max": 2}
    ])[0] is False
    
    # Fails category
    assert validator.validate_composition(composition, [
        {"category": "Adults", "max": 1}
    ])[0] is False
    
    # Fails household size
    assert validator.validate_composition(composition, [
        {"household_size": True, "max": 4}
    ])[0] is False

# =========================================================
# Tests added after self-audit — filling gaps
# =========================================================

def test_validate_numerical_attr_diff_multiple_children(validator):
    """
    Test with MULTIPLE children — the code checks against MAX child age for
    min_difference and MIN child age for max_difference. This is a subtle
    and critical detail that needs explicit verification.
    """
    parent = MockPerson(1, age=45, sex='male')
    children = [
        MockPerson(2, age=5, sex='female'),   # youngest
        MockPerson(3, age=15, sex='male'),    # oldest
    ]

    constraint = {
        'attribute': 'age',
        'min_difference': 16,
        'max_difference': 50
    }

    # diff_max = parent(45) - max_child(15) = 30 >= 16 ✓
    # diff_min = parent(45) - min_child(5)  = 40 <= 50 ✓
    is_valid, _ = validator.validate_numerical_attribute_difference_constraint(
        parent, children, constraint
    )
    assert is_valid is True

    # Now with a parent who is too old for the youngest child
    old_parent = MockPerson(4, age=60, sex='male')
    # diff_min = 60 - 5 = 55 > 50 ✗
    is_valid2, penalty = validator.validate_numerical_attribute_difference_constraint(
        old_parent, children, constraint
    )
    assert is_valid2 is False
    assert penalty == 5  # 55 - 50

    # Parent too young for oldest child
    young_parent = MockPerson(5, age=28, sex='female')
    # diff_max = 28 - 15 = 13 < 16 ✗
    is_valid3, penalty3 = validator.validate_numerical_attribute_difference_constraint(
        young_parent, children, constraint
    )
    assert is_valid3 is False
    assert penalty3 == 3  # 16 - 13

def test_select_person_with_constraint(validator):
    """Test the full select_person_with_constraint method — not just validation internals."""
    candidates = [
        MockPerson(1, age=25, sex='male'),   # too young (diff=15 < 16)
        MockPerson(2, age=26, sex='female'), # just right (diff=16)
        MockPerson(3, age=50, sex='male'),   # also valid (diff=40)
    ]

    existing = {"role_A": [MockPerson(10, age=10, sex='female')]}
    constraints = [{
        'type': 'numerical_attribute_difference',
        'attribute': 'age',
        'role_1': 'role_B',
        'role_2': 'role_A',
        'min_difference': 16,
        'max_difference': 50
    }]

    np.random.seed(42)
    selected = validator.select_person_with_constraint(
        candidates, existing, constraints, current_role='role_B'
    )

    assert selected is not None
    # Person 1 (age 25) should never be selected (diff=15 < 16)
    assert selected.age >= 26

def test_select_person_best_candidate_fallback(validator):
    """
    When NO candidate perfectly satisfies constraints, best_candidate logic
    should pick the one with lowest penalty.
    """
    candidates = [
        MockPerson(1, age=20, sex='male'),  # diff=10, penalty=6
        MockPerson(2, age=24, sex='female'),  # diff=14, penalty=2
        MockPerson(3, age=15, sex='male'),  # diff=5, penalty=11
    ]

    existing = {"role_A": [MockPerson(10, age=10, sex='female')]}
    constraints = [{
        'type': 'numerical_attribute_difference',
        'attribute': 'age',
        'role_1': 'role_B',
        'role_2': 'role_A',
        'min_difference': 16,
        'max_difference': 50
    }]

    selected = validator.select_person_with_constraint(
        candidates, existing, constraints, current_role='role_B'
    )

    # Best candidate should be person 2 (lowest penalty = 2)
    assert selected is not None
    assert selected.id == 2
    assert validator.stats['best_candidate_selections'] >= 1

def test_select_person_use_best_false_returns_none(validator):
    """When use_best_candidate is False and no valid candidate, should return None."""
    validator.selection_strategy['use_best_candidate'] = False
    
    candidates = [
        MockPerson(1, age=20, sex='male'),  # diff=10 < 16
    ]
    existing = {"role_A": [MockPerson(10, age=10, sex='female')]}
    constraints = [{
        'type': 'numerical_attribute_difference',
        'attribute': 'age',
        'role_1': 'role_B',
        'role_2': 'role_A',
        'min_difference': 16,
        'max_difference': 50
    }]

    selected = validator.select_person_with_constraint(
        candidates, existing, constraints, current_role='role_B'
    )
    assert selected is None

def test_validate_pair_numerical_attribute_difference_passes(validator):
    """Test the passing case — close ages within max_absolute_difference."""
    p1 = MockPerson(1, age=30, sex='male')
    p2 = MockPerson(2, age=33, sex='female')  # diff = 3

    constraint = {
        'numerical_attribute': {
            'attribute': 'age',
            'max_absolute_difference': 19
        }
    }
    is_valid, penalty = validator.validate_pair_numerical_attribute_difference(p1, p2, constraint)
    assert is_valid is True
    assert penalty == 0.0

def test_validate_pair_no_numerical_config(validator):
    """If constraint has no numerical_attribute config, should return valid."""
    p1 = MockPerson(1, age=30, sex='male')
    p2 = MockPerson(2, age=80, sex='female')
    is_valid, penalty = validator.validate_pair_numerical_attribute_difference(p1, p2, {})
    assert is_valid is True

def test_select_pair_age_gap_too_large(validator):
    """If all potential partners exceed max_absolute_difference, pair fails or uses best."""
    candidates = [
        MockPerson(1, age=20, sex='male'),
        MockPerson(2, age=60, sex='female'),  # diff = 40 > 19
    ]
    constraint = {
        'categorical_attribute': {
            'attribute': 'sex',
            'same_category_probability': 0.0
        },
        'numerical_attribute': {
            'attribute': 'age',
            'max_absolute_difference': 19
        }
    }
    # With use_best=True, it should still return a pair (best-effort)
    pair = validator.select_pair(candidates, constraint)
    assert pair is not None  # Best candidate fallback kicks in

def test_validate_composition_multi_category_sum(validator):
    """Test category_sum across multiple categories (real config uses ["Kids", "Young Adults"])."""
    composition = {"Kids": 3, "Young Adults": 2, "Adults": 1}

    # Sum of Kids+YA = 5 <= 8: valid
    assert validator.validate_composition(composition, [
        {"category_sum": ["Kids", "Young Adults"], "max": 8}
    ])[0] is True

    # Sum of Kids+YA = 5 > 4: invalid
    is_valid, msg = validator.validate_composition(composition, [
        {"category_sum": ["Kids", "Young Adults"], "max": 4}
    ])
    assert is_valid is False
    assert "sum" in msg.lower()

def test_validate_composition_missing_category(validator):
    """Composition missing a category should default to 0 count."""
    composition = {"Adults": 2}  # No Kids key

    assert validator.validate_composition(composition, [
        {"category_sum": ["Kids", "Adults"], "max": 5}
    ])[0] is True  # 0 + 2 = 2 <= 5

