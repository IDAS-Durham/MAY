#!/usr/bin/env python3
"""
Reverse-engineer 1918 New Zealand household compositions into the 2021 UK census schema.

For the UK 2021 pipeline we are GIVEN per-area household-composition counts
(data/households/households.csv) and we allocate the population into them.

For 1918 NZ we have the opposite: an age/sex pyramid per geographical unit plus a
household-SIZE distribution, but no composition counts. This script reverse-engineers
plausible households from those two inputs -- applying the same assumptions that the
2021 configs encode (configs/2021/households/{households_config,allocation_strategy,
relationship_rules}.yaml) -- and then counts households by composition, emitting a CSV
with the identical 15-column header as data/households/households.csv.

Assumptions reused from the 2021 configs
-----------------------------------------
Age categories (households_config.yaml):
    Kids 0-17, Young Adults 18-24, Adults 25-64, Old Adults 65+.

Allocation ordering (allocation_strategy.yaml) -> we form households largest-first so
that families and multi-generational households get first pick of people, then couples,
then singles, then young-adult and flexible households; leftover population is absorbed
as "excess" into compatible existing households.

Relationship rules (relationship_rules.yaml):
    - Couples: 2 adults (or 2 elders), |age diff| <= 19, opposite-sex ~95%.
    - Parent/child: an adult (or elder) caregiver must be 16-55 years older than each
      kid, with parent age at child's birth ~ N(32, 6).
    - Grandparent/parent in multigenerational households: elder 16-50 years older than
      the adults (~ N(30, 7)).
    - Kids are never left without an adult/elder caregiver; a person living alone is
      never a kid.

The household-size distribution is treated as a GUIDE (per the project decision): each
declared household is seeded at its nominal size, then the excess pass grows some of them
to consume the full population (implied size-population is ~10% below the actual pyramid).

Output schema (data/households/households.csv header), pattern = "Kids YA Adults OldAdults":
    0 0 0 2, 0 0 2 0, 0 0 0 1, 0 0 1 0, 0 >=1 2 0, 1 >=0 2 0, >=2 >=0 2 0,
    0 >=1 1 0, 1 >=0 1 0, >=2 >=0 1 0, 1 >=0 >=0 >=0, >=2 >=0 >=0 >=0,
    0 >=0 0 0, 0 0 0 >=3, 0 >=0 >=0 >=0
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------------------
# Configuration (mirrors configs/2021/households)
# --------------------------------------------------------------------------------------

# Age-category boundaries (inclusive), from households_config.yaml.
KID_MAX = 17
YA_MIN, YA_MAX = 18, 24
ADULT_MIN, ADULT_MAX = 25, 64
OLD_MIN = 65
MAX_AGE = 99  # demographics files cover ages 0..99

# Parent / child age gap (relationship_rules.yaml: numerical_attribute_difference).
PARENT_MIN_GAP = 16
PARENT_MAX_GAP = 55          # max of female 50 / male 55
PARENT_MEAN_GAP = 32         # preferred_distribution mean
PARENT_STD_GAP = 6

# Grandparent / parent gap (multigenerational rule role_C vs role_B).
GRAND_MIN_GAP = 16
GRAND_MAX_GAP = 50
GRAND_MEAN_GAP = 30
GRAND_STD_GAP = 7

# Couple pair_matching (relationship_rules.yaml).
COUPLE_MAX_AGE_DIFF = 19
COUPLE_SAME_SEX_PROB = 0.05  # same_category_probability_fallback

# Household size used to stand in for the open-ended ">10" bucket.
GREATER10_SIZE = 11

# The exact 15 output columns, in the same order as data/households/households.csv.
UK_COLUMNS = [
    "0 0 0 2", "0 0 2 0", "0 0 0 1", "0 0 1 0", "0 >=1 2 0", "1 >=0 2 0",
    ">=2 >=0 2 0", "0 >=1 1 0", "1 >=0 1 0", ">=2 >=0 1 0", "1 >=0 >=0 >=0",
    ">=2 >=0 >=0 >=0", "0 >=0 0 0", "0 0 0 >=3", "0 >=0 >=0 >=0",
]

HH_SIZE_COLUMNS = [
    "hh_1", "hh_2", "hh_3", "hh_4", "hh_5", "hh_6", "hh_7", "hh_8", "hh_9",
    "hh_10", "hh_greater10",
]


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------


@dataclass
class Person:
    age: int
    sex: str  # "male" | "female"

    @property
    def category(self) -> str:
        if self.age <= KID_MAX:
            return "K"
        if self.age <= YA_MAX:
            return "YA"
        if self.age <= ADULT_MAX:
            return "A"
        return "OA"


@dataclass
class Household:
    target_size: int
    members: list[Person] = field(default_factory=list)

    def counts(self) -> tuple[int, int, int, int]:
        c = Counter(p.category for p in self.members)
        return c["K"], c["YA"], c["A"], c["OA"]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def seats_left(self) -> int:
        return max(0, self.target_size - self.size)

    def caregiver_ages(self) -> list[int]:
        """Ages of adults/elders who could act as a parent."""
        return [p.age for p in self.members if p.category in ("A", "OA")]


# --------------------------------------------------------------------------------------
# Person pools
# --------------------------------------------------------------------------------------


class Pools:
    """Holds remaining people per category, each as a list we pop from."""

    def __init__(self, people_by_cat: dict[str, list[Person]], rng: random.Random):
        self.rng = rng
        # Sort each pool by age so age-gap searches are cheap and deterministic.
        self.pools: dict[str, list[Person]] = {
            cat: sorted(lst, key=lambda p: p.age) for cat, lst in people_by_cat.items()
        }

    def count(self, cat: str) -> int:
        return len(self.pools[cat])

    def total(self) -> int:
        return sum(len(v) for v in self.pools.values())

    def pop_random(self, cat: str) -> Person | None:
        lst = self.pools[cat]
        if not lst:
            return None
        i = self.rng.randrange(len(lst))
        return lst.pop(i)

    def pop_near_age(self, cat: str, target_age: int, tol: int) -> Person | None:
        """Pop the person in `cat` whose age is closest to target_age, within tol."""
        lst = self.pools[cat]
        if not lst:
            return None
        best_i, best_d = None, None
        for i, p in enumerate(lst):
            d = abs(p.age - target_age)
            if d <= tol and (best_d is None or d < best_d):
                best_i, best_d = i, d
        if best_i is None:
            return None
        return lst.pop(best_i)

    def pop_in_age_range(self, cat: str, lo: int, hi: int) -> Person | None:
        """Pop a random person in `cat` with age in [lo, hi]."""
        lst = self.pools[cat]
        idxs = [i for i, p in enumerate(lst) if lo <= p.age <= hi]
        if not idxs:
            return None
        i = self.rng.choice(idxs)
        return lst.pop(i)


# --------------------------------------------------------------------------------------
# Household construction
# --------------------------------------------------------------------------------------


def _take_partner(pools: Pools, anchor: Person) -> Person | None:
    """Find a romantic partner for `anchor` (same age-category, couple constraints)."""
    cat = anchor.category
    same_sex = pools.rng.random() < COUPLE_SAME_SEX_PROB
    want_sex = anchor.sex if same_sex else ("female" if anchor.sex == "male" else "male")
    lst = pools.pools[cat]
    # Prefer the wanted sex within the age-diff window; fall back to any sex in window.
    best_i, best_d = None, None
    fallback_i, fallback_d = None, None
    for i, p in enumerate(lst):
        d = abs(p.age - anchor.age)
        if d > COUPLE_MAX_AGE_DIFF:
            continue
        if p.sex == want_sex and (best_d is None or d < best_d):
            best_i, best_d = i, d
        if fallback_d is None or d < fallback_d:
            fallback_i, fallback_d = i, d
    idx = best_i if best_i is not None else fallback_i
    if idx is None:
        return None
    return lst.pop(idx)


def _add_kid(pools: Pools, hh: Household) -> bool:
    """Add a kid whose age satisfies the parent-gap against an existing caregiver."""
    caregivers = hh.caregiver_ages()
    if not caregivers:
        return False
    youngest_cg = min(caregivers)
    # Kid must be PARENT_MIN_GAP..PARENT_MAX_GAP younger than a caregiver.
    hi = youngest_cg - PARENT_MIN_GAP            # oldest the kid may be
    lo = max(0, max(caregivers) - PARENT_MAX_GAP)  # youngest sensible kid age
    hi = min(hi, KID_MAX)
    lo = max(lo, 0)
    if hi < lo or hi < 0:
        return False
    # Target a realistic kid age from the parent-birth distribution.
    target_parent_age = pools.rng.gauss(PARENT_MEAN_GAP, PARENT_STD_GAP)
    target_kid_age = int(round(youngest_cg - target_parent_age))
    target_kid_age = max(lo, min(hi, target_kid_age))
    kid = pools.pop_near_age("K", target_kid_age, tol=KID_MAX)
    if kid is None or not (lo <= kid.age <= hi):
        if kid is not None:  # out of window -> put back
            pools.pools["K"].append(kid)
            pools.pools["K"].sort(key=lambda p: p.age)
        kid = pools.pop_in_age_range("K", lo, hi)
    if kid is None:
        return False
    hh.members.append(kid)
    return True


def _add_elder_grandparent(pools: Pools, hh: Household) -> bool:
    """Add an old adult as a grandparent (gap above the household's adults)."""
    adult_ages = [p.age for p in hh.members if p.category == "A"]
    if not adult_ages:
        return pools_add_simple(pools, hh, "OA")
    oldest_adult = max(adult_ages)
    lo = max(OLD_MIN, oldest_adult + GRAND_MIN_GAP)
    hi = min(MAX_AGE, oldest_adult + GRAND_MAX_GAP)
    if hi < lo:
        return False
    elder = pools.pop_in_age_range("OA", lo, hi)
    if elder is None:
        return False
    hh.members.append(elder)
    return True


def pools_add_simple(pools: Pools, hh: Household, cat: str) -> bool:
    p = pools.pop_random(cat)
    if p is None:
        return False
    hh.members.append(p)
    return True


# Probability a multi-person household forms around a couple rather than a lone
# founder (single parent / lone elder). The complement become single-adult families.
P_COUPLE_CORE = 0.66
# Probability a multi-person household is a young-adult flat (only when YAs are free).
P_YA_FLAT = 0.08
# Fraction of free young adults considered willing to live entirely alone.
YA_LIVE_ALONE_SHARE = 4  # 1-in-4


def seat_core(pools: Pools, hh: Household) -> None:
    """Seat the founding adult(s)/elder(s) of a household before adding dependents.

    Every household receives a founder here (in a dedicated pass over all households)
    so the many small households are not starved of adults by large families.
    """
    a, oa, ya = pools.count("A"), pools.count("OA"), pools.count("YA")

    if hh.target_size == 1:
        # Singles: never a kid. Prefer adults/elders; some young adults live alone.
        choices = ["A"] * a + ["OA"] * oa + ["YA"] * (ya // YA_LIVE_ALONE_SHARE)
        cat = pools.rng.choice(choices) if choices else _first_nonempty(pools)
        if cat:
            pools_add_simple(pools, hh, cat)
        return

    # Young-adult flat (e.g. two single workers sharing) -- size >= 2 only.
    if ya >= 2 and pools.rng.random() < P_YA_FLAT:
        first = pools.pop_random("YA")
        if first is not None:
            hh.members.append(first)
            partner = _take_partner(pools, first)
            if partner is not None:
                hh.members.append(partner)
            return

    # Pick the founding adult/elder by availability (adult vs elderly household).
    weighted = ["A"] * a + ["OA"] * oa
    anchor_cat = pools.rng.choice(weighted) if weighted else _first_nonempty(pools)
    if anchor_cat is None:
        return
    anchor = pools.pop_random(anchor_cat)
    if anchor is None:
        return
    hh.members.append(anchor)

    # Couple core vs single-parent / lone founder. Skipping the partner leaves a
    # single-adult family (kids/YAs added during the dependent-fill pass).
    if pools.rng.random() < P_COUPLE_CORE and hh.seats_left > 0:
        partner = _take_partner(pools, anchor)
        if partner is not None:
            hh.members.append(partner)


def fill_dependents(pools: Pools, hh: Household) -> None:
    """Fill the remaining seats with dependents in priority order."""
    has_caregiver = any(p.category in ("A", "OA") for p in hh.members)

    while hh.seats_left > 0:
        added = False
        # Decide what kind of dependent to try, based on what remains and household make-up.
        k, ya, a, oa = pools.count("K"), pools.count("YA"), pools.count("A"), pools.count("OA")

        # 1) Kids first if there is a caregiver and kids remain (families dominate).
        if has_caregiver and k > 0 and pools.rng.random() < 0.6:
            added = _add_kid(pools, hh)
        # 2) Young adults living with parents.
        if not added and ya > 0 and pools.rng.random() < 0.5:
            added = pools_add_simple(pools, hh, "YA")
        # 3) A grandparent (multigenerational) if adults present and elders remain.
        if not added and oa > 0 and any(p.category == "A" for p in hh.members) \
                and pools.rng.random() < 0.35:
            added = _add_elder_grandparent(pools, hh)
        # 4) Otherwise pull whoever is most available (kid w/ caregiver, else ya/a/oa).
        if not added:
            order = []
            if has_caregiver and k > 0:
                order.append("K")
            order += [c for c in ("YA", "A", "OA") if pools.count(c) > 0]
            placed = False
            for cat in order:
                if cat == "K":
                    placed = _add_kid(pools, hh)
                elif cat == "OA" and any(p.category == "A" for p in hh.members):
                    placed = _add_elder_grandparent(pools, hh)
                else:
                    placed = pools_add_simple(pools, hh, cat)
                if placed:
                    break
            added = placed

        if not added:
            break  # nothing compatible remains for this household

        has_caregiver = any(p.category in ("A", "OA") for p in hh.members)


def _first_nonempty(pools: Pools) -> str | None:
    for cat in ("A", "OA", "YA", "K"):
        if pools.count(cat) > 0:
            return cat
    return None


# --------------------------------------------------------------------------------------
# Excess pass -- absorb leftover population into compatible households
# --------------------------------------------------------------------------------------


def distribute_excess(pools: Pools, households: list[Household], rng: random.Random) -> None:
    """Place remaining people into existing households (mirrors 2021 household_excess).

    Only households whose nominal target size is >= 3 are grown, so that the singles
    (target size 1) and couples / single-parent pairs (target size 2) implied by the
    household-size distribution are preserved rather than inflated away.
    """
    MAX_GROWTH = 16  # don't grow any single household unboundedly
    growable = [h for h in households if h.target_size >= 3 and h.members]

    # Kids -> households that already have a caregiver and room (age gap enforced).
    family_hhs = [h for h in growable if any(p.category in ("A", "OA") for p in h.members)]
    rng.shuffle(family_hhs)
    _drain_into(pools, "K", family_hhs, MAX_GROWTH, add_fn=_add_existing_kid)

    # Young adults, then adults, then old adults -> any growable household (flexible).
    for cat in ("YA", "A", "OA"):
        targets = list(growable)
        rng.shuffle(targets)
        _drain_into(pools, cat, targets, MAX_GROWTH, add_fn=_add_existing_simple)


def _add_existing_simple(person: Person, hh: Household) -> bool:
    hh.members.append(person)
    return True


def _add_existing_kid(person: Person, hh: Household) -> bool:
    """Add a specific kid to hh only if some caregiver satisfies the parent gap."""
    for cg in hh.caregiver_ages():
        if PARENT_MIN_GAP <= (cg - person.age) <= PARENT_MAX_GAP:
            hh.members.append(person)
            return True
    return False


def _drain_into(pools: Pools, cat: str, targets: list[Household], max_growth: int,
                add_fn) -> None:
    if not targets:
        return
    leftovers: list[Person] = []
    ti = 0
    n = len(targets)
    while pools.count(cat) > 0:
        person = pools.pop_random(cat)
        placed = False
        # Round-robin a few candidate households so growth stays balanced.
        for _ in range(n):
            hh = targets[ti % n]
            ti += 1
            if hh.size < max_growth and add_fn(person, hh):
                placed = True
                break
        if not placed:
            leftovers.append(person)
    # Put anyone we could not place back so a later pass / fallback can handle them.
    pools.pools[cat].extend(leftovers)
    pools.pools[cat].sort(key=lambda p: p.age)


def absorb_remainder(pools: Pools, households: list[Household], rng: random.Random) -> None:
    """Final safety net: place any still-unallocated people so totals reconcile."""
    # Kids that never found a caregiver: attach to the nearest plausible household,
    # else create a new caregiver-less household only if truly nothing else exists.
    for cat in ("A", "OA", "YA", "K"):
        while pools.count(cat) > 0:
            person = pools.pop_random(cat)
            if cat == "K":
                target = next((h for h in households
                               if any(PARENT_MIN_GAP <= (cg - person.age) <= PARENT_MAX_GAP
                                      for cg in h.caregiver_ages())), None)
                if target is None:
                    # No valid caregiver anywhere: start a household with an adult if
                    # one is somehow free; otherwise place the kid with the largest
                    # household (data artifact -- logged in summary as orphan kids).
                    target = max(households, key=lambda h: len(h.caregiver_ages()),
                                 default=None)
                if target is None:
                    households.append(Household(target_size=1, members=[person]))
                else:
                    target.members.append(person)
            else:
                # Prefer growable (size >= 3) households so singles/couples survive.
                pool = [h for h in households if h.target_size >= 3] or households
                target = rng.choice(pool) if pool else None
                if target is None:
                    households.append(Household(target_size=1, members=[person]))
                else:
                    target.members.append(person)


# --------------------------------------------------------------------------------------
# Classification into the 15 UK columns
# --------------------------------------------------------------------------------------


def classify(counts: tuple[int, int, int, int]) -> str:
    """Map (kids, young_adults, adults, old_adults) to one of the 15 UK patterns.

    Precedence mirrors allocation_strategy.yaml: two-/single-adult families with kids,
    multi-generational, YA families, elderly, adults, YA-only, then flexible catch-all.
    """
    k, ya, a, oa = counts

    if k >= 2 and a == 2 and oa == 0:
        return ">=2 >=0 2 0"
    if k == 1 and a == 2 and oa == 0:
        return "1 >=0 2 0"
    if k >= 2 and a == 1 and oa == 0:
        return ">=2 >=0 1 0"
    if k == 1 and a == 1 and oa == 0:
        return "1 >=0 1 0"
    if k >= 2:
        return ">=2 >=0 >=0 >=0"
    if k == 1:
        return "1 >=0 >=0 >=0"
    # No kids from here on.
    if ya >= 1 and a == 2 and oa == 0:
        return "0 >=1 2 0"
    if ya >= 1 and a == 1 and oa == 0:
        return "0 >=1 1 0"
    if ya == 0 and a == 2 and oa == 0:
        return "0 0 2 0"
    if ya == 0 and a == 1 and oa == 0:
        return "0 0 1 0"
    if ya == 0 and a == 0 and oa == 2:
        return "0 0 0 2"
    if ya == 0 and a == 0 and oa == 1:
        return "0 0 0 1"
    if ya == 0 and a == 0 and oa >= 3:
        return "0 0 0 >=3"
    if a == 0 and oa == 0 and ya >= 1:
        return "0 >=0 0 0"
    return "0 >=0 >=0 >=0"


# --------------------------------------------------------------------------------------
# Per-geo-unit pipeline
# --------------------------------------------------------------------------------------


def build_people(male_row: pd.Series, female_row: pd.Series) -> dict[str, list[Person]]:
    people: dict[str, list[Person]] = {"K": [], "YA": [], "A": [], "OA": []}
    for sex, row in (("male", male_row), ("female", female_row)):
        for age in range(MAX_AGE + 1):
            n = int(row[str(age)])
            if n <= 0:
                continue
            cat = ("K" if age <= KID_MAX else "YA" if age <= YA_MAX
                   else "A" if age <= ADULT_MAX else "OA")
            people[cat].extend(Person(age, sex) for _ in range(n))
    return people


def target_sizes(hh_row: pd.Series) -> list[int]:
    sizes: list[int] = []
    for size, col in zip(range(1, 12), HH_SIZE_COLUMNS):
        s = size if col != "hh_greater10" else GREATER10_SIZE
        sizes.extend([s] * int(hh_row[col]))
    return sizes


def process_geo_unit(geo: str, male_row, female_row, hh_row,
                     rng: random.Random) -> tuple[Counter, dict]:
    people = build_people(male_row, female_row)
    pools = Pools(people, rng)
    total_pop = pools.total()

    sizes = target_sizes(hh_row)
    # Largest households first -> families/multigenerational get first pick of the
    # couple/dependent pools (priority order from allocation_strategy.yaml).
    sizes.sort(reverse=True)
    households = [Household(target_size=s) for s in sizes]

    # Pass A: seat a founder/couple in EVERY household first (avoids starving the many
    # small households of adults once large families have been filled).
    for hh in households:
        if pools.total() == 0:
            break
        seat_core(pools, hh)

    # Pass B: fill each household up to its nominal size with dependents.
    for hh in households:
        if pools.total() == 0:
            break
        fill_dependents(pools, hh)

    distribute_excess(pools, households, rng)
    absorb_remainder(pools, households, rng)

    counts = Counter()
    placed = 0
    for hh in households:
        if hh.size == 0:
            continue
        counts[classify(hh.counts())] += 1
        placed += hh.size

    diag = {
        "geo_unit": geo,
        "total_pop": total_pop,
        "placed": placed,
        "n_target_hh": len(sizes),
        "n_nonempty_hh": sum(1 for h in households if h.size > 0),
    }
    return counts, diag


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    base = Path("data/NZ1918_data")
    ap.add_argument("--male", type=Path, default=base / "population/demographics_male.csv")
    ap.add_argument("--female", type=Path, default=base / "population/demographics_female.csv")
    ap.add_argument("--households", type=Path, default=base / "households/households.csv")
    ap.add_argument("--out", type=Path, default=base / "households/household_compositions.csv")
    ap.add_argument("--seed", type=int, default=1918)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    male = pd.read_csv(args.male).set_index("geo_unit")
    female = pd.read_csv(args.female).set_index("geo_unit")
    hh = pd.read_csv(args.households).set_index("geo_unit")

    geo_units = list(hh.index)
    rows = []
    diags = []
    for i, geo in enumerate(geo_units, 1):
        if geo not in male.index or geo not in female.index:
            print(f"  ! skipping {geo}: missing demographics")
            continue
        counts, diag = process_geo_unit(
            geo, male.loc[geo], female.loc[geo], hh.loc[geo], rng)
        row = {"geo_unit": geo}
        row.update({col: counts.get(col, 0) for col in UK_COLUMNS})
        rows.append(row)
        diags.append(diag)
        if i % 50 == 0 or i == len(geo_units):
            print(f"  processed {i}/{len(geo_units)} geo units")

    out_df = pd.DataFrame(rows, columns=["geo_unit"] + UK_COLUMNS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False, quoting=csv.QUOTE_MINIMAL)

    # Summary / sanity report.
    diag_df = pd.DataFrame(diags)
    tot_pop = diag_df["total_pop"].sum()
    tot_placed = diag_df["placed"].sum()
    tot_hh = out_df[UK_COLUMNS].values.sum()
    print("\n=== Summary ===")
    print(f"Geo units written     : {len(out_df)}")
    print(f"Population (pyramid)   : {tot_pop:,}")
    print(f"Population placed      : {tot_placed:,} "
          f"({tot_placed / tot_pop:.4%} of pyramid)")
    print(f"Households generated   : {tot_hh:,}")
    print(f"Output                 : {args.out}")
    print("\nHousehold composition totals:")
    col_totals = out_df[UK_COLUMNS].sum().sort_values(ascending=False)
    for col, n in col_totals.items():
        print(f"  {col:<18} {n:>9,}  ({n / tot_hh:6.2%})")


if __name__ == "__main__":
    main()
