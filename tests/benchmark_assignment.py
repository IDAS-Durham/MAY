import time
import timeit
import logging
import random
from typing import List, Dict, Any
from unittest.mock import MagicMock

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("benchmark")

# Mock classes to avoid full dependency chain
class MockGeoUnit:
    def __init__(self, name="E0000001"):
        self.name = name

class MockPerson:
    def __init__(self, pid, age, sex):
        self.id = pid
        self.age = age
        self.sex = sex
        self.geographical_unit = MockGeoUnit()
        self.activities = ["school", "leisure"]
        self.properties = {}
        # UNIFIED STRUCTURE: activity_map['residence']['household'] = [subsets]
        self.activity_map = {}

    def has_activity(self, activity):
        return activity in self.activities

class MockVenue:
    def __init__(self, vid, vtype="household"):
        self.id = vid
        self.type = vtype
        self.geographical_unit = MockGeoUnit()
        self.properties = {'_age_categories': []}
        self.members = []
    
    def get_all_members(self):
        return self.members
    
    def size(self):
        return len(self.members)
    
class MockSubset:
    def __init__(self, venue, subset_name):
        self.venue = venue
        self.subset_name = subset_name

class MockVenueManager:
    def __init__(self, venues):
        self.venues = venues
    
    def get_all_venues_list(self):
        return self.venues
        
    def get_residence_types(self):
        return ["household"]

# Import actual classes to benchmark
from may.attribute_assignment.assigner import AttributeAssigner
from may.attribute_assignment.assignment_config import AttributeAssignmentConfig, Role, HouseholdStructure, MatchingRule, AssignmentRule

def setup_mock_config():
    """Setup a mock configuration similar to ethnicity and comorbidities."""
    config = MagicMock(spec=AttributeAssignmentConfig)
    config.attribute_name = "ethnicity"
    config.assignment_level = "person_by_household" # Structure based
    config.filters = {}
    config.required_attributes = {}
    config.settings = {}
    
    # Mock Roles
    role1 = Role("primary_adult", "", ["adults"])
    role2 = Role("children", "", ["children"])
    config.roles = {"primary_adult": role1, "children": role2}
    
    # Mock Structure
    rule = MatchingRule(actual_patterns=["1+ 0+"], original_patterns=[])
    structure = HouseholdStructure("family", "", False, [rule])
    config.household_structures = {"family": structure}
    
    # Mock Assignment Rules
    assign_rule1 = AssignmentRule("primary_adult", 1, "", {'strategy': 'probabilistic', 'data_source': 'geo_dist'})
    assign_rule2 = AssignmentRule("children", 2, "", {'strategy': 'inheritance', 'inherit_from': {'roles': ['primary_adult']}})
    
    # Mock Structure Rules
    struct_rules = MagicMock()
    struct_rules.rules = [assign_rule1, assign_rule2]
    config.assignment_rules = {"family": struct_rules, "person": struct_rules} # Reuse for simplicity
    
    # Mock Methods
    config.get_household_structure.return_value = "family"
    
    # Simple role determination logic for mock
    def get_person_role(person, structure, assigned_roles, verbose=False, person_category=None):
        # Use person_category if provided, otherwise fallback to finding it (not needed for mock logic really)
        subset_name = person_category if person_category else (person.subset_name if hasattr(person, 'subset_name') else "children")
        
        if "adults" in subset_name:
            if "primary_adult" not in assigned_roles:
                return "primary_adult"
        return "children" # Fallback
        
    # We will patch Config's methods in the benchmark loop if needed, 
    # but for now let's use the real Config class logic if possible? 
    # Actually, constructing a real Config is complex without files.
    # Let's rely on the Assigner using the config object we pass.
    
    # For Role determination in _assign_household, it calls config.get_person_role
    # fast mock side effect
    config.get_person_role.side_effect = get_person_role
    
    # Mock get_assignment_rule
    def get_assignment_rule(structure, role, verbose=False):
        if role == "primary_adult": return assign_rule1
        return assign_rule2
    config.get_assignment_rule.side_effect = get_assignment_rule
    
    # Mock get_person_assignment_rule
    config.get_person_assignment_rule.return_value = assign_rule1

    return config

def setup_mock_data_manager():
    dm = MagicMock()
    # Mock lookup
    def lookup(source, key, *args):
        if source == "geo_dist":
            return {"White": 0.8, "Asian": 0.1, "Black": 0.1}
        return None
    dm.lookup.side_effect = lookup
    return dm

def benchmark_passes_filters():
    """Benchmark _passes_filters method."""
    logger.info("Benchmarking _passes_filters...")
    
    # Setup
    config = MagicMock(spec=AttributeAssignmentConfig)
    config.attribute_name = "test"
    config.filters = {
        'activities': {'include': ['school']}
    }
    config.required_attributes = {}
    config.settings = {}
    
    dm = setup_mock_data_manager()
    assigner = AttributeAssigner(config, dm)
    
    person = MockPerson(1, 20, 'male')
    person.activities = ["school", "leisure"]
    
    # Run
    start_time = time.time()
    iterations = 1_000_000
    for _ in range(iterations):
        assigner._passes_filters(person)
    end_time = time.time()
    
    duration = end_time - start_time
    logger.info(f"  _passes_filters: {iterations} calls in {duration:.4f}s ({iterations/duration:.2f} calls/s)")
    return duration

def benchmark_assign_household():
    """Benchmark _assign_household (Ethnicity case)."""
    logger.info("Benchmarking _assign_household (Ethnicity case)...")
    
    # Setup
    config = setup_mock_config()
    dm = setup_mock_data_manager()
    assigner = AttributeAssigner(config, dm)
    
    # Create household with members
    household = MockVenue(1, "household")
    p1 = MockPerson(1, 35, 'female')
    p1.subset_name = "adults" # Helper for our mock config logic
    p1.activity_map = {'residence': {'household': [MockSubset(household, "adults")]}}
    
    p2 = MockPerson(2, 5, 'male')
    p2.subset_name = "children"
    p2.activity_map = {'residence': {'household': [MockSubset(household, "children")]}}
    
    household.members = [p1, p2]
    
    # Mock strategy creation to avoid overhead
    strategy = MagicMock()
    strategy.assign.return_value = "White"
    strategy.strategy_type = "mock"
    assigner._get_or_create_strategy = MagicMock(return_value=strategy)
    
    # Run
    start_time = time.time()
    iterations = 5_000 # Households
    for _ in range(iterations):
        assigner._assign_household(household)
        # Reset stats to avoid huge dicts
        assigner.stats['assignments_by_role'] = {} 
    end_time = time.time()
    
    duration = end_time - start_time
    logger.info(f"  _assign_household: {iterations} households in {duration:.4f}s ({iterations/duration:.2f} hh/s)")
    return duration

def benchmark_assign_all_people():
    """Benchmark _assign_all_people (Comorbidities case)."""
    logger.info("Benchmarking _assign_all_people (Comorbidities case)...")
    
    # Setup
    config = setup_mock_config()
    config.assignment_level = "person"
    dm = setup_mock_data_manager()
    assigner = AttributeAssigner(config, dm)
    
    # Mock Venue Manager
    people = [MockPerson(i, 20+i%50, 'female') for i in range(10_000)]
    venue = MockVenue(1, "household")
    venue.members = people
    venue_manager = MockVenueManager([venue])
    
    # Mock passing filters
    assigner._passes_filters = MagicMock(return_value=True)
    
    # Mock strategy
    strategy = MagicMock()
    strategy.assign.return_value = ["cvd"]
    strategy.strategy_type = "probabilistic_conditions"
    assigner._get_or_create_strategy = MagicMock(return_value=strategy)

    # Run
    start_time = time.time()
    assigner._assign_all_people(venue_manager)
    end_time = time.time()
    
    duration = end_time - start_time
    logger.info(f"  _assign_all_people: 10,000 people in {duration:.4f}s ({10000/duration:.2f} people/s)")
    return duration

if __name__ == "__main__":
    t1 = benchmark_passes_filters()
    t2 = benchmark_assign_household()
    t3 = benchmark_assign_all_people()
    
    print("-" * 40)
    print(f"Total Benchmark Time: {t1+t2+t3:.4f}s")
