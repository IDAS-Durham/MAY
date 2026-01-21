"""
CSV export utilities for romantic relationship data.

Provides functions to export relationship networks and cheating data to CSV.
"""

import logging
import pandas as pd
from typing import Dict, List, Callable

logger = logging.getLogger("romantic_relationships")


def export_relationships_csv(
    population,
    person_by_id: Dict[int, any],
    partners_key: str,
    status_key: str,
    orientation_key: str,
    output_path: str = "romantic_relationships_detailed.csv"
):
    """
    Export detailed relationship data to CSV.

    Creates a CSV with one row per relationship, including:
    - Both partners' details (age, sex, ethnicity, orientation)
    - Relationship type
    - Whether household couple
    - Cheating status

    Args:
        population: Population object with people list
        person_by_id: Dict mapping person ID to person object
        partners_key: Key for partners in person.properties
        status_key: Key for relationship status in person.properties
        orientation_key: Key for sexual orientation in person.properties
        output_path: Path to save CSV file
    """
    logger.info(f"\nExporting detailed relationships to: {output_path}")

    relationships = []

    for person in population.people:
        if partners_key not in person.properties:
            continue

        partners_dict = person.properties[partners_key]

        # Process exclusive partners
        for partner_id in partners_dict.get('exclusive', []):
            # Avoid duplicates (only process if person.id < partner.id)
            if person.id < partner_id:
                partner = person_by_id.get(partner_id)
                if partner:
                    relationships.append(_make_relationship_record(
                        person, partner, 'exclusive',
                        status_key, orientation_key
                    ))

        # Process non-exclusive partners
        for partner_id in partners_dict.get('non_exclusive', []):
            # Avoid duplicates
            if person.id < partner_id:
                partner = person_by_id.get(partner_id)
                if partner:
                    relationships.append(_make_relationship_record(
                        person, partner, 'non_exclusive',
                        status_key, orientation_key
                    ))

    # Convert to DataFrame and save
    df = pd.DataFrame(relationships)
    df.to_csv(output_path, index=False)

    logger.info(f"  Exported {len(relationships):,} relationships")
    logger.info(f"  Columns: {list(df.columns)}")


def _make_relationship_record(
    person1, person2, rel_type: str,
    status_key: str, orientation_key: str
) -> dict:
    """
    Create a detailed record for a single relationship.

    Args:
        person1: First person
        person2: Second person
        rel_type: Relationship type ('exclusive' or 'non_exclusive')
        status_key: Key for relationship status in person.properties
        orientation_key: Key for sexual orientation in person.properties

    Returns:
        Dictionary with all relationship details
    """
    # Check if household couple
    is_household = (person1.properties.get('household_couple') == person2.id)

    # Check cheating status
    status1 = person1.properties.get(status_key, {})
    status2 = person2.properties.get(status_key, {})

    person1_cheating = not status1.get('consensual', True)
    person2_cheating = not status2.get('consensual', True)

    return {
        # Person 1 details
        'person1_id': person1.id,
        'person1_age': person1.age,
        'person1_sex': person1.sex,
        'person1_ethnicity': person1.properties.get('ethnicity', 'Unknown'),
        'person1_orientation': person1.properties.get(orientation_key, 'Unknown'),

        # Person 2 details
        'person2_id': person2.id,
        'person2_age': person2.age,
        'person2_sex': person2.sex,
        'person2_ethnicity': person2.properties.get('ethnicity', 'Unknown'),
        'person2_orientation': person2.properties.get(orientation_key, 'Unknown'),

        # Relationship details
        'relationship_type': rel_type,
        'is_household_couple': is_household,
        'person1_cheating': person1_cheating,
        'person2_cheating': person2_cheating,
        'is_consensual': status1.get('consensual', True) and status2.get('consensual', True),

        # Computed fields
        'age_difference': abs(person1.age - person2.age),
        'same_sex': person1.sex == person2.sex,
        'same_ethnicity': person1.properties.get('ethnicity') == person2.properties.get('ethnicity'),
    }


def export_cheating_network_csv(
    population,
    person_by_id: Dict[int, any],
    partners_key: str,
    status_key: str,
    orientation_key: str,
    output_path: str = "cheating_network_detailed.csv"
):
    """
    Export detailed cheating network to CSV.

    Shows each cheater with their main partner and affair partner(s).

    Args:
        population: Population object with people list
        person_by_id: Dict mapping person ID to person object
        partners_key: Key for partners in person.properties
        status_key: Key for relationship status in person.properties
        orientation_key: Key for sexual orientation in person.properties
        output_path: Path to save CSV file
    """
    logger.info(f"\nExporting cheating network to: {output_path}")

    cheating_records = []

    for person in population.people:
        # Check if person is cheating
        status = person.properties.get(status_key, {})
        if status.get('consensual', True):
            continue  # Not cheating

        # Get partners
        partners_dict = person.properties.get(partners_key, {})
        exclusive_partners = partners_dict.get('exclusive', [])
        non_exclusive_partners = partners_dict.get('non_exclusive', [])

        # Main partner (exclusive)
        main_partner_id = exclusive_partners[0] if exclusive_partners else None
        main_partner = person_by_id.get(main_partner_id) if main_partner_id else None

        # Affair partners (non-exclusive)
        for affair_partner_id in non_exclusive_partners:
            affair_partner = person_by_id.get(affair_partner_id)
            if affair_partner:
                cheating_records.append({
                    # Cheater details
                    'cheater_id': person.id,
                    'cheater_age': person.age,
                    'cheater_sex': person.sex,
                    'cheater_ethnicity': person.properties.get('ethnicity', 'Unknown'),
                    'cheater_orientation': person.properties.get(orientation_key, 'Unknown'),

                    # Main partner details (being cheated on)
                    'main_partner_id': main_partner.id if main_partner else None,
                    'main_partner_age': main_partner.age if main_partner else None,
                    'main_partner_sex': main_partner.sex if main_partner else None,
                    'main_partner_ethnicity': main_partner.properties.get('ethnicity', 'Unknown') if main_partner else None,
                    'main_partner_orientation': main_partner.properties.get(orientation_key, 'Unknown') if main_partner else None,
                    'is_household_couple': person.properties.get('household_couple') == main_partner_id if main_partner_id else False,

                    # Affair partner details
                    'affair_partner_id': affair_partner.id,
                    'affair_partner_age': affair_partner.age,
                    'affair_partner_sex': affair_partner.sex,
                    'affair_partner_ethnicity': affair_partner.properties.get('ethnicity', 'Unknown'),
                    'affair_partner_orientation': affair_partner.properties.get(orientation_key, 'Unknown'),
                    'affair_partner_relationship_type': affair_partner.properties.get(status_key, {}).get('type', 'Unknown'),
                })

    # Convert to DataFrame and save
    df = pd.DataFrame(cheating_records)
    df.to_csv(output_path, index=False)

    logger.info(f"  Exported {len(cheating_records):,} affairs")
    if len(cheating_records) > 0:
        logger.info(f"  Columns: {list(df.columns)}")


def print_statistics(all_adults: List, stats: Dict, status_key: str):
    """
    Print statistics about relationship distribution.

    Args:
        all_adults: List of all adult persons
        stats: Statistics dictionary from distributor
        status_key: Key for relationship status in person.properties
    """
    logger.info("\n" + "=" * 60)
    logger.info("RELATIONSHIP DISTRIBUTION SUMMARY")
    logger.info("=" * 60)

    # Orientation distribution
    logger.info("\nSexual Orientation Distribution:")
    for orientation in ['heterosexual', 'homosexual', 'bisexual']:
        count = stats.get(f'orientation_{orientation}', 0)
        pct = (count / len(all_adults)) * 100 if all_adults else 0
        logger.info(f"  {orientation:20s}: {count:6,} ({pct:5.2f}%)")

    # Relationship type distribution
    logger.info("\nRelationship Type Distribution:")
    exclusive = stats.get('relationship_type_exclusive', 0)
    non_exclusive = stats.get('relationship_type_non_exclusive', 0)
    no_partner = stats.get('no_partner', 0)

    total = len(all_adults)
    logger.info(f"  Exclusive:      {exclusive:6,} ({(exclusive/total)*100:5.2f}%)")
    logger.info(f"  Non-exclusive:  {non_exclusive:6,} ({(non_exclusive/total)*100:5.2f}%)")
    logger.info(f"  No partner:     {no_partner:6,} ({(no_partner/total)*100:5.2f}%)")

    # Relationships created
    logger.info("\nRelationships Created:")
    logger.info(f"  Total relationships: {stats.get('relationships_created', 0):,}")
    logger.info(f"  From household couples: {stats.get('household_couples_processed', 0):,}")
    logger.info(f"  Exclusive (new): {stats.get('exclusive_relationships_created', 0):,}")
    logger.info(f"  Non-exclusive: {stats.get('non_exclusive_relationships_created', 0):,}")

    # Cheating statistics
    cheaters = len([p for p in all_adults
                   if status_key in p.properties
                   and not p.properties[status_key].get('consensual', True)])
    logger.info(f"\nCheating Statistics:")
    logger.info(f"  People cheating: {cheaters:,}")
    logger.info(f"  Cheating rate: {(cheaters/total)*100:.2f}%")
