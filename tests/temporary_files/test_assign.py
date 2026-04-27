import sys
import yaml
from may.attribute_assignment.assigner import AttributeAssigner
from may.attribute_assignment.assignment_config import AttributeAssignmentConfig
from may.population.person import Person
class Household:
    def __init__(self, id, gu):
        self.id = id
        self.geographical_unit = MockGU()
        self.members = []
        self.properties = {}
    def get_all_members(self):
        return self.members
    def add_member(self, p):
        self.members.append(p)
    def get_source(self, name):
        class MockSource:
            def lookup(self, *args, **kwargs):
                return {"mock_val": 1.0}
        return MockSource()
    def load_sources(self, *args): pass
    def lookup(self, name, key):
        print(f"Lookup {name} {key}")
        return {"mock_val": 1.0}

config = AttributeAssignmentConfig("tests/test_data/micro_world/attributes/test_attribute_config.yaml")

print(config.assignment_level)
print(config.roles)
print(config.data_sources)

class MockGU: 
    def __init__(self): self.name="GU1"
class MockGeo: 
    def get_geographical_unit(self, *args): return MockGU()

assigner = AttributeAssigner(config, None, None, verbose=True)
assigner.data_manager = MockDataMan()
assigner.geography = MockGeo()

p = Person(1, 30, "M", "GU1")
p.properties = {}
p.activity_map = {"residence": {"household": [type("Sub",(),{"subset_name":"Adults"})()]}}
p.geographical_unit = MockGU()

h = Household(1, "GU1")
h.add_member(p)
h.properties = {"_structure": "Single Adult", "original_pattern": "0 0 1 0", "actual_pattern": "0 0 1 0"}
h.geographical_unit = MockGU()

print("Assigning")
assigner._assign_household(h)
print(p.properties)
