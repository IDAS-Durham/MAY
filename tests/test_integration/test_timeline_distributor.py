import pytest
import logging
import sys

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

class MockPerson:
    def __init__(self, id, age, sex, geographical_unit):
        self.id = id
        self.age = age
        self.sex = sex
        self.geographical_unit = geographical_unit
        self.properties = {}
        self.activity_map = {}
        self.activities = []
        self.residence = None
        
    def has_residence(self):
        return self.residence is not None
        
    def add_activity(self, activity_name):
        if activity_name not in self.activities:
            self.activities.append(activity_name)
class MockGeoUnit:
    def __init__(self, name, level):
        self.name = name
        self.id = name
        self.level = level
        self.coordinates = None
        self.attributes = {}
        self.parent = None
        self.people = []

    def get_ancestor_by_level(self, level):
        current = self
        while current and current.level != level:
            current = current.parent
        return current
        
    def get_people(self):
        return self.people

class MockGeography:
    def __init__(self, geo_units):
        self.geo_units = geo_units
        
    def get_units_by_level(self, level):
        return {g.name: g for g in self.geo_units if g.level == level}

class MockPopulation:
    def __init__(self):
        self.people = []

class MockWorld:
    def __init__(self):
        self.population = MockPopulation()
        self.venues = []
        self.geography = None
        
    @property
    def people(self):
        return self.population.people
        
    def venues_by_type(self, venue_type):
        return [v for v in self.venues if v.type == venue_type]

import yaml

from may.venue_distributor.venue_distributor import VenueDistributor
from may.venue_distributor.property_matching_distributor import PropertyMatchingDistributor
from may.venue_distributor.multi_venue_distributor import MultiVenueDistributor
from may.venue_distributor.resident_linked_distributor import ResidentLinkedDistributor
from may.venue_distributor import distributor_from_yaml

class MockVenue:
    def __init__(self, id, type, name, lat, lon):
        self.id = id
        self.type = type
        self.name = name
        self.coordinates = (lat, lon)
        self.subsets = {}
        self.properties = {}
        
        geo = MockGeoUnit(name="GeoA", level="MGU")
        geo.coordinates = (lat, lon)
        self.geographical_unit = geo
        
    def add_to_subset(self, person, subset_key, activity_name, activity_type):
        if subset_key not in self.subsets:
            self.subsets[subset_key] = []
        self.subsets[subset_key].append(person)
        
        # System natively assigns this during add_to_subset
        if activity_name not in person.activity_map:
            person.activity_map[activity_name] = {}
        if activity_type not in person.activity_map[activity_name]:
            person.activity_map[activity_name][activity_type] = []
        person.activity_map[activity_name][activity_type].append(self)

@pytest.fixture
def test_config():
    with open("tests/test_data/micro_world/distributors/test_distributor_config.yaml", "r") as f:
        return yaml.safe_load(f)

@pytest.fixture
def mock_world():
    world = MockWorld()
    
    # Common geo context
    geo = MockGeoUnit("DefaultGeo", "SGU")
    geo.coordinates = (5.0, 5.0)

    # 3 People. P1 and P2 are adults. P3 is a child. P1 is a CEO.
    p1 = MockPerson(id=1, age=40, sex="W", geographical_unit=geo)
    p1.properties = {"is_ceo": True, "ceo_target": "HQ"}
    
    p2 = MockPerson(id=2, age=30, sex="M", geographical_unit=geo)
    p2.properties = {}
    
    p3 = MockPerson(id=3, age=10, sex="W", geographical_unit=geo)
    p3.properties = {}

    geo.people = [p1, p2, p3]
    world.population.people = [p1, p2, p3]
    world.geography = MockGeography([geo])
    
    # Generate spatial venues
    v1 = MockVenue(1, "standard_office", "HQ", 0.0, 0.0)
    v2 = MockVenue(2, "standard_office", "Branch", 10.0, 10.0)
    world.venues = [v1, v2]
    
    return world, [p1, p2, p3], [v1, v2]

def test_venue_distributor_exhaustion(test_config, mock_world):
    """
    Validates Standard VenueDistributor (School/Company) functionality:
    - Factory identifies type: "single_venue"
    - filtering.apply_global_filters (ignores child P3 based on age > 18)
    - special_cases.handle_special_cases (P1 CEO explicitly matched to 'HQ')
    - allocation.allocate (P2 logically matched to spatial closest)
    - fallback handling (enforce_no_empty_venues)
    """
    world, people, venues = mock_world
    
    # 1. P1 & P2 physically are close to Branch (10.0, 10.0), far from HQ (0.0, 0.0)
    # But P1 has a special case pointing to HQ. Let's place them both near Branch.
    p1_geo = MockGeoUnit("GeoB", "SGU")
    p1_geo.coordinates = (10.1, 10.1)
    people[0].geographical_unit = p1_geo
    
    p2_geo = MockGeoUnit("GeoB", "SGU")
    p2_geo.coordinates = (10.1, 10.1)
    people[1].geographical_unit = p2_geo
    
    # Child (should be filtered out from work)
    people[2].geographical_unit = p2_geo

    # Initialize directly via dictionary (simulating factory extraction from config)
    distributor = VenueDistributor(config_dict=test_config["standard_distributor"])
    distributor.allocate(world)
    
    # Assertions
    # 1. Age filter validation
    assert "work" not in people[2].activity_map, "Child < 18 should have been filtered out"
    
    # 2. Special Cases validation
    hq_venue = venues[0]
    branch_venue = venues[1]
    assert hq_venue.name == "HQ"
    
    print(f"DEBUG HQ Subsets: {hq_venue.subsets}")
    print(f"DEBUG Branch Subsets: {branch_venue.subsets}")
    print(f"DEBUG P1 Activity Map: {people[0].activity_map}")
    
    assert people[0] in hq_venue.subsets["employees"], "CEO special case ignored spatial proximity and went to HQ"
    
    # 3. Spatial Matching validation
    assert branch_venue.name == "Branch"
    assert people[1] in branch_venue.subsets["employees"], "Standard employee matched nearest spatial coordinate"
    
    # 4. Global fallback validation (enforce_no_empty_venues)
    # The HQ only had P1. The Branch had P2. Both have > 0 capacity so no empty venue logic was skipped natively.
    assert len(branch_venue.subsets["employees"]) == 1
    assert len(hq_venue.subsets["employees"]) == 1

class MockSubset:
    def __init__(self, members):
        self.members = members

def test_property_matching_distributor_routing(test_config, mock_world):
    world, people, venues = mock_world
    
    # 1. Setup exact property match
    people[0].properties["building_id"] = "HQ_ID"
    venues[0].properties["building_id"] = "HQ_ID"
    
    # Ensure venue matches target_venue_type
    venues[0].type = "strict_building"
    
    distributor = PropertyMatchingDistributor(config_dict=test_config["property_distributor"])
    distributor.allocate(world)
    
    # Validation
    assert "assigned_worker" in venues[0].subsets
    assert people[0] in venues[0].subsets["assigned_worker"]
    assert people[1] not in venues[0].subsets["assigned_worker"]

def test_multi_venue_distributor_exhaustion(test_config, mock_world):
    world, people, venues = mock_world
    
    # Transform venues 
    venues[0].type = "pub"
    venues[1].type = "restaurant"
    
    # People MUST have a residence to participate in Leisure activities (unless require_residence=False config)
    people[0].residence = venues[0]
    
    distributor = MultiVenueDistributor(config_dict=test_config["multi_venue_distributor"])
    distributor.allocate(world)
    
    # Both P1 and P2 should get assigned to Both venues! 
    assert "patron" in venues[0].subsets
    assert "patron" in venues[1].subsets
    assert people[0] in venues[0].subsets["patron"].members
    assert people[0] in venues[1].subsets["patron"].members

def test_resident_linked_distributor_exhaustion(test_config, mock_world):
    from may.venue_distributor.resident_linked_distributor import ResidentLinkedDistributor
    
    world, people, venues = mock_world
    
    # Transform venue
    venues[0].type = "care_home"
    
    # Assign P1 to live at the care home manually
    venues[0].subsets["resident"] = MockSubset([people[0]])
    people[0].residence = venues[0]
    
    # Associate the venue geographically so _venue_matches_geo_unit passes!
    venues[0].geographical_unit = people[0].geographical_unit
    
    # P2 needs a valid residence to pass the 'household' linkage level grouping
    people[1].residence = venues[1]
    
    # Exclude P1 from the visitor candidate pool by stripping them from the geographic area
    geo_unit = people[0].geographical_unit
    geo_unit.people = [people[1], people[2]]
    
    distributor = ResidentLinkedDistributor(config_dict=test_config["resident_linked_distributor"])
    distributor.allocate(world)
    
    # Validation: P2 should be assigned as a 'visitor' to venues[0] ('care_home') because of dependency
    assert "care_home_visitor" in venues[0].subsets
    assert people[1] in venues[0].subsets["care_home_visitor"].members
