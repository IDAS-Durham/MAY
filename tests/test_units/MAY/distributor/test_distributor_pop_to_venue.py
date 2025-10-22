import logging
import random
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.world import World

from may.distributor.distributor_pop_to_venue import Distributor
from may.population import Person
import may.geography
from may.population import PopulationManager

import pytest

logger = logging.getLogger(__name__)

##########################################################################
##########################################################################

# if os.environ.get('PYTHONHASHSEED') is None:
#     os.environ['PYTHONHASHSEED'] = '0'
#     os.execv(sys.executable, [sys.executable] + sys.argv)

# logger = logging.getLogger("create_world")
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     handlers=[
#         logging.StreamHandler(sys.stdout)
#     ]
# )

# # Suppress numexpr logging
# logging.getLogger('numexpr').setLevel(logging.WARNING)

# def set_random_seed(seed=999):
#     """
#     Sets global seeds for testing in numpy, random, and numbaised numpy.
#     """

#     @nb.njit(cache=True)
#     def set_seed_numba(seed):
#         random.seed(seed)
#         return np.random.seed(seed)

#     np.random.seed(seed)
#     set_seed_numba(seed)
#     random.seed(seed)
#     return

# set_random_seed(0)

##########################################################################
##########################################################################

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
    venues = VenueManager(geography=geo, data_dir="data/venues")
    venues.load_from_csv()
    return venues

@pytest.fixture
def population(config, geo):
    # Load population
    logger.info("")
    logger.info("Loading population...")
    pop_config = config.get("population", {})
    population = PopulationManager(
        geography=geo,
        data_dir=pop_config.get("data_dir", "data/population")
    )

    # Load demographic data
    male_file = pop_config.get("demographics_male_file", "demographics_male.csv")
    female_file = pop_config.get("demographics_female_file", "demographics_female.csv")
    population.load_demographics_from_csv(male_file, female_file)

    # Generate population
    population.generate_population()
    return population

# def test_Distributor_init():
#     # given.
#     venue_type, venue_manager, people =  venues, population.people
#     mydist = Distributor(venue_type, venue_manager, people)
#     assert
