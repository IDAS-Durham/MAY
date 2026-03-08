import pytest
from unittest.mock import MagicMock
from may.venue_distributor.property_matching_distributor import PropertyMatchingDistributor
from may.population import Person
from may.geography import GeographicalUnit

class MockVenue:
    def __init__(self, venue_id, venue_type, properties):
        self.id = venue_id
        self.type = venue_type
        self.properties = properties
        self.subsets = {}
    
    def add_to_subset(self, person, subset_key, activity_name, activity_type):
        if subset_key not in self.subsets:
            self.subsets[subset_key] = []
        self.subsets[subset_key].append(person)
        
        # Mock activity map update
        if activity_name not in person.activity_map:
            person.activity_map[activity_name] = {}
        if activity_type not in person.activity_map[activity_name]:
            person.activity_map[activity_name][activity_type] = []
        person.activity_map[activity_name][activity_type].append(self)

def test_property_matching_distributor():
    # Setup people
    p1 = Person(age=25, sex='male', properties={'HID': 'H1'})
    p2 = Person(age=30, sex='female', properties={'HID': 'H2'})
    p3 = Person(age=10, sex='male', properties={'HID': 'H1'})
    p4 = Person(age=20, sex='female', properties={}) # No HID
    
    # Setup venues
    v1 = MockVenue(1, 'household', {'HID': 'H1'})
    v2 = MockVenue(2, 'household', {'HID': 'H2'})
    
    # Setup world
    world = MagicMock()
    world.population.people = [p1, p2, p3, p4]
    world.venues_by_type.return_value = [v1, v2]
    
    # Distributor config
    config = {
        'target_venue_type': 'household',
        'mapping_key': 'HID',
        'venue_property': 'HID',
        'subset_key': 'resident',
        'activity_name': 'residence'
    }
    
    distributor = PropertyMatchingDistributor(config_dict=config)
    result = distributor.allocate(world)
    
    assert result['matched_count'] == 3
    assert result['missed_count'] == 0 # p4 matched but had no key, so skipped before check
    
    # Verify links
    assert p1 in v1.subsets['resident']
    assert p3 in v1.subsets['resident']
    assert p2 in v2.subsets['resident']
    assert p4 not in v1.subsets.get('resident', [])
    assert p4 not in v2.subsets.get('resident', [])
