"""
Unit tests for PopulationManager class (population.py)

Tests the PopulationManager class that handles population generation and management.
"""

import pytest
import pandas as pd
from collections import defaultdict
from unittest.mock import Mock, patch, MagicMock
import os
import tempfile

from may.population import PopulationManager, Person, PopulationError
from may.geography import Geography, GeographicalUnit


@pytest.fixture
def mock_geography():
    """Create a mock geography with some geographical units."""
    geography = Geography(levels=['SGU', 'MSOA', 'LAD'])

    # Create some SGUs (smallest geographical units)
    sgu1 = GeographicalUnit(id=0, name='E00000001', level='SGU')
    sgu2 = GeographicalUnit(id=1, name='E00000002', level='SGU')
    sgu3 = GeographicalUnit(id=2, name='E00000003', level='SGU')

    # Add units to geography
    geography.units = {
        'E00000001': sgu1,
        'E00000002': sgu2,
        'E00000003': sgu3
    }

    geography.units_by_level = {
        'SGU': {'E00000001': sgu1, 'E00000002': sgu2, 'E00000003': sgu3}
    }

    return geography


@pytest.fixture(autouse=True)
def reset_person_counter():
    """Reset Person ID counter before each test."""
    Person.reset_counter()
    yield
    Person.reset_counter()


# ============================================================================
# Initialization Tests
# ============================================================================

class TestPopulationManagerInitialization:
    """Test PopulationManager initialization."""

    def test_init_basic(self, mock_geography):
        """data_dir is whatever the caller passes; nothing is defaulted."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        assert pop_manager.geography == mock_geography
        assert pop_manager.data_dir == "data/population"
        assert pop_manager.people == []
        assert pop_manager.people_by_id == {}
        assert pop_manager.precise_demographics == {}

    def test_init_with_custom_data_dir(self, mock_geography):
        """Test initialization with custom data directory."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="custom/path")

        assert pop_manager.data_dir == "custom/path"

    def test_data_dir_is_required(self, mock_geography):
        """PopulationManager has no default for data_dir; production callers
        always provide one (see create_world.py and the integration tests)."""
        with pytest.raises(TypeError, match="data_dir"):
            PopulationManager(geography=mock_geography)

    def test_len_initially_zero(self, mock_geography):
        """Test that initial population size is zero."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        assert len(pop_manager) == 0


# ============================================================================
# Demographics Loading Tests
# ============================================================================

class TestDemographicsLoading:
    """Test demographics loading functionality."""

    def test_create_nested_defaultdict(self):
        """Test the nested defaultdict creation helper."""
        result = PopulationManager._create_nested_defaultdict()

        assert isinstance(result, defaultdict)
        # Should return empty dict for missing keys
        test_key = result['test_key']
        assert isinstance(test_key, dict)

    def test_load_demographics_file_not_found(self, mock_geography):
        """Missing demographics files fail loud (adr/0010) rather than leaving
        an empty manager that silently builds a zero-person world."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="/nonexistent/path")

        with pytest.raises(PopulationError, match="not found"):
            pop_manager.load_demographics_from_csv()
        assert len(pop_manager.precise_demographics) == 0

    def test_load_demographics_from_csv_success(self, mock_geography):
        """Test successful loading of demographics from CSV."""
        # Create temporary CSV files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create male demographics CSV
            male_data = {
                'geo_unit': ['E00000001', 'E00000002', 'E00000003'],
                '0': [5, 3, 4],
                '1': [6, 4, 5],
                '25': [10, 8, 9],
                '65': [7, 6, 5]
            }
            male_df = pd.DataFrame(male_data)
            male_path = os.path.join(tmpdir, 'demographics_male.csv')
            male_df.to_csv(male_path, index=False)

            # Create female demographics CSV
            female_data = {
                'geo_unit': ['E00000001', 'E00000002', 'E00000003'],
                '0': [4, 5, 3],
                '1': [7, 5, 6],
                '25': [11, 9, 10],
                '65': [8, 7, 6]
            }
            female_df = pd.DataFrame(female_data)
            female_path = os.path.join(tmpdir, 'demographics_female.csv')
            female_df.to_csv(female_path, index=False)

            # Load demographics
            pop_manager = PopulationManager(geography=mock_geography, data_dir=tmpdir)
            pop_manager.load_demographics_from_csv()

            # Verify demographics loaded
            assert len(pop_manager.precise_demographics) == 3
            assert 'E00000001' in pop_manager.precise_demographics
            assert pop_manager.precise_demographics['E00000001'][0]['male'] == 5
            assert pop_manager.precise_demographics['E00000001'][0]['female'] == 4
            assert pop_manager.precise_demographics['E00000001'][25]['male'] == 10
            assert pop_manager.precise_demographics['E00000001'][25]['female'] == 11


# ============================================================================
# Population Generation Tests
# ============================================================================

class TestPopulationGeneration:
    """Test population generation functionality."""

    def test_generate_population_without_demographics(self, mock_geography):
        """Generation with nothing loaded fails loud (adr/0010), not an empty
        population."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        with pytest.raises(PopulationError, match="No demographics data loaded"):
            pop_manager.generate_population()
        assert len(pop_manager.people) == 0

    def test_generate_population_basic(self, mock_geography):
        """Test basic population generation from demographics."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        # Manually set up simple demographics
        pop_manager.precise_demographics = {
            'E00000001': {
                0: {'male': 2, 'female': 1},
                25: {'male': 3, 'female': 2}
            },
            'E00000002': {
                0: {'male': 1, 'female': 2},
                50: {'male': 2, 'female': 1}
            }
        }

        pop_manager.generate_population()

        # Should create 14 people total (2+1+3+2 + 1+2+2+1)
        assert len(pop_manager.people) == 14
        assert len(pop_manager.people_by_id) == 14

    def test_generate_population_age_ordering(self, mock_geography):
        """Test that people are generated in age order."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                50: {'male': 2},
                10: {'female': 2},
                30: {'male': 2}
            }
        }

        pop_manager.generate_population()

        # First 2 people should be age 10, next 2 age 30, last 2 age 50
        assert pop_manager.people[0].age == 10
        assert pop_manager.people[1].age == 10
        assert pop_manager.people[2].age == 30
        assert pop_manager.people[3].age == 30
        assert pop_manager.people[4].age == 50
        assert pop_manager.people[5].age == 50

    def test_generate_population_with_kwargs(self, mock_geography):
        """Test population generation with additional kwargs."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                25: {'male': 2}
            }
        }

        test_activities = ['work', 'home']
        test_properties = {'test': 'value'}

        pop_manager.generate_population(
            activities=test_activities,
            properties=test_properties
        )

        # Person stores activities as a set (no duplicates, order-independent)
        assert pop_manager.people[0].activities == set(test_activities)
        assert pop_manager.people[0].properties == test_properties

    def test_generate_population_assigns_to_geo_units(self, mock_geography):
        """Test that people are assigned to their geographical units."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                25: {'male': 3}
            }
        }

        pop_manager.generate_population()

        # All people should have geographical unit E00000001
        unit = mock_geography.get_unit('E00000001')
        assert all(p.geographical_unit == unit for p in pop_manager.people)


# ============================================================================
# Query Methods Tests
# ============================================================================

class TestQueryMethods:
    """Test methods for querying the population."""

    @pytest.fixture
    def populated_manager(self, mock_geography):
        """Create a population manager with some people."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        # Create some people directly
        unit1 = mock_geography.get_unit('E00000001')
        unit2 = mock_geography.get_unit('E00000002')

        p1 = Person(age=10, sex='male', geographical_unit=unit1, activities=['school'])
        p2 = Person(age=25, sex='female', geographical_unit=unit1, activities=['work'])
        p3 = Person(age=65, sex='male', geographical_unit=unit2, activities=['leisure'])
        p4 = Person(age=30, sex='female', geographical_unit=unit2, activities=['work'])
        p5 = Person(age=5, sex='male', geographical_unit=unit1, activities=['home'])

        pop_manager.people = [p1, p2, p3, p4, p5]
        pop_manager.people_by_id = {p.id: p for p in pop_manager.people}

        # Add people to their units
        unit1.people = [p1, p2, p5]
        unit2.people = [p3, p4]

        return pop_manager

    def test_get_person(self, populated_manager):
        """Test retrieving person by ID."""
        person = populated_manager.get_person(0)

        assert person is not None
        assert person.id == 0

    def test_get_person_nonexistent(self, populated_manager):
        """Test retrieving nonexistent person returns None."""
        person = populated_manager.get_person(9999)

        assert person is None

    def test_get_all_people(self, populated_manager):
        """Test retrieving all people."""
        all_people = populated_manager.get_all_people()

        assert isinstance(all_people, list)
        assert len(all_people) == 5

    def test_get_people_by_age_range(self, populated_manager):
        """Test filtering people by age range."""
        # Get people aged 20-40
        people = populated_manager.get_people_by_age_range(20, 40)

        assert len(people) == 2
        assert all(20 <= p.age <= 40 for p in people)

    def test_get_people_by_age_range_inclusive(self, populated_manager):
        """Test that age range is inclusive."""
        people = populated_manager.get_people_by_age_range(25, 30)

        assert len(people) == 2
        ages = [p.age for p in people]
        assert 25 in ages
        assert 30 in ages

    def test_get_people_by_age_range_none(self, populated_manager):
        """Test age range with no matches."""
        people = populated_manager.get_people_by_age_range(80, 100)

        assert len(people) == 0

    def test_get_people_by_sex(self, populated_manager):
        """Test filtering people by sex."""
        males = populated_manager.get_people_by_sex('male')
        females = populated_manager.get_people_by_sex('female')

        assert len(males) == 3
        assert len(females) == 2
        assert all(p.sex == 'male' for p in males)
        assert all(p.sex == 'female' for p in females)

    def test_get_people_by_activity(self, populated_manager):
        """Test filtering people by activity."""
        workers = populated_manager.get_people_by_activity('work')

        assert len(workers) == 2
        assert all(p.has_activity('work') for p in workers)

    def test_get_people_by_activity_none(self, populated_manager):
        """Test activity filter with no matches."""
        people = populated_manager.get_people_by_activity('shopping')

        assert len(people) == 0

    def test_get_people_by_geo_unit(self, populated_manager):
        """Test filtering people by geographical unit."""
        people_unit1 = populated_manager.get_people_by_geo_unit('E00000001')
        people_unit2 = populated_manager.get_people_by_geo_unit('E00000002')

        assert len(people_unit1) == 3
        assert len(people_unit2) == 2

    def test_get_people_by_geo_unit_nonexistent(self, populated_manager):
        """Test filtering by nonexistent geo unit."""
        people = populated_manager.get_people_by_geo_unit('INVALID')

        assert len(people) == 0


# ============================================================================
# Statistics Tests
# ============================================================================

class TestStatistics:
    """Test population statistics methods."""

    @pytest.fixture
    def populated_manager(self, mock_geography):
        """Create a population manager with some people."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        unit1 = mock_geography.get_unit('E00000001')

        people = [
            Person(age=10, sex='male', geographical_unit=unit1, activities=['school']),
            Person(age=20, sex='female', geographical_unit=unit1, activities=['work']),
            Person(age=30, sex='male', geographical_unit=unit1, activities=['work', 'leisure']),
            Person(age=40, sex='female', geographical_unit=unit1, activities=['work']),
            Person(age=50, sex='male', geographical_unit=unit1, activities=['leisure'])
        ]

        pop_manager.people = people
        pop_manager.people_by_id = {p.id: p for p in people}

        return pop_manager

    def test_get_statistics_empty_population(self, mock_geography):
        """Test statistics with empty population."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        stats = pop_manager.get_statistics()

        assert stats == {}

    def test_get_statistics_basic(self, populated_manager):
        """Test basic statistics calculation."""
        stats = populated_manager.get_statistics()

        assert stats['total_population'] == 5
        assert stats['mean_age'] == 30.0  # (10+20+30+40+50)/5
        assert stats['median_age'] == 30.0
        assert stats['min_age'] == 10
        assert stats['max_age'] == 50

    def test_get_statistics_sex_distribution(self, populated_manager):
        """Test sex distribution in statistics."""
        stats = populated_manager.get_statistics()

        assert 'sex_distribution' in stats
        assert stats['sex_distribution']['male'] == 3
        assert stats['sex_distribution']['female'] == 2

    def test_get_statistics_activity_counts(self, populated_manager):
        """Test activity counts in statistics."""
        stats = populated_manager.get_statistics()

        assert 'activity_counts' in stats
        assert stats['activity_counts']['work'] == 3
        assert stats['activity_counts']['leisure'] == 2
        assert stats['activity_counts']['school'] == 1


# ============================================================================
# Integration Tests
# ============================================================================

class TestPopulationManagerIntegration:
    """Integration tests for PopulationManager."""

    def test_full_workflow(self, mock_geography):
        """Test complete workflow from loading to querying."""
        # Create temporary demographics files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create simple demographics
            male_data = {
                'geo_unit': ['E00000001', 'E00000002'],
                '0': [2, 1],
                '25': [3, 2],
                '65': [1, 2]
            }
            male_df = pd.DataFrame(male_data)
            male_path = os.path.join(tmpdir, 'demographics_male.csv')
            male_df.to_csv(male_path, index=False)

            female_data = {
                'geo_unit': ['E00000001', 'E00000002'],
                '0': [1, 2],
                '25': [2, 3],
                '65': [2, 1]
            }
            female_df = pd.DataFrame(female_data)
            female_path = os.path.join(tmpdir, 'demographics_female.csv')
            female_df.to_csv(female_path, index=False)

            # Initialize and load
            pop_manager = PopulationManager(geography=mock_geography, data_dir=tmpdir)
            pop_manager.load_demographics_from_csv()
            pop_manager.generate_population()

            # Verify total population
            # Male: age 0: 2+1=3, age 25: 3+2=5, age 65: 1+2=3, total = 11
            # Female: age 0: 1+2=3, age 25: 2+3=5, age 65: 2+1=3, total = 11
            # Total = 22
            assert len(pop_manager) == 22

            # Verify age distribution
            babies = pop_manager.get_people_by_age_range(0, 0)
            assert len(babies) == 6  # Males: 2+1=3, Females: 1+2=3

            # Verify sex distribution
            males = pop_manager.get_people_by_sex('male')
            females = pop_manager.get_people_by_sex('female')
            assert len(males) == 11
            assert len(females) == 11

            # Verify statistics
            stats = pop_manager.get_statistics()
            assert stats['total_population'] > 0
            assert stats['min_age'] == 0
            assert stats['max_age'] == 65

    def test_len_after_population_generation(self, mock_geography):
        """Test __len__ returns correct count after generation."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                25: {'male': 5, 'female': 3}
            }
        }

        pop_manager.generate_population()

        assert len(pop_manager) == 8


# ============================================================================
# Edge Cases Tests
# ============================================================================

class TestPopulationManagerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_population_queries(self, mock_geography):
        """Test querying empty population."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        assert pop_manager.get_all_people() == []
        assert pop_manager.get_people_by_age_range(0, 100) == []
        assert pop_manager.get_people_by_sex('male') == []
        assert pop_manager.get_people_by_activity('work') == []

    def test_demographics_with_zero_counts(self, mock_geography):
        """Test demographics where some age/sex combinations have zero count."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                25: {'male': 0, 'female': 5}
            }
        }

        pop_manager.generate_population()

        # Should only create 5 people (the females)
        assert len(pop_manager.people) == 5
        assert all(p.sex == 'female' for p in pop_manager.people)

    def test_single_person_population(self, mock_geography):
        """Test population with single person."""
        pop_manager = PopulationManager(geography=mock_geography, data_dir="data/population")

        pop_manager.precise_demographics = {
            'E00000001': {
                42: {'male': 1}
            }
        }

        pop_manager.generate_population()

        assert len(pop_manager.people) == 1
        assert pop_manager.people[0].age == 42
        assert pop_manager.people[0].sex == 'male'

        # Statistics should still work
        stats = pop_manager.get_statistics()
        assert stats['total_population'] == 1
        assert stats['mean_age'] == 42
