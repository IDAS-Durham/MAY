# Venues Data Directory

This directory contains CSV files defining venues (places where people live, work, learn, or receive services).

## File Convention

Each venue type has its own CSV file with type-specific columns:

- `hospitals.csv` → venue type: "hospital"
- `schools.csv` → venue type: "school"
- `companies.csv` → venue type: "company"
- `care_homes.csv` → venue type: "care_home"
- `prisons.csv` → venue type: "prison"
- `universities.csv` → venue type: "university"

**Naming Pattern**: `{type}s.csv` where the type is singular (e.g., `hospital` → `hospitals.csv`)

## Required Columns

Every venue CSV must have:
- **name**: Unique name of the venue
- **geo_unit**: Name of the geographical unit where the venue is located

## Optional Standard Columns

- **latitude**: Latitude coordinate (if not provided, inherits from geo_unit)
- **longitude**: Longitude coordinate (if not provided, inherits from geo_unit)

## Type-Specific Columns

All other columns become properties specific to that venue type. Examples:

### Hospitals
- `beds`: Number of beds
- `icu_beds`: Number of ICU beds
- `emergency_dept`: yes/no

### Schools
- `school_level`: primary/secondary
- `student_capacity`: Maximum students
- `staff_count`: Number of staff

### Companies
- `industry`: Industry sector
- `employee_count`: Number of employees
- `office_space_sqm`: Office space in square meters

### Care Homes
- `resident_capacity`: Maximum residents
- `staff_count`: Number of staff
- `dementia_care`: yes/no

### Prisons
- `prisoner_capacity`: Maximum prisoners
- `staff_count`: Number of staff
- `security_level`: high/medium/low

### Universities
- `student_capacity`: Maximum students
- `staff_count`: Number of staff
- `campus_area_hectares`: Campus area

## Creating New Venue Types

To add a new venue type:

1. Create a new CSV file: `{type}s.csv` with your venue data
2. Add the venue type to `venues_config.yaml`:

```yaml
venue_types:
  # ... existing types ...

  factory:
    enabled: true
    filename: factories.csv
    description: "Manufacturing facilities"
```

3. Include required columns: `name`, `geo_unit`
4. Add optional coordinates: `latitude`, `longitude`
5. Add any type-specific columns you need

## Example

**factories.csv**:
```csv
name,geo_unit,latitude,longitude,production_type,worker_count,area_sqm
Steel Works,E02000414,51.5900,-0.0800,steel,450,15000
Textile Mill,E02000187,51.5320,-0.1350,textiles,180,8000
```

This creates venues of type "factory" with properties: `production_type`, `worker_count`, `area_sqm`.

## Configuration

Venues are defined through a YAML configuration file. This provides:
- Clear documentation of which venue types are enabled
- Easy enabling/disabling of venue types
- Better control over venue loading
- Single source of truth for venue configuration

**venues_config.yaml**:
```yaml
venue_types:
  hospital:
    enabled: true
    filename: hospitals.csv
    description: "Healthcare facilities"

  school:
    enabled: true
    filename: schools.csv
    description: "Educational institutions"

  company:
    enabled: false  # Temporarily disabled
    filename: companies.csv

settings:
  filter_by_geography: true
```

**Usage**:
```python
from geography import Geography, VenueManager

# Load geography
geo = Geography(data_dir="data/geography")
geo.load_from_csv()

# Load venues from YAML config
venues = VenueManager(geography=geo, data_dir="data/venues")
venues.load_from_yaml_config("venues_config.yaml")
```

The main `config.yaml` file specifies which YAML configuration to use:
```yaml
venues:
  config_file: "venues_config.yaml"
```

## Notes

- Files starting with `_` are ignored (use for templates or notes)
- Empty cells are treated as missing values
- All property values are accessible via `venue.properties` dict
- Venue types are completely generic - use any name that makes sense for your simulation
