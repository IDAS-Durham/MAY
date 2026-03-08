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

1. Create a new CSV file: `{type}s.csv`
2. Include required columns: `name`, `geo_unit`
3. Add optional coordinates: `latitude`, `longitude`
4. Add any type-specific columns you need

The VenueManager will automatically discover and load the file.

## Example

**factories.csv**:
```csv
name,geo_unit,latitude,longitude,production_type,worker_count,area_sqm
Steel Works,E02000414,51.5900,-0.0800,steel,450,15000
Textile Mill,E02000187,51.5320,-0.1350,textiles,180,8000
```

This creates venues of type "factory" with properties: `production_type`, `worker_count`, `area_sqm`.

## Usage

```python
from geography import Geography, VenueManager

# Load geography
geo = Geography(data_dir="data/geography")
geo.load_from_csv()

# Load all venues (auto-discovers all CSV files)
venues = VenueManager(geography=geo, data_dir="data/venues")
venues.load_from_csv()

# Or load specific types
venues.load_from_csv(venue_types=["hospital", "school"])
```

## Notes

- Files starting with `_` are ignored (use for templates or notes)
- Empty cells are treated as missing values
- All property values are accessible via `venue.properties` dict
- Venue types are completely generic - use any name that makes sense for your simulation
