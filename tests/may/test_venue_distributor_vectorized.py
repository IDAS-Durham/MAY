
import unittest
import numpy as np
import sys
import os

# Ensure we can import the module
sys.path.append(os.getcwd())

from may.venue_distributor.venue_distributor import VenueDistributor

class MockPerson:
    def __init__(self, id, age, sex, residence_type=None):
        self.id = id
        self.age = age
        self.sex = sex
        self.residence_type = residence_type
        self.properties = {}
        # Mock activity map
        self.activity_map = {}

    def __repr__(self):
        return f"Person(id={self.id}, age={self.age}, sex={self.sex})"

class TestVenueDistributorVectorized(unittest.TestCase):
    def setUp(self):
        # minimalist config for testing
        config = {
            'venue_type': 'test_venue',
            'activity_map_key': 'test_activity',
            'eligibility': {
                'global_filters': [
                    {'attribute': 'age', 'min': 5, 'max': 18},
                    {'attribute': 'sex', 'value': 'female', 'type': 'categorical'}
                ]
            },
            'settings': {'verbose': True}
        }
        self.dist = VenueDistributor(config_dict=config)
        # manually set pre-processed filters based on config
        self.dist._pre_processed_filters = config['eligibility']['global_filters']

    def test_build_population_arrays(self):
        people = [
            MockPerson(1, 10, 'male', 'household'),
            MockPerson(2, 20, 'female', 'care_home'),
            MockPerson(3, 5, 'female', 'household')
        ]
        
        self.dist._build_population_arrays(people)
        
        arrays = self.dist.population_arrays
        self.assertEqual(len(arrays['age']), 3)
        np.testing.assert_array_equal(arrays['age'], np.array([10, 20, 5]))
        np.testing.assert_array_equal(arrays['sex'], np.array([1, 0, 0])) # male=1, female=0
        np.testing.assert_array_equal(arrays['residence_type'], np.array([0, 1, 0])) # household=0, care_home=1

    def test_vectorized_filtering(self):
        # Setup people
        # 1. 10yo Male (Fail Sex)
        # 2. 20yo Female (Fail Age)
        # 3. 5yo  Female (Pass)
        # 4. 18yo Female (Pass)
        # 5. 15yo Male (Fail Sex)
        people = [
            MockPerson(1, 10, 'male', 'household'),
            MockPerson(2, 20, 'female', 'household'),
            MockPerson(3, 5, 'female', 'household'),
            MockPerson(4, 18, 'female', 'household'),
            MockPerson(5, 15, 'male', 'household')
        ]
        
        # 1. Build arrays
        self.dist._build_population_arrays(people)
        
        # 2. Test _apply_filters_vectorized directly
        indices = np.arange(len(people))
        filtered_indices = self.dist._apply_filters_vectorized(
            indices, 
            self.dist._pre_processed_filters
        )
        
        self.assertEqual(len(filtered_indices), 2)
        # Should contain index 2 (Person 3) and index 3 (Person 4)
        self.assertTrue(2 in filtered_indices)
        self.assertTrue(3 in filtered_indices)
        self.assertTrue(0 not in filtered_indices)
        self.assertTrue(1 not in filtered_indices)
        self.assertTrue(4 not in filtered_indices)

    def test_apply_global_filters_integration(self):
        # This tests the integration in _apply_global_filters
        
        # Create 1000 eligible people and 1000 ineligible
        eligible = [MockPerson(i, 10, 'female', 'household') for i in range(1000)]
        ineligible = [MockPerson(i+1000, 25, 'male', 'household') for i in range(1000)]
        all_people = eligible + ineligible
        
        # 1. Build arrays (mimic what allocate() does)
        self.dist._build_population_arrays(all_people)
        
        # 2. Call _apply_global_filters
        # It should detect that people == self.population_arrays['people'] and use fast path
        result = self.dist._apply_global_filters(all_people)
        
        self.assertEqual(len(result), 1000)
        self.assertTrue(all(p.age == 10 for p in result))
        self.assertTrue(all(p.sex == 'female' for p in result))

if __name__ == "__main__":
    unittest.main()
