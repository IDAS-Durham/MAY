"""
Enhanced Epidemiology Simulation Visualizer

Comprehensive visualizations including age, occupation, venue types, and transmission analysis.
"""

import h5py
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter, defaultdict
from datetime import datetime
import pandas as pd

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (15, 10)

class EnhancedSimulationAnalyzer:
    def __init__(self, h5_path):
        self.h5_path = h5_path
        self.load_data()

    def load_data(self):
        """Load all data from HDF5 file"""
        print("Loading data from HDF5 file...")
        with h5py.File(self.h5_path, 'r') as f:
            # Load events
            self.infections = f['events/infections'][:]
            self.deaths = f['events/deaths'][:]
            self.symptom_changes = f['events/symptom_changes'][:]
            self.hospital_admissions = f['events/hospital_admissions'][:]
            self.hospital_discharges = f['events/hospital_discharges'][:]
            self.icu_admissions = f['events/icu_admissions'][:]

            # Load lookups
            self.people = f['lookups/people'][:]
            self.venues = f['lookups/venues'][:]
            self.person_activities = f['lookups/person_activities'][:]

        print(f"Loaded {len(self.infections)} infections, {len(self.deaths)} deaths")
        print(f"  {len(self.hospital_admissions)} hospital admissions, {len(self.icu_admissions)} ICU admissions")
        print(f"  {len(self.people)} people, {len(self.venues)} venues")

        # Pre-build occupation lookup for speed
        print("Building occupation lookup...")
        self.build_occupation_lookup()

    def get_person_info(self, person_ids):
        """Get person information for given IDs"""
        # Create a mapping for fast lookup
        person_map = {p['person_id']: p for p in self.people}
        return [person_map.get(pid) for pid in person_ids]

    def get_venue_info(self, venue_ids):
        """Get venue information for given IDs"""
        venue_map = {v['venue_id']: v for v in self.venues}
        return [venue_map.get(vid) for vid in venue_ids]

    def build_occupation_lookup(self):
        """Pre-build occupation lookup for all people - FAST version"""
        self.occupation_map = {}

        # Create venue map first
        venue_map = {v['venue_id']: self.decode_bytes(v['type']) for v in self.venues}

        # Filter to primary activities only
        primary_mask = np.char.decode(self.person_activities['activity_name'].astype('bytes'), 'utf-8') == 'primary_activity'
        primary_activities = self.person_activities[primary_mask]

        # Build occupation map
        for activity in primary_activities:
            person_id = activity['person_id']
            venue_id = activity['venue_id']
            if person_id not in self.occupation_map:  # Take first primary activity
                self.occupation_map[person_id] = venue_map.get(venue_id, 'unknown')

        print(f"  Built occupation lookup for {len(self.occupation_map)} people")

    def get_person_occupation(self, person_id):
        """Get person's occupation from pre-built lookup"""
        return self.occupation_map.get(person_id, 'no_primary_activity')

    def decode_bytes(self, value):
        """Decode bytes to string"""
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return value

    def compute_statistics(self):
        """Compute comprehensive epidemiological statistics"""
        print("\n" + "="*70)
        print("EPIDEMIOLOGICAL STATISTICS")
        print("="*70)

        total_infections = len(self.infections)
        seed_infections = np.sum(self.infections['infector_id'] == -1)
        secondary_infections = total_infections - seed_infections
        total_deaths = len(self.deaths)

        print(f"\n📊 Overall Statistics:")
        print(f"  Total infections: {total_infections:,}")
        print(f"  Seed infections: {seed_infections:,}")
        print(f"  Secondary infections: {secondary_infections:,}")
        print(f"  Deaths: {total_deaths:,}")
        print(f"  Hospital admissions: {len(self.hospital_admissions):,}")
        print(f"  ICU admissions: {len(self.icu_admissions):,}")
        print(f"  CFR: {100*total_deaths/total_infections:.2f}%")

        # Age analysis
        print(f"\n👥 Age Analysis of Infected:")
        infected_person_ids = self.infections['person_id']
        infected_people = self.get_person_info(infected_person_ids)
        ages = [p['age'] for p in infected_people if p is not None]
        print(f"  Mean age: {np.mean(ages):.1f} years")
        print(f"  Median age: {np.median(ages):.1f} years")
        print(f"  Age range: {np.min(ages):.0f} - {np.max(ages):.0f} years")

        # Occupation analysis from primary activities
        print(f"\n💼 Occupation Analysis (Primary Activities):")
        occupations = []
        for person_id in infected_person_ids:
            occupation = self.get_person_occupation(person_id)
            occupations.append(occupation)
        occupation_counts = Counter(occupations)
        for occ, count in occupation_counts.most_common(15):
            pct = 100 * count / len(occupations)
            print(f"  {occ}: {count:,} ({pct:.1f}%)")

        # Venue type analysis
        print(f"\n🏢 Where Infections Happened (Venue Types):")
        infection_venue_ids = self.infections['venue_id']
        infection_venues = self.get_venue_info(infection_venue_ids)
        venue_types = [self.decode_bytes(v['type']) for v in infection_venues if v is not None]
        venue_counts = Counter(venue_types)
        for vtype, count in venue_counts.most_common(15):
            pct = 100 * count / len(venue_types)
            print(f"  {vtype}: {count:,} ({pct:.1f}%)")

        return {
            'total_infections': total_infections,
            'ages': ages,
            'occupations': occupation_counts,
            'venue_types': venue_counts
        }

    def plot_age_distribution(self, ax):
        """Plot age distribution of infected people"""
        infected_person_ids = self.infections['person_id']
        infected_people = self.get_person_info(infected_person_ids)
        ages = [p['age'] for p in infected_people if p is not None]

        # Create age bins
        bins = range(0, 101, 5)
        ax.hist(ages, bins=bins, alpha=0.7, color='#e74c3c', edgecolor='black')
        ax.set_xlabel('Age (years)', fontsize=12)
        ax.set_ylabel('Number of Infections', fontsize=12)
        ax.set_title('Age Distribution of Infected Individuals', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)

        # Add mean and median lines
        mean_age = np.mean(ages)
        median_age = np.median(ages)
        ax.axvline(mean_age, color='red', linestyle='--', linewidth=2, label=f'Mean: {mean_age:.1f}')
        ax.axvline(median_age, color='blue', linestyle='--', linewidth=2, label=f'Median: {median_age:.1f}')
        ax.legend()

    def plot_occupation_breakdown(self, ax):
        """Plot infection breakdown by occupation (primary activity venue type)"""
        infected_person_ids = self.infections['person_id']

        # Get occupations from primary activities
        print("  Computing occupations from primary activities...")
        occupations = []
        for person_id in infected_person_ids:
            occupation = self.get_person_occupation(person_id)
            occupations.append(occupation)

        occupation_counts = Counter(occupations)

        # Get top occupations
        top_occupations = occupation_counts.most_common(15)
        labels = [s[0] for s in top_occupations]
        values = [s[1] for s in top_occupations]

        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        y_pos = np.arange(len(labels))

        ax.barh(y_pos, values, color=colors, alpha=0.8, edgecolor='black')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=10)
        ax.set_xlabel('Number of Infections', fontsize=12)
        ax.set_title('Infections by Occupation (Primary Activity)', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')

        # Add value labels
        for i, v in enumerate(values):
            ax.text(v + max(values) * 0.01, i, f' {v}', va='center', fontsize=9)

    def plot_venue_type_breakdown(self, ax):
        """Plot where infections happened by venue type"""
        infection_venue_ids = self.infections['venue_id']
        infection_venues = self.get_venue_info(infection_venue_ids)
        venue_types = [self.decode_bytes(v['type']) for v in infection_venues if v is not None]
        venue_counts = Counter(venue_types)

        # Get top venue types
        top_venues = venue_counts.most_common(15)
        labels = [v[0] for v in top_venues]
        values = [v[1] for v in top_venues]

        colors = plt.cm.tab20(np.linspace(0, 1, len(labels)))
        y_pos = np.arange(len(labels))

        ax.barh(y_pos, values, color=colors, alpha=0.8, edgecolor='black')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=10)
        ax.set_xlabel('Number of Infections', fontsize=12)
        ax.set_title('Where Infections Happened (Venue Types)', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')

        # Add value labels
        for i, v in enumerate(values):
            ax.text(v + max(values) * 0.01, i, f' {v}', va='center', fontsize=9)

    def plot_age_vs_severity(self, ax):
        """Plot age distribution for different outcomes"""
        # Get people who died
        dead_person_ids = self.deaths['person_id']
        dead_people = self.get_person_info(dead_person_ids)
        dead_ages = [p['age'] for p in dead_people if p is not None]

        # Get people hospitalized
        hosp_person_ids = self.hospital_admissions['person_id']
        hosp_people = self.get_person_info(hosp_person_ids)
        hosp_ages = [p['age'] for p in hosp_people if p is not None]

        # Get people in ICU
        icu_person_ids = self.icu_admissions['person_id']
        icu_people = self.get_person_info(icu_person_ids)
        icu_ages = [p['age'] for p in icu_people if p is not None]

        # All infected
        infected_person_ids = self.infections['person_id']
        infected_people = self.get_person_info(infected_person_ids)
        infected_ages = [p['age'] for p in infected_people if p is not None]

        bins = range(0, 101, 10)

        ax.hist([infected_ages, hosp_ages, icu_ages, dead_ages], bins=bins,
                label=['All Infected', 'Hospitalized', 'ICU', 'Deaths'],
                alpha=0.6, color=['#3498db', '#f39c12', '#e67e22', '#e74c3c'])
        ax.set_xlabel('Age (years)', fontsize=12)
        ax.set_ylabel('Count', fontsize=12)
        ax.set_title('Age Distribution by Severity', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

    def plot_epidemic_curve(self, ax):
        """Plot infections over time"""
        times = self.infections['time']
        bins = np.arange(0, times.max() + 1, 1)
        counts, edges = np.histogram(times, bins=bins)

        ax.bar(edges[:-1], counts, width=0.8, alpha=0.7, color='#e74c3c')
        ax.set_xlabel('Time (days)', fontsize=12)
        ax.set_ylabel('Number of Infections', fontsize=12)
        ax.set_title('Epidemic Curve', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)

    def plot_transmission_heatmap(self, ax):
        """Plot transmission matrix by occupation"""
        # Get infector and infectee information
        infections_with_infector = self.infections[self.infections['infector_id'] != -1]

        print("  Computing occupations for transmission matrix...")
        infector_occupations = [self.get_person_occupation(pid) for pid in infections_with_infector['infector_id']]
        infectee_occupations = [self.get_person_occupation(pid) for pid in infections_with_infector['person_id']]

        # Create transmission matrix
        # Limit to top occupations for readability
        all_occupation_counts = Counter(infector_occupations + infectee_occupations)
        top_occupations = [s[0] for s in all_occupation_counts.most_common(10)]

        matrix = np.zeros((len(top_occupations), len(top_occupations)))
        for infector, infectee in zip(infector_occupations, infectee_occupations):
            if infector in top_occupations and infectee in top_occupations:
                i = top_occupations.index(infector)
                j = top_occupations.index(infectee)
                matrix[i, j] += 1

        sns.heatmap(matrix, xticklabels=top_occupations, yticklabels=top_occupations,
                   annot=True, fmt='.0f', cmap='YlOrRd', ax=ax, cbar_kws={'label': 'Transmissions'})
        ax.set_xlabel('Infectee Occupation', fontsize=10)
        ax.set_ylabel('Infector Occupation', fontsize=10)
        ax.set_title('Transmission Matrix by Occupation (Primary Activity)', fontsize=12, fontweight='bold')
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)
        plt.setp(ax.get_yticklabels(), rotation=0, fontsize=8)

    def plot_venue_transmission_heatmap(self, ax):
        """Plot transmission by venue type"""
        infection_venue_ids = self.infections['venue_id']
        infection_venues = self.get_venue_info(infection_venue_ids)
        venue_types = [self.decode_bytes(v['type']) for v in infection_venues if v is not None]

        # Time bins
        times = self.infections['time']
        time_bins = np.arange(0, times.max() + 1, 2)  # 2-day bins

        # Get top venue types
        venue_counts = Counter(venue_types)
        top_venues = [v[0] for v in venue_counts.most_common(10)]

        # Create matrix
        matrix = np.zeros((len(top_venues), len(time_bins) - 1))
        for venue_type, time in zip(venue_types, times):
            if venue_type in top_venues:
                v_idx = top_venues.index(venue_type)
                t_idx = np.searchsorted(time_bins, time, side='right') - 1
                if 0 <= t_idx < len(time_bins) - 1:
                    matrix[v_idx, t_idx] += 1

        sns.heatmap(matrix, yticklabels=top_venues,
                   xticklabels=[f'{int(time_bins[i])}-{int(time_bins[i+1])}' for i in range(len(time_bins)-1)],
                   cmap='YlOrRd', ax=ax, cbar_kws={'label': 'Infections'})
        ax.set_xlabel('Time (days)', fontsize=10)
        ax.set_ylabel('Venue Type', fontsize=10)
        ax.set_title('Infections by Venue Type Over Time', fontsize=12, fontweight='bold')
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right', fontsize=8)

    def plot_hospital_timeline(self, ax):
        """Plot hospital admissions and ICU over time"""
        # Bin by day
        max_time = max(self.hospital_admissions['time'].max() if len(self.hospital_admissions) > 0 else 0,
                      self.icu_admissions['time'].max() if len(self.icu_admissions) > 0 else 0)
        bins = np.arange(0, max_time + 1, 1)

        hosp_counts, _ = np.histogram(self.hospital_admissions['time'], bins=bins)
        icu_counts, _ = np.histogram(self.icu_admissions['time'], bins=bins)

        ax.bar(bins[:-1], hosp_counts, width=0.8, alpha=0.7, color='#f39c12', label='Hospital Admissions')
        ax.bar(bins[:-1], icu_counts, width=0.8, alpha=0.7, color='#e74c3c', label='ICU Admissions')

        ax.set_xlabel('Time (days)', fontsize=12)
        ax.set_ylabel('Number of Admissions', fontsize=12)
        ax.set_title('Hospital & ICU Admissions Over Time', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

    def plot_sex_breakdown(self, ax):
        """Plot infection breakdown by sex"""
        infected_person_ids = self.infections['person_id']
        infected_people = self.get_person_info(infected_person_ids)
        sexes = [self.decode_bytes(p['sex']) for p in infected_people if p is not None]
        sex_counts = Counter(sexes)

        labels = list(sex_counts.keys())
        values = list(sex_counts.values())
        colors = ['#3498db', '#e74c3c']

        ax.pie(values, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        ax.set_title('Infections by Sex', fontsize=14, fontweight='bold')

    def plot_symptom_progression(self, ax):
        """Plot symptom state transitions"""
        transitions = defaultdict(int)
        for event in self.symptom_changes:
            old_sym = self.decode_bytes(event['old_symptom'])
            new_sym = self.decode_bytes(event['new_symptom'])
            transitions[(old_sym, new_sym)] += 1

        # Sort by frequency
        sorted_transitions = sorted(transitions.items(), key=lambda x: x[1], reverse=True)

        # Plot top transitions
        top_n = min(15, len(sorted_transitions))
        labels = [f"{old} → {new}" for (old, new), _ in sorted_transitions[:top_n]]
        values = [count for _, count in sorted_transitions[:top_n]]

        y_pos = np.arange(len(labels))
        colors = plt.cm.viridis(np.linspace(0.3, 0.9, len(labels)))

        ax.barh(y_pos, values, color=colors, alpha=0.8)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_xlabel('Number of Transitions', fontsize=12)
        ax.set_title('Symptom State Transitions', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')

        # Add value labels
        for i, v in enumerate(values):
            ax.text(v + max(values) * 0.01, i, f' {v}', va='center', fontsize=9)

    def plot_transmission_network_stats(self, ax):
        """Plot transmission network statistics (offspring distribution)"""
        infectors = self.infections['infector_id']
        valid_infectors = infectors[infectors != -1]
        offspring_counts = Counter(valid_infectors)

        # Distribution of offspring
        offspring_values = list(offspring_counts.values())
        if offspring_values:
            max_offspring = max(offspring_values)
            counts, bins = np.histogram(offspring_values, bins=range(0, max_offspring + 2))

            ax.bar(bins[:-1], counts, width=0.8, alpha=0.7, color='#3498db')
            ax.set_xlabel('Number of Secondary Infections per Person', fontsize=12)
            ax.set_ylabel('Number of People', fontsize=12)
            ax.set_title('Offspring Distribution (Secondary Infections)',
                        fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)

            # Add statistics text
            mean_offspring = np.mean(offspring_values)
            median_offspring = np.median(offspring_values)
            stats_text = f'Mean: {mean_offspring:.2f}\nMedian: {median_offspring:.1f}'
            ax.text(0.7, 0.95, stats_text, transform=ax.transAxes,
                   fontsize=10, verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    def plot_incubation_period(self, ax):
        """Plot distribution of time from infection to symptom onset"""
        incubation_periods = []

        for infection in self.infections:
            person_id = infection['person_id']
            infection_time = infection['time']

            # Find first symptom change for this person
            person_symptoms = self.symptom_changes[
                self.symptom_changes['person_id'] == person_id
            ]

            if len(person_symptoms) > 0:
                # Sort by time
                person_symptoms = person_symptoms[np.argsort(person_symptoms['time'])]
                first_symptom_time = person_symptoms[0]['time']
                incubation = first_symptom_time - infection_time

                if incubation >= 0:
                    incubation_periods.append(incubation)

        if incubation_periods:
            ax.hist(incubation_periods, bins=30, alpha=0.7, color='#2ecc71', edgecolor='black')
            ax.set_xlabel('Incubation Period (days)', fontsize=12)
            ax.set_ylabel('Number of Cases', fontsize=12)
            ax.set_title('Incubation Period Distribution', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)

            # Add statistics
            mean_inc = np.mean(incubation_periods)
            median_inc = np.median(incubation_periods)
            ax.axvline(mean_inc, color='red', linestyle='--', linewidth=2,
                      label=f'Mean: {mean_inc:.2f} days')
            ax.axvline(median_inc, color='blue', linestyle='--', linewidth=2,
                      label=f'Median: {median_inc:.2f} days')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'No incubation data available', ha='center', va='center',
                   transform=ax.transAxes, fontsize=12)

    def plot_cumulative_infections(self, ax):
        """Plot cumulative infections over time"""
        times = np.sort(self.infections['time'])
        cumulative = np.arange(1, len(times) + 1)

        ax.plot(times, cumulative, linewidth=2, color='#e74c3c')
        ax.set_xlabel('Time (days)', fontsize=12)
        ax.set_ylabel('Cumulative Infections', fontsize=12)
        ax.set_title('Cumulative Infections Over Time', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.fill_between(times, 0, cumulative, alpha=0.3, color='#e74c3c')

    def plot_r0_estimate(self, ax):
        """Plot R0 estimation from seed cases"""
        # Calculate R0 - infections caused by seed cases
        infectors = self.infections['infector_id']
        seed_ids = self.infections['person_id'][self.infections['infector_id'] == -1]

        infections_by_person = Counter(infectors[infectors != -1])
        seed_offspring = [infections_by_person.get(seed_id, 0) for seed_id in seed_ids]

        if seed_offspring:
            ax.hist(seed_offspring, bins=range(0, max(seed_offspring) + 2),
                   alpha=0.7, color='#9b59b6', edgecolor='black')
            ax.set_xlabel('Number of Secondary Infections', fontsize=12)
            ax.set_ylabel('Number of Seed Cases', fontsize=12)
            ax.set_title('R0 Distribution (Seed Cases Only)', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)

            r0_mean = np.mean(seed_offspring)
            r0_median = np.median(seed_offspring)
            ax.axvline(r0_mean, color='red', linestyle='--', linewidth=2,
                      label=f'Mean R0: {r0_mean:.2f}')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'No R0 data available', ha='center', va='center',
                   transform=ax.transAxes, fontsize=12)

    def create_all_visualizations(self, output_dir='outputs'):
        """Create all visualizations"""
        import os
        os.makedirs(output_dir, exist_ok=True)

        print("\n" + "="*70)
        print("GENERATING COMPREHENSIVE VISUALIZATIONS")
        print("="*70)

        # Create comprehensive dashboard with all plots
        fig = plt.figure(figsize=(30, 20))
        gs = fig.add_gridspec(5, 4, hspace=0.4, wspace=0.35)

        axes = [
            fig.add_subplot(gs[0, 0]),  # 1. Epidemic curve
            fig.add_subplot(gs[0, 1]),  # 2. Cumulative infections
            fig.add_subplot(gs[0, 2]),  # 3. Age distribution
            fig.add_subplot(gs[0, 3]),  # 4. Sex breakdown
            fig.add_subplot(gs[1, 0]),  # 5. Occupation breakdown
            fig.add_subplot(gs[1, 1]),  # 6. Venue type breakdown
            fig.add_subplot(gs[1, 2]),  # 7. Age vs severity
            fig.add_subplot(gs[1, 3]),  # 8. Hospital timeline
            fig.add_subplot(gs[2, 0]),  # 9. Symptom progression
            fig.add_subplot(gs[2, 1]),  # 10. Offspring distribution
            fig.add_subplot(gs[2, 2]),  # 11. Incubation period
            fig.add_subplot(gs[2, 3]),  # 12. R0 distribution
            fig.add_subplot(gs[3, :2]), # 13. Transmission matrix by occupation
            fig.add_subplot(gs[3, 2:]), # 14. Venue transmission over time
            fig.add_subplot(gs[4, :]),  # 15. (Reserved for future use)
        ]

        print("\n1. Epidemic curve...")
        self.plot_epidemic_curve(axes[0])

        print("2. Cumulative infections...")
        self.plot_cumulative_infections(axes[1])

        print("3. Age distribution...")
        self.plot_age_distribution(axes[2])

        print("4. Sex breakdown...")
        self.plot_sex_breakdown(axes[3])

        print("5. Occupation breakdown...")
        self.plot_occupation_breakdown(axes[4])

        print("6. Venue type breakdown...")
        self.plot_venue_type_breakdown(axes[5])

        print("7. Age vs severity...")
        self.plot_age_vs_severity(axes[6])

        print("8. Hospital timeline...")
        self.plot_hospital_timeline(axes[7])

        print("9. Symptom progression...")
        self.plot_symptom_progression(axes[8])

        print("10. Offspring distribution...")
        self.plot_transmission_network_stats(axes[9])

        print("11. Incubation period...")
        self.plot_incubation_period(axes[10])

        print("12. R0 distribution...")
        self.plot_r0_estimate(axes[11])

        print("13. Transmission matrix...")
        self.plot_transmission_heatmap(axes[12])

        print("14. Venue transmission over time...")
        self.plot_venue_transmission_heatmap(axes[13])

        # Hide the last unused subplot
        axes[14].axis('off')

        fig.suptitle('Comprehensive Epidemiology Simulation Analysis Dashboard',
                    fontsize=22, fontweight='bold', y=0.998)

        output_path = f'{output_dir}/comprehensive_dashboard.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\n✓ Saved comprehensive dashboard to: {output_path}")
        plt.close()


def main():
    """Main execution"""
    h5_path = '../simulation_events.h5'

    print("\n" + "="*70)
    print("ENHANCED EPIDEMIOLOGY SIMULATION VISUALIZER")
    print("="*70)

    analyzer = EnhancedSimulationAnalyzer(h5_path)
    stats = analyzer.compute_statistics()
    analyzer.create_all_visualizations()

    print("\n" + "="*70)
    print("ANALYSIS COMPLETE!")
    print("="*70)
    print("\nCheck outputs/comprehensive_dashboard.png for all visualizations!")
    print("  - 14 comprehensive plots covering all aspects of the simulation")
    print("  - Demographics, transmission, outcomes, and epidemiology metrics")


if __name__ == '__main__':
    main()
