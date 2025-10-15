"""
Detailed household allocation analysis for June Zero.

Shows comprehensive statistics about created households including:
- Which rules were used
- People allocated (age, sex)
- Household compositions
- Age gap analysis
- Constraint satisfaction
"""

import logging
import sys
from collections import defaultdict, Counter
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from create_world import main, set_random_seed

logger = logging.getLogger("household_analysis")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Suppress other loggers
logging.getLogger('create_world').setLevel(logging.WARNING)
logging.getLogger('geography').setLevel(logging.WARNING)
logging.getLogger('venue').setLevel(logging.WARNING)
logging.getLogger('population').setLevel(logging.WARNING)
logging.getLogger('distributor').setLevel(logging.WARNING)
logging.getLogger('config_loader').setLevel(logging.WARNING)
logging.getLogger('rule_engine').setLevel(logging.WARNING)


def analyze_household_composition(household):
    """Get detailed composition of a household."""
    composition = {
        'kid': [],
        'young_adult': [],
        'adult': [],
        'elder': []
    }

    for person in household.residents:
        category = None
        if 0 <= person.age <= 17:
            category = 'kid'
        elif 18 <= person.age <= 25:
            category = 'young_adult'
        elif 26 <= person.age <= 64:
            category = 'adult'
        else:
            category = 'elder'

        composition[category].append({
            'id': person.id,
            'age': person.age,
            'sex': person.sex
        })

    return composition


def calculate_age_gaps(composition):
    """Calculate age gaps between members."""
    gaps = {}

    # Parent-child gaps (if kids and adults present)
    if composition['kid'] and composition['adult']:
        oldest_kid = max(composition['kid'], key=lambda p: p['age'])
        for i, adult in enumerate(composition['adult'], 1):
            gap = adult['age'] - oldest_kid['age']
            gaps[f'parent{i}_oldest_kid'] = gap

    # Partner gaps (if 2 adults)
    if len(composition['adult']) == 2:
        gap = abs(composition['adult'][0]['age'] - composition['adult'][1]['age'])
        gaps['partners'] = gap

    # Grandparent-grandchild gaps
    if composition['kid'] and composition['elder']:
        oldest_kid = max(composition['kid'], key=lambda p: p['age'])
        for i, elder in enumerate(composition['elder'], 1):
            gap = elder['age'] - oldest_kid['age']
            gaps[f'grandparent{i}_oldest_kid'] = gap

    return gaps


def analyze_sex_distribution(composition):
    """Analyze sex distribution in household."""
    all_people = (
        composition['kid'] +
        composition['young_adult'] +
        composition['adult'] +
        composition['elder']
    )

    sex_counts = Counter(p['sex'] for p in all_people)
    return dict(sex_counts)


def format_person_list(people):
    """Format list of people for display."""
    if not people:
        return "None"

    return ", ".join([
        f"{p['sex'][0]}/{p['age']}" for p in people
    ])


def print_detailed_household_report(world):
    """Print comprehensive household analysis."""
    households = world.households.households

    logger.info("")
    logger.info("=" * 100)
    logger.info("DETAILED HOUSEHOLD ALLOCATION REPORT")
    logger.info("=" * 100)

    # Overall statistics
    logger.info("")
    logger.info(f"Total households created: {len(households)}")
    logger.info(f"Total people allocated: {len(world.households.allocated_people)}")
    logger.info(f"Total population: {len(world.population.get_all_people())}")
    logger.info(f"Allocation rate: {len(world.households.allocated_people) / len(world.population.get_all_people()) * 100:.1f}%")

    # Group households by rule
    households_by_rule = defaultdict(list)
    households_by_pattern = defaultdict(list)

    for household in households:
        rule_name = household.properties.get('rule_name', 'unknown')
        pattern = household.properties.get('original_pattern', 'unknown')
        households_by_rule[rule_name].append(household)
        households_by_pattern[pattern].append(household)

    # Statistics by rule
    logger.info("")
    logger.info("-" * 100)
    logger.info("HOUSEHOLDS BY RULE")
    logger.info("-" * 100)

    for rule_name, hhs in sorted(households_by_rule.items(), key=lambda x: len(x[1]), reverse=True):
        total_people = sum(h.size() for h in hhs)
        avg_size = total_people / len(hhs)
        logger.info(f"{rule_name:40s} {len(hhs):6d} households  {total_people:8d} people  Avg: {avg_size:.2f}")

    # Statistics by pattern
    logger.info("")
    logger.info("-" * 100)
    logger.info("HOUSEHOLDS BY PATTERN")
    logger.info("-" * 100)

    for pattern, hhs in sorted(households_by_pattern.items(), key=lambda x: len(x[1]), reverse=True)[:20]:
        total_people = sum(h.size() for h in hhs)
        rule_name = hhs[0].properties.get('rule_name', 'unknown')
        logger.info(f"{pattern:20s} → {rule_name:30s} {len(hhs):6d} households  {total_people:6d} people")

    # Detailed examples for each rule
    logger.info("")
    logger.info("-" * 100)
    logger.info("DETAILED HOUSEHOLD EXAMPLES (5 per rule)")
    logger.info("-" * 100)

    for rule_name, hhs in sorted(households_by_rule.items()):
        logger.info("")
        logger.info(f"RULE: {rule_name}")
        logger.info(f"Total: {len(hhs)} households")
        logger.info("")

        # Show up to 5 examples
        for i, household in enumerate(hhs[:5], 1):
            composition = analyze_household_composition(household)
            age_gaps = calculate_age_gaps(composition)
            sex_dist = analyze_sex_distribution(composition)

            logger.info(f"  Example {i}:")
            logger.info(f"    Household ID: {household.id}")
            logger.info(f"    Location: {household.geographical_unit.name}")
            logger.info(f"    Original Pattern: {household.properties.get('original_pattern', 'N/A')}")
            logger.info(f"    Actual Pattern: {household.properties.get('actual_pattern', 'N/A')}")
            logger.info(f"    Size: {household.size()} people")
            logger.info(f"    ")
            logger.info(f"    Composition:")
            logger.info(f"      Kids:         {format_person_list(composition['kid'])}")
            logger.info(f"      Young Adults: {format_person_list(composition['young_adult'])}")
            logger.info(f"      Adults:       {format_person_list(composition['adult'])}")
            logger.info(f"      Elders:       {format_person_list(composition['elder'])}")
            logger.info(f"    ")
            logger.info(f"    Sex Distribution: {', '.join([f'{k}: {v}' for k, v in sex_dist.items()])}")

            if age_gaps:
                logger.info(f"    ")
                logger.info(f"    Age Gaps:")
                for gap_type, gap_value in age_gaps.items():
                    logger.info(f"      {gap_type}: {gap_value} years")

            logger.info("")

    # Age gap analysis
    logger.info("")
    logger.info("-" * 100)
    logger.info("AGE GAP ANALYSIS (All Households)")
    logger.info("-" * 100)

    all_parent_child_gaps = []
    all_partner_gaps = []
    all_grandparent_gaps = []

    for household in households:
        composition = analyze_household_composition(household)
        gaps = calculate_age_gaps(composition)

        for key, value in gaps.items():
            if 'parent' in key and 'oldest_kid' in key:
                all_parent_child_gaps.append(value)
            elif key == 'partners':
                all_partner_gaps.append(value)
            elif 'grandparent' in key:
                all_grandparent_gaps.append(value)

    if all_parent_child_gaps:
        logger.info(f"")
        logger.info(f"Parent-Child Age Gaps ({len(all_parent_child_gaps)} relationships):")
        logger.info(f"  Min: {min(all_parent_child_gaps)} years")
        logger.info(f"  Max: {max(all_parent_child_gaps)} years")
        logger.info(f"  Mean: {sum(all_parent_child_gaps) / len(all_parent_child_gaps):.1f} years")
        logger.info(f"  Median: {sorted(all_parent_child_gaps)[len(all_parent_child_gaps)//2]} years")

    if all_partner_gaps:
        logger.info(f"")
        logger.info(f"Partner Age Gaps ({len(all_partner_gaps)} couples):")
        logger.info(f"  Min: {min(all_partner_gaps)} years")
        logger.info(f"  Max: {max(all_partner_gaps)} years")
        logger.info(f"  Mean: {sum(all_partner_gaps) / len(all_partner_gaps):.1f} years")
        logger.info(f"  Median: {sorted(all_partner_gaps)[len(all_partner_gaps)//2]} years")

    if all_grandparent_gaps:
        logger.info(f"")
        logger.info(f"Grandparent-Grandchild Age Gaps ({len(all_grandparent_gaps)} relationships):")
        logger.info(f"  Min: {min(all_grandparent_gaps)} years")
        logger.info(f"  Max: {max(all_grandparent_gaps)} years")
        logger.info(f"  Mean: {sum(all_grandparent_gaps) / len(all_grandparent_gaps):.1f} years")

    # Sex composition analysis
    logger.info("")
    logger.info("-" * 100)
    logger.info("SEX COMPOSITION ANALYSIS")
    logger.info("-" * 100)

    # Count households by sex composition for couples
    couple_sex_patterns = defaultdict(int)

    for household in households:
        if household.size() == 2:
            composition = analyze_household_composition(household)
            all_people = (
                composition['kid'] +
                composition['young_adult'] +
                composition['adult'] +
                composition['elder']
            )

            if len(all_people) == 2:
                sexes = tuple(sorted([p['sex'] for p in all_people]))
                couple_sex_patterns[sexes] += 1

    logger.info("")
    logger.info("Two-Person Households (Couples):")
    for pattern, count in sorted(couple_sex_patterns.items(), key=lambda x: x[1], reverse=True):
        pattern_name = "Opposite sex" if pattern[0] != pattern[1] else "Same sex"
        pct = count / sum(couple_sex_patterns.values()) * 100
        logger.info(f"  {pattern}: {count:6d} ({pct:.1f}%) - {pattern_name}")

    logger.info("")
    logger.info("=" * 100)


def main_analysis():
    """Main analysis entry point."""
    set_random_seed(0)

    logger.info("Creating world with household allocation...")
    world = main()

    # Add rule names to household properties (they should already be there from allocation)
    # But let's make sure by checking
    households_with_rules = sum(1 for h in world.households.households if 'rule_name' in h.properties)
    logger.info(f"Households with rule names: {households_with_rules}/{len(world.households.households)}")

    print_detailed_household_report(world)


if __name__ == "__main__":
    main_analysis()
