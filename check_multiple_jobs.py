"""
Check and visualize people with multiple jobs.

Run this after your distributors have assigned people to companies.
"""

def analyze_multiple_jobs(world):
    """Analyze how many people have multiple primary_activity venues."""

    print("=" * 70)
    print("MULTIPLE JOBS ANALYSIS")
    print("=" * 70)

    # Track statistics
    total_people = len(world.population.people)
    people_with_primary_activity = 0
    people_with_multiple_venues = 0
    venue_count_distribution = {}

    # Examples of people with multiple jobs
    examples = []

    for person in world.population.people:
        if 'primary_activity' in person.activity_map:
            people_with_primary_activity += 1

            activity_value = person.activity_map['primary_activity']

            # Count total venues across all venue types
            total_venues = 0
            venue_details = []

            if isinstance(activity_value, dict):
                for venue_type, subset_list in activity_value.items():
                    if isinstance(subset_list, list):
                        for subset in subset_list:
                            if hasattr(subset, 'venue'):
                                total_venues += 1
                                venue_details.append({
                                    'venue_type': venue_type,
                                    'venue_name': subset.venue.name,
                                    'venue_id': subset.venue.id,
                                    'subset_name': subset.subset_name if hasattr(subset, 'subset_name') else 'unknown'
                                })

            # Track distribution
            if total_venues not in venue_count_distribution:
                venue_count_distribution[total_venues] = 0
            venue_count_distribution[total_venues] += 1

            # Count people with multiple venues
            if total_venues > 1:
                people_with_multiple_venues += 1

                # Save examples (limit to 10)
                if len(examples) < 10:
                    examples.append({
                        'person_id': person.id,
                        'age': person.age,
                        'sex': person.sex,
                        'total_venues': total_venues,
                        'venues': venue_details
                    })

    # Print summary statistics
    print(f"\nTotal population: {total_people:,}")
    print(f"People with primary_activity: {people_with_primary_activity:,}")
    print(f"People with multiple venues: {people_with_multiple_venues:,}")

    if people_with_primary_activity > 0:
        pct = (people_with_multiple_venues / people_with_primary_activity) * 100
        print(f"Percentage with multiple jobs: {pct:.2f}%")

    # Print distribution
    print("\n" + "-" * 70)
    print("VENUE COUNT DISTRIBUTION")
    print("-" * 70)
    print(f"{'# of Jobs':<15} {'# of People':<15} {'Percentage':<15}")
    print("-" * 70)

    for count in sorted(venue_count_distribution.keys()):
        num_people = venue_count_distribution[count]
        pct = (num_people / people_with_primary_activity) * 100 if people_with_primary_activity > 0 else 0
        print(f"{count:<15} {num_people:<15,} {pct:>6.2f}%")

    # Print examples
    if examples:
        print("\n" + "-" * 70)
        print("EXAMPLES OF PEOPLE WITH MULTIPLE JOBS")
        print("-" * 70)

        for i, example in enumerate(examples, 1):
            print(f"\nExample {i}:")
            print(f"  Person ID: {example['person_id']}")
            print(f"  Age: {example['age']}, Sex: {example['sex']}")
            print(f"  Total jobs: {example['total_venues']}")
            print(f"  Jobs:")

            for j, venue in enumerate(example['venues'], 1):
                print(f"    Job {j}: {venue['venue_name']} (type: {venue['venue_type']}, ID: {venue['venue_id']})")
                print(f"           Role: {venue['subset_name']}")

    print("\n" + "=" * 70)

    return {
        'total_people': total_people,
        'people_with_primary_activity': people_with_primary_activity,
        'people_with_multiple_venues': people_with_multiple_venues,
        'distribution': venue_count_distribution,
        'examples': examples
    }


if __name__ == "__main__":
    print("\nThis script should be imported and run with:")
    print("  from check_multiple_jobs import analyze_multiple_jobs")
    print("  analyze_multiple_jobs(world)")
    print()
