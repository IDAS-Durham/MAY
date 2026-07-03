import logging

from may.geography import VenueManager, Venue, Geography
from may.geography import GeographicalUnit
from may.population import Person

import pytest

logger = logging.getLogger(__name__)

@pytest.fixture
def geo():
    """Create a minimal geography with 4 units (enough for all tests)."""
    geography = Geography(levels=["SGU", "MGU"])
    units = [
        GeographicalUnit(id=i, name=f'E0000{i}', level='SGU',
                         coordinates=(51.5 + i*0.01, -0.1 - i*0.01))
        for i in range(4)
    ]
    for u in units:
        geography.units[u.name] = u
        geography.units_by_id[u.id] = u
        geography.units_by_level['SGU'][u.name] = u
    return geography


@pytest.fixture
def venues(geo):
    # Create venue manager without loading from CSV
    logger.info("")
    logger.info("Creating venues programmatically...")
    venues = VenueManager(geography=geo, filter_by_geography=False)

    # Get geographical units for venues (using first available units)
    geo_units = list(geo.get_all_units().values())
    if len(geo_units) < 4:
        raise ValueError("Test requires at least 4 geographical units")

    # Create care homes (3 expected)
    for i, name in enumerate(['Riverside Care Home', 'Sunset Care Home', 'Oakwood Care Home']):
        venue = Venue(
            name=name,
            venue_type='care_home',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.5 + i*0.01, -0.4 + i*0.05),
            properties={'resident_capacity': 50 + i*10, 'staff_count': 35 + i*5}
        )
        venues.add_venue(venue)

    # Create companies (4 expected)
    for i, name in enumerate(['Tech Corp Office', 'Finance Ltd HQ', 'Manufacturing Co', 'Retail Solutions']):
        venue = Venue(
            name=name,
            venue_type='company',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.5 + i*0.01, -0.15 + i*0.02),
            properties={'employee_count': 100 + i*50, 'office_space_sqm': 2000 + i*1000}
        )
        venues.add_venue(venue)

    # Create hospitals (3 expected)
    for i, name in enumerate(['St Mary\'s Hospital', 'Royal London Hospital', 'City General Hospital']):
        venue = Venue(
            name=name,
            venue_type='hospital',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.52 + i*0.01, -0.16 + i*0.05),
            properties={'beds': 300 + i*100, 'icu_beds': 25 + i*10}
        )
        venues.add_venue(venue)

    # Create prisons (2 expected)
    for i, name in enumerate(['City Prison', 'Northern Detention Center']):
        venue = Venue(
            name=name,
            venue_type='prison',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.54 + i*0.01, -0.12 + i*0.05),
            properties={'prisoner_capacity': 1000 + i*200, 'staff': 300 + i*50}
        )
        venues.add_venue(venue)

    # Create schools (4 expected)
    for i, name in enumerate(['Springfield Primary', 'Oakwood Secondary', 'Riverside Primary', 'Greenfield Secondary']):
        venue = Venue(
            name=name,
            venue_type='school',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.53 + i*0.01, -0.13 + i*0.03),
            properties={'student_capacity': 400 + i*200, 'staff_count': 35 + i*20}
        )
        venues.add_venue(venue)

    # Create universities (2 expected)
    for i, name in enumerate(['University College', 'City Technical University']):
        venue = Venue(
            name=name,
            venue_type='university',
            geographical_unit=geo_units[i % len(geo_units)],
            coordinates=(51.52 + i*0.01, -0.13 + i*0.05),
            properties={'student_capacity': 10000 + i*5000, 'staff_count': 2000 + i*500}
        )
        venues.add_venue(venue)

    # Note: 'vampire castle' and 'narnia' are intentionally not created (0 expected)

    return venues


@pytest.mark.parametrize("venue_type, expected_num, result", [
    ('care_home', 3, True),
    ('care_home', 4, False),    
    ('company', 4, True),
    ('company', 2, False),
    ('company', -1, False),        
    ('hospital', 3, True),
    ('hospital', 0, False),
    ('hospital', 1, False),
    ('hospital', 7, False),            
    ('prison', 2, True),
    ('school', 4, True),
    ('university',2, True),
    ('vampire castle',0, True),
    ('vampire castle',1, False),    
    ('narnia', 0, True),
    ('narnia', 2, False)    
])
def test_venue_numbers_correct(venue_type, expected_num, result, venues):
    assert (len(venues.get_venues_by_type(venue_type)) == expected_num) == result

def test_venues_are_venues(venues):
    for v in venues.get_all_venues_list():
        assert isinstance(v, Venue)
        assert isinstance(v.name, str)


def test_venue_has_correct_properties(venues):
    """Test that venues have correct basic properties"""
    hospital = venues.get_venue('St Mary\'s Hospital')

    assert hospital.name == 'St Mary\'s Hospital'
    assert hospital.type == 'hospital'
    assert hospital.coordinates == (51.52, -0.16)
    assert hospital.properties['beds'] == 300
    assert hospital.properties['icu_beds'] == 25


def test_venue_coordinates(venues):
    """Test venue coordinate handling"""
    # Test venue with coordinates
    care_home = venues.get_venue('Riverside Care Home')
    assert care_home.coordinates is not None
    assert len(care_home.coordinates) == 2
    assert isinstance(care_home.coordinates[0], float)
    assert isinstance(care_home.coordinates[1], float)


def test_venue_properties_dict(venues):
    """Test that venue properties are stored correctly"""
    company = venues.get_venue('Tech Corp Office')

    assert 'employee_count' in company.properties
    assert 'office_space_sqm' in company.properties
    assert company.properties['employee_count'] == 100
    assert company.properties['office_space_sqm'] == 2000


def test_venue_geographical_unit(venues):
    """Test that venues are correctly associated with geographical units"""
    prison = venues.get_venue('City Prison')

    assert prison.geographical_unit is not None
    assert hasattr(prison.geographical_unit, 'name')


def test_venue_id_uniqueness(venues):
    """Test that all venues have unique IDs"""
    venue_ids = [v.id for v in venues.get_all_venues_list()]

    assert len(venue_ids) == len(set(venue_ids)), "Venue IDs should be unique"


def test_venue_properties_default_empty_dict(geo):
    """Test that venue properties defaults to empty dict when not provided"""
    geo_units = list(geo.get_all_units().values())
    venue = Venue(
        name='Test Venue',
        venue_type='test',
        geographical_unit=geo_units[0]
    )

    assert venue.properties == {}


def test_venue_subsets_default_empty_dict(geo):
    """Test that venue subsets defaults to empty dict when not provided"""
    geo_units = list(geo.get_all_units().values())
    venue = Venue(
        name='Test Venue',
        venue_type='test',
        geographical_unit=geo_units[0]
    )

    assert venue.subsets == {}


def test_venue_repr(venues):
    """Test venue string representation"""
    hospital = venues.get_venue('St Mary\'s Hospital')
    repr_str = repr(hospital)

    assert 'St Mary\'s Hospital' in repr_str
    assert 'hospital' in repr_str
    assert 'Venue' in repr_str


def test_venue_equality_same_venue(geo):
    """Test that the same venue equals itself"""
    geo_units = list(geo.get_all_units().values())
    venue = Venue(
        name='Test Venue',
        venue_type='test',
        geographical_unit=geo_units[0],
        coordinates=(51.5, -0.1),
        properties={'capacity': 100}
    )

    assert venue == venue


def test_venue_num_members_empty(venues):
    """Test num_members property when venue has no subsets"""
    hospital = venues.get_venue('St Mary\'s Hospital')

    # No subsets added yet, should be 0
    assert hospital.num_members == 0


def test_get_venue_by_name(venues):
    """Test retrieving venues by name"""
    hospital = venues.get_venue('St Mary\'s Hospital')

    assert hospital is not None
    assert hospital.name == 'St Mary\'s Hospital'
    assert hospital.type == 'hospital'


def test_get_venue_nonexistent(venues):
    """Test retrieving nonexistent venue returns None"""
    result = venues.get_venue('Nonexistent Venue')

    assert result is None


def test_get_venue_by_type_and_id(venues):
    """Test retrieving venues by type and ID"""
    hospital = venues.get_venue('St Mary\'s Hospital')
    hospital_id = hospital.id

    retrieved = venues.get_venue_by_type_and_id('hospital', hospital_id)

    assert retrieved is not None
    assert retrieved.id == hospital_id
    assert retrieved.name == 'St Mary\'s Hospital'


def test_get_venue_by_type_and_id_nonexistent(venues):
    """Test retrieving nonexistent venue type/ID returns None"""
    result = venues.get_venue_by_type_and_id('hospital', 999999999)

    assert result is None


def test_get_venues_by_type(venues):
    """Test retrieving venues by type"""
    hospitals = venues.get_venues_by_type('hospital')

    assert len(hospitals) == 3
    assert all(v.type == 'hospital' for v in hospitals)


def test_get_venues_by_nonexistent_type(venues):
    """Test retrieving venues of nonexistent type returns empty"""
    result = venues.get_venues_by_type('dragon_lair')

    assert not result


def test_get_all_venues_list(venues):
    """Test retrieving all venues as a list"""
    all_venues = venues.get_all_venues_list()

    assert isinstance(all_venues, list)
    assert len(all_venues) == 18  # 3+4+3+2+4+2 = 18 total venues
    assert any(v.name == 'St Mary\'s Hospital' for v in all_venues)


def test_get_venue_types(venues):
    """Test retrieving list of all venue types"""
    types = venues.get_venue_types()

    assert isinstance(types, list)
    assert 'hospital' in types
    assert 'school' in types
    assert 'care_home' in types
    assert 'company' in types
    assert 'prison' in types
    assert 'university' in types
    assert len(types) == 6


def test_add_venue_updates_all_dicts(geo):
    """Test that add_venue properly updates all internal data structures"""
    manager = VenueManager(geography=geo, filter_by_geography=False)
    geo_units = list(geo.get_all_units().values())

    venue = Venue(
        name='New Hospital',
        venue_type='hospital',
        geographical_unit=geo_units[0],
        coordinates=(51.5, -0.1),
        properties={'beds': 200}
    )

    manager.add_venue(venue)

    # Check venues_by_type_and_id dict
    assert venue.id in manager.venues_by_type_and_id['hospital']
    assert manager.venues_by_type_and_id['hospital'][venue.id] == venue

    # Check venues_by_type lookup
    assert 'hospital' in manager.get_venue_types()
    assert venue in manager.get_venues_by_type('hospital')


def test_extend_combines_venue_managers(geo):
    """Test that extend properly combines two VenueManagers"""
    manager1 = VenueManager(geography=geo, filter_by_geography=False)
    manager2 = VenueManager(geography=geo, filter_by_geography=False)

    geo_units = list(geo.get_all_units().values())

    # Add venue to manager1
    venue1 = Venue(
        name='Hospital A',
        venue_type='hospital',
        geographical_unit=geo_units[0],
        properties={'beds': 100}
    )
    manager1.add_venue(venue1)

    # Add venue to manager2
    venue2 = Venue(
        name='Hospital B',
        venue_type='hospital',
        geographical_unit=geo_units[0],
        properties={'beds': 200}
    )
    manager2.add_venue(venue2)

    # Extend manager1 with manager2
    manager1.extend(manager2)

    # Check that both venues are now in manager1
    assert len(manager1.get_venues_by_type('hospital')) == 2
    hospital_ids = {v.id for v in manager1.get_venues_by_type('hospital')}
    assert venue1.id in hospital_ids
    assert venue2.id in hospital_ids


def test_venue_manager_repr(venues):
    """Test VenueManager string representation"""
    repr_str = repr(venues)

    assert 'VenueManager' in repr_str
    assert '18 venues' in repr_str
    assert '6 types' in repr_str


def test_get_capacity_for_attributes_no_config(venues):
    """Test get_capacity_for_attributes returns 0 when no capacity config"""
    hospital = venues.get_venue('St Mary\'s Hospital')

    # No capacity config, should return 0
    capacity = hospital.get_capacity_for_attributes(None, age=85, sex='male')
    assert capacity == 0


def test_get_capacity_for_attributes_with_config(geo):
    """Test get_capacity_for_attributes with proper config"""
    geo_units = list(geo.get_all_units().values())

    # Create a venue with age/sex capacity properties
    venue = Venue(
        name='Test Care Home',
        venue_type='care_home',
        geographical_unit=geo_units[0],
        properties={
            'age_65_84_male': 20,
            'age_65_84_female': 25,
            'age_85_94_male': 15,
            'age_85_94_female': 18
        }
    )

    # Create capacity config
    capacity_config = {
        'attribute_capacities': {
            'column_mappings': {
                'age_65_84_male': {'age_band': [65, 84], 'sex': 'male'},
                'age_65_84_female': {'age_band': [65, 84], 'sex': 'female'},
                'age_85_94_male': {'age_band': [85, 94], 'sex': 'male'},
                'age_85_94_female': {'age_band': [85, 94], 'sex': 'female'}
            }
        }
    }

    # Test different age/sex combinations
    assert venue.get_capacity_for_attributes(capacity_config, age=75, sex='male') == 20
    assert venue.get_capacity_for_attributes(capacity_config, age=75, sex='female') == 25
    assert venue.get_capacity_for_attributes(capacity_config, age=90, sex='male') == 15
    assert venue.get_capacity_for_attributes(capacity_config, age=90, sex='female') == 18


def test_get_capacity_for_attributes_no_match(geo):
    """Test get_capacity_for_attributes returns 0 when no matching column"""
    geo_units = list(geo.get_all_units().values())

    venue = Venue(
        name='Test Care Home',
        venue_type='care_home',
        geographical_unit=geo_units[0],
        properties={
            'age_65_84_male': 20
        }
    )

    capacity_config = {
        'attribute_capacities': {
            'column_mappings': {
                'age_65_84_male': {'age_band': [65, 84], 'sex': 'male'}
            }
        }
    }

    # Age out of range
    assert venue.get_capacity_for_attributes(capacity_config, age=50, sex='male') == 0

    # Wrong sex
    assert venue.get_capacity_for_attributes(capacity_config, age=75, sex='female') == 0


def test_get_capacity_config(venues):
    """Test retrieving capacity config for venue type"""
    # No capacity configs set in fixture
    config = venues.get_capacity_config('hospital')
    assert config is None


def test_get_capacity_config_with_stored_config(geo):
    """Test capacity config storage and retrieval"""
    manager = VenueManager(geography=geo, filter_by_geography=False)

    test_config = {
        'attribute_capacities': {
            'column_mappings': {
                'age_65_84_male': {'age_band': [65, 84], 'sex': 'male'}
            }
        }
    }

    manager.capacity_configs['care_home'] = test_config

    retrieved = manager.get_capacity_config('care_home')
    assert retrieved == test_config


# ============================================================================
# add_to_subset Tests
# ============================================================================

def test_add_to_subset_records_multiple_distinct_subsets_at_same_venue(geo):
    """A person added to two distinct subsets of the same venue, under the
    same activity_name/activity_type, should end up with both subsets in
    their activity_map list (not just the first, deduped-by-venue-id)."""
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Fair Ground', venue_type='Fair', geographical_unit=geo_unit, properties={})
    person = Person(age=30, sex='male', geographical_unit=geo_unit)

    venue.add_to_subset(person, subset_key='feast_1', activity_name='Fair', activity_type='Fair')
    venue.add_to_subset(person, subset_key='feast_2', activity_name='Fair', activity_type='Fair')

    recorded_subsets = person.activity_map['Fair']['Fair']
    assert len(recorded_subsets) == 2
    assert {subset.subset_name for subset in recorded_subsets} == {'feast_1', 'feast_2'}


def test_add_to_subset_does_not_duplicate_the_same_subset(geo):
    """Re-adding the same person to the same subset twice should not create
    a duplicate entry in their activity_map list."""
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Fair Ground', venue_type='Fair', geographical_unit=geo_unit, properties={})
    person = Person(age=30, sex='male', geographical_unit=geo_unit)

    venue.add_to_subset(person, subset_key='feast_1', activity_name='Fair', activity_type='Fair')
    venue.add_to_subset(person, subset_key='feast_1', activity_name='Fair', activity_type='Fair')

    recorded_subsets = person.activity_map['Fair']['Fair']
    assert len(recorded_subsets) == 1


# ============================================================================
# get_all_members Tests
# ============================================================================

def test_get_all_members_default_returns_every_subset(geo):
    """Default behaviour (no filtering) must match existing callers' expectations."""
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Household 1', venue_type='household', geographical_unit=geo_unit, properties={})
    resident = Person(age=30, sex='male', geographical_unit=geo_unit)
    guest = Person(age=40, sex='female', geographical_unit=geo_unit)

    venue.add_to_subset(resident, subset_key='Adults', activity_name='residence', activity_type='household')
    venue.add_to_subset(guest, subset_key='guest', activity_name='Fair_accommodation', activity_type='Fair')

    assert set(venue.get_all_members()) == {resident, guest}


def test_get_all_members_exclude_subset_keys_skips_named_subset(geo):
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Household 1', venue_type='household', geographical_unit=geo_unit, properties={})
    resident = Person(age=30, sex='male', geographical_unit=geo_unit)
    guest = Person(age=40, sex='female', geographical_unit=geo_unit)

    venue.add_to_subset(resident, subset_key='Adults', activity_name='residence', activity_type='household')
    venue.add_to_subset(guest, subset_key='guest', activity_name='Fair_accommodation', activity_type='Fair')

    assert venue.get_all_members(exclude_subset_keys=['guest']) == [resident]


def test_get_all_members_include_subset_keys_restricts_to_named_subset(geo):
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Household 1', venue_type='household', geographical_unit=geo_unit, properties={})
    resident = Person(age=30, sex='male', geographical_unit=geo_unit)
    guest = Person(age=40, sex='female', geographical_unit=geo_unit)

    venue.add_to_subset(resident, subset_key='Adults', activity_name='residence', activity_type='household')
    venue.add_to_subset(guest, subset_key='guest', activity_name='Fair_accommodation', activity_type='Fair')

    assert venue.get_all_members(include_subset_keys=['guest']) == [guest]


def test_get_all_members_exclude_and_include_are_mutually_exclusive(geo):
    geo_unit = list(geo.get_all_units().values())[0]
    venue = Venue(name='Household 1', venue_type='household', geographical_unit=geo_unit, properties={})

    with pytest.raises(ValueError):
        venue.get_all_members(exclude_subset_keys=['guest'], include_subset_keys=['Adults'])


# ============================================================================
# migrate_subsets_to Tests
# ============================================================================

def test_migrate_subsets_to_moves_residence_type_and_activity_map(geo):
    """Migrating a household's subsets to a care_home must move the person's
    activity_map entries from 'household' to 'care_home', with no stale
    entries left under the old type."""
    geo_unit = list(geo.get_all_units().values())[0]
    old_venue = Venue(name='Old House', venue_type='household', geographical_unit=geo_unit, properties={'is_residence': True})
    new_venue = Venue(name='Care Home', venue_type='care_home', geographical_unit=geo_unit, properties={'is_residence': True})
    resident = Person(age=80, sex='female', geographical_unit=geo_unit)

    old_venue.add_to_subset(resident, subset_key='residents', activity_name='residence', activity_type='household')

    old_venue.migrate_subsets_to(new_venue)

    assert old_venue.subsets == {}
    assert 'residents' in new_venue.subsets
    moved_subset = new_venue.subsets['residents']
    assert moved_subset.venue is new_venue

    assert 'household' not in resident.activity_map['residence']
    assert resident.activity_map['residence']['care_home'] == [moved_subset]


def test_migrate_subsets_to_only_touches_migrated_venues_subset(geo):
    """A person resident at venue A and a guest at venue B (same type) —
    migrating A must not disturb B's entry."""
    geo_unit = list(geo.get_all_units().values())[0]
    venue_a = Venue(name='House A', venue_type='household', geographical_unit=geo_unit, properties={})
    venue_b = Venue(name='House B', venue_type='household', geographical_unit=geo_unit, properties={})
    new_venue = Venue(name='Care Home', venue_type='care_home', geographical_unit=geo_unit, properties={})
    person = Person(age=40, sex='male', geographical_unit=geo_unit)

    venue_a.add_to_subset(person, subset_key='residents', activity_name='residence', activity_type='household')
    venue_b.add_to_subset(person, subset_key='guests', activity_name='visiting', activity_type='household')

    venue_a.migrate_subsets_to(new_venue)

    assert venue_a.subsets == {}
    resident_subset_moved = new_venue.subsets['residents']
    assert resident_subset_moved.venue is new_venue
    assert person.activity_map['residence']['care_home'] == [resident_subset_moved]

    # venue B's subset is untouched.
    guest_subset = venue_b.subsets['guests']
    assert person.activity_map['visiting']['household'] == [guest_subset]


def test_migrate_subsets_to_preserves_activity_type_override_key(geo):
    """A subset registered under an activity_type override unrelated to
    venue.type (e.g. Fair attendance) must keep its override key after
    migration, not get remapped to the new venue's type."""
    geo_unit = list(geo.get_all_units().values())[0]
    old_venue = Venue(name='Fair Ground', venue_type='fair', geographical_unit=geo_unit, properties={})
    new_venue = Venue(name='New Fair Ground', venue_type='fair_relocated', geographical_unit=geo_unit, properties={})
    attendee = Person(age=25, sex='female', geographical_unit=geo_unit)

    old_venue.add_to_subset(attendee, subset_key='feast_1', activity_name='Fair', activity_type='Fair')

    old_venue.migrate_subsets_to(new_venue)

    moved_subset = new_venue.subsets['feast_1']
    # Key preserved as 'Fair' (the override), not remapped to 'fair_relocated'.
    assert attendee.activity_map['Fair']['Fair'] == [moved_subset]
    assert 'fair_relocated' not in attendee.activity_map['Fair']


def test_migrate_subsets_to_raises_on_subset_key_collision(geo):
    geo_unit = list(geo.get_all_units().values())[0]
    old_venue = Venue(name='Old House', venue_type='household', geographical_unit=geo_unit, properties={})
    new_venue = Venue(name='New House', venue_type='household', geographical_unit=geo_unit, properties={})
    person_a = Person(age=30, sex='male', geographical_unit=geo_unit)
    person_b = Person(age=35, sex='female', geographical_unit=geo_unit)

    old_venue.add_to_subset(person_a, subset_key='residents', activity_name='residence', activity_type='household')
    new_venue.add_to_subset(person_b, subset_key='residents', activity_name='residence', activity_type='household')

    with pytest.raises(ValueError):
        old_venue.migrate_subsets_to(new_venue)


def test_migrate_subsets_to_reassigns_subset_index_to_avoid_collision(geo):
    """subset_index must stay unique within new_venue — migrating a subset
    whose old index collides with one already present must be reassigned."""
    geo_unit = list(geo.get_all_units().values())[0]
    old_venue = Venue(name='Old House', venue_type='household', geographical_unit=geo_unit, properties={})
    new_venue = Venue(name='New House', venue_type='household', geographical_unit=geo_unit, properties={})
    person_a = Person(age=30, sex='male', geographical_unit=geo_unit)
    person_b = Person(age=35, sex='female', geographical_unit=geo_unit)

    # Both venues' first subset gets index 0 (per add_to_subset's len()-based assignment).
    old_venue.add_to_subset(person_a, subset_key='old_residents', activity_name='residence', activity_type='household')
    new_venue.add_to_subset(person_b, subset_key='existing_residents', activity_name='residence', activity_type='household')

    assert old_venue.subsets['old_residents'].subset_index == 0
    assert new_venue.subsets['existing_residents'].subset_index == 0

    old_venue.migrate_subsets_to(new_venue)

    indices = [s.subset_index for s in new_venue.subsets.values()]
    assert len(indices) == len(set(indices)), "subset_index must stay unique within new_venue"


