"""
Quick script to inspect the HDF5 world state file.
"""

import h5py
import sys

def inspect_hdf5(filename):
    """Inspect HDF5 file structure and contents."""
    print(f"\n{'='*60}")
    print(f"HDF5 File: {filename}")
    print(f"{'='*60}\n")

    with h5py.File(filename, 'r') as f:
        # Print metadata
        print("METADATA:")
        for key, value in f.attrs.items():
            print(f"  {key}: {value}")

        print("\nFILE STRUCTURE:")

        def print_structure(name, obj):
            indent = "  " * name.count('/')
            if isinstance(obj, h5py.Dataset):
                print(f"{indent}- {name}: {obj.shape} {obj.dtype}")
            elif isinstance(obj, h5py.Group):
                print(f"{indent}+ {name}/")

        f.visititems(print_structure)

        # Print some sample data
        print("\nSAMPLE DATA:")

        # Geography
        if 'geography/names' in f:
            names = f['geography/names'][:]
            print(f"\n  Geography names (first 5): {names[:5].tolist()}")

        # Population
        if 'population/ages' in f:
            ages = f['population/ages'][:]
            print(f"\n  Population ages (first 10): {ages[:10].tolist()}")
            print(f"  Age range: {ages.min():.1f} - {ages.max():.1f}")

        # Venues
        if 'venues/types' in f:
            types = f['venues/types'][:]
            unique_types = set(types.astype(str))
            print(f"\n  Venue types: {unique_types}")

        # Activity map
        if 'relationships/activity_map/activity_names' in f:
            activities = f['relationships/activity_map/activity_names'][:]
            print(f"\n  Activities: {[a.decode() if isinstance(a, bytes) else a for a in activities]}")

            if 'relationships/activity_map/activity_data' in f:
                activity_data = f['relationships/activity_map/activity_data'][:]
                print(f"  Total activity mappings: {len(activity_data):,}")
                print(f"  Sample (first 5):")
                print(f"    (person_id, activity_idx, venue_id, subset_idx)")
                for row in activity_data[:5]:
                    print(f"    {tuple(row)}")

if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "world_state.h5"
    inspect_hdf5(filename)
