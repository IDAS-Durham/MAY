import pytest
from pathlib import Path
import logging

logging.basicConfig(level=logging.DEBUG)

class MockPopulation:
    def __init__(self, people):
        self.people = people

class MockWorld:
    def __init__(self, population):
        self.population = population

class MockPerson:
    def __init__(self, id_val, age, sex, properties=None):
        self.id = id_val
        self.age = age
        self.sex = sex
        self.properties = properties or {}

@pytest.fixture
def mock_romantic_world():
    people = [
        # Scenario 1: Base singles mapping (testing probabilities)
        MockPerson(1, 30, "male"),
        MockPerson(2, 30, "female"),
        
        # Scenario 2: Age adjustments (18-24)
        MockPerson(3, 20, "male"),
        MockPerson(4, 20, "female"),
        
        # Scenario 3 & 4: Cohabiting couples (Opposite sex and Same sex)
        MockPerson(5, 40, "male", {"cohabiting_couple": [6]}),
        MockPerson(6, 38, "female", {"cohabiting_couple": [5]}),
        
        MockPerson(7, 45, "male", {"cohabiting_couple": [8]}),
        MockPerson(8, 42, "male", {"cohabiting_couple": [7]}),
        
        # Scenario 5: Bug isolation (Partner ID 999 where 999 doesn't exist)
        MockPerson(9, 50, "female", {"cohabiting_couple": [999]}),
    ]
    
    return MockWorld(MockPopulation(people))
    
def test_romantic_distributor_exhaustion(mock_romantic_world):
    from may.relationships.romantic_relationships.romantic_distributor import RomanticDistributor
    config_path = str(Path(__file__).parent.parent / "test_data" / "micro_world" / "relationships" / "test_romantic_config.yaml")

    distributor = RomanticDistributor(mock_romantic_world, config_path)
    distributor.distribute_all()
    
    people = mock_romantic_world.population.people
    
    # Validation 1: Everyone got an assignment
    for p in people:
        assert 'sexual_orientation' in p.properties
        assert 'relationship_status' in p.properties
        
    # Validation 2: Opposite sex couple compatibility forces valid mapping
    p5_orient = people[4].properties['sexual_orientation']
    p6_orient = people[5].properties['sexual_orientation']
    assert p5_orient in ['heterosexual', 'bisexual']
    assert p6_orient in ['heterosexual', 'bisexual']
    assert people[4].properties['relationship_status']['type'] == 'exclusive'
    
    # Validation 3: Same sex couple compatibility forces valid mapping
    p7_orient = people[6].properties['sexual_orientation']
    p8_orient = people[7].properties['sexual_orientation']
    assert p7_orient in ['homosexual', 'bisexual']
    assert p8_orient in ['homosexual', 'bisexual']
    
    # Validation 4: Bug isolation survived (P9 had an invalid partner 999, which triggered exception logic inside but shouldn't crash python!)
    assert 'sexual_orientation' in people[8].properties
