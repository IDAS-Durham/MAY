import pytest
from may.geography import Geography
from may.geography.venue_manager import VenueManager
from may.geography.venue import Venue

@pytest.fixture
def loaded_geography():
    """Fixture that initializes a Geography with the micro_world data for tests"""
    geo = Geography(data_dir="tests/test_data/micro_world/geography")
    geo.load_from_csv()
    return geo

def test_venue_manager_initialization(loaded_geography):
    """
    Test VenueManager initializes correctly with a Geography object
    """
    vm = VenueManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/venues")
    assert vm.geography is not None
    assert vm.data_dir == "tests/test_data/micro_world/venues"
    assert vm.filter_by_geography is True
    assert len(vm.venues) == 0

def test_venue_manager_load_from_yaml(loaded_geography):
    """
    Test VenueManager loads from the micro-world YAML config.
    This tests:
    - Loading CSVs implicitly from config definitions
    - Geographic filtering (ignoring 'hh_out_of_bounds')
    - Disabling modules (ignoring the disabled 'hospital' module)
    - Mapping SGU vs MGU correctly
    - is_residence mapping
    """
    vm = VenueManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/venues")
    vm.load_from_yaml_config("test_venues_config.yaml")

    all_venues = vm.get_all_venues()
    
    # Check households
    households = vm.get_venues_by_type("household")
    # There are 4 in the CSV, but hh_out_of_bounds has SGU_999 which is not loaded in Micro-World Geo
    # Therefore, we only expect 3
    assert len(households) == 3, f"Expected 3 households loaded, got {len(households)}. Geo-filtering might have failed."
    assert vm.get_venue("hh_1") is not None
    assert vm.get_venue("hh_out_of_bounds") is None

    # Verify is_residence flag was parsed
    assert vm.is_residence_type("household") is True
    assert vm.is_residence_type("school") is False

    # Check schools (Mapped at MGU level)
    schools = vm.get_venues_by_type("school")
    assert len(schools) == 2
    sch_1 = vm.get_venue("sch_1")
    assert sch_1.geographical_unit.name == "MGU_01"  # Correct geographical mapping
    assert sch_1.properties.get('capacity') == 50

    # Ensure disabled types are not loaded
    hospitals = vm.get_venues_by_type("hospital")
    assert len(hospitals) == 0

def test_venue_manager_create_child_venue(loaded_geography):
    """
    Test the programmatic interface for creating parent and child venues.
    """
    vm = VenueManager(geography=loaded_geography, data_dir="tests/test_data/micro_world/venues")
    
    # Create an arbitrary venue dynamically
    geo_unit = loaded_geography.get_unit("SGU_001")
    parent_school = vm.create_venue("test_school", geo_unit, properties={"capacity": 100})
    
    assert parent_school.name == "test_school_0"
    assert parent_school.geographical_unit.name == "SGU_001"
    
    # Create child classrooms
    vm.create_child_venue(parent_school, "classroom", properties={"capacity": 20})
    vm.create_child_venue(parent_school, "classroom", properties={"capacity": 30})
    
    # Check parent-child linkage
    assert len(parent_school.children) == 2
    classrooms = vm.get_venues_by_type("classroom")
    assert len(classrooms) == 2
    assert classrooms[0].parent == parent_school
    
    # Create multiple children in one go
    parent_factory, factories = vm.create_venue_with_children(
        parent_type="factory",
        geo_unit=geo_unit,
        children_spec=[
            {'type': 'assembly_line', 'count': 3, 'properties': {'risk': 'high'}}
        ]
    )
    
    assert parent_factory.type == "factory"
    assert len(factories) == 3
    assert vm.get_venues_by_type("assembly_line")[0].properties.get("risk") == "high"
