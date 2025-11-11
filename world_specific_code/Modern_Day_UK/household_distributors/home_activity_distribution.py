import os
import time
import logging
import random
import sys
import numpy as np
import numba as nb
import yaml
import joblib
from may.config_loader import setup_geography
from may.geography import VenueManager
from may.population import PopulationManager
from may.world import World
from world_specific_code.Modern_Day_UK.household_distributors import HouseholdDistributor, HouseholdSubsetDistributor, HouseholdManager
from world_specific_code.Modern_Day_UK.care_home_distributor import CareHomeDistributor, CareHomeSubsetDistributor
from world_specific_code.Modern_Day_UK.student_dorms import StudentDormDistributor, StudentDormSubsetDistributor
from world_specific_code.Modern_Day_UK.prisons import PrisonDistributor, PrisonSubsetDistributor

from may.stats import StatMakerVenues, StatMaker, StatMakerPop, print_world_examples

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)



def assign_home_activity(geo, venues):
    
    # Distribute people to households by smallest geographical unit.
    smallest_geo_unit_dict = geo.units_by_level[geo.levels[0]]
    
    logger.info("Allocating people to venues geo-unit by geo-unit...")
    i, printed, num_geo_units = 0, set(), len(smallest_geo_unit_dict)
    for geo_unit in smallest_geo_unit_dict.values():
        still_unallocated_people = geo_unit.people

        # Distribute people to Student Dorms
        potential_venues = geo_unit.get_venues_by_type('student_dorm')
        if potential_venues:
            logger.debug(f"Doing student dorm {potential_venues[0].name} in {potential_venues[0].geographical_unit.name}")
            student_dorm_distributor = StudentDormDistributor(
                'student_dorm',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues
            )
            student_dorm_distributor.assign_people_venues(
                'home',
                'student_dorm',
                people=still_unallocated_people
            )
            still_unallocated_people = student_dorm_distributor.unallocated_people

        # Distribute people to Care Homes
        potential_venues = geo_unit.get_venues_by_type('care_home')
        if potential_venues:
            logger.debug(f"Doing care home {potential_venues[0].name} in {potential_venues[0].geographical_unit.name}")            
            care_home_distributor = CareHomeDistributor(
                'care_home',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues
            )
            care_home_distributor.assign_people_venues(
                'home',
                'care_home',
                people=still_unallocated_people
            )
            still_unallocated_people = care_home_distributor.unallocated_people
        
        # Distribute people to Households with expansion
        potential_venues = geo_unit.get_venues_by_type('household')
        if potential_venues:
            household_distributor = HouseholdDistributor(
                'household',
                venues,
                still_unallocated_people,
                potential_venues=geo_unit.get_venues_by_type('household')
            )
            # Use multi-pass assignment (configured in HouseholdDistributor._multi_pass_config)
            # Don't do too many passes, as will go through them again after allocating to prisons. 
            household_distributor.num_passes = 2
            household_distributor.assign_people_venues_multi_pass('home', 'household')
            still_unallocated_people = household_distributor.unallocated_people
        
        # Fill prisons
        potential_venues = geo_unit.parent.get_venues_by_type('prison')
        if potential_venues:
            prison_distributor = PrisonDistributor(
                'prison',
                venues,
                still_unallocated_people,
                potential_venues=potential_venues,
            )
            prison_distributor.assign_people_venues('home','prison')
            still_unallocated_people = prison_distributor.unallocated_people

        # Restart household distributor
        potential_venues = geo_unit.get_venues_by_type('household')
        if potential_venues and still_unallocated_people:
            household_distributor = HouseholdDistributor(
                'household',
                venues,
                still_unallocated_people,
                potential_venues=geo_unit.get_venues_by_type('household')
            )
            # Use multi-pass assignment (configured in HouseholdDistributor._multi_pass_config)
            # Don't do too many passes, as will go through them again after allocating to prisons. 
            household_distributor.num_passes = 5
            household_distributor.assign_people_venues_multi_pass('home',
                                                                  'household')
            still_unallocated_people = household_distributor.unallocated_people

            if household_distributor.allocation_rate < 99.999999:
                logger.info(f"--Low allocation rate of {household_distributor.allocation_rate:.1f}% in geo_unit {geo_unit.name}")
                logger.info(f"--Printing stats of unallocated people: ")
                my_statmaker = StatMakerPop(household_distributor.unallocated_people)
                my_statmaker.get_sex_breakdown()
                my_statmaker.get_age_group_breakdown()
                for p in household_distributor.unallocated_people:
                    logger.info(f"Person = {p}")
                # morestats = my_statmaker.get_age_stats()
                # for key, val in morestats.items():
                #     logger.info(f"    {key} : {val}")
                    
        i+=1
        percent=int(i/num_geo_units*100)
        milestone = (percent // 10) * 10
        if milestone not in printed and milestone % 10 == 0:
            logger.info(f"             ...{milestone}% complete")
            printed.add(milestone)
