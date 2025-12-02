import h5py
import numpy as np

def explore_group(group, indent=0):
    """Recursively explore HDF5 groups and datasets"""
    prefix = "  " * indent
    for key in group.keys():
        item = group[key]
        if isinstance(item, h5py.Group):
            print(f"{prefix}{key}/ (Group)")
            explore_group(item, indent + 1)
        elif isinstance(item, h5py.Dataset):
            print(f"{prefix}{key} (Dataset)")
            print(f"{prefix}  Shape: {item.shape}")
            print(f"{prefix}  Dtype: {item.dtype}")

            if len(item) > 0:
                print(f"{prefix}  First 10 rows:")
                print(f"{prefix}    {item[:10]}")

                # Show column info for structured arrays
                if item.dtype.names:
                    print(f"{prefix}  Column info:")
                    for col_name in item.dtype.names:
                        col_data = item[col_name]
                        # Handle string columns differently
                        if np.issubdtype(col_data.dtype, np.bytes_) or np.issubdtype(col_data.dtype, np.str_):
                            print(f"{prefix}    {col_name}: dtype={col_data.dtype}")
                            unique_vals = np.unique(col_data)
                            print(f"{prefix}      Unique values: {unique_vals}")
                        else:
                            print(f"{prefix}    {col_name}: dtype={col_data.dtype}, min={col_data.min()}, max={col_data.max()}")
                            if len(np.unique(col_data)) < 20:
                                print(f"{prefix}      Unique values: {np.unique(col_data)}")
            else:
                print(f"{prefix}  (empty)")
            print()

# Open and explore the HDF5 file
with h5py.File('../simulation_events.h5', 'r') as f:
    print("=== HDF5 File Structure ===\n")
    print(f"Top-level keys: {list(f.keys())}\n")
    explore_group(f)
