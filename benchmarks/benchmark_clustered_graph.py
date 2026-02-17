"""
Benchmark script for social network graph building.

Tests graph construction performance across varying node counts and clustering levels.
Produces timing plots for analysis.

Usage:
    python benchmarks/benchmark_clustered_graph.py
    python benchmarks/benchmark_clustered_graph.py --output results.png
    python benchmarks/benchmark_clustered_graph.py --repeats 5 --algorithms watts_strogatz connected_watts_strogatz
"""

import time
import argparse
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from may.social_networks.clustered_graph import create_clustered_graph, graph_creators


def benchmark_single_run(n_nodes: int, algorithm: str, **kwargs) -> tuple[float, dict]:
    """
    Time a single graph creation and return timing plus graph stats.

    Returns:
        tuple: (elapsed_time, stats_dict)
    """
    start = time.perf_counter()
    G = create_clustered_graph(n_nodes=n_nodes, algorithm=algorithm, **kwargs)
    elapsed = time.perf_counter() - start

    stats = {
        'nodes': G.number_of_nodes(),
        'edges': G.number_of_edges(),
    }
    return elapsed, stats


def run_benchmarks(
    node_counts: list[int],
    clustering_levels: list[float],
    algorithms: list[str],
    repeats: int = 3,
    k: int = 4
) -> dict:
    """
    Run benchmarks across all parameter combinations.

    Returns:
        dict: Results keyed by algorithm, containing timing matrices
    """
    results = {}

    for algorithm in algorithms:
        print(f"\n{'='*60}")
        print(f"Algorithm: {algorithm}")
        print(f"{'='*60}")

        # Check if algorithm supports clustering_level
        supports_clustering = algorithm in ['watts_strogatz', 'connected_watts_strogatz']

        if supports_clustering:
            # 2D results: nodes x clustering_levels
            times = np.zeros((len(node_counts), len(clustering_levels)))
            times_std = np.zeros((len(node_counts), len(clustering_levels)))

            for i, n_nodes in enumerate(node_counts):
                for j, clustering_level in enumerate(clustering_levels):
                    run_times = []
                    for r in range(repeats):
                        elapsed, stats = benchmark_single_run(
                            n_nodes, algorithm, k=k, clustering_level=clustering_level
                        )
                        run_times.append(elapsed)

                    times[i, j] = np.mean(run_times)
                    times_std[i, j] = np.std(run_times)

                    print(f"  n={n_nodes:>6}, clustering={clustering_level:.1f}: "
                          f"{times[i,j]*1000:>8.2f} ms (±{times_std[i,j]*1000:.2f})")

            results[algorithm] = {
                'times': times,
                'times_std': times_std,
                'node_counts': node_counts,
                'clustering_levels': clustering_levels,
                'supports_clustering': True
            }
        else:
            # 1D results: just nodes
            times = np.zeros(len(node_counts))
            times_std = np.zeros(len(node_counts))

            for i, n_nodes in enumerate(node_counts):
                run_times = []
                for r in range(repeats):
                    elapsed, stats = benchmark_single_run(n_nodes, algorithm, d=k)
                    run_times.append(elapsed)

                times[i] = np.mean(run_times)
                times_std[i] = np.std(run_times)

                print(f"  n={n_nodes:>6}: {times[i]*1000:>8.2f} ms (±{times_std[i]*1000:.2f})")

            results[algorithm] = {
                'times': times,
                'times_std': times_std,
                'node_counts': node_counts,
                'supports_clustering': False
            }

    return results


def plot_results(results: dict, output_path: Path | None = None):
    """
    Create visualization of benchmark results.
    """
    # Count how many plots we need
    clustering_algorithms = [alg for alg, data in results.items() if data['supports_clustering']]
    other_algorithms = [alg for alg, data in results.items() if not data['supports_clustering']]

    n_plots = len(clustering_algorithms) + (1 if other_algorithms else 0) + 1  # +1 for comparison

    fig, axes = plt.subplots(1, n_plots, figsize=(6 * n_plots, 5))
    if n_plots == 1:
        axes = [axes]

    plot_idx = 0
    colors = plt.cm.viridis(np.linspace(0, 1, 10))

    # Plot clustering algorithms (one plot per algorithm, lines per clustering level)
    for algorithm in clustering_algorithms:
        ax = axes[plot_idx]
        data = results[algorithm]
        node_counts = data['node_counts']
        clustering_levels = data['clustering_levels']
        times = data['times']
        times_std = data['times_std']

        for j, cl in enumerate(clustering_levels):
            color = colors[int(j * 9 / (len(clustering_levels) - 1))] if len(clustering_levels) > 1 else colors[4]
            ax.errorbar(
                node_counts,
                times[:, j] * 1000,
                yerr=times_std[:, j] * 1000,
                marker='o',
                label=f'clustering={cl:.1f}',
                color=color,
                capsize=3
            )

        ax.set_xlabel('Number of Nodes')
        ax.set_ylabel('Time (ms)')
        ax.set_title(f'{algorithm}')
        ax.legend(loc='upper left', fontsize=8)
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.grid(True, alpha=0.3)
        plot_idx += 1

    # Plot non-clustering algorithms together
    if other_algorithms:
        ax = axes[plot_idx]
        for i, algorithm in enumerate(other_algorithms):
            data = results[algorithm]
            node_counts = data['node_counts']
            times = data['times']
            times_std = data['times_std']

            ax.errorbar(
                node_counts,
                times * 1000,
                yerr=times_std * 1000,
                marker='o',
                label=algorithm,
                capsize=3
            )

        ax.set_xlabel('Number of Nodes')
        ax.set_ylabel('Time (ms)')
        ax.set_title('Other Algorithms')
        ax.legend(loc='upper left', fontsize=8)
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.grid(True, alpha=0.3)
        plot_idx += 1

    # Comparison plot: all algorithms at middle clustering level
    ax = axes[plot_idx]
    for algorithm, data in results.items():
        node_counts = data['node_counts']
        if data['supports_clustering']:
            mid_idx = len(data['clustering_levels']) // 2
            times = data['times'][:, mid_idx]
            times_std = data['times_std'][:, mid_idx]
            label = f"{algorithm} (cl=0.5)"
        else:
            times = data['times']
            times_std = data['times_std']
            label = algorithm

        ax.errorbar(
            node_counts,
            times * 1000,
            yerr=times_std * 1000,
            marker='o',
            label=label,
            capsize=3
        )

    ax.set_xlabel('Number of Nodes')
    ax.set_ylabel('Time (ms)')
    ax.set_title('Algorithm Comparison')
    ax.legend(loc='upper left', fontsize=8)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"\nPlot saved to: {output_path}")

    plt.show()


def main():
    parser = argparse.ArgumentParser(description='Benchmark clustered graph creation')
    parser.add_argument(
        '--nodes',
        type=int,
        nargs='+',
        default=[100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000, 5000000, 10000000, 50000000, 100000000],
        help='Node counts to test'
    )
    parser.add_argument(
        '--clustering-levels',
        type=float,
        nargs='+',
        default=[0.1, 0.7],
        help='Clustering levels to test (0.0 to 1.0)'
    )
    parser.add_argument(
        '--algorithms',
        type=str,
        nargs='+',
        default=['watts_strogatz', 'connected_watts_strogatz', 'barabasi_albert', 'random_regular_graph'],
        choices=list(graph_creators.keys()),
        help='Algorithms to benchmark'
    )
    parser.add_argument(
        '--repeats',
        type=int,
        default=3,
        help='Number of repeats per configuration'
    )
    parser.add_argument(
        '--k',
        type=int,
        default=4,
        help='k parameter (neighbors) for graph algorithms'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Output path for plot image'
    )

    args = parser.parse_args()

    print("Social Network Graph Benchmark")
    print("=" * 60)
    print(f"Node counts: {args.nodes}")
    print(f"Clustering levels: {args.clustering_levels}")
    print(f"Algorithms: {args.algorithms}")
    print(f"Repeats per config: {args.repeats}")
    print(f"k (neighbors): {args.k}")

    results = run_benchmarks(
        node_counts=args.nodes,
        clustering_levels=args.clustering_levels,
        algorithms=args.algorithms,
        repeats=args.repeats,
        k=args.k
    )

    print("\n" + "=" * 60)
    print("Benchmark complete. Generating plot...")

    plot_results(results, args.output)


if __name__ == "__main__":
    main()
