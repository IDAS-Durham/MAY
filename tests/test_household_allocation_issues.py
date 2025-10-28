"""
Tests to identify household allocation issues:
1. Check if empty households exist when there are unallocated people
2. Calculate total household capacity vs population
"""

import pytest
from unittest.mock import Mock
from may.geography import GeographicalUnit, Venue
from may.population import Person, Subset
from world_specific_code.household_distributors import HouseholdDistributor


@pytest.fixture
def mock_geo_unit():
    """Create a mock geographical unit."""
    return GeographicalUnit(id=0, name='TestSGU', level='SGU')


def create_household(geo_unit, name, composition):
    """Helper to create a household venue with subsets."""
    h = Venue(
        name=name,
        venue_type='household',
        geographical_unit=geo_unit,
        properties={'composition': composition}
    )
    h.subsets = {
        'kids': Subset(h, 0, 'kids'),
        'independent children': Subset(h, 1, 'independent children'),
        'adults': Subset(h, 2, 'adults'),
        'elderly': Subset(h, 3, 'elderly')
    }
    return h


def test_no_empty_households_with_unallocated_people(mock_geo_unit):
    """
    Test that there are no empty households when people remain unallocated.

    This should fail if there's a bug causing households to be skipped.
    """
    # Create diverse household compositions
    households = [
        create_household(mock_geo_unit, 'H1', '>=2 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H2', '>=2 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H3', '1 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H4', '0 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H5', '0 0 2 0'),
        create_household(mock_geo_unit, 'H6', '>=2 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H7', '>=2 >=0 >=0 >=0'),
        create_household(mock_geo_unit, 'H8', '0 >=0 >=0 >=0'),
    ]

    venue_manager = Mock()
    venue_manager.venues_by_type = {'household': households}
    venue_manager.get_venues_by_type = Mock(return_value=households)

    # Create 20 people (fewer than total capacity)
    Person.reset_counter()
    people = [
        Person(age=30, sex='male', geographical_unit=mock_geo_unit, activities=['home'])
        for _ in range(20)
    ]

    # Create distributor and assign
    distributor = HouseholdDistributor('household', venue_manager, people)
    distributor.assign_people_venues_with_expansion('home', 'household')

    # Check results
    empty_households = [h for h in households if h.num_members == 0]
    unallocated = len(distributor.unallocated_people)

    print(f"\n=== Test Results ===")
    print(f"Total households: {len(households)}")
    print(f"Empty households: {len(empty_households)}")
    print(f"Unallocated people: {unallocated}")

    if empty_households:
        print(f"\nEmpty households:")
        for h in empty_households:
            print(f"  - {h.name} (composition: {h.properties['composition']})")

    if unallocated > 0:
        print(f"\nUnallocated people: {unallocated}")

    # Print household occupancy
    print(f"\nHousehold occupancy:")
    for h in households:
        print(f"  {h.name} ({h.properties['composition']}): {h.num_members} people")

    # THE CRITICAL TEST: If there are unallocated people, there should be NO empty households
    if unallocated > 0:
        assert len(empty_households) == 0, \
            f"BUG FOUND: {len(empty_households)} empty households exist while {unallocated} people are unallocated!"


def test_calculate_household_capacity(mock_geo_unit):
    """
    Calculate total household capacity based on composition thresholds.

    This helps understand if there's enough capacity for the population.
    """
    # Create households matching typical distribution
    household_compositions = [
        ('>=2 >=0 >=0 >=0', 10),  # 10 large flexible households
        ('1 >=0 >=0 >=0', 5),     # 5 medium flexible households
        ('0 >=0 >=0 >=0', 5),     # 5 no-kids households
        ('0 0 2 0', 3),           # 3 strict 2-adult households
        ('0 0 0 2', 2),           # 2 strict 2-elderly households
        ('0 0 0 >=3', 3),         # 3 elderly-only flexible
    ]

    households = []
    for composition, count in household_compositions:
        for i in range(count):
            h = create_household(mock_geo_unit, f'H_{composition}_{i}', composition)
            households.append(h)

    venue_manager = Mock()
    venue_manager.venues_by_type = {'household': households}
    venue_manager.get_venues_by_type = Mock(return_value=households)

    # Create distributor to get thresholds
    Person.reset_counter()
    dummy_people = [Person(age=30, sex='male', geographical_unit=mock_geo_unit, activities=['home'])]
    distributor = HouseholdDistributor('household', venue_manager, dummy_people)

    # Calculate capacities
    print(f"\n=== Household Capacity Analysis ===")
    print(f"Total households: {len(households)}")

    first_pass_capacity = 0
    second_pass_capacity = 0

    composition_counts = {}

    for h in households:
        comp = h.properties['composition'].strip()

        # Count compositions
        composition_counts[comp] = composition_counts.get(comp, 0) + 1

        # Get first pass threshold
        threshold_first = distributor.composition_thresholds.get(
            comp,
            distributor.backup_venue_capacity_threshold
        )
        first_pass_capacity += threshold_first

        # Get second pass threshold (if expandable)
        threshold_second = distributor.expanded_thresholds.get(comp, threshold_first)
        second_pass_capacity += threshold_second

    print(f"\nComposition breakdown:")
    for comp, count in sorted(composition_counts.items()):
        first_thresh = distributor.composition_thresholds.get(comp, distributor.backup_venue_capacity_threshold)
        second_thresh = distributor.expanded_thresholds.get(comp, first_thresh)
        print(f"  {comp}: {count} households")
        print(f"    - First pass threshold: {first_thresh} → capacity: {count * first_thresh}")
        print(f"    - Second pass threshold: {second_thresh} → capacity: {count * second_thresh}")

    print(f"\nTotal capacity:")
    print(f"  First pass:  {first_pass_capacity} people")
    print(f"  Second pass: {second_pass_capacity} people")
    print(f"  Expansion:   +{second_pass_capacity - first_pass_capacity} people")

    # Test with different population sizes
    for population_size in [50, 100, 200, 300]:
        print(f"\nWith {population_size} people:")
        if population_size <= first_pass_capacity:
            print(f"  ✓ Should fit in first pass (capacity: {first_pass_capacity})")
        elif population_size <= second_pass_capacity:
            print(f"  ⚠ Needs second pass (first: {first_pass_capacity}, second: {second_pass_capacity})")
        else:
            shortfall = population_size - second_pass_capacity
            print(f"  ✗ INSUFFICIENT CAPACITY! Shortfall: {shortfall} people")

    return {
        'households': len(households),
        'first_pass_capacity': first_pass_capacity,
        'second_pass_capacity': second_pass_capacity,
        'composition_counts': composition_counts
    }


def test_specific_bug_scenario(mock_geo_unit):
    """
    Test a specific scenario that should expose the enumerate bug.

    If available_venue_indices = [2, 5, 7] but we use enumerate(i),
    then i = 0, 1, 2 instead of actual indices 2, 5, 7.
    """
    # Create 10 households
    households = [
        create_household(mock_geo_unit, f'H{i}', '>=2 >=0 >=0 >=0')
        for i in range(10)
    ]

    venue_manager = Mock()
    venue_manager.venues_by_type = {'household': households}
    venue_manager.get_venues_by_type = Mock(return_value=households)

    # Create 30 people
    Person.reset_counter()
    people = [
        Person(age=30, sex='male', geographical_unit=mock_geo_unit, activities=['home'])
        for _ in range(30)
    ]

    # Create distributor
    distributor = HouseholdDistributor('household', venue_manager, people)

    # Manually set available_venue_indices to non-contiguous values
    # This simulates what happens after first pass when some venues are closed
    custom_indices = [2, 5, 7]  # Only use households at indices 2, 5, 7

    print(f"\n=== Testing with custom venue indices: {custom_indices} ===")

    # Before fix: This would use i=0,1,2 instead of venue_idx=2,5,7
    # causing wrong venues to be removed from available_venue_indices
    distributor.assign_people_venues('home', 'household',
                                     available_venue_indices=custom_indices,
                                     randomize_venue_order=False)

    print(f"\nResults:")
    print(f"  Unallocated: {len(distributor.unallocated_people)}")

    for i in range(10):
        h = households[i]
        marker = " ←" if i in custom_indices else ""
        print(f"  H{i}: {h.num_members} members{marker}")

    # Verify that ONLY the specified households got people
    for i in range(10):
        if i in custom_indices:
            # These should have people (unless composition full)
            pass  # May be 0 if closed during assignment
        else:
            # These should definitely be empty (never available)
            assert households[i].num_members == 0, \
                f"BUG: Household {i} has {households[i].num_members} members but was NOT in available_venue_indices!"


def test_empty_households_analysis(mock_geo_unit):
    """
    Analyze why households end up empty.
    """
    # Create many households
    households = [
        create_household(mock_geo_unit, f'H{i}', '>=2 >=0 >=0 >=0')
        for i in range(50)
    ]

    venue_manager = Mock()
    venue_manager.venues_by_type = {'household': households}
    venue_manager.get_venues_by_type = Mock(return_value=households)

    # Create 100 people (should fit in first pass with threshold=4: 50*4=200 capacity)
    Person.reset_counter()
    people = [
        Person(age=30, sex='male', geographical_unit=mock_geo_unit, activities=['home'])
        for _ in range(100)
    ]

    # Create distributor
    distributor = HouseholdDistributor('household', venue_manager, people)
    distributor.assign_people_venues_with_expansion('home', 'household')

    # Analyze results
    empty = [h for h in households if h.num_members == 0]
    non_empty = [h for h in households if h.num_members > 0]

    print(f"\n=== Empty Households Analysis ===")
    print(f"Total households: {len(households)}")
    print(f"Empty: {len(empty)}")
    print(f"Non-empty: {len(non_empty)}")
    print(f"Unallocated people: {len(distributor.unallocated_people)}")

    if non_empty:
        occupancies = [h.num_members for h in non_empty]
        print(f"\nOccupancy statistics:")
        print(f"  Min: {min(occupancies)}")
        print(f"  Max: {max(occupancies)}")
        print(f"  Avg: {sum(occupancies)/len(occupancies):.1f}")
        print(f"  Total allocated: {sum(occupancies)}")

    # Check threshold
    threshold = distributor.composition_thresholds.get('>=2 >=0 >=0 >=0',
                                                        distributor.backup_venue_capacity_threshold)
    expected_capacity = len(households) * threshold

    print(f"\nCapacity check:")
    print(f"  Threshold per household: {threshold}")
    print(f"  Expected capacity: {expected_capacity}")
    print(f"  Population: {len(people)}")
    print(f"  Utilization: {len(people)/expected_capacity*100:.1f}%")

    # The bug: if there are empty households but all people are allocated,
    # it means the distribution is uneven
    if len(empty) > 0 and len(distributor.unallocated_people) == 0:
        print(f"\n⚠ UNEVEN DISTRIBUTION:")
        print(f"  {len(empty)} households are empty")
        print(f"  All {len(people)} people are allocated")
        print(f"  Some households likely exceeded threshold while others never received anyone")


if __name__ == "__main__":
    import sys

    # Create geo unit
    geo = GeographicalUnit(id=0, name='TestSGU', level='SGU')

    print("="*70)
    print("TEST 1: Empty households with unallocated people")
    print("="*70)
    try:
        test_no_empty_households_with_unallocated_people(geo)
        print("\n✓ Test passed!")
    except AssertionError as e:
        print(f"\n✗ Test FAILED: {e}")
        sys.exit(1)

    print("\n" + "="*70)
    print("TEST 2: Household capacity calculation")
    print("="*70)
    test_calculate_household_capacity(geo)

    print("\n" + "="*70)
    print("TEST 3: Specific bug scenario (enumerate index)")
    print("="*70)
    try:
        test_specific_bug_scenario(geo)
        print("\n✓ Test passed!")
    except AssertionError as e:
        print(f"\n✗ Test FAILED: {e}")
        sys.exit(1)

    print("\n" + "="*70)
    print("TEST 4: Empty households analysis")
    print("="*70)
    test_empty_households_analysis(geo)

    print("\n" + "="*70)
    print("ALL TESTS COMPLETED")
    print("="*70)
