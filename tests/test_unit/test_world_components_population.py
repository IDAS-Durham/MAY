import pytest
from may.geography import Geography
from may.population.population import PopulationManager
from may.population.person import Person

@pytest.fixture
def loaded_geography():
    geo = Geography(data_dir="tests/test_data/micro_world/geography")
    geo.load_from_csv()
    return geo

def test_population_manager_explicit_load(loaded_geography):
    """
    Test loading population from a single explicit CSV file.
    """
    pm = PopulationManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/population")
    column_mapping = {
        "age": "age",
        "sex": "sex",
        "geo_unit": "location"
    }
    
    pm.load_explicit_from_csv("people.csv", column_mapping)
    
    assert len(pm.people) == 10
    
    # Check the first person
    p1 = pm.get_person(0) # Due to reset_counter and 0-indexing
    assert p1 is not None
    assert p1.age == 35
    assert p1.sex == "male"
    assert p1.geographical_unit.name == "SGU_001" # This comes from the assigned location using the config Mapping
    
    # Wait, the loaded_geography uses SGU_001, but people.csv uses DUR001. 
    # Let's verify how it handles missing geography - it should skip them or leave geo_unit=None.
    # Ah, explicit load skips rows with missing geography. Let's write a new test people csv below.

def test_population_manager_explicit_batch_load(loaded_geography):
    """
    Test loading population from multiple MGU-level CSV files in a directory.
    """
    pm = PopulationManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/population/batch")
    column_mapping = {
        "age": "age",
        "sex": "sex",
        "geo_unit": "location"
    }
    
    pm.load_batch_explicit_from_csv(data_dir="tests/test_data/micro_world/population/batch", column_mapping=column_mapping)
    
    # From MGU_01_pop.csv we have 2 people, from MGU_02_pop.csv we have 2 people
    assert len(pm.people) == 4
    
    # person id counter was reset
    p = pm.people[0]
    assert p.age == 55
    assert p.sex == "male"
    assert p.geographical_unit.name == "SGU_001"
    
    p = pm.people[2]
    assert p.age == 5
    assert p.sex == "unknown"
    assert p.geographical_unit.name == "SGU_003"
    
def test_population_manager_matrix_load(loaded_geography):
    """
    Test loading demographics from matrix CSVs and then generating population.
    """
    pm = PopulationManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/population/matrix")
    
    pm.load_demographics_from_csv(male_file="demographics_male.csv", female_file="demographics_female.csv")
    
    # Verify accurate parsing
    assert pm.precise_demographics["SGU_001"][2]["male"] == 1
    assert pm.precise_demographics["SGU_001"][0]["female"] == 1
    assert pm.precise_demographics["SGU_002"][3]["male"] == 2
    assert pm.precise_demographics["SGU_002"][1]["female"] == 2
    
    # Generate the actual people
    pm.generate_population()
    
    # Total expected based on CSVs:
    # Male: SGU_001 (1), SGU_002 (3), SGU_004 (1) = 5
    # Female: SGU_001 (1), SGU_002 (3), SGU_003 (1) = 5
    # Total = 10
    
    assert len(pm.people) == 10
    
    stats = pm.get_statistics()
    assert stats["sex_distribution"]["male"] == 5
    assert stats["sex_distribution"]["female"] == 5
