# Simplified Activity Assignment Framework

## Overview

This framework provides a simple, modular way to assign activities to Person objects during population generation. Activities are assigned using two types of rules:

1. **Independent Rules**: Activities that can be assigned independently (person can have multiple)
2. **Choice Rules**: Mutually exclusive activities where person gets ONE from a set of options

## Key Concepts

### Independent Rules

Independent rules assign activities that can coexist. A person can have multiple activities from independent rules.

**Example**: A person can have `home`, `education`, and `leisure` all at once.

```python
# Everyone gets home
assigner.add_independent_rule('home', lambda p: True, 1.0)

# School-age children get education (95% probability)
assigner.add_independent_rule('education', lambda p: 5 <= p.age <= 18, 0.95)

# Adults get leisure (70% probability)
assigner.add_independent_rule('leisure', lambda p: p.age >= 18, 0.70)
```

### Choice Rules

Choice rules define mutually exclusive options. A person will be assigned **exactly ONE** activity from the options (or none if condition doesn't apply).

**Example**: Employment status - a person is either employed, unemployed, or not in labor force.

```python
# Working age people get ONE employment status
assigner.add_choice_rule(
    choice_name='employment_status',
    condition=lambda p: 19 <= p.age <= 64,
    options=[
        ('employed', 0.75),           # 75% chance
        ('unemployed', 0.15),         # 15% chance
        ('not_in_labor_force', 0.10)  # 10% chance
    ]
)
```

## Basic Usage

### Creating an Assigner Programmatically

```python
from may.population.activity_assigner import ActivityAssigner

assigner = ActivityAssigner()

# Add independent rules
assigner.add_independent_rule('home', lambda p: True, 1.0)
assigner.add_independent_rule('education', lambda p: 5 <= p.age <= 18, 0.95)

# Add choice rules
assigner.add_choice_rule(
    choice_name='employment',
    condition=lambda p: 19 <= p.age <= 64,
    options=[
        ('employed', 0.80),
        ('unemployed', 0.20)
    ]
)

# Assign activities to a person
activities = assigner.assign_activities(person)
```

### Loading from YAML

```yaml
# config.yaml
independent_rules:
  - activity: home
    condition: {}
    probability: 1.0

  - activity: education
    condition:
      age: [5, 18]
    probability: 0.95

choice_rules:
  - name: employment_status
    condition:
      age: [19, 64]
    options:
      - activity: employed
        weight: 0.75
      - activity: unemployed
        weight: 0.25
```

```python
assigner = ActivityAssigner.from_yaml('config.yaml')
activities = assigner.assign_activities(person)
```

### Using Pre-built Assigners

```python
from may.population.activity_assigner import (
    create_simple_assigner,
    create_modern_assigner,
    create_medieval_assigner
)

# For a simple modern world
assigner = create_simple_assigner()

# For a detailed modern world
assigner = create_modern_assigner()

# For a medieval world
assigner = create_medieval_assigner()
```

## How It Works

When `assign_activities(person)` is called:

1. **Apply all independent rules**
   - Each rule checks if its condition applies
   - If yes, check probability
   - If passes, add the activity
   - Result: Person can get 0, 1, or many activities

2. **Apply all choice rules**
   - Each choice checks if its condition applies
   - If yes, select ONE option based on weights
   - Add the selected activity
   - Result: Person gets 0 or 1 activity per choice rule

3. **Return combined list**
   - All assigned activities are returned

## Examples

### Example 1: Basic Modern World

```python
assigner = ActivityAssigner()

# Independent: Everyone has home
assigner.add_independent_rule('home', lambda p: True, 1.0)

# Independent: Children in education
assigner.add_independent_rule('education', lambda p: 5 <= p.age <= 18, 0.95)

# Choice: Employment status for adults
assigner.add_choice_rule(
    choice_name='employment',
    condition=lambda p: 19 <= p.age <= 64,
    options=[
        ('employed', 0.75),
        ('unemployed', 0.25)
    ]
)

# Independent: Leisure for adults
assigner.add_independent_rule('leisure', lambda p: p.age >= 18, 0.70)
```

**Outcomes for different people:**
- Child age 10: `['home', 'education']` (95% chance of education)
- Adult age 30: `['home', 'employed', 'leisure']` (if employed, and leisure passes 70% check)
- Adult age 30: `['home', 'unemployed']` (if unemployed, no leisure)
- Elderly age 70: `['home', 'leisure']` (70% chance of leisure)

### Example 2: Medieval World with Occupation Types

```python
assigner = ActivityAssigner()

# Everyone has home
assigner.add_independent_rule('home', lambda p: True, 1.0)

# Males get ONE occupation type
assigner.add_choice_rule(
    choice_name='male_occupation',
    condition=lambda p: 16 <= p.age <= 60 and p.sex == 'male',
    options=[
        ('agricultural_work', 0.70),  # 70% farmers
        ('craft_work', 0.20),         # 20% artisans
        ('service_work', 0.10)        # 10% servants
    ]
)

# Females independently do domestic work
assigner.add_independent_rule(
    'domestic_work',
    lambda p: 16 <= p.age <= 55 and p.sex == 'female',
    0.95
)

# Church is independent for all adults
assigner.add_independent_rule('church', lambda p: 16 <= p.age <= 70, 0.80)
```

**Outcomes:**
- Male age 30: `['home', 'agricultural_work', 'church']` (if selected farming and passes 80% church)
- Female age 25: `['home', 'domestic_work', 'church']` (if passes both probabilities)

### Example 3: Multiple Choice Groups

```python
assigner = ActivityAssigner()

assigner.add_independent_rule('home', lambda p: True, 1.0)

# Choice 1: Employment
assigner.add_choice_rule(
    choice_name='employment',
    condition=lambda p: 25 <= p.age <= 64,
    options=[
        ('employed_fulltime', 0.60),
        ('employed_parttime', 0.20),
        ('unemployed', 0.20)
    ]
)

# Choice 2: Housing type (independent choice)
assigner.add_choice_rule(
    choice_name='housing',
    condition=lambda p: p.age >= 18,
    options=[
        ('own_home', 0.65),
        ('rent_home', 0.30),
        ('shared_housing', 0.05)
    ]
)
```

**Outcome for adult age 30:**
- Gets ONE from employment choices
- Gets ONE from housing choices
- Example: `['home', 'employed_fulltime', 'rent_home']`

## Condition Specifications

### In Python (Lambda Functions)

```python
# Age range
condition=lambda p: 18 <= p.age <= 64

# Age and sex
condition=lambda p: p.age >= 16 and p.sex == 'female'

# Properties
condition=lambda p: p.properties.get('occupation') == 'farmer'

# Complex
condition=lambda p: (
    25 <= p.age <= 64 and
    p.sex == 'male' and
    p.geographical_unit.properties.get('urban_rural') == 'urban'
)
```

### In YAML

```yaml
# Age range
condition:
  age: [18, 64]

# Age minimum
condition:
  age_min: 16

# Age and sex
condition:
  age: [18, 64]
  sex: female

# Properties
condition:
  age_min: 25
  properties:
    occupation: farmer

# Geo unit type
condition:
  age: [25, 64]
  geo_unit_type: urban
```

## Integration with PopulationManager

```python
from may.population import PopulationManager
from may.population.activity_assigner import create_modern_assigner

# Create population manager
population = PopulationManager(geography=geo)

# Load demographics
population.load_demographics_from_csv('male.csv', 'female.csv')

# Create activity assigner
activity_assigner = create_modern_assigner()

# During generation, assign activities
for age, sex, unit, count in all_age_sex_geo:
    for _ in range(count):
        person = Person(age=age, sex=sex, geographical_unit=unit)

        # Assign activities
        activities = activity_assigner.assign_activities(person)
        for activity in activities:
            person.add_activity(activity)

        population.people.append(person)
```

## Advantages of This Approach

1. **Simple**: Only two rule types to understand
2. **Modular**: Easy to add/remove activities
3. **Clear**: Distinction between independent and mutually exclusive activities
4. **Flexible**: Supports both programmatic and YAML configuration
5. **Intuitive**: Probabilities work as expected
6. **Testable**: Easy to unit test individual rules

## Comparison: Independent vs Choice

| Aspect | Independent Rule | Choice Rule |
|--------|------------------|-------------|
| Number assigned | 0 or 1 per rule | 0 or 1 total |
| Can have multiple | Yes | No (within same choice) |
| Probability | Individual check | Weighted selection |
| Example | education, leisure | employed/unemployed/student |
| Use case | Activities that coexist | Mutually exclusive states |

## Best Practices

1. **Use independent rules for:**
   - Activities everyone can have simultaneously
   - Optional activities (education, leisure, shopping)
   - Activities based on different life aspects

2. **Use choice rules for:**
   - Mutually exclusive states (employed/unemployed)
   - Categories where only one applies (occupation type)
   - Status classifications (housing type, education level)

3. **Organize logically:**
   - Group related activities in choice rules
   - Keep independent rules separate
   - Use descriptive choice names

4. **Test distributions:**
   - Generate many people to verify probabilities
   - Check that choices are mutually exclusive
   - Ensure independent rules can coexist

## Files

- **Implementation**: `may/population/activity_assigner.py`
- **Example configs**: `configs/activities_*.yaml`
- **Usage examples**: `examples/activity_assignment_usage.py`
- **This documentation**: `docs/ACTIVITY_ASSIGNMENT_SIMPLIFIED.md`
