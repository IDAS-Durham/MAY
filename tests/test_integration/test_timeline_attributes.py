import pytest
import os
from may.world import World
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.attribute_assignment.assigner import assign_attributes, AttributeAssigner, AttributeAssignmentError
from may.attribute_assignment.assignment_config import AttributeAssignmentConfig
from may.attribute_assignment.data_sources import DataSourceManager

@pytest.fixture
def test_dir():
    return "tests/test_data/micro_world"

@pytest.fixture
def geography(test_dir):
    geo = Geography(data_dir=os.path.join(test_dir, "geography"), levels=["SGU", "MGU", "LGU"])
    geo.load_from_csv()
    return geo

@pytest.fixture
def venue_manager(geography, test_dir):
    vm = VenueManager(geography, data_dir=os.path.join(test_dir, "venues"))
    vm.load_from_yaml_config("test_venues_config.yaml")
    return vm

@pytest.fixture
def population_manager(geography, test_dir):
    pm = PopulationManager(geography=geography, data_dir=os.path.join(test_dir, "population"))
    pm.load_explicit_from_csv("people.csv", column_mapping={"age": "age", "sex": "sex", "geo_unit": "location"})
    return pm

@pytest.fixture
def household_distributor(geography, population_manager, venue_manager, test_dir):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir=os.path.join(test_dir, "households"),
        config_file="test_households_config.yaml"
    )
    distributor.load_household_data("households.csv")
    
    # Needs to process people pools and run allocation so subsets attach to venues
    # Let's execute the raw pattern mapping locally to build the subsets for Attribute assigner to find
    from may.residence.allocation_strategy import execute_allocation_strategy
    execute_allocation_strategy(population_manager, venue_manager, distributor, os.path.join(test_dir, "households", "test_allocation_strategy.yaml"))
    return distributor

@pytest.fixture
def fully_formed_world(geography, population_manager, venue_manager, household_distributor):
    return World(
        geography=geography, 
        population=population_manager, 
        venues=venue_manager, 
        household_distributor=household_distributor
    )

def test_timeline_routing_and_geo_preload(fully_formed_world, test_dir, caplog):
    """
    Test routing configuration via `world.assign_attributes()` wrappers and geo_units preload.
    """
    import logging
    caplog.set_level(logging.INFO)
    
    # Grab the attributes mock file we built
    config_path = os.path.join(test_dir, "attributes", "test_attribute_config.yaml")

    # The mock config's household_structures don't cover every micro_world
    # household (young-adult-only, elderly-only, …), so some people can't be
    # classified. That incomplete config must fail loud rather than return a
    # half-assigned attribute. The wrapper still routes by assignment_level and
    # preloads geo_units before the guard fires.
    with pytest.raises(AttributeAssignmentError, match="unassigned"):
        fully_formed_world.assign_attributes(config_path)

    # Routing reached the assigner: the classifiable people DID get assigned
    # before the end-of-run guard aborted (proves execution, not just the raise).
    assigned_count = sum(1 for p in fully_formed_world.people if "test_attribute" in p.properties)
    assert assigned_count > 0

def test_person_assignment_filters(fully_formed_world, test_dir):
    """
    Test `_passes_filters` correctly blocking assignments based on defined `min/max` bounds in yaml.
    """
    config_path = os.path.join(test_dir, "attributes", "test_attribute_config.yaml")
    config = AttributeAssignmentConfig.from_yaml(config_path)
    data_manager = DataSourceManager(config)
    assigner = AttributeAssigner(config, data_manager)
    
    # Get a "Baby" person (e.g. age 0)
    # the yaml blocks anyone < 1
    babies = [p for p in fully_formed_world.people if p.age == 0]
    if babies:
        baby = babies[0]
        # Should fail filter
        assert not assigner._passes_filters(baby)
        
    adults = [p for p in fully_formed_world.people if p.age > 10]
    if adults:
        adult = adults[0]
        assert assigner._passes_filters(adult)

def test_person_by_residence_dependencies(fully_formed_world, test_dir):
    """
    Test Topological Graph Sorting: Roles with inherited dependencies correctly resolve backwards when sorted.
    """
    config_path = os.path.join(test_dir, "attributes", "test_attribute_config.yaml")
    config = AttributeAssignmentConfig.from_yaml(config_path)
    data_manager = DataSourceManager(config)
    assigner = AttributeAssigner(config, data_manager)
    
    # We need to test the internal execution of _assign_household where topological sort happens
    households = fully_formed_world.get_households()
    family_households = [h for h in households if h.size() >= 3] # e.g. a pattern holding >=1 adult and kids
    
    if family_households:
        household = family_households[0]
        assigner._assign_household(household)
        
        # Verify the dependency chain "Parent -> parent_val, Child -> inherit_from_household -> parent_val"
        # happened by looking at members
        for person in household.get_all_members():
            if "test_attribute" in person.properties:
                # The rule configures both child and parent to resolve to 'parent_val' 
                # because the child inherits from Parent
                if assigner._passes_filters(person):
                     val = person.properties["test_attribute"]
                     assert val == "parent_val"

def test_person_by_residence_flat_assignment(fully_formed_world, test_dir):
    """
    Test 'other residences' logic assigns blanket strategies rather than building structural dependency trees.
    """
    config_path = os.path.join(test_dir, "attributes", "test_attribute_config.yaml")
    config = AttributeAssignmentConfig.from_yaml(config_path)
    data_manager = DataSourceManager(config)
    assigner = AttributeAssigner(config, data_manager)
    
    # Mock a care home venue
    care_homes = fully_formed_world.get_residences_by_type("care_home")
    if not care_homes:
        # Create a mock one if the micro_world data didn't allocate one
        # Note: the venues manager has an `add_venue` if needed, or we just rely on data.
        pass
    else:
        care_home = care_homes[0]
        
        # Throw some random people inside
        members = fully_formed_world.people[-3:]
        for m in members:
            care_home.add_to_subset(m)
            
        assigner._assign_other_residences([care_home])
        
        # Verified they get the flat 'care_home_val' defined in venue_assignment_rules override
        for m in members:
            assert m.properties["test_attribute"] == "care_home_val"
