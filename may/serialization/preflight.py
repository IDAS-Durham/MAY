"""
Compare the serialization schema with the venue data before the world is built.

The HDF5 export runs last, so a property the schema names and the venue files
omit surfaces once the rest of the run has been paid for. Reading one header per
venue file at the start costs a few milliseconds and reports the same mismatch
while there is still time to act on it.

The comparison covers venue types loaded from a file, where both sides of it
exist on disk. Types assembled during the run, and the person properties, take
their values from the build itself and are checked as the export writes them.
"""

import os

import pandas as pd

from may.utils.stacked_input import as_path_list


def venue_property_gaps(serialization_config, venue_types, venues_data_dir):
    """
    Configured venue properties whose name is missing from the venue files.

    Args:
        serialization_config: Parsed serialization YAML.
        venue_types: Parsed venue types (name -> type config), as in `VenueConfig`.
        venues_data_dir: Directory the venue filenames are relative to.

    Returns:
        List of (venue_type, property, columns_available), one entry per
        property whose name is absent from the header of every file that
        supplies the type. columns_available holds the names those headers do
        carry, sorted.
    """
    configured = ((serialization_config.get("venues") or {}).get("types")) or {}

    gaps = []
    for venue_type, type_settings in configured.items():
        properties = (type_settings or {}).get("properties") or []
        spec = venue_types.get(venue_type)
        if not isinstance(spec, dict) or not spec.get("filename"):
            # The run assembles this type, so its properties appear once the
            # build reaches them.
            continue

        paths = [
            os.path.join(venues_data_dir, p)
            for p in as_path_list(spec["filename"], f"venue type '{venue_type}'")
        ]
        present = [p for p in paths if os.path.exists(p)]
        if not present:
            continue

        columns = set()
        for path in present:
            columns |= set(pd.read_csv(path, nrows=0).columns)

        for prop in properties:
            if prop not in columns:
                gaps.append((venue_type, prop, sorted(columns)))
    return gaps

