"""
Profile script for world creation to identify performance bottlenecks.
"""
import cProfile
import pstats
import io
from pstats import SortKey

# Run the main world creation with profiling
if __name__ == "__main__":
    profiler = cProfile.Profile()

    print("Starting profiling...")
    profiler.enable()

    # Import and run main (do this AFTER enabling profiler)
    from create_world_households import main
    world = main()

    profiler.disable()
    print("\n" + "="*80)
    print("PROFILING RESULTS")
    print("="*80 + "\n")

    # Create a stats object
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)

    # Sort by cumulative time (time spent in function + subfunctions)
    print("="*80)
    print("TOP 30 FUNCTIONS BY CUMULATIVE TIME")
    print("="*80)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats(30)
    print(s.getvalue())

    # Sort by internal time (time spent in function only, excluding subfunctions)
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    print("\n" + "="*80)
    print("TOP 30 FUNCTIONS BY INTERNAL TIME (self time)")
    print("="*80)
    stats.sort_stats(SortKey.TIME)
    stats.print_stats(30)
    print(s.getvalue())

    # Focus on specific modules
    print("\n" + "="*80)
    print("POPULATION MODULE BREAKDOWN")
    print("="*80)
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats('population')
    print(s.getvalue())

    print("\n" + "="*80)
    print("DISTRIBUTOR MODULE BREAKDOWN")
    print("="*80)
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats('distributor')
    print(s.getvalue())

    print("\n" + "="*80)
    print("VENUE MANAGER BREAKDOWN")
    print("="*80)
    s = io.StringIO()
    stats = pstats.Stats(profiler, stream=s)
    stats.sort_stats(SortKey.CUMULATIVE)
    stats.print_stats('venue_manager')
    print(s.getvalue())

    # Save detailed stats to file for later analysis
    with open('profile_output.txt', 'w') as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats()

    print("\nDetailed profile saved to: profile_output.txt")
    print("\nTo visualize with snakeviz: pip install snakeviz && snakeviz profile_output.txt")
