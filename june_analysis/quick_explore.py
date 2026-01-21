"""Quick check of what's in the simulation_events.h5 file"""
import h5py

with h5py.File('../simulation_events.h5', 'r') as f:
    print("=" * 70)
    print("SIMULATION_EVENTS.H5 CONTENTS")
    print("=" * 70)

    print("\nTop-level groups:", list(f.keys()))

    if 'events' in f:
        print("\n/events/ datasets:")
        for key in f['events'].keys():
            ds = f['events'][key]
            print(f"  - {key}: {len(ds):,} records")
            print(f"    Fields: {list(ds.dtype.names)}")

    if 'lookups' in f:
        print("\n/lookups/ datasets:")
        for key in f['lookups'].keys():
            ds = f['lookups'][key]
            print(f"  - {key}: {len(ds):,} records")
            print(f"    Fields: {list(ds.dtype.names)}")

    print("\n" + "=" * 70)
