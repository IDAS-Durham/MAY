import unittest
import random
from unittest.mock import MagicMock, patch
import sys
import os
import numpy as np

# Ensure we can import the module
sys.path.append(os.getcwd())

from may.venue_distributor.resident_linked_distributor import ResidentLinkedDistributor

class MockPerson:
    def __init__(self, id, age=20, sex='female', residence=None, geo_unit=None):
        self.id = id
        self.age = age
        self.sex = sex
        self.residence = residence
        self.geographical_unit = geo_unit
        self.activity_map = {}
        self.activities = set()

    def add_activity(self, activity):
        self.activities.add(activity)

class MockVenue:
    def __init__(self, id, type, geo_unit=None):
        self.id = id
        self.type = type
        self.geographical_unit = geo_unit
        self.subsets = {}
        self.properties = {}

class MockGeoUnit:
    def __init__(self, name, level):
        self.name = name
        self.level = level
        self.people = []
        self.id = random.randint(1, 1000)

    def get_people(self):
        return self.people

class TestResidentLinkedDistributor(unittest.TestCase):
    def setUp(self):
        self.mgu1 = MockGeoUnit("MGU1", "MGU")
        self.mgu1.id = 1
        self.mgu2 = MockGeoUnit("MGU2", "MGU")
        self.mgu2.id = 2
        
        self.config = {
            'target_venue_type': 'care_home',
            'activity_map_key': 'leisure',
            'link_level': 'household',
            'multiplier': 1,
            'geography_level': 'MGU',
            'visitor_eligibility': {'global_filters': []}
        }
        self.dist = ResidentLinkedDistributor(config_dict=self.config)

    def test_group_visitors_household(self):
        # Setup world and people
        world = MagicMock()
        
        hh1 = MagicMock(id=101)
        hh2 = MagicMock(id=102)
        
        p1 = MockPerson(1, residence=hh1, geo_unit=self.mgu1)
        p2 = MockPerson(2, residence=hh1, geo_unit=self.mgu1)
        p3 = MockPerson(3, residence=hh2, geo_unit=self.mgu2)
        
        people = [p1, p2, p3]
        
        # Mock _get_geo_unit_at_level is not needed as we use optimized grouping
        self.dist.person_id_to_index = {1: 0, 2: 1, 3: 2}
        self.dist.population_arrays = {
            'residence.id': np.array([101, 101, 102], dtype=np.int32)
        }
        
        groups = self.dist._group_visitors_optimized(people)
        
        # Since _group_visitors_optimized returns a flat list of units (list of lists)
        self.assertEqual(len(groups), 2) # 2 households
        
        # We need to be careful with ordering, but usually stable
        lens = sorted([len(g) for g in groups])
        self.assertEqual(lens[0], 1) # Household 102 has 1 member
        self.assertEqual(lens[1], 2) # Household 101 has 2 members

    def test_allocate_simple(self):
        world = MagicMock()
        
        # Venues
        v1 = MockVenue(201, "care_home", geo_unit=self.mgu1)
        res_subset = MagicMock()
        res_subset.members = [MockPerson(50)] # 1 resident
        v1.subsets["resident"] = res_subset
        
        world.venues_by_type.return_value = [v1]
        
        # People (1 household in MGU1)
        hh1 = MagicMock(id=101)
        p1 = MockPerson(1, residence=hh1, geo_unit=self.mgu1)
        p2 = MockPerson(2, residence=hh1, geo_unit=self.mgu1)
        
        world.people = [p1, p2]
        
        self.dist.person_id_to_index = {1: 0, 2: 1}
        self.dist.population_arrays = {
            'residence.id': np.array([101, 101], dtype=np.int32),
            'age': np.array([20, 20], dtype=np.int32),
            'sex': np.array([0, 0], dtype=np.int32)
        }
        
        # Setup world geography for batching
        world.geography.get_units_by_level.return_value = {self.mgu1.id: self.mgu1}
        self.mgu1.people = [p1, p2]

        stats = self.dist.allocate(world)
        
        self.assertEqual(stats["total_links"], 1) # 1 household linked
        
        # Check links
        self.assertIn("leisure", p1.activity_map)
        self.assertIn("care_home", p1.activity_map["leisure"])
        self.assertEqual(len(p1.activity_map["leisure"]["care_home"]), 1)
        
        subset = p1.activity_map["leisure"]["care_home"][0]
        self.assertEqual(subset.venue, v1)
        self.assertEqual(subset.subset_name, "visitor")
        
        self.assertIn("leisure", p2.activity_map)
        self.assertEqual(p2.activity_map["leisure"]["care_home"][0].venue, v1)
        self.assertEqual(p2.activity_map["leisure"]["care_home"][0].subset_name, "visitor")

if __name__ == "__main__":
    unittest.main()
