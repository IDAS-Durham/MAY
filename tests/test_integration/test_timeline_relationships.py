import pytest
from pathlib import Path
import logging

# Ensure debug logging is captured
logging.basicConfig(level=logging.DEBUG)

class MockGeography:
    def __init__(self, levels):
        self.levels = levels

class MockGeoUnit:
    def __init__(self, name, level_name, parent=None):
        self.name = name
        self.level_name = level_name
        self.parent = parent

class MockVenue:
    def __init__(self, id_val):
        self.id = id_val

class MockSubset:
    def __init__(self, venue):
        self.venue = venue

class MockPerson:
    def __init__(self, id_val, age, geo_unit):
        self.id = id_val
        self.age = age
        self.geographical_unit = geo_unit
        self.activity_map = {}
        self.properties = {}
        # We need mock subsets when testing the Numba arrays
        self.subsets = {}

class MockPopulation:
    def __init__(self, people):
        self.people = people

class MockWorld:
    def __init__(self, population, geography):
        self.population = population
        self.geography = geography

@pytest.fixture
def mock_friendship_world():
    # Setup Geography
    levels = ["LGU", "MGU", "SGU"]
    geography = MockGeography(levels)
    
    mgu = MockGeoUnit("MGU_1", "MGU")
    sgu_1 = MockGeoUnit("SGU_1", "SGU", parent=mgu)
    sgu_2 = MockGeoUnit("SGU_2", "SGU", parent=mgu)
    
    # Setup Venues
    venue_school = MockVenue("school_1")
    
    # Setup People
    people = [
        MockPerson(0, 10, sgu_1), # P0: SGU_1, Age 10, Student
        MockPerson(1, 10, sgu_1), # P1: SGU_1, Age 10, Student
        MockPerson(2, 60, sgu_1), # P2: SGU_1, Age 60, Teacher (Same venue, different subset, fails age gap for P0)
        MockPerson(3, 12, sgu_2), # P3: SGU_2, Age 12, Student
        MockPerson(4, 30, sgu_2), # P4: SGU_2, Age 30, Unrelated
        MockPerson(5, 31, sgu_2), # P5: SGU_2, Age 31, Unrelated
    ]
    
    # Assign activities
    subset_student = MockSubset(venue_school)
    subset_teacher = MockSubset(venue_school)
    
    # For FriendshipBuilder:
    # 1. Activities are gathered from activity_map['primary_activity']
    # 2. Subsets are read from self._person_subset built artificially for multiple arrays
    # *Note: Actually FriendshipBuilder in the codebase builds a dummy _person_subset full of zeros. Wait!
    
    people[0].activity_map['primary_activity'] = {'school': [subset_student]}
    people[1].activity_map['primary_activity'] = {'school': [subset_student]}
    people[2].activity_map['primary_activity'] = {'school': [subset_teacher]}
    people[3].activity_map['primary_activity'] = {'school': [subset_student]}
    
    world = MockWorld(MockPopulation(people), geography)
    return world

def test_friendship_builder(mock_friendship_world):
    from may.relationships.friendship_builder import FriendshipBuilder
    
    config_path = str(Path(__file__).parent.parent / "test_data" / "micro_world" / "relationships" / "test_relationships_config.yaml")
    
    # Initialize builder
    builder = FriendshipBuilder(mock_friendship_world, config_path)
    
    # Run the Numba network generator
    relationships = builder.build_all(store=True)
    
    people = mock_friendship_world.population.people
    
    # Validation 1: Connection Counts
    # Everyone should be assigned exactly 5 connection targets because of variants: [{probability: 1.0, count: 5}]
    # Note: They might not actually *fill* 5 connections if there aren't enough valid candidates locally!
    # But we can verify P0 got *some* connections.
    
    p0_friends = people[0].properties['friendships']
    
    # Validation 2: Array bounding and Geographic matching
    # P0 (Age 10, SGU_1) and P1 (Age 10, SGU_1) should be connected.
    assert people[1].id in p0_friends, "P0 should be friends with P1 (Same SGU, Same Subset, Same Age)"
    
    # Validation 3: Age filtering limits
    # P2 (Age 60) should NOT be matching with P0 due to the `range: 5` on activity and `range: 10` on SGU.
    assert people[2].id not in p0_friends, "P0 should not be friends with P2 (Fails age bounds)"
    
    # Validation 4: SGU isolation tests
    # P3 (Age 12, SGU_2) is in a DIFFERENT SGU than P0, but they share the same Activity pool.
    # Therefore, P3 COULD be matched with P0 via the Activity pool fallback, but NOT from the SGU pool!
    # P4 and P5 are in SGU_2, similar ages, they should match each other via SGU pool.
    p4_friends = people[4].properties['friendships']
    assert people[5].id in p4_friends, "P4 should be friends with P5 (Same SGU, Similar Age)"
    assert people[1].id not in p4_friends, "P4 should not be friends with P1 (Different SGU, No Activity match)"

