# MAY: open-source world builder
A high-performance population simulation framework for modeling geographical hierarchies and distributing people across venues (households, schools, hospitals, etc.). **Completely generic** - works with any geographical structure worldwide, past or present.

## About
See [here](about.md) for more info about MAY.


## Features

- **Universal Geography System** - Generic S.G.U/M.G.U/L.G.U levels work with any administrative boundaries
- **Precise Demographics** - Age/sex distributions per smallest geographical unit
- **Flexible Venue System** - Households, care homes, student dorms, prisons, schools, hospitals, and more
- **Multi-Pass Distribution** - Intelligent household expansion with configurable thresholds
- **Extensible Design** - Easy to add new venue types and distribution strategies

## Project Structure

```
MAY/
├── may/                          # Core framework. Should not need to be changed when using a new world.
│   ├── geography/               # Geography and venue classes
│   ├── population/              # Population and person classes
│   ├── distributor/             # Generic distribution system
│   └── stats/                   # Statistics and reporting
├── world_specific_code/         # Code specific to the world being created. Will need edited for each new world. 
│   ├── household_distributors/  # Household distribution
│   ├── care_home_distributor/   # Care home distribution
│   ├── student_dorms/           # Student dorm distribution
│   └── prisons/                 # Prison distribution
├── data/                        # Data used to create the world (e.g. census information). 
│   ├── geography/               # Hierarchy and coordinates
│   ├── population/              # Demographics (age/sex)
│   ├── venues/                  # Venue data (schools, hospitals, etc.)
│   └── households/              # Household compositions
└── create_world_households.py   # Main entry point
```

## Key Concepts

### Geography Hierarchy
The Geographical Units are able to expand or contract, creating a tree-structure that can be as large as desired. 

The default levels are
- **SGU** (Smallest Geographical Unit) - Base level where people are generated
- **MGU** (Medium Geographical Unit) - Middle administrative level
- **LGU** (Largest Geographical Unit) - Top level (e.g., country, region)
Additional levels can be created simply by adding them to the hierarchy data file. 

Parent-child tree structure: `SGU → MGU → LGU`

### Venue System
For each activity a Person is given, they need to be assigned a suitable Venue and Subset.
The Venues are the locations the person will go to in order to do that activity.
Subsets are a descriptor used in the creation of the world, to help decide what attributes people have giving them access to a venue.
For example, if for a given venue (e.g. a household) we know the breakdown of members by age category (e.g. 'kids', 'adults', 'elderly'), then the subsets would correspond to these age categories.
If, however, a given venue has a certain number of members by activity they do there (e.g. a known number of inmates and staff, for prisons) then the subsets would correspond to those categories.
Subsets are used to help make sure the composition of people who can go to a venue are accurate when building the world.

Venues contain **Subsets** (groups within venues):
- Household: `['kids', 'independent children', 'adults', 'elderly']`
- Care Home: Age/sex-based subsets
- Prison: `['inmates', 'staff']`

People are assigned to Subsets, not directly to Venues.

These subsets will then be mapped to interaction_sets, which are decided by the interaction dynamics.


### Distribution Process
1. Load geography and demographics
2. Generate people with precise age/sex distributions per SGU
3. Load venues and create subsets
4. Distribute people using multi-pass algorithm:
   - Student dorms → Care homes → Households (with a little expansion) → Prisons → Households (final expansion)

## Data Format

### Geography (`data/geography/`)
- `hierarchy.csv`: SGU, MGU, LGU columns
- `coord_sgu.csv`: SGU, latitude, longitude
- `coord_mgu.csv`: MGU, latitude, longitude

### Population (`data/population/`)
- `demographics_male.csv`: Rows=geo_units, Columns=ages (0-100)
- `demographics_female.csv`: Same structure

### Venues (`data/venues/`)
Each `{type}s.csv` requires:
- `geo_unit` (required)
- `name` (required)
- `latitude`, `longitude` (optional)
- Custom properties as needed

### Households (`data/households/`)
- `households.csv` with `composition` column (e.g., `'0 0 2 0'` = 2 adults, no kids)
- Format: `kids independent_children adults elderly`

## Testing

```bash
# Run all tests
pytest

# Run specific module
pytest tests/test_units/may/population/

# Verbose output
pytest -v
```

## Performance

Current benchmarks (95,231 people, 36,443 households):
- **Total runtime**: ~1.5s
- Geography loading: ~0.01s
- Population generation: ~0.3s
- Venue generation: ~0.3s
- Venue distribution: ~0.8s

## Development

### Adding a New Venue Type

1. Create CSV in `data/venues/{type}s.csv`
2. Create `{Type}SubsetDistributor` in `world_specific_code/`
3. Create `{Type}Distributor` extending `Distributor`
4. Add to `create_world_households.py` distribution chain

### Adding Custom Person Properties

```python
person = Person(age=30, sex='male', geographical_unit=sgu, activities=['home'])
person.properties['occupation'] = 'teacher'
person.properties['income'] = 50000
```

## Requirements

- Python 3.13+
- pandas
- numpy
- numba (for optimizations)

## License

[Add license information]

## Citation

[Add citation information if applicable]





