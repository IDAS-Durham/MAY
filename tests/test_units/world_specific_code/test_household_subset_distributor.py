import pytest
from world_specific_code.household_distributors import HouseholdSubsetDistributor
from may.population import Person
from may.geography import GeographicalUnit


class TestHouseholdSubsetDistributor:
    """Test suite for HouseholdSubsetDistributor class."""

    @pytest.fixture
    def distributor(self):
        subset_names = ['kids', 'independent children', 'adults', 'elderly']
        return HouseholdSubsetDistributor('household', subset_names)

    @pytest.fixture
    def mock_geo_unit(self):
        return GeographicalUnit(id=0, name="TestSGU", level="SGU")

    def test_initialization(self, distributor):
        """Test that the distributor initializes correctly."""
        assert distributor.venue_type == 'household'
        assert distributor.subset_names == ['kids', 'independent children', 'adults', 'elderly']
        assert distributor.n_subsets == 4

    def test_find_subset_for_kid(self, distributor, mock_geo_unit):
        """Test that children under 18 are assigned to 'kids' subset."""
        # Test various ages under 18
        for age in [0, 5, 10, 15, 17]:
            person = Person(age=age, sex='male', geographical_unit=mock_geo_unit)
            venue_has_capacity = [True, True, True, True]

            subset_index, subset_name = distributor.find_subset_for_person(
                'home', venue_has_capacity, person
            )

            assert subset_index == 0, f"Age {age} should map to index 0"
            assert subset_name == 'kids', f"Age {age} should map to 'kids'"

    def test_find_subset_for_independent_children(self, distributor, mock_geo_unit):
        """Test that people aged 18-24 are assigned to 'independent children' subset."""
        for age in [18, 20, 22, 24]:
            person = Person(age=age, sex='female', geographical_unit=mock_geo_unit)
            venue_has_capacity = [True, True, True, True]

            subset_index, subset_name = distributor.find_subset_for_person(
                'home', venue_has_capacity, person
            )

            assert subset_index == 1, f"Age {age} should map to index 1"
            assert subset_name == 'independent children', f"Age {age} should map to 'independent children'"

    def test_find_subset_for_adults(self, distributor, mock_geo_unit):
        """Test that people aged 25-59 are assigned to 'adults' subset."""
        for age in [25, 30, 40, 50, 59]:
            person = Person(age=age, sex='male', geographical_unit=mock_geo_unit)
            venue_has_capacity = [True, True, True, True]

            subset_index, subset_name = distributor.find_subset_for_person(
                'home', venue_has_capacity, person
            )

            assert subset_index == 2, f"Age {age} should map to index 2"
            assert subset_name == 'adults', f"Age {age} should map to 'adults'"

    def test_find_subset_for_elderly(self, distributor, mock_geo_unit):
        """Test that people aged 60+ are assigned to 'elderly' subset."""
        for age in [60, 65, 75, 85, 100]:
            person = Person(age=age, sex='female', geographical_unit=mock_geo_unit)
            venue_has_capacity = [True, True, True, True]

            subset_index, subset_name = distributor.find_subset_for_person(
                'home', venue_has_capacity, person
            )

            assert subset_index == 3, f"Age {age} should map to index 3"
            assert subset_name == 'elderly', f"Age {age} should map to 'elderly'"

    def test_no_capacity_for_kids(self, distributor, mock_geo_unit):
        """Test that a kid gets 'No subset available' when kids subset is full."""
        person = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [False, True, True, True]  # Kids subset full

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == -1
        assert subset_name == 'No subset available'

    def test_no_capacity_for_independent_children(self, distributor, mock_geo_unit):
        """Test independent children subset capacity constraint."""
        person = Person(age=20, sex='female', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, False, True, True]  # Independent children subset full

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == -1
        assert subset_name == 'No subset available'

    def test_no_capacity_for_adults(self, distributor, mock_geo_unit):
        """Test adults subset capacity constraint."""
        person = Person(age=40, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, False, True]  # Adults subset full

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == -1
        assert subset_name == 'No subset available'

    def test_no_capacity_for_elderly(self, distributor, mock_geo_unit):
        """Test elderly subset capacity constraint."""
        person = Person(age=75, sex='female', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True, False]  # Elderly subset full

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == -1
        assert subset_name == 'No subset available'

    def test_all_subsets_full(self, distributor, mock_geo_unit):
        """Test that 'No subset available' is returned when all subsets are full."""
        venue_has_capacity = [False, False, False, False]

        # Test with people from each age group
        test_cases = [
            Person(age=10, sex='male', geographical_unit=mock_geo_unit),
            Person(age=20, sex='female', geographical_unit=mock_geo_unit),
            Person(age=40, sex='male', geographical_unit=mock_geo_unit),
            Person(age=75, sex='female', geographical_unit=mock_geo_unit),
        ]

        for person in test_cases:
            subset_index, subset_name = distributor.find_subset_for_person(
                'home', venue_has_capacity, person
            )
            assert subset_index == -1, f"Person age {person.age} should have no subset available"
            assert subset_name == 'No subset available'

    def test_age_priority_ordering(self, distributor, mock_geo_unit):
        """Test that age-based assignment follows the priority order (kids -> ind. children -> adults -> elderly)."""
        # A kid should be assigned to kids, not independent children, even if both are available
        person_kid = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True, True]

        idx, name = distributor.find_subset_for_person('home', venue_has_capacity, person_kid)
        assert idx == 0 and name == 'kids', "Kids should be assigned to kids subset, not others"


    @pytest.mark.parametrize("person_age, subset_name", [
        (17.5,'kids'),
        (18.5,'independent children'),
        (24.9,'independent children'),
        (25.1,'adults'),
        (59.99999,'adults'),
        (60.01,'elderly'),
    ])        
    def test_fractional_ages(self, person_age, subset_name, distributor, mock_geo_unit):
        """Test that fractional ages work correctly with boundary conditions."""
        venue_has_capacity = [True, True, True, True]
        # Test fractional ages near boundaries
        for sex in ['male', 'female']:
            person = Person(age=person_age, sex=sex, geographical_unit=mock_geo_unit)
            idx, name = distributor.find_subset_for_person('home', venue_has_capacity, person)
            assert name == subset_name

    @pytest.mark.parametrize("age,expected_idx,expected_name", [
        (0, 0, 'kids'),
        (5, 0, 'kids'),
        (17, 0, 'kids'),
        (18, 1, 'independent children'),
        (21, 1, 'independent children'),
        (24, 1, 'independent children'),
        (25, 2, 'adults'),
        (35, 2, 'adults'),
        (59, 2, 'adults'),
        (60, 3, 'elderly'),
        (80, 3, 'elderly'),
        (100, 3, 'elderly'),
    ])
    def test_age_mapping_parametrized(self, distributor, mock_geo_unit, age, expected_idx, expected_name):
        """Parametrized test for comprehensive age mapping coverage."""
        person = Person(age=age, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True, True]

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == expected_idx, f"Age {age} should map to index {expected_idx}"
        assert subset_name == expected_name, f"Age {age} should map to '{expected_name}'"

    @pytest.mark.parametrize("capacity,person_age,expected_available", [
        ([True, True, True, True], 10, True),     # All available
        ([False, True, True, True], 10, False),   # Kids not available
        ([True, False, True, True], 20, False),   # Independent children not available
        ([True, True, False, True], 40, False),   # Adults not available
        ([True, True, True, False], 70, False),   # Elderly not available
        ([False, False, False, False], 30, False), # None available
    ])
    def test_capacity_constraints_parametrized(self, distributor, mock_geo_unit, capacity, person_age, expected_available):
        """Parametrized test for capacity constraints across age groups."""
        person = Person(age=person_age, sex='male', geographical_unit=mock_geo_unit)

        subset_index, subset_name = distributor.find_subset_for_person('home', capacity, person)

        if expected_available:
            assert subset_index >= 0, f"Should find a subset for age {person_age} with capacity {capacity}"
            assert subset_name != 'No subset available'
        else:
            assert subset_index == -1, f"Should not find a subset for age {person_age} with capacity {capacity}"
            assert subset_name == 'No subset available'

    def test_sex_does_not_affect_assignment(self, distributor, mock_geo_unit):
        """Test that sex does not affect subset assignment (age is the only factor)."""
        venue_has_capacity = [True, True, True, True]

        # Test same age, different sex
        male_kid = Person(age=10, sex='male', geographical_unit=mock_geo_unit)
        female_kid = Person(age=10, sex='female', geographical_unit=mock_geo_unit)

        idx_male, name_male = distributor.find_subset_for_person('home', venue_has_capacity, male_kid)
        idx_female, name_female = distributor.find_subset_for_person('home', venue_has_capacity, female_kid)

        assert idx_male == idx_female == 0
        assert name_male == name_female == 'kids'

    def test_negative_age_handling(self, distributor, mock_geo_unit):
        """Test that negative ages are handled (should go to kids subset)."""
        person = Person(age=-1, sex='male', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True, True]

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        # Negative ages should be < 18, so should go to kids
        assert subset_index == 0
        assert subset_name == 'kids'

    def test_very_old_age_handling(self, distributor, mock_geo_unit):
        """Test that very old ages (>100) are handled correctly."""
        person = Person(age=150, sex='female', geographical_unit=mock_geo_unit)
        venue_has_capacity = [True, True, True, True]

        subset_index, subset_name = distributor.find_subset_for_person(
            'home', venue_has_capacity, person
        )

        assert subset_index == 3
        assert subset_name == 'elderly'
