"""
Shared test infrastructure for venue_distributor unit tests.

Uses real domain objects (Person, Venue, GeographicalUnit) with
minimal configuration. No mocks.
"""

import pytest
from may.population.person import Person
from may.geography.venue import Venue
from may.geography.geographical_unit import GeographicalUnit
from may.venue_distributor.venue_distributor import VenueDistributor


# ==============================================================================
# Lightweight World (real interface, no heavy dependencies)
# ==============================================================================

class SimpleWorld:
    """
    Minimal world that satisfies the venue_distributor interface
    (world.people, world.venues_by_type) without VenueManager/PopulationManager.
    """
    def __init__(self, people=None, venues_map=None):
        self._people = people or []
        self._venues_map = venues_map or {}

    @property
    def people(self):
        return self._people

    def venues_by_type(self, venue_type):
        return self._venues_map.get(venue_type, [])


# ==============================================================================
# Factory helpers — all produce real domain objects
# ==============================================================================

_geo_id_counter = 0


def make_geo(name='SGU_1', coordinates=(51.5, -0.1), level='SGU'):
    global _geo_id_counter
    _geo_id_counter += 1
    return GeographicalUnit(id=_geo_id_counter, name=name, level=level, coordinates=coordinates)


def make_person(geo=None, age=30, sex='male', properties=None):
    return Person(age=age, sex=sex, geographical_unit=geo, properties=properties)


def make_venue(name='venue_0', geo=None, venue_type='school', coordinates=None, properties=None):
    coords = coordinates or (geo.coordinates if geo else None)
    return Venue(name=name, venue_type=venue_type, geographical_unit=geo,
                 coordinates=coords, properties=properties)


def make_residence(name='household_0', geo=None, residence_type='household',
                   properties=None, coordinates=None):
    """Create a residence venue. is_residence=True so Venue.add_to_subset works."""
    props = properties or {}
    props['is_residence'] = True
    return Venue(name=name, venue_type=residence_type, geographical_unit=geo,
                 coordinates=coordinates, properties=props)


def assign_residence(person, residence_venue):
    """Put a person into a residence so person.residence returns the venue."""
    residence_venue.add_to_subset(
        person, subset_key='residents',
        activity_name='residence',
        activity_type=residence_venue.type
    )


def make_distributor_config(**overrides):
    """Minimal VenueDistributor config dict. Overrides are shallow-merged per key."""
    config = {
        'venue_type': 'school',
        'activity_map_key': 'primary_activity',
        'subset_key': 'student',
        'activity_type': 'education',
        'settings': {'verbose': False, 'use_spatial_index': True},
        'venue_selection': {
            'venue_geo_level': 'SGU',
            'batch_geo_level': 'SGU',
            'consider_by': 'count',
            'count': 5,
            'max_distance': 10,
            'person_location_source': 'geographical_unit.coordinates',
        },
        'allocation': {
            'track_capacity': True,
            'when_full': 'exclude',
            'fixed_capacity': 100,
            'strategy': 'closest',
        },
        'eligibility': {
            'global_filters': [],
            'attributes': [],
            'exclude': {},
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and key in config and isinstance(config[key], dict):
            config[key] = {**config[key], **val}
        else:
            config[key] = val
    return config


def make_vd(**config_kw):
    """Create a real VenueDistributor from a minimal config dict."""
    cfg = make_distributor_config(**config_kw)
    vd = VenueDistributor(config_dict=cfg)
    vd.world = SimpleWorld()
    vd.allocated_this_run = 0
    return vd


def build_world(vd, people, venues):
    """
    Wire a VenueDistributor to a minimal world with real spatial indices.
    Call this after creating people and venues to prepare the VD for allocation.
    """
    world = SimpleWorld(people=people, venues_map={vd.venue_type: venues})
    vd.world = world
    vd.venue_ids = {id(v) for v in venues}
    if venues:
        vd._build_spatial_indices({vd.venue_type: venues})
        vd.matcher.build_attribute_index(venues)
    return world


# ==============================================================================
# Autouse Fixtures
# ==============================================================================

@pytest.fixture(autouse=True)
def reset_person_ids():
    Person.reset_counter()
    yield


@pytest.fixture(autouse=True)
def reset_geo_id_counter():
    global _geo_id_counter
    _geo_id_counter = 0
    yield
