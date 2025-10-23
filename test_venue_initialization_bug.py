"""
Test to demonstrate the venue initialization bug.
"""

from unittest.mock import Mock
from may.geography import GeographicalUnit, Venue
from may.population import Person, Subset
from may.specific_distributors import HouseholdDistributor

# Setup
geo = GeographicalUnit(id=0, name='TestSGU', level='SGU')

# Create 5 households
households = []
for i in range(5):
    h = Venue(
        name=f'Household {i}',
        venue_type='household',
        geographical_unit=geo,
        properties={'composition': '>=2 >=0 >=0 >=0'}
    )
    h.subsets = {
        'kids': Subset(h, 0, 'kids'),
        'independent children': Subset(h, 1, 'independent children'),
        'adults': Subset(h, 2, 'adults'),
        'elderly': Subset(h, 3, 'elderly')
    }
    households.append(h)

venue_manager = Mock()
venue_manager.venues_by_type = {'household': households}
venue_manager.get_venues_by_type = Mock(return_value=households)

# Create 20 people
Person.reset_counter()
people = [
    Person(age=30, sex='male', geographical_unit=geo, activities=['home'])
    for _ in range(20)
]

# Create distributor
distributor = HouseholdDistributor('household', venue_manager, people)

print("Before assignment:")
print(f"Potential venues: {len(distributor.potential_venues)}")

# Assign with custom available_venue_indices
# If we pass [1, 3] but the initialization loop uses enumerate index instead of venue_idx,
# it will try to remove wrong indices
custom_indices = [1, 3]  # Only use households 1 and 3
distributor.assign_people_venues('home', 'household', available_venue_indices=custom_indices, randomize_venue_order=False)

print("\nAfter assignment:")
print(f"Available venue indices: {distributor.available_venue_indices}")
print(f"Unallocated people: {len(distributor.unallocated_people)}")

print("\nHousehold occupancy:")
for i, h in enumerate(households):
    print(f"  Household {i}: {h.num_members} members")

# The bug: with enumerate(i), when i=0, venue_idx=1
# So _update_venue_membership_capacity gets called with trial_venue_index=0
# But it should be called with trial_venue_index=1
# This causes wrong venues to be removed from available_venue_indices
