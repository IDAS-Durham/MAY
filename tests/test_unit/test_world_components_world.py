import pytest
from may.world import World
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.population.person import Person

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
    pm.load_explicit_from_csv("people.csv", column_mapping={"age": "age", "sex": "sex", "geo_unit": "location"})
    return pm

@pytest.fixture
def household_distributor(geography, population_manager, venue_manager):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir="tests/test_data/micro_world/households",
        config_file="test_households_config.yaml"
    )
    distributor.load_household_data("households.csv")
    return distributor

def test_world_initialization(geography, population_manager, venue_manager, household_distributor):
    """
    Test creating the world maps underlying references and registers residence types directly to `Person`.
    """
    # Reset person residence types explicitly to ensure the state isn't poisoned by previous tests loaded classes
    Person._residence_types_registry = None
    
    world = World(
        geography=geography, 
        population=population_manager, 
        venues=venue_manager, 
        household_distributor=household_distributor
    )
    
    assert world.geography is geography
    assert world.population is population_manager
    assert world.venues is venue_manager
    assert world.household_distributor is household_distributor
    
    # Validation point: `World.__init__` forces `Person.register_residence_types` upon `venues` load.
    assert "household" in Person._residence_types_registry

def test_venue_retrieval(geography, population_manager, venue_manager):
    """
    Test wrappers around VenueManager specifically passed through the World interface.
    """
    world = World(geography=geography, population=population_manager, venues=venue_manager)
    
    # 1. get_households
    sys_households = world.get_households()
    assert isinstance(sys_households, list)
    
    # 2. get_all_residences
    sys_residences = world.get_all_residences()
    assert isinstance(sys_residences, list)
    
    # 3. by_type explicit wrapper
    sys_specific = world.get_residences_by_type("household")
    assert isinstance(sys_specific, list)

def test_world_statistics_and_representation(geography, population_manager, venue_manager, household_distributor):
    """
    Test representation prints cleanly and comprehensive `get_statistics` tallies state values accurately.
    """
    world = World(
        geography=geography, 
        population=population_manager, 
        venues=venue_manager, 
        household_distributor=household_distributor
    )
    
    # 1. Test Representation string
    repr_str = repr(world)
    assert "<World:" in repr_str
    assert "units" in repr_str
    assert "people" in repr_str
    assert "venues" in repr_str
    
    # 2. Test Statistics Generator
    stats = world.get_statistics()
    # Dict layout tests
    assert "geography" in stats
    assert "population" in stats
    assert "venues" in stats
    assert "households" in stats
    
    assert stats["population"]["total_population"] == 16 # based on the micro-world people.csv
    assert len(stats["geography"]["units_by_level"]) == 3 # SGU, MGU, LGU
