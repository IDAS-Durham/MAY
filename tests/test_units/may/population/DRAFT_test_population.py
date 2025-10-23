import logging
import random
import sys
import numpy as np
import numba as nb
import yaml
from may.config_loader import setup_default_geography
from may.geography import VenueManager
from may.world import World

from may.distributor.distributor_pop_to_venue import Distributor
from may.population import Person
import may.geography
from may.population import PopulationManager

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture
def config():
    with open("may/config.yaml", "r") as f:
        cnfg = yaml.safe_load(f)
    return cnfg

@pytest.fixture
def geo(config):
    # Setup geography from config and command-line arguments
    geo, filters = setup_default_geography()

    # Load the geography data
    geo.load_from_csv()
    return geo

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

def test_population_is_persons(population):
    for p in population.people:
        assert isinstance(p, Person)

def test_population_size(population):
    total_male = 46234
    total_female = 48997
    total = total_male+total_female
    assert len(population.get_people_by_sex('male')) == total_male
    assert len(population.get_people_by_sex('female')) == total_female    
    assert len(population.people) == total

def test_population_max_age(population):
    minage, maxage = 100, 0
    for p in population.people:
        if p.age < minage:
            minage = p.age
        if p.age > maxage:
            maxage = p.age
    assert minage < maxage
    assert minage >= 0
    assert maxage <= 150

@pytest.mark.parametrize("minage, maxage, number, result", [
    (0, 101, 46234+48997, True)
])
def test_age_range_breakdown(population, minage, maxage, number, result):
    assert (len(population.get_people_by_age_range(minage, maxage))==number) == result

