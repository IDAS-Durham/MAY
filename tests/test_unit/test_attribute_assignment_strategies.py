import pytest
import numpy as np
from may.attribute_assignment.strategies import ConstantStrategy

class MockPerson:
    def __init__(self, id, age, sex, geographical_unit):
        self.id = id
        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit

class MockVenue:
    def __init__(self, id, geographical_unit):
        self.id = id
        self.geographical_unit = geographical_unit

class MockDataManager:
    def get_source(self, name):
        return None

@pytest.fixture
def mock_person():
    return MockPerson(id=1, age=30, sex="W", geographical_unit=None)

@pytest.fixture
def mock_household():
    return MockVenue(id=101, geographical_unit=None)

@pytest.fixture
def data_manager():
    return MockDataManager()

def test_constant_strategy_assign(mock_person, mock_household, data_manager):
    """Test assigning a constant value to a single person."""
    config = {'strategy': 'constant', 'value': 'test_static_value'}
    strategy = ConstantStrategy(config, data_manager)
    
    context = {'attribute_name': 'test_attribute'}
    result = strategy.assign(mock_person, mock_household, context)
    
    assert result == 'test_static_value'

def test_constant_strategy_batch_assign(mock_person, mock_household, data_manager):
    """Test assigning a constant value to a batch of people."""
    config = {'strategy': 'constant', 'value': 42}
    strategy = ConstantStrategy(config, data_manager)
    
    people = [mock_person, MockPerson(id=2, age=40, sex="M", geographical_unit=None)]
    households = [mock_household, mock_household]
    contexts = [{'attribute_name': 'test_attribute'}, {'attribute_name': 'test_attribute'}]
    
    results = strategy.assign_batch(people, households, contexts)
    
    assert len(results) == 2
    assert results == [42, 42]

def test_constant_strategy_missing_value(mock_person, mock_household, data_manager):
    """Test fallback when value is not provided in config."""
    config = {'strategy': 'constant'} # Missing 'value' param
    strategy = ConstantStrategy(config, data_manager)
    
    context = {'attribute_name': 'test_attribute'}
    
    # We expect this to use the _fallback method, which returns None if data manager provides None
    result = strategy.assign(mock_person, mock_household, context)
    
    assert result is None
    assert context.get('fallback_reason') == 'NO_CONSTANT_VALUE'
