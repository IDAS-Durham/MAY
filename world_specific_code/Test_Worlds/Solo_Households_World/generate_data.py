"""
Generate synthetic data for the Solo Households World.

Creates a world with:
- 1,000,000 people each in their own single-person household
- 1 SGU, 1 MGU, 1 LGU
- 2 company venues for working-age people (18-64)
"""

import csv
import os
import random

random.seed(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

TOTAL_POPULATION = 1_000_000
NUM_AGES = 100  # ages 0-99

SGU = "AREA_001"
MGU = "REGION_01"
LGU = "TestLand"


def generate_geography():
    path = os.path.join(DATA_DIR, "geography", "hierarchy.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SGU", "MGU", "LGU"])
        writer.writerow([SGU, MGU, LGU])

    path = os.path.join(DATA_DIR, "geography", "coord_sgu.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SGU", "latitude", "longitude"])
        writer.writerow([SGU, "51.500000", "-0.100000"])


def generate_demographics():
    header = ["geo_unit"] + [str(a) for a in range(NUM_AGES)]
    males = TOTAL_POPULATION // 2
    females = TOTAL_POPULATION - males

    for total, filename in [
        (males, "demographics_male.csv"),
        (females, "demographics_female.csv"),
    ]:
        base = total // NUM_AGES
        remainder = total - base * NUM_AGES
        counts = [base] * NUM_AGES
        for i in range(remainder):
            counts[i] += 1
        random.shuffle(counts)

        path = os.path.join(DATA_DIR, "population", filename)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerow([SGU] + counts)


def generate_households():
    path = os.path.join(DATA_DIR, "households", "households.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["geo_unit", "1"])
        writer.writerow([SGU, TOTAL_POPULATION])


def generate_companies():
    path = os.path.join(DATA_DIR, "venues", "companies.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["geo_unit", "name", "employee_count"])
        writer.writerow([SGU, "Company_A", TOTAL_POPULATION])
        writer.writerow([SGU, "Company_B", TOTAL_POPULATION])


if __name__ == "__main__":
    print("Generating Solo Households World data...")
    print(f"  Population: {TOTAL_POPULATION:,}")
    print(f"  Households: {TOTAL_POPULATION:,} (1 person each)")
    print(f"  Companies: 2")
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
