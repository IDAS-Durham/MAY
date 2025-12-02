import h5py
import numpy as np

def explore_group(group, indent=0, max_rows=10):
    """Recursively explore HDF5 groups and datasets"""
    prefix = "  " * indent
    for key in group.keys():
        item = group[key]
        if isinstance(item, h5py.Group):
            print(f"{prefix}{key}/ (Group)")
            explore_group(item, indent + 1, max_rows)
        elif isinstance(item, h5py.Dataset):
            print(f"{prefix}{key} (Dataset)")
            print(f"{prefix}  Shape: {item.shape}")
            print(f"{prefix}  Dtype: {item.dtype}")

            if len(item) > 0:
                # Show first few rows
                n_show = min(max_rows, len(item))
                print(f"{prefix}  First {n_show} rows:")
                if item.dtype.names:
                    # Structured array
                    for i in range(n_show):
                        print(f"{prefix}    {item[i]}")
                else:
                    # Regular array
                    print(f"{prefix}    {item[:n_show]}")

                # Show column info for structured arrays
                if item.dtype.names:
                    print(f"{prefix}  Column info:")
                    for col_name in item.dtype.names:
                        col_data = item[col_name]
                        # Handle string columns differently
                        if np.issubdtype(col_data.dtype, np.bytes_) or np.issubdtype(col_data.dtype, np.str_):
                            print(f"{prefix}    {col_name}: dtype={col_data.dtype}")
                            unique_vals = np.unique(col_data)
                            if len(unique_vals) < 30:
                                print(f"{prefix}      Unique values ({len(unique_vals)}): {unique_vals[:20]}")
                            else:
                                print(f"{prefix}      Unique values: {len(unique_vals)} unique values")
                        else:
                            print(f"{prefix}    {col_name}: dtype={col_data.dtype}, min={col_data.min()}, max={col_data.max()}")
                            unique_count = len(np.unique(col_data))
                            if unique_count < 30:
                                print(f"{prefix}      Unique values ({unique_count}): {np.unique(col_data)}")
            else:
                print(f"{prefix}  (empty)")
            print()

# Open and explore the world_state HDF5 file
print("="*70)
print("EXPLORING world_state.h5")
print("="*70)
with h5py.File('../world_state.h5', 'r') as f:
    print(f"\nTop-level keys: {list(f.keys())}\n")
    explore_group(f, max_rows=5)
