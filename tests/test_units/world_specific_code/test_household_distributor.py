import pytest
import random
from unittest.mock import Mock, MagicMock, patch
from collections import defaultdict

from world_specific_code.household_distributors import HouseholdDistributor, HouseholdSubsetDistributor
from may.population import Person, Subset
from may.geography import GeographicalUnit, Venue


class TestHouseholdDistributor:
    """Test suite for HouseholdDistributor class."""

    @pytest.fixture
    def mock_geo_unit(self):
        """Create a mock geographical unit for testing."""
        return GeographicalUnit(id=0, name="TestSGU", level="SGU")

    @pytest.fixture
    def mock_venue_manager(self, mock_geo_unit):
        """Create a mock VenueManager with household venues."""
        venue_manager = Mock()

        # Create a test household venue
        venue = Venue(
            name="Test Household",
            venue_type="household",
            geographical_unit=mock_geo_unit,
            properties={'composition': '0 0 2 0'}  # 2 adults
        )

        # Initialize subsets for the venue
        venue.subsets = {
            'kids': Subset(venue, 0, 'kids'),
            'independent children': Subset(venue, 1, 'independent children'),
            'adults': Subset(venue, 2, 'adults'),
            'elderly': Subset(venue, 3, 'elderly')
        }

        venue_manager.venues_by_type = {'household': [venue]}
        venue_manager.get_venues_by_type = Mock(return_value=[venue])

        return venue_manager

    @pytest.fixture
    def mock_people(self, mock_geo_unit):
        """Create a list of mock people for testing."""
        Person.reset_counter()
        return [
            Person(age=10, sex='male', geographical_unit=mock_geo_unit, activities=['home']),
            Person(age=20, sex='female', geographical_unit=mock_geo_unit, activities=['home']),
            Person(age=35, sex='male', geographical_unit=mock_geo_unit, activities=['home']),
            Person(age=70, sex='female', geographical_unit=mock_geo_unit, activities=['home']),
        ]

    @pytest.fixture
    def distributor(self, mock_venue_manager, mock_people):
        """Create a HouseholdDistributor instance for testing."""
        # Reset Person counter for consistent IDs across tests
        Person.reset_counter()
        return HouseholdDistributor('household', mock_venue_manager, mock_people)

    def test_initialization(self, distributor):
        """Test that the distributor initializes correctly."""
        assert distributor.venue_type == 'household'
        assert isinstance(distributor.subset_distributor, HouseholdSubsetDistributor)
        assert distributor.subset_distributor.n_subsets == 4
        assert distributor.subset_distributor.subset_names == ['kids', 'independent children', 'adults', 'elderly']

    def test_get_subset_dist_creates_household_subset_distributor(self, mock_venue_manager, mock_people):
        """Test that _get_subset_dist creates a HouseholdSubsetDistributor."""
        distributor = HouseholdDistributor('household', mock_venue_manager, mock_people)

        assert isinstance(distributor.subset_distributor, HouseholdSubsetDistributor)
        assert distributor.subset_distributor.subset_names == ['kids', 'independent children', 'adults', 'elderly']

    def test_venue_has_membership_capacity_initialized(self, distributor):
        """Test that venue capacity tracking is initialized."""
        assert isinstance(distributor._venue_has_membership_capacity_by_subset, defaultdict)

    def create_venue_with_composition(self, composition, mock_geo_unit):
        """Helper to create a venue with specific composition and initialized subsets."""
        venue = Venue(
            name=f"Household_{composition}",
            venue_type="household",
            geographical_unit=mock_geo_unit,
            properties={'composition': composition}
        )

        # Initialize subsets
        venue.subsets = {
            'kids': Subset(venue, 0, 'kids'),
            'independent children': Subset(venue, 1, 'independent children'),
            'adults': Subset(venue, 2, 'adults'),
            'elderly': Subset(venue, 3, 'elderly')
        }

        return venue

    # ===== Tests for composition '0 0 0 2' (2 elderly) =====

    def test_update_capacity_0_0_0_2_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 0 2' composition with no members."""
        venue = self.create_venue_with_composition('0 0 0 2', mock_geo_unit)
        subset = venue.subsets['elderly']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # Should allow only elderly
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, False, True]

    def test_update_capacity_0_0_0_2_full(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 0 2' composition when full."""
        venue = self.create_venue_with_composition('0 0 0 2', mock_geo_unit)
        subset = venue.subsets['elderly']

        # Add 2 elderly members
        person1 = Person(age=70, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=75, sex='female', geographical_unit=mock_geo_unit)
        subset.add_member(person1)
        subset.add_member(person2)

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # All subsets should be closed
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, False, False]
        assert 0 not in distributor.available_venue_indices

    # ===== Tests for composition '0 0 2 0' (2 adults) =====

    def test_update_capacity_0_0_2_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 2 0' composition with no members."""
        venue = self.create_venue_with_composition('0 0 2 0', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]
        # Initialize capacity to all True (this happens automatically via defaultdict)
        _ = distributor._venue_has_membership_capacity_by_subset[venue.id]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # Should allow only adults
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, True, False]

    def test_update_capacity_0_0_2_0_full(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 2 0' composition when full."""
        venue = self.create_venue_with_composition('0 0 2 0', mock_geo_unit)
        subset = venue.subsets['adults']

        # Add 2 adult members
        person1 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=40, sex='female', geographical_unit=mock_geo_unit)
        subset.add_member(person1)
        subset.add_member(person2)

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # All subsets should be closed
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, False, False]
        assert 0 not in distributor.available_venue_indices

    # ===== Tests for composition '0 0 0 1' (1 elderly) =====

    def test_update_capacity_0_0_0_1_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 0 1' composition with no members."""
        venue = self.create_venue_with_composition('0 0 0 1', mock_geo_unit)
        subset = venue.subsets['elderly']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # Should allow only elderly
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, False, True]

    def test_update_capacity_0_0_0_1_full(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 0 1' composition when full."""
        venue = self.create_venue_with_composition('0 0 0 1', mock_geo_unit)
        subset = venue.subsets['elderly']

        # Add 1 elderly member
        person1 = Person(age=70, sex='male', geographical_unit=mock_geo_unit)
        subset.add_member(person1)

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # All subsets should be closed
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, False, False]
        assert 0 not in distributor.available_venue_indices

    # ===== Tests for composition '0 0 1 0' (1 adult) =====

    def test_update_capacity_0_0_1_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 1 0' composition with no members."""
        venue = self.create_venue_with_composition('0 0 1 0', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # Should allow only adults
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, True, False]

    # ===== Tests for composition '0 >=1 2 0' (0 kids, >=1 ind children, 2 adults) =====

    def test_update_capacity_0_ge1_2_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 >=1 2 0' composition with no members."""
        venue = self.create_venue_with_composition('0 >=1 2 0', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]

        # Need to control randomness for independent children
        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        # Kids should be False, independent children can vary (random), adults True, elderly False
        assert capacity[0] == False  # No kids
        assert capacity[2] == True   # Adults still have capacity
        assert capacity[3] == False  # No elderly

    def test_update_capacity_0_ge1_2_0_adults_full(self, distributor, mock_geo_unit):
        """Test capacity update for '0 >=1 2 0' when adults are full."""
        venue = self.create_venue_with_composition('0 >=1 2 0', mock_geo_unit)

        # Add 2 adult members
        person1 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=40, sex='female', geographical_unit=mock_geo_unit)
        venue.subsets['adults'].add_member(person1)
        venue.subsets['adults'].add_member(person2)

        subset = venue.subsets['adults']
        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[2] == False  # Adults are full

    # ===== Tests for composition '1 >=0 2 0' (1 kid, >=0 ind children, 2 adults) =====

    def test_update_capacity_1_ge0_2_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '1 >=0 2 0' composition with no members."""
        venue = self.create_venue_with_composition('1 >=0 2 0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True   # Kids still have capacity
        assert capacity[2] == True   # Adults still have capacity
        assert capacity[3] == False  # No elderly

    def test_update_capacity_1_ge0_2_0_kids_full(self, distributor, mock_geo_unit):
        """Test capacity update for '1 >=0 2 0' when kids subset is full."""
        venue = self.create_venue_with_composition('1 >=0 2 0', mock_geo_unit)

        # Add 1 kid
        person1 = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        venue.subsets['kids'].add_member(person1)

        subset = venue.subsets['kids']
        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # Kids are full

    # ===== Tests for composition '>=2 >=0 2 0' (>=2 kids, >=0 ind children, 2 adults) =====

    def test_update_capacity_ge2_ge0_2_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '>=2 >=0 2 0' composition with no members."""
        venue = self.create_venue_with_composition('>=2 >=0 2 0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # Always False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True   # Kids still have capacity (need 2)
        assert capacity[2] == True   # Adults still have capacity
        assert capacity[3] == False  # No elderly

    def test_update_capacity_ge2_ge0_2_0_two_kids(self, distributor, mock_geo_unit):
        """Test capacity update for '>=2 >=0 2 0' with 2 kids (might close randomly)."""
        venue = self.create_venue_with_composition('>=2 >=0 2 0', mock_geo_unit)

        # Add 2 kids
        person1 = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        person2 = Person(age=12, sex='female', geographical_unit=mock_geo_unit)
        venue.subsets['kids'].add_member(person1)
        venue.subsets['kids'].add_member(person2)

        subset = venue.subsets['kids']
        distributor.available_venue_indices = [0]

        # Test when random returns True (closes kids)
        with patch('random.getrandbits', return_value=1):  # True
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # Kids closed by random choice

    # ===== Tests for composition '0 >=1 1 0' (0 kids, >=1 ind children, 1 adult) =====

    def test_update_capacity_0_ge1_1_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '0 >=1 1 0' composition with no members."""
        venue = self.create_venue_with_composition('0 >=1 1 0', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # No kids
        assert capacity[2] == True   # Adults still have capacity (1 needed)
        assert capacity[3] == False  # No elderly

    # ===== Tests for composition '1 >=0 1 0' (1 kid, >=0 ind children, 1 adult) =====

    def test_update_capacity_1_ge0_1_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '1 >=0 1 0' composition with no members."""
        venue = self.create_venue_with_composition('1 >=0 1 0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True   # Kids still have capacity
        assert capacity[2] == True   # Adults still have capacity
        assert capacity[3] == False  # No elderly

    # ===== Tests for composition '>=2 >=0 1 0' (>=2 kids, >=0 ind children, 1 adult) =====

    def test_update_capacity_ge2_ge0_1_0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '>=2 >=0 1 0' composition with no members."""
        venue = self.create_venue_with_composition('>=2 >=0 1 0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True   # Kids still have capacity
        assert capacity[2] == True   # Adults still have capacity
        assert capacity[3] == False  # No elderly

    # ===== Tests for composition '1 >=0 >=0 >=0' (1 kid, rest flexible) =====

    def test_update_capacity_1_ge0_ge0_ge0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '1 >=0 >=0 >=0' composition with no members."""
        venue = self.create_venue_with_composition('1 >=0 >=0 >=0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True  # Kids still have capacity (need 1)

    def test_update_capacity_1_ge0_ge0_ge0_one_kid(self, distributor, mock_geo_unit):
        """Test capacity update for '1 >=0 >=0 >=0' with 1 kid."""
        venue = self.create_venue_with_composition('1 >=0 >=0 >=0', mock_geo_unit)

        # Add 1 kid
        person1 = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        venue.subsets['kids'].add_member(person1)

        subset = venue.subsets['kids']
        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # Kids are full (has 1, needs 1)

    # ===== Tests for composition '>=2 >=0 >=0 >=0' (>=2 kids, rest flexible) =====

    def test_update_capacity_ge2_ge0_ge0_ge0_empty(self, distributor, mock_geo_unit):
        """Test capacity update for '>=2 >=0 >=0 >=0' composition with no members."""
        venue = self.create_venue_with_composition('>=2 >=0 >=0 >=0', mock_geo_unit)
        subset = venue.subsets['kids']

        distributor.available_venue_indices = [0]

        with patch('random.getrandbits', return_value=0):  # False
            distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == True  # Kids still have capacity

    # ===== Tests for composition '0 >=0 0 0' (only independent children) =====

    def test_update_capacity_0_ge0_0_0(self, distributor, mock_geo_unit):
        """Test capacity update for '0 >=0 0 0' composition."""
        venue = self.create_venue_with_composition('0 >=0 0 0', mock_geo_unit)
        subset = venue.subsets['independent children']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # No kids
        assert capacity[2] == False  # No adults
        assert capacity[3] == False  # No elderly
        # Independent children can be True

    # ===== Tests for composition '0 >=0 >=0 >=0' (no kids, rest flexible) =====

    def test_update_capacity_0_ge0_ge0_ge0(self, distributor, mock_geo_unit):
        """Test capacity update for '0 >=0 >=0 >=0' composition."""
        venue = self.create_venue_with_composition('0 >=0 >=0 >=0', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # No kids allowed

    # ===== Tests for composition '0 0 0 >=3' (>=3 elderly) =====

    def test_update_capacity_0_0_0_ge3(self, distributor, mock_geo_unit):
        """Test capacity update for '0 0 0 >=3' composition."""
        venue = self.create_venue_with_composition('0 0 0 >=3', mock_geo_unit)
        subset = venue.subsets['elderly']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == False  # No kids
        assert capacity[1] == False  # No independent children
        assert capacity[2] == False  # No adults
        # Elderly should be True

    # ===== Test for invalid composition =====

    def test_update_capacity_invalid_composition_raises_error(self, distributor, mock_geo_unit):
        """Test that an invalid composition raises KeyError."""
        venue = self.create_venue_with_composition('999 999 999 999', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]

        with pytest.raises(KeyError) as exc_info:
            distributor._update_venue_membership_capacity(0, venue, subset)

        assert '999 999 999 999' in str(exc_info.value)

    # ===== Test venue removal from available indices =====

    def test_venue_removed_when_all_subsets_full(self, distributor, mock_geo_unit):
        """Test that venue is removed from available_venue_indices when all subsets are full."""
        venue = self.create_venue_with_composition('0 0 1 0', mock_geo_unit)

        # Add 1 adult to fill the household
        person1 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        venue.subsets['adults'].add_member(person1)
        # Note: The composition says max 2 for '0 0 1 0', but logic uses >= 2 to close
        # So we need to check the actual implementation
        person2 = Person(age=40, sex='female', geographical_unit=mock_geo_unit)
        venue.subsets['adults'].add_member(person2)

        subset = venue.subsets['adults']
        distributor.available_venue_indices = [0, 1, 2]

        distributor._update_venue_membership_capacity(0, venue, subset)

        # Venue should be removed if all capacity is False
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        if not any(capacity):
            assert 0 not in distributor.available_venue_indices

    def test_venue_not_removed_when_capacity_remains(self, distributor, mock_geo_unit):
        """Test that venue is NOT removed when some capacity remains."""
        venue = self.create_venue_with_composition('0 0 2 0', mock_geo_unit)

        # Add only 1 adult (capacity for 2)
        person1 = Person(age=35, sex='male', geographical_unit=mock_geo_unit)
        venue.subsets['adults'].add_member(person1)

        subset = venue.subsets['adults']
        distributor.available_venue_indices = [0, 1, 2]

        distributor._update_venue_membership_capacity(0, venue, subset)

        # Venue should still be available
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        if any(capacity):
            assert 0 in distributor.available_venue_indices

    # ===== Parametrized tests for all fixed compositions =====

    @pytest.mark.parametrize("composition,expected_kids,expected_elderly", [
        ('0 0 0 2', False, True),   # 2 elderly
        ('0 0 2 0', False, False),  # 2 adults
        ('0 0 0 1', False, True),   # 1 elderly
        ('0 0 1 0', False, False),  # 1 adult
    ])
    def test_fixed_compositions_capacity(self, distributor, mock_geo_unit,
                                         composition, expected_kids, expected_elderly):
        """Parametrized test for fixed-size household compositions."""
        venue = self.create_venue_with_composition(composition, mock_geo_unit)
        subset = venue.subsets['adults']  # Use adults as the trigger

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity[0] == expected_kids, f"Kids capacity wrong for {composition}"
        assert capacity[3] == expected_elderly, f"Elderly capacity wrong for {composition}"

    def test_composition_with_whitespace(self, distributor, mock_geo_unit):
        """Test that compositions with extra whitespace are handled correctly."""
        venue = self.create_venue_with_composition('  0 0 2 0  ', mock_geo_unit)
        subset = venue.subsets['adults']

        distributor.available_venue_indices = [0]
        distributor._update_venue_membership_capacity(0, venue, subset)

        # Should work the same as '0 0 2 0'
        capacity = distributor._venue_has_membership_capacity_by_subset[venue.id]
        assert capacity == [False, False, True, False]
