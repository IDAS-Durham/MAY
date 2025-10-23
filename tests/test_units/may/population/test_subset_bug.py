"""
Test to demonstrate the mutable default parameter bug in Subset class.

This bug causes all Subset instances to share the same members set,
resulting in every subset showing the total population count.
"""

import pytest
from may.population import Subset, Person
from may.geography import GeographicalUnit, Venue


class TestSubsetMutableDefaultBug:
    """Tests that demonstrate the mutable default parameter bug."""

    @pytest.fixture
    def mock_geo_unit(self):
        """Create a mock geographical unit."""
        return GeographicalUnit(id=0, name="TestSGU", level="SGU")

    @pytest.fixture
    def two_households(self, mock_geo_unit):
        """Create two separate household venues."""
        household1 = Venue(
            name="Household 1",
            venue_type="household",
            geographical_unit=mock_geo_unit,
            properties={'composition': '0 0 2 0'}
        )

        household2 = Venue(
            name="Household 2",
            venue_type="household",
            geographical_unit=mock_geo_unit,
            properties={'composition': '0 0 2 0'}
        )

        return household1, household2

    def test_subset_members_are_shared_across_instances(self, two_households, mock_geo_unit):
        """
        DEMONSTRATES THE BUG: All Subset instances share the same members set.

        This test will FAIL until the bug is fixed, showing that when you add
        a member to one subset, it appears in ALL subsets.
        """
        household1, household2 = two_households

        # Create subsets for household 1
        subset1_adults = Subset(household1, 0, 'adults')

        # Create subsets for household 2
        subset2_adults = Subset(household2, 0, 'adults')

        # Create two people
        person1 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=40, sex='female', geographical_unit=mock_geo_unit)

        # Add person1 to household1's adults subset
        subset1_adults.add_member(person1)

        # Add person2 to household2's adults subset
        subset2_adults.add_member(person2)

        # BUG: Both subsets will show 2 members because they share the same set!
        print(f"\nHousehold 1 adults members: {subset1_adults.num_members}")
        print(f"Household 2 adults members: {subset2_adults.num_members}")
        print(f"Are they the same set? {subset1_adults.members is subset2_adults.members}")

        # EXPECTED BEHAVIOR: Each subset should have 1 member
        # ACTUAL BEHAVIOR (BUG): Both subsets have 2 members (the shared set)

        # This assertion will FAIL due to the bug
        assert subset1_adults.num_members == 1, \
            f"Expected 1 member in household1, but got {subset1_adults.num_members}. " \
            f"BUG: Subsets are sharing the same members set!"

        assert subset2_adults.num_members == 1, \
            f"Expected 1 member in household2, but got {subset2_adults.num_members}. " \
            f"BUG: Subsets are sharing the same members set!"

        # This assertion will FAIL - it should be False but is True due to bug
        assert subset1_adults.members is not subset2_adults.members, \
            "BUG CONFIRMED: subset1_adults.members is the SAME object as subset2_adults.members!"

    def test_multiple_subsets_same_household_share_members(self, mock_geo_unit):
        """
        DEMONSTRATES THE BUG: Even different subsets within the same household share members.

        This shows that 'kids', 'adults', 'elderly' subsets all use the same set.
        """
        household = Venue(
            name="Test Household",
            venue_type="household",
            geographical_unit=mock_geo_unit,
            properties={'composition': '1 0 2 1'}
        )

        # Create different subsets for the same household
        kids_subset = Subset(household, 0, 'kids')
        adults_subset = Subset(household, 1, 'adults')
        elderly_subset = Subset(household, 2, 'elderly')

        # Create people of different ages
        kid = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        adult = Person(age=35, sex='female', geographical_unit=mock_geo_unit)
        elderly = Person(age=70, sex='male', geographical_unit=mock_geo_unit)

        # Add each person to their appropriate subset
        kids_subset.add_member(kid)
        adults_subset.add_member(adult)
        elderly_subset.add_member(elderly)

        # BUG: All subsets will show 3 members!
        print(f"\nKids subset members: {kids_subset.num_members}")
        print(f"Adults subset members: {adults_subset.num_members}")
        print(f"Elderly subset members: {elderly_subset.num_members}")
        print(f"All same set? kids is adults: {kids_subset.members is adults_subset.members}")
        print(f"All same set? adults is elderly: {adults_subset.members is elderly_subset.members}")

        # EXPECTED: Each subset should have 1 member
        # ACTUAL (BUG): All subsets have 3 members
        assert kids_subset.num_members == 1, \
            f"Expected 1 kid, got {kids_subset.num_members}. BUG: Sharing members set!"
        assert adults_subset.num_members == 1, \
            f"Expected 1 adult, got {adults_subset.num_members}. BUG: Sharing members set!"
        assert elderly_subset.num_members == 1, \
            f"Expected 1 elderly, got {elderly_subset.num_members}. BUG: Sharing members set!"

    def test_people_present_also_shared(self, mock_geo_unit):
        """
        DEMONSTRATES THE BUG: people_present list is also shared due to default=[].

        This affects which people are "present" at venues during simulation.
        """
        household1 = Venue(
            name="Household 1",
            venue_type="household",
            geographical_unit=mock_geo_unit,
        )

        household2 = Venue(
            name="Household 2",
            venue_type="household",
            geographical_unit=mock_geo_unit,
        )

        # Create subsets without specifying people_present
        subset1 = Subset(household1, 0, 'adults')
        subset2 = Subset(household2, 0, 'adults')

        # Create a person
        person = Person(age=35, sex='male', geographical_unit=mock_geo_unit)

        # Add person to subset1's people_present
        subset1.append(person)

        # BUG: person will also appear in subset2's people_present!
        print(f"\nSubset1 people_present: {len(subset1.people_present)}")
        print(f"Subset2 people_present: {len(subset2.people_present)}")
        print(f"Same list? {subset1.people_present is subset2.people_present}")

        # EXPECTED: Only subset1 should have the person present
        # ACTUAL (BUG): Both subsets have the person present
        assert len(subset1.people_present) == 1, "Subset1 should have 1 person present"
        assert len(subset2.people_present) == 0, \
            f"Subset2 should have 0 people present, got {len(subset2.people_present)}. " \
            f"BUG: people_present list is shared!"

    def test_demonstrates_total_population_in_all_subsets(self, mock_geo_unit):
        """
        DEMONSTRATES THE EXACT BUG YOU REPORTED:
        Every subset shows total population count.

        This simulates what happens during create_world_households.py
        """
        # Create 5 households
        households = []
        for i in range(5):
            household = Venue(
                name=f"Household {i+1}",
                venue_type="household",
                geographical_unit=mock_geo_unit,
                properties={'composition': '0 0 2 0'}
            )

            # Create subsets for each household
            household.subsets = {
                'kids': Subset(household, 0, 'kids'),
                'adults': Subset(household, 1, 'adults'),
                'elderly': Subset(household, 2, 'elderly')
            }
            households.append(household)

        # Create 10 people and distribute them
        people = [
            Person(age=10, sex='male', geographical_unit=mock_geo_unit),
            Person(age=12, sex='female', geographical_unit=mock_geo_unit),
            Person(age=35, sex='male', geographical_unit=mock_geo_unit),
            Person(age=38, sex='female', geographical_unit=mock_geo_unit),
            Person(age=40, sex='male', geographical_unit=mock_geo_unit),
            Person(age=42, sex='female', geographical_unit=mock_geo_unit),
            Person(age=70, sex='male', geographical_unit=mock_geo_unit),
            Person(age=72, sex='female', geographical_unit=mock_geo_unit),
            Person(age=75, sex='male', geographical_unit=mock_geo_unit),
            Person(age=80, sex='female', geographical_unit=mock_geo_unit),
        ]

        # Assign people to different households/subsets
        households[0].subsets['kids'].add_member(people[0])
        households[1].subsets['kids'].add_member(people[1])
        households[2].subsets['adults'].add_member(people[2])
        households[2].subsets['adults'].add_member(people[3])
        households[3].subsets['adults'].add_member(people[4])
        households[3].subsets['adults'].add_member(people[5])
        households[4].subsets['elderly'].add_member(people[6])
        households[4].subsets['elderly'].add_member(people[7])
        households[0].subsets['elderly'].add_member(people[8])
        households[1].subsets['elderly'].add_member(people[9])

        print("\n" + "="*60)
        print("DEMONSTRATING THE BUG YOU REPORTED:")
        print("="*60)

        total_population = len(people)

        for i, household in enumerate(households):
            print(f"\nHousehold {i+1}:")
            for subset_name, subset in household.subsets.items():
                print(f"  {subset_name}: {subset.num_members} members")

                # BUG: Every subset will show total_population (10)
                # EXPECTED: Different counts based on assignments above
                if subset.num_members == total_population:
                    print(f"    ⚠️  BUG DETECTED: Shows total population ({total_population})!")

        # Check the bug is present
        all_show_total = all(
            subset.num_members == total_population
            for household in households
            for subset in household.subsets.values()
        )

        assert not all_show_total, \
            f"BUG CONFIRMED: ALL subsets show total population ({total_population})! " \
            f"This is because they all share the same members set due to " \
            f"mutable default parameter in Subset.__init__(members=set())"

    def test_venue_properties_and_subsets_also_shared(self, mock_geo_unit):
        """
        DEMONSTRATES: Venue class also has mutable default bugs.

        properties={} and subsets={} are shared across all Venue instances.
        """
        # Create two venues without specifying properties or subsets
        venue1 = Venue(
            name="Venue 1",
            venue_type="school",
            geographical_unit=mock_geo_unit
        )

        venue2 = Venue(
            name="Venue 2",
            venue_type="school",
            geographical_unit=mock_geo_unit
        )

        # Add a property to venue1
        venue1.properties['capacity'] = 100

        # BUG: venue2 will also have this property!
        print(f"\nVenue1 properties: {venue1.properties}")
        print(f"Venue2 properties: {venue2.properties}")
        print(f"Same dict? {venue1.properties is venue2.properties}")

        assert 'capacity' in venue1.properties, "Venue1 should have capacity"
        assert 'capacity' not in venue2.properties, \
            f"Venue2 should NOT have capacity, but got {venue2.properties}. " \
            f"BUG: properties dict is shared!"

        # Same bug with subsets
        subset1 = Subset(venue1, 0, 'group1')
        venue1.subsets['group1'] = subset1

        print(f"\nVenue1 subsets: {venue1.subsets}")
        print(f"Venue2 subsets: {venue2.subsets}")
        print(f"Same dict? {venue1.subsets is venue2.subsets}")

        assert 'group1' in venue1.subsets, "Venue1 should have group1"
        assert 'group1' not in venue2.subsets, \
            f"Venue2 should NOT have group1, but got {venue2.subsets}. " \
            f"BUG: subsets dict is shared!"
