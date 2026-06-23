import pytest
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.residence.composition_pattern import CompositionPattern
from may.residence.relationship_rules import RelationshipRule
from may.population.person import Person
import numpy as np

# --- Real Objects Setup ---

@pytest.fixture
def geography():
    geo = Geography(data_dir="tests/test_data/micro_world/geography")
    geo.load_from_csv()
    return geo

@pytest.fixture
def venue_manager(geography):
    vm = VenueManager(geography, data_dir="tests/test_data/micro_world/venues")
    vm.load_from_yaml_config("test_venues_config.yaml")
    return vm

@pytest.fixture
def population_manager(geography):
    pm = PopulationManager(geography=geography, data_dir="tests/test_data/micro_world/population")
    # We don't load from CSV here because we want exact control over the people for the tests
    pm.people = []
    # Initialize the ID counter to avoid conflicting IDs if other tests run first
    Person.reset_counter()
    return pm

@pytest.fixture
def distributor(geography, population_manager, venue_manager):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir="tests/test_data/micro_world/households",
        config_file="test_households_config.yaml"
    )
    # Ensure person pools are initialized as empty dicts for each category
    distributor.person_pool_by_geo_unit = {"SGU_001": [{} for _ in distributor.categories]}
    
    # Force relationship rules to be enabled even if no realistic YAML is loaded for them
    distributor.relationship_rules.enabled = True
    distributor.relationship_rules.selection_strategy = {'max_attempts': 50, 'use_best_candidate': True}
    
    return distributor

def create_person(age, sex="female", geo_unit=None):
    p = Person(age=age, sex=sex, geographical_unit=geo_unit)
    # Ensure they have a properties dict and no cohabiting_couple flag initially
    p.properties = {}
    return p

# --- Helper Methods Tests ---

def test_adjust_role_count_for_pattern_matches(distributor):
    """When pattern needs exactly what the role demands, role_count remains unchanged."""
    pattern = CompositionPattern.from_string("2 >=0 2 0")
    cat_names = ["Kids"]
    cat_indices = [0]
    
    role_count, skip = distributor._adjust_role_count_for_pattern(
        role_count=2, role_name="child", category_names=cat_names, 
        category_indices=cat_indices, pattern=pattern, show_detailed_logs=False
    )
    
    assert role_count == 2
    assert skip is False

def test_adjust_role_count_for_pattern_demoted(distributor):
    """When pattern acts demoted (pattern asks for less than role)."""
    pattern = CompositionPattern.from_string("1 >=0 2 0")
    cat_indices = [0] # Kids
    
    role_count, skip = distributor._adjust_role_count_for_pattern(
        role_count=2, role_name="child", category_names=["Kids"], 
        category_indices=cat_indices, pattern=pattern, show_detailed_logs=False
    )
    
    assert role_count == 1
    assert skip is False

def test_adjust_role_count_for_pattern_skip_zero(distributor):
    """If pattern count is 0, the role should be completely skipped."""
    pattern = CompositionPattern.from_string("0 >=0 2 0")
    cat_indices = [0] # Kids
    
    role_count, skip = distributor._adjust_role_count_for_pattern(
        role_count=2, role_name="child", category_names=["Kids"], 
        category_indices=cat_indices, pattern=pattern, show_detailed_logs=False
    )
    
    assert role_count == 0
    assert skip is True

def test_prepare_role_candidates(distributor):
    geo_mock = distributor.geography.get_unit("SGU_001")
    p1 = create_person(10, geo_unit=geo_mock)
    p2 = create_person(12, geo_unit=geo_mock)
    p3 = create_person(20, geo_unit=geo_mock)
    p4 = create_person(40, geo_unit=geo_mock)
    p5 = create_person(45, geo_unit=geo_mock)
    
    # Mock pools: list of dicts of {person_id: Person} for each category index
    pools = [
        {p1.id: p1, p2.id: p2}, # Kids (idx 0)
        {p3.id: p3},            # YA (idx 1)
        {p4.id: p4, p5.id: p5}, # Adults (idx 2)
        {}                      # Old Adults (idx 3)
    ]
    
    # 1. Standard retrieval
    candidates = distributor._prepare_role_candidates(
        pools, category_indices=[2], role_index=0, backtrack_attempt=0, 
        tried_first_role_ids=set(), avoid_duplicates=True, show_detailed_logs=False, log_backtracks=False
    )
    assert len(candidates) == 2
    assert {c.id for c in candidates} == {p4.id, p5.id}
    
    # 2. Backtracking exclusion (only applies to role_index == 0)
    candidates_bt = distributor._prepare_role_candidates(
        pools, category_indices=[2], role_index=0, backtrack_attempt=1, 
        tried_first_role_ids={p4.id},  # we already tried person 4 as the first role
        avoid_duplicates=True, show_detailed_logs=False, log_backtracks=False
    )
    assert len(candidates_bt) == 1
    assert candidates_bt[0].id == p5.id

    # 3. Backtracking on a non-first role (role_index > 0) shouldn't exclude globally
    candidates_bt_second = distributor._prepare_role_candidates(
        pools, category_indices=[2], role_index=1, backtrack_attempt=1, 
        tried_first_role_ids={p4.id},
        avoid_duplicates=True, show_detailed_logs=False, log_backtracks=False
    )
    assert len(candidates_bt_second) == 2 

def test_can_skip_role_with_no_candidates(distributor):
    pattern = CompositionPattern.from_string("0 >=0 2 0")
    cat_indices = [1] # YA is index 1, which pattern has as ">=0"
    
    # 1. If role is "any" and minimum pattern require is 0 -> Can skip
    can_skip = distributor._can_skip_role_with_no_candidates(
        role_count="any", category_indices=[1], pattern=pattern, show_detailed_logs=False
    )
    assert can_skip is True
    
    # 2. If role is "any" but minimum pattern require is > 0 -> Cannot skip
    pattern_strict = CompositionPattern.from_string("0 1 2 0") # YA is 1
    can_skip_strict = distributor._can_skip_role_with_no_candidates(
        role_count="any", category_indices=[1], pattern=pattern_strict, show_detailed_logs=False
    )
    assert can_skip_strict is False
    
    # 3. If role is numeric -> Cannot skip
    can_skip_num = distributor._can_skip_role_with_no_candidates(
        role_count=1, category_indices=[1], pattern=pattern, show_detailed_logs=False
    )
    assert can_skip_num is False

# --- Core Backtracking Test Setup ---

@pytest.fixture
def mock_rule():
    return RelationshipRule(
        name="Test Rule",
        roles={
            "parent": {"categories": ["Adults"], "count": 2},
            "child": {"categories": ["Kids"], "count": 1}
        },
        selection_order=["child", "parent"],
        constraints=[
            {
                "type": "numerical_attribute_difference",
                "attribute": "age",
                "role_1": "parent",
                "role_2": "child",
                "min_difference": 20, # Parent must be 20y older
                "max_difference": 50
            }
        ]
    )

def test_select_roles_with_backtracking_success(distributor, mock_rule):
    pattern = CompositionPattern.from_string("1 0 2 0")
    geo_mock = distributor.geography.get_unit("SGU_001")
    
    p_kid = create_person(10, geo_unit=geo_mock)
    p_adult1 = create_person(35, geo_unit=geo_mock)
    p_adult2 = create_person(40, geo_unit=geo_mock)
    
    # Pools
    pools = [
        {p_kid.id: p_kid},       # Kid
        {},                      # YA
        {p_adult1.id: p_adult1, p_adult2.id: p_adult2}, # Adults
        {}                       # Old Adults
    ]
    
    backtrack_config = {"enabled": True, "max_backtracks": 3, "avoid_duplicates": True}
    
    selected, failed_idx = distributor._select_roles_with_backtracking(
        rule=mock_rule, pattern=pattern, pools=pools, backtrack_config=backtrack_config, show_detailed_logs=False
    )
    
    assert failed_idx is None
    assert "parent" in selected
    assert "child" in selected
    assert len(selected["parent"]) == 2
    assert len(selected["child"]) == 1

def test_select_roles_with_backtracking_trigger_backtrack(distributor, mock_rule):
    """
    Force a backtrack.
    Adult pool has P1 (age 25) and P2 (age 40).
    Child pool has C1 (age 10).
    Rule needs parent to be 20 years older.
    If the algorithm randomly picks P1 first, age difference is 15 -> Child validation fails!
    It should backtrack and try P2 instead.
    """
    pattern = CompositionPattern.from_string("1 0 1 0") # Need 1 parent, 1 child
    
    # Modify rule for 1 parent
    mock_rule.roles["parent"]["count"] = 1
    
    geo_mock = distributor.geography.get_unit("SGU_001")
    p_kid = create_person(10, geo_unit=geo_mock)
    p_adult_young = create_person(25, geo_unit=geo_mock) # Fails 20y diff constraint
    p_adult_old = create_person(40, geo_unit=geo_mock)   # Passes constraint
    
    pools = [
        {p_kid.id: p_kid},
        {},
        {p_adult_young.id: p_adult_young, p_adult_old.id: p_adult_old},
        {}
    ]
    
    # Force the relationship rules to NOT fallback to the best candidate so failure happens
    distributor.relationship_rules.selection_strategy['use_best_candidate'] = False
    
    # We must patch random selection in Validator to be deterministic for this test.
    original_shuffle = np.random.shuffle
    def fake_shuffle(x): 
        # Sort so the invalid 25yo is always picked as the FIRST candidate
        x.sort(key=lambda p: p.age)
    
    np.random.shuffle = fake_shuffle
    
    backtrack_config = {"enabled": True, "max_backtracks": 3, "avoid_duplicates": True, "log_backtracks": False}
    
    try:
        selected, failed_idx = distributor._select_roles_with_backtracking(
            rule=mock_rule, pattern=pattern, pools=pools, backtrack_config=backtrack_config, show_detailed_logs=True
        )
        
        # It should succeed after backtracking!
        assert failed_idx is None
        assert len(selected["parent"]) == 1
        assert selected["parent"][0].id == p_adult_old.id # Should be the 40yo!
    finally:
        np.random.shuffle = original_shuffle

def test_select_roles_with_backtracking_exhausted(distributor, mock_rule):
    """If no combinations work, it should exhaust backtracks and fail."""
    pattern = CompositionPattern.from_string("1 0 1 0")
    mock_rule.roles["parent"]["count"] = 1
    
    geo_mock = distributor.geography.get_unit("SGU_001")
    p_kid = create_person(10, geo_unit=geo_mock)
    p_adult1 = create_person(25, geo_unit=geo_mock) # Neither is 20y older
    p_adult2 = create_person(22, geo_unit=geo_mock)
    
    pools = [
        {p_kid.id: p_kid},
        {},
        {p_adult1.id: p_adult1, p_adult2.id: p_adult2},
        {}
    ]
    
    distributor.relationship_rules.selection_strategy['use_best_candidate'] = False
    backtrack_config = {"enabled": True, "max_backtracks": 1, "avoid_duplicates": True}
    
    selected, failed_idx = distributor._select_roles_with_backtracking(
        rule=mock_rule, pattern=pattern, pools=pools, backtrack_config=backtrack_config, show_detailed_logs=False
    )
    
    assert selected is None
    assert failed_idx == 0 # Failed at child selection

def test_select_roles_with_backtracking_fail_first_role(distributor, mock_rule):
    """If pool for the very first role is empty, it fails immediately (cannot backtrack)."""
    pattern = CompositionPattern.from_string("1 0 2 0")
    geo_mock = distributor.geography.get_unit("SGU_001")
    p_adult = create_person(30, geo_unit=geo_mock)
    
    pools = [
        {}, # Empty Kid pool! Child is the first role in selection_order.
        {},
        {p_adult.id: p_adult}, 
        {}
    ]
    
    selected, failed_idx = distributor._select_roles_with_backtracking(
        rule=mock_rule, pattern=pattern, pools=pools, backtrack_config={"enabled": True}, show_detailed_logs=False
    )
    
    assert selected is None
    assert failed_idx == 0 # Failed at Kid index (index 0)

def test_select_roles_defer_couple_flagging(distributor):
    """Verify that creates_romantic_couple flagging only happens ON SUCCESS."""
    pattern = CompositionPattern.from_string("0 0 2 0")
    
    rule = RelationshipRule(
        name="Couples",
        roles={"couple": {"categories": ["Adults"], "count": 2}},
        selection_order=["couple"],
        constraints=[
            {
                "type": "pair_matching", "role": "couple",
                "creates_romantic_couple": True,
                "categorical_attribute": {"attribute": "sex", "same_category_probability": 0.0},
                "numerical_attribute": {"max_absolute_difference": 10}
            }
        ]
    )
    
    geo_mock = distributor.geography.get_unit("SGU_001")
    p1 = create_person(30, geo_unit=geo_mock)
    p2 = create_person(35, sex="male", geo_unit=geo_mock)
    
    pools = [{}, {}, {p1.id: p1, p2.id: p2}, {}]
    distributor.relationship_rules.selection_strategy['use_best_candidate'] = False
    
    selected, failed_idx = distributor._select_roles_with_backtracking(
        rule=rule, pattern=pattern, pools=pools, backtrack_config={}, show_detailed_logs=False
    )
    
    assert failed_idx is None
    assert "couple" in selected
    # They should be flagged
    assert p1.properties['cohabiting_couple'] == [p2.id]
    assert p2.properties['cohabiting_couple'] == [p1.id]
