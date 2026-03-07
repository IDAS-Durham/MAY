"""
Generate synthetic data for the Simple Test World.

Creates a world with:
- 1,000,000 people across 100 areas (SGUs)
- 10 regions (MGUs), each containing 10 areas
- Randomized ages (0-99) and sexes (50/50)
- Households of 5 people each
- 10 companies per region (100 total)
"""

import csv
import os
import random

random.seed(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

NUM_SGUS = 100
NUM_MGUS = 10
SGUS_PER_MGU = NUM_SGUS // NUM_MGUS
TOTAL_POPULATION = 1_000_000
POP_PER_SGU = TOTAL_POPULATION // NUM_SGUS  # 10,000
HOUSEHOLD_SIZE = 5
COMPANIES_PER_MGU = 10
NUM_AGES = 100  # ages 0-99

LGU_NAME = "TestLand"

sgus = [f"AREA_{i+1:03d}" for i in range(NUM_SGUS)]
mgus = [f"REGION_{i+1:02d}" for i in range(NUM_MGUS)]

sgu_to_mgu = {}
for i, sgu in enumerate(sgus):
    mgu_idx = i // SGUS_PER_MGU
    sgu_to_mgu[sgu] = mgus[mgu_idx]


def generate_geography():
    # hierarchy.csv
    path = os.path.join(DATA_DIR, "geography", "hierarchy.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SGU", "MGU", "LGU"])
        for sgu in sgus:
            writer.writerow([sgu, sgu_to_mgu[sgu], LGU_NAME])

    # coord_sgu.csv
    path = os.path.join(DATA_DIR, "geography", "coord_sgu.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SGU", "latitude", "longitude"])
        for i, sgu in enumerate(sgus):
            lat = 51.0 + (i // 10) * 0.1
            lon = -1.0 + (i % 10) * 0.1
            writer.writerow([sgu, f"{lat:.6f}", f"{lon:.6f}"])


def distribute_population(total, num_bins):
    """Distribute total evenly across bins with random noise, ensuring exact sum."""
    base = total // num_bins
    remainder = total - base * num_bins
    counts = [base] * num_bins
    for i in range(remainder):
        counts[i] += 1
    random.shuffle(counts)
    return counts


def generate_demographics():
    """Generate demographics CSVs with randomized age distributions."""
    header = ["geo_unit"] + [str(a) for a in range(NUM_AGES)]
    males_per_sgu = POP_PER_SGU // 2  # 5,000
    females_per_sgu = POP_PER_SGU - males_per_sgu  # 5,000

    for sex, total_per_sgu, filename in [
        ("male", males_per_sgu, "demographics_male.csv"),
        ("female", females_per_sgu, "demographics_female.csv"),
    ]:
        path = os.path.join(DATA_DIR, "population", filename)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for sgu in sgus:
                age_counts = distribute_population(total_per_sgu, NUM_AGES)
                writer.writerow([sgu] + age_counts)


def generate_households():
    """Generate household composition CSV. Single pattern: 5 people per household."""
    path = os.path.join(DATA_DIR, "households", "households.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["geo_unit", "5"])
        for sgu in sgus:
            num_households = POP_PER_SGU // HOUSEHOLD_SIZE
            writer.writerow([sgu, num_households])


def generate_companies():
    """Generate 10 companies per MGU region."""
    path = os.path.join(DATA_DIR, "venues", "companies.csv")
    pop_per_mgu = POP_PER_SGU * SGUS_PER_MGU  # 100,000
    capacity_per_company = pop_per_mgu // COMPANIES_PER_MGU  # 10,000

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["geo_unit", "name", "employee_count"])
        company_idx = 0
        for mgu in mgus:
            # Place companies in the first SGU of each MGU for simplicity
            first_sgu = sgus[mgus.index(mgu) * SGUS_PER_MGU]
            for j in range(COMPANIES_PER_MGU):
                writer.writerow([
                    first_sgu,
                    f"Company_{company_idx:03d}",
                    capacity_per_company,
                ])
                company_idx += 1


if __name__ == "__main__":
    print("Generating Simple Test World data...")
    print(f"  Population: {TOTAL_POPULATION:,}")
    print(f"  Areas (SGUs): {NUM_SGUS}")
    print(f"  Regions (MGUs): {NUM_MGUS}")
    print(f"  People per area: {POP_PER_SGU:,}")
    print(f"  Household size: {HOUSEHOLD_SIZE}")
    print(f"  Companies: {COMPANIES_PER_MGU} per region ({COMPANIES_PER_MGU * NUM_MGUS} total)")
    print()

    generate_geography()
    print("  Generated geography data")

    generate_demographics()
    print("  Generated demographics data")

    generate_households()
    print("  Generated household data")

    generate_companies()
    print("  Generated company data")

    print("\nDone! Data written to:", DATA_DIR)
