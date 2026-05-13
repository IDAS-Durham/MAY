"""
Utilities for exporting relationship data to CSV.
"""
import csv
import logging

logger = logging.getLogger("export_properties")


def export_relationships(world, property_key, output_file):
    """Export relationships to CSV for inspection."""
    logger.info(f"Exporting relationships to {output_file}...")

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['person_id', 'age', 'sex', 'sgu', 'subset_name', 'n_connections', 'connection_ids'])

        for person in world.population.people:
            connections = person.properties.get(property_key, [])

            # Get subset name if available
            # UNIFIED STRUCTURE: activity_map['primary_activity'][venue_type] = [subsets]
            subset_name = ""
            if 'primary_activity' in person.activity_map and person.activity_map['primary_activity']:
                activity_dict = person.activity_map['primary_activity']
                # Get first subset from any venue type
                for subsets in activity_dict.values():
                    if subsets:
                        subset_name = getattr(subsets[0], 'subset_name', '')
                        break

            sgu = person.geographical_unit.name if person.geographical_unit else ""

            writer.writerow([
                person.id,
                person.age,
                person.sex,
                sgu,
                subset_name,
                len(connections),
                ';'.join(str(p.id) for p in connections)
            ])

    logger.info(f"Exported {len(world.population.people):,} people's relationships to {output_file}")
