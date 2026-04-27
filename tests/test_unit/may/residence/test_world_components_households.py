import pytest
from may.geography import Geography
from may.population.population import PopulationManager
from may.geography.venue_manager import VenueManager
from may.residence.household_distributor import HouseholdDistributor
from may.residence.composition_pattern import CompositionPattern
from may.residence.allocation_strategy import execute_allocation_strategy


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
def hd(geography, population_manager, venue_manager):
    distributor = HouseholdDistributor(
        geography=geography,
        population=population_manager,
        venue_manager=venue_manager,
        data_dir="tests/test_data/micro_world/households",
        config_file="test_households_config.yaml"
    )
    distributor.load_household_data("households.csv")
    return distributor

def test_household_distributor_initialization(hd):
    """
    Test that categories, relationship rules, and household data are loaded securely.
    """
    assert len(hd.categories) == 4
    assert hd.categories[0].name == "Kids"
    assert hd.categories[3].name == "Old Adults"

    # From households.csv mock -> SGU_001 should have 2 bounds for '>=2 >=0 2 0'
    assert "SGU_001" in hd.household_counts_by_geo_unit
    assert hd.household_counts_by_geo_unit["SGU_001"][">=2 >=0 2 0"] == 2
    assert hd.household_counts_by_geo_unit["SGU_002"]["1 >=0 2 0"] == 1

def test_person_pooling(hd):
    """
    Test shuffling and segregating people inside SGUs by matched Category criteria.
    """
    hd._prepare_person_pools()
    
    assert "SGU_001" in hd.person_pool_by_geo_unit
    assert "SGU_002" in hd.person_pool_by_geo_unit

    sgu_001_pools = hd.person_pool_by_geo_unit["SGU_001"]
    
    # 4 Kids in SGU_001
    assert len(sgu_001_pools[0]) == 4
    # 2 Young Adults in SGU_001
    assert len(sgu_001_pools[1]) == 2
    # 6 Adults in SGU_001
    assert len(sgu_001_pools[2]) == 6

def test_sequential_allocation(hd):
    """
    Test simple 'min-max' allocation with NO rules logic involved to ensure pure logic operates.
    """
    hd._prepare_person_pools()
    pattern = CompositionPattern.from_string(">=2 >=0 2 0")
    household, failed_cat = hd._allocate_household("SGU_001", pattern, max_size=4, allocate_flexible=False)
    
    assert household is not None
    assert failed_cat is None
    assert household.size() == 4
    
    # Should be 2 kids and 2 adults based on min bounds of >=2 and 2
    composition = household.get_composition(hd.categories)
    assert composition["Kids"] == 2
    assert composition["Adults"] == 2
    
    # Check that subsets were properly populated by category key
    assert len(household.subsets["Kids"].members) == 2
    assert len(household.subsets["Adults"].members) == 2
    
def test_rules_based_allocation(hd):
    """
    Test explicitly grabbing couples using the relationship rules defined in yaml.
    """
    hd._prepare_person_pools()
    pattern = CompositionPattern.from_string("0 0 2 0")

    household, failed_cat = hd._allocate_household_with_rules(
        "SGU_001", pattern, rule_name="Adult pair"
    )
    
    assert household is not None
    assert failed_cat is None
    assert household.size() == 2
    # They should be male/female based on the couple rules likelihood mostly picking different
    members = household.get_all_members()
    sexes = [p.sex for p in members]
    assert "male" in sexes and "female" in sexes

    # VERY IMPORTANT: Verify that the household pipeline properly tagged these 2 individuals 
    # as a cohabiting pair! This data drives the Romantic Distributions later.
    p0, p1 = members
    assert "cohabiting_couple" in p0.properties
    assert "cohabiting_couple" in p1.properties
    assert p0.properties["cohabiting_couple"] == [p1.id]
    assert p1.properties["cohabiting_couple"] == [p0.id]

def test_excess_allocation(hd):
    """
    Test HouseholdExcessHandler respects adding elements directly to existing structures up to constraints.
    """
    # Create an initial household
    hd._prepare_person_pools()
    pattern = CompositionPattern.from_string(">=2 >=0 2 0")
    household, _ = hd._allocate_household("SGU_001", pattern)
    initial_size = household.size()

    # Now run an excess round via config parameters for Excess kids
    stats = hd.allocate_excess_to_households(
        target_patterns=[">=2 >=0 2 0"],
        add_category="Kids",
        constraints=[{"category_sum": ["Kids"], "max": 4}],
        max_per_household=None,
        add_distribution={"type": "weighted", "probabilities": {"1": 1.0}}
    )
    assert stats["people_added"] > 0
    assert household.size() == initial_size + 1

def test_unified_allocation_strategy(geography, population_manager, venue_manager, hd):
    """
    Test the entire execute_allocation_strategy step iterator parsing the YAML and orchestrating distributing everything.
    """
    stats = execute_allocation_strategy(
        population=population_manager,
        venues=venue_manager,
        household_distributor=hd,
        strategy_file="tests/test_data/micro_world/households/test_allocation_strategy.yaml"
    )

    # Validate that steps were parsed and ran
    assert "Two-Adult Families with Children (Rule-based)" in stats
    assert "Adult Couples (Rule-based Pair Matching)" in stats
    assert "Overflow remaining Young Adults" in stats
    
    # Check households were actually mapped into the VenueManager overall
    all_households = venue_manager.get_venues_by_type("household")
    assert len(all_households) > 0

    # Ensure some Young Adults got mapped (handled by our Overflow round test)
    p_ya = hd.population.get_person(15) # p(id=15) is 22 in SGU_001
    assert p_ya.id in hd.allocated_people
