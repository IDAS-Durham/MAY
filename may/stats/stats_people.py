import numpy as np
from scipy import stats
import logging
import random

from .statmaker import StatMaker

logger = logging.getLogger("statsvenues")

class StatMakerPop(StatMaker):
    """Class to collect and print some stuff about a list of Person objects. 

    """
    def __init__(self, people):
        super().__init__()
        self.people = people


    def get_sex_breakdown(self):
        num_male, num_female, total = 0,0,0
        for person in self.people:
            total += 1
            if person.sex == 'male':
                num_male += 1
            if person.sex == 'female':
                num_female += 1
        logger.info(f"    Total {total} : {num_male} male, {num_female} female")
        
    def get_age_group_breakdown(self):
        breakdown = np.zeros(4)
        for person in self.people:
            if person.age < 18:
                breakdown[0] += 1
            elif person.age < 25:
                breakdown[1] += 1
            elif person.age < 60:
                breakdown[2] += 1
            else:
                breakdown[3] += 1
        logger.info(f"    Number       age < 18 : {breakdown[0]}")
        logger.info(f"    Number 18 <= age < 25 : {breakdown[1]}")
        logger.info(f"    Number 25 <= age < 60 : {breakdown[2]}")
        logger.info(f"    Number 60 <= Age      : {breakdown[3]}")        

    def get_age_stats(self):
        ages = np.zeros(len(self.people))
        for i,person in enumerate(self.people):
            ages[i] = person.age
        return self.collect_statistics(ages)

        
        
