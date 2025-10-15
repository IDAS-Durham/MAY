# June Zero Project Documentation

## Project Overview

June Zero is a simulation project that models geographical hierarchies and populations. The system is designed to be **completely generic** and work with any geographical structure, past or present, anywhere in the world.

## Geographical Hierarchy

### Level Definitions

The project uses three levels of geographical units:

- **S.G.U (Small Geographical Unit)**: The most granular level
  - Typically represents 100-300 people
  - Example: UK Output Areas (OAs), neighborhood blocks, small villages

- **M.G.U (Medium Geographical Unit)**: The intermediate level
  - Typically represents 2,000-3,000 people (can be 5,000-15,000 in some contexts)
  - Example: UK Middle Layer Super Output Areas (MSOAs), districts, towns

- **L.G.U (Large Geographical Unit)**: The highest level
  - Represents regions, boroughs, or cities
  - Example: London, provinces, counties

### Why Generic Names?

We use **generic level names** (S.G.U, M.G.U, L.G.U) instead of specific terms like "Output Area" or "MSOA" because:

1. **Universality**: The system should work for any geography worldwide
2. **Historical Flexibility**: Geography definitions change over time (e.g., census boundaries are redrawn)
3. **Adaptability**: Users can map these generic levels to their specific geography
4. **Abstraction**: The simulation logic doesn't need to know about specific administrative boundaries

### Data Structure

The project expects three CSV files in `data/geography/`:

1. **hierarchy.csv**: Defines parent-child relationships
   ```csv
   SGU,MGU,LGU
   E00004320,E02000173,London
   E00004321,E02000173,London
   ```

2. **coord_sgu.csv**: Coordinates for Small Geographical Units
   ```csv
   SGU,latitude,longitude
   E00004320,51.5497,-0.17438
   E00004321,51.5502,-0.17913
   ```

3. **coord_mgu.csv**: Coordinates for Medium Geographical Units
   ```csv
   MGU,latitude,longitude
   E02000173,51.54971,-0.17294
   E02000187,51.5316,-0.13087
   ```

Additional coordinate files can be added for other levels (e.g., `coord_lgu.csv`).

## Development Environment

### Conda Environment: JuneZero

The project uses a dedicated Anaconda environment named **JuneZero**.

**Environment Location**: `/opt/homebrew/anaconda3/envs/JuneZero`

**Activate the environment**:
```bash
conda activate JuneZero
```

**Installed Packages**:
- Python 3.13.7
- numpy 2.2.5
- numba 0.61.2
- pandas 2.3.3
- Additional dependencies: llvmlite, openblas, etc.

**Installing New Packages**:
```bash
# Always activate the environment first
conda activate JuneZero

# Install packages
conda install -y package_name

# Or with pip
pip install package_name
```

### Conda Initialization

The conda installation is located at: `/opt/homebrew/anaconda3/`

To initialize conda in a new shell:
```bash
source /opt/homebrew/anaconda3/etc/profile.d/conda.sh
```

## Project Structure

```
june_zero/
├── PROJECT.md                    # This file
├── config.yaml                   # Configuration file
├── create_world.py              # Main world creation script
├── config_loader.py             # Config and argument parsing
├── geography/                   # Geography module
│   ├── __init__.py
│   ├── geography.py            # Geography classes
│   └── venue.py                # Venue classes
├── data/
│   ├── geography/              # Geography data files
│   │   ├── hierarchy.csv       # Parent-child relationships
│   │   ├── coord_sgu.csv      # SGU coordinates
│   │   └── coord_mgu.csv      # MGU coordinates
│   └── venues/                 # Venue data files (type-specific CSVs)
│       ├── hospitals.csv
│       ├── schools.csv
│       ├── companies.csv
│       └── ...
└── filters/                    # Geography filter files
    └── example_mgu.txt
```

## Geography Module

### Classes

#### `GeographicalUnit`
Represents a single geographical unit at any level.

**Attributes**:
- `id`: Unique numeric ID (auto-generated)
- `name`: Unique identifier (e.g., "E00004320", "London")
- `level`: "SGU", "MGU", or "LGU"
- `coordinates`: Tuple of (latitude, longitude) or None
- `parent`: Reference to parent unit
- `children`: List of child units
- `venues`: List of venues in this unit
- `properties`: Dict for extensible metadata

**Methods**:
- `add_child(child)`: Add a child unit
- `add_venue(venue)`: Add a venue to this unit
- `get_venues_by_type(venue_type)`: Get venues of specific type in this unit
- `get_ancestors()`: Get all parent units up the hierarchy
- `get_descendants(level=None)`: Get all child units, optionally filtered by level

#### `Geography`
Main container for loading and managing geographical hierarchies.

**Attributes**:
- `units`: Dict of all units by name
- `units_by_id`: Dict of all units by ID
- `units_by_level`: Dict organizing units by level
- `levels`: List of level names (default: ["SGU", "MGU", "LGU"])
- `data_dir`: Path to geography data files

**Methods**:
- `load_from_csv()`: Load all geography data from CSV files
- `get_unit(name)`: Get a specific unit by name
- `get_unit_by_id(id)`: Get a specific unit by ID
- `get_units_by_level(level)`: Get all units at a specific level
- `get_all_units()`: Get all units as dict
- `get_all_units_list()`: Get all units as list sorted by ID
- `get_roots()`: Get all root units (units with no parent)

### Usage Example

```python
from geography import Geography

# Create and load geography
geo = Geography(data_dir="data/geography")
geo.load_from_csv()

# Get a specific unit
unit = geo.get_unit("E00004320")
print(f"Unit: {unit}")
print(f"ID: {unit.id}, Name: {unit.name}")
print(f"Coordinates: {unit.coordinates}")
print(f"Parent: {unit.parent}")

# Get all units at a level
sgu_units = geo.get_units_by_level("SGU")
print(f"Total SGU units: {len(sgu_units)}")

# Navigate hierarchy
for ancestor in unit.get_ancestors():
    print(f"Ancestor: {ancestor}")

# Get root units and their structure
for root in geo.get_roots():
    print(f"{root.name}: {len(root.children)} direct children")
    sgu_descendants = root.get_descendants("SGU")
    print(f"  Total SGU descendants: {len(sgu_descendants)}")
```

### Adapting to Different Geographies

The system can be adapted to any geography by:

1. **Custom Level Names**:
   ```python
   geo = Geography(
       data_dir="data/geography",
       levels=["village", "district", "province"]
   )
   ```

2. **Custom CSV Structure**: Prepare CSV files with the same format but different codes/names

3. **Additional Properties**: Use the `properties` dict on `GeographicalUnit` to store custom metadata

## Venue System

Venues are places where people live, work, learn, or receive services (hospitals, schools, companies, etc.). The venue system is designed to be completely generic and extensible.

### Classes

#### `Venue`
Represents a place within a geographical unit.

**Attributes**:
- `id`: Unique numeric ID (auto-generated)
- `name`: Name of the venue
- `type`: Type of venue (e.g., "hospital", "school", "company")
- `geographical_unit`: Reference to the GeographicalUnit containing this venue
- `coordinates`: Optional (latitude, longitude) tuple
- `properties`: Dict for venue-specific data (beds, staff_count, etc.)

#### `VenueManager`
Manages all venues and their relationships to geographical units.

**Attributes**:
- `geography`: Reference to Geography object
- `venues`: Dict of all venues by name
- `venues_by_id`: Dict of all venues by ID
- `venues_by_type`: Dict organizing venues by type
- `filter_by_geography`: Auto-filter venues to loaded geo units

**Methods**:
- `load_from_csv(venue_types=None)`: Load venues from CSV files (auto-discovers all types)
- `load_venue_type_from_csv(venue_type, filename=None)`: Load specific venue type
- `get_venue(name)`: Get a venue by name
- `get_venue_by_id(id)`: Get a venue by ID
- `get_venues_by_type(venue_type)`: Get all venues of a specific type
- `get_venue_types()`: Get list of all venue types

### Venue Data Structure

Each venue type has its own CSV file with type-specific columns:

**Required columns**:
- `name`: Venue name
- `geo_unit`: Name of geographical unit

**Optional columns**:
- `latitude`, `longitude`: Specific coordinates
- Any other columns become properties (e.g., `beds`, `staff_count`, `industry`)

**Example** (`hospitals.csv`):
```csv
name,geo_unit,latitude,longitude,beds,icu_beds,emergency_dept
St Mary's Hospital,E02000173,51.5155,-0.1677,300,25,yes
Royal London Hospital,E02000414,51.5179,-0.0607,800,80,yes
```

**File naming**: `{type}s.csv` → infers type (e.g., `hospitals.csv` → type "hospital")

### Usage Example

```python
from geography import Geography, VenueManager

# Load geography
geo = Geography(data_dir="data/geography")
geo.load_from_csv()

# Load venues (auto-discovers all CSV files in data/venues/)
venues = VenueManager(geography=geo, data_dir="data/venues")
venues.load_from_csv()

# Get venue by name
hospital = venues.get_venue("St Mary's Hospital")
print(hospital.properties["beds"])  # 300

# Get all hospitals
all_hospitals = venues.get_venues_by_type("hospital")

# Get venues in a geographical unit
unit = geo.get_unit("E02000173")
print(f"{unit.name} has {len(unit.venues)} venues")
hospitals_in_unit = unit.get_venues_by_type("hospital")
```

## Configuration and Filtering

The project uses `config.yaml` for configuration and supports command-line argument overrides.

### Geography Filtering

Filter which geographical units to load:

**Config file** (`config.yaml`):
```yaml
geography:
  data_dir: "data/geography"
  load_all: false

  filter:
    level: MGU              # Filter by level: SGU, MGU, or LGU
    codes: []               # Inline codes for small lists
    file: filters/my_mgus.txt  # Or file for large lists
```

**Command line**:
```bash
# Load all
python create_world.py --load-all

# Filter by MGU
python create_world.py --mgu E02000173,E02000187

# Filter by MGU from file
python create_world.py --mgu-file filters/my_mgus.txt

# Filter by LGU
python create_world.py --lgu London
```

Venues automatically filter to match loaded geographical units.

## Random Seed Management

The project uses fixed random seeds for reproducibility:

```python
set_random_seed(0)  # Sets seeds for numpy, random, and numba
```

This ensures deterministic behavior across runs.

## Logging

The project uses Python's logging module with output to stdout:

- **Main logger**: `create_world`
- **Geography logger**: `geography`
- **Venue logger**: `venue`
- **Config loader logger**: `config_loader`
- **Log level**: INFO
- **Output**: Console only (no log file)

## Running the Simulation

To create a world:

```bash
# Activate environment
conda activate JuneZero

# Run with default config
python create_world.py

# Or with filters
python create_world.py --mgu-file filters/example_mgu.txt
```

## Important Notes

- **Generic Design**: Always maintain the generic nature of the code
- **Extensibility**: Use the `properties` dict for additional metadata rather than hardcoding attributes
- **Performance**: The system is designed to handle thousands of small geographical units efficiently
- **Reproducibility**: Always use the random seed functions for deterministic behavior
