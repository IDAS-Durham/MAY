import logging
import random
import numpy as np
import numba as nb
import yaml

from may.config_loader import setup_default_geography
from may.geography import VenueManager
from may.geography import Venue
from may.world import World
from may.population import Person
import may.geography
from may.population import PopulationManager

import pytest

# import sys
# from pathlib import Path
# project_root = Path(__file__).parent.parent.parent
# print(project_root)
# sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

@pytest.fixture
def geo():
    # Load config file
    with open("may/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Setup geography from config and command-line arguments
    geo, filters = setup_default_geography()

    # Load the geography data
    geo.load_from_csv()
    return geo


@pytest.fixture
def venues(geo):
    # Load venues
    logger.info("")
    logger.info("Loading venues...")
    venues = VenueManager(geography=geo, data_dir="tests/test_units/may/geography/data")
    venues.load_from_csv()
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
    assert (len(venues.venues_by_type[venue_type]) == expected_num) == result

def test_venues_are_venues(venues):
    for name,v in venues.venues.items():
        assert isinstance(v, Venue)
        assert isinstance(name, str)


