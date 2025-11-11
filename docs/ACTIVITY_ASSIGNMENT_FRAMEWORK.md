# Activity Assignment Framework

## Overview

This document outlines a flexible, extensible framework for assigning activities to Person objects during population generation. Activities determine which venues people can be assigned to and are correlated with person attributes (age, sex, geographical unit, custom properties).

## Current System

The current `PopulationManager` has a basic `_assign_activities()` method that assigns activities based solely on age. This needs to be expanded to support:

1. **Multi-attribute correlation** (age, sex, geo_unit, custom properties)
2. **Configurable rules** (YAML/JSON-based or programmatic)
3. **Historical/cultural variation** (different activity patterns for different worlds)
4. **Probabilistic assignment** (not all working-age people work)
5. **Geo-spatial variation** (urban vs rural differences)

## Proposed Architecture

### 1. Activity Configuration System

#### Option A: YAML Configuration (Recommended)

Create configuration files that define activity rules:

```yaml
# activity_config.yaml

activity_rules:
  # Rule-based assignment with priorities (evaluated in order)
  - name: "Young children"
    conditions:
      age: [0, 4]
    activities: ["home"]
    probability: 1.0  # Always assigned

  - name: "School age children"
    conditions:
      age: [5, 18]
    activities: ["education", "home"]
    probability: 0.95  # 95% attend school

  - name: "Working age adults - urban"
    conditions:
      age: [19, 64]
      geo_unit_type: "urban"  # Based on geo_unit properties
    activities: ["work", "home", "leisure"]
    probability: 0.85  # 85% employment rate

  - name: "Working age adults - rural"
    conditions:
      age: [19, 64]
      geo_unit_type: "rural"
    activities: ["work", "home", "leisure"]
    probability: 0.75  # 75% employment rate (lower in rural areas)

  - name: "Working age females - historical"
    conditions:
      age: [19, 64]
      sex: "female"
      world_type: "medieval"
    activities: ["home", "domestic_work"]
    probability: 0.90

  - name: "Elderly"
    conditions:
      age: [65, 150]
    activities: ["home", "leisure"]
    probability: 1.0

# Activity definitions with metadata
activity_definitions:
  home:
    description: "Residential activities"
    venue_types: ["household", "care_home", "student_dorm"]
    required: true  # Everyone must have this

  work:
    description: "Employment activities"
    venue_types: ["company", "factory", "farm"]
    required: false

  education:
    description: "School and university"
    venue_types: ["school", "university"]
    required: false

  leisure:
    description: "Social and recreational activities"
    venue_types: ["pub", "church", "park"]
    required: false

  domestic_work:
    description: "Home-based economic activities"
    venue_types: ["household"]
    required: false

# Geo-spatial configuration (optional)
geo_classifications:
  urban:
    - "E02000001"  # Specific geo_unit codes
    - "E02000002"
  rural:
    - "E02000100"
    - "E02000101"
```

#### Option B: Programmatic Configuration

Create configurable Python classes:

```python
from dataclasses import dataclass
from typing import Callable, Optional, List
import random

@dataclass
class ActivityRule:
    """Defines a rule for assigning activities to people."""
    name: str
    condition: Callable[['Person'], bool]
    activities: List[str]
    probability: float = 1.0
    priority: int = 0  # Lower number = higher priority

    def applies_to(self, person: 'Person') -> bool:
        """Check if this rule applies to a person."""
        return self.condition(person) and random.random() < self.probability

class ActivityAssigner:
    """Manages activity assignment based on configurable rules."""

    def __init__(self):
        self.rules: List[ActivityRule] = []
        self.activity_definitions = {}

    def add_rule(self, rule: ActivityRule):
        """Add an activity rule (inserted by priority)."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def assign_activities(self, person: 'Person') -> List[str]:
        """Assign activities to a person based on rules."""
        activities = set()

        # Apply rules in priority order
        for rule in self.rules:
            if rule.applies_to(person):
                activities.update(rule.activities)

        return list(activities)
```

### 2. Integration with PopulationManager

Update `PopulationManager` to use the activity framework:

```python
class PopulationManager:
    def __init__(self, geography, data_dir="data/population",
                 activity_config=None):
        # ... existing init code ...

        # New: Load activity configuration
        if activity_config:
            self.activity_assigner = ActivityAssigner.from_config(activity_config)
        else:
            self.activity_assigner = ActivityAssigner.default()

    def generate_population(self, **kwargs):
        """Generate population from precise demographics."""
        # ... existing code to create Person objects ...

        for age, sex, unit, count in all_age_sex_geo:
            for _ in range(count):
                person = Person(age=age, sex=sex,
                              geographical_unit=unit)

                # NEW: Assign activities using the framework
                activities = self.activity_assigner.assign_activities(person)
                for activity in activities:
                    person.add_activity(activity)

                self.people.append(person)
                # ... rest of code ...
```

### 3. Example Activity Assigners

#### Modern World Activity Assigner

```python
def create_modern_activity_assigner():
    """Create activity assigner for modern/contemporary world."""
    assigner = ActivityAssigner()

    # Everyone gets 'home'
    assigner.add_rule(ActivityRule(
        name="Universal home",
        condition=lambda p: True,
        activities=['home'],
        probability=1.0,
        priority=0
    ))

    # Young children (0-4)
    assigner.add_rule(ActivityRule(
        name="Young children",
        condition=lambda p: 0 <= p.age <= 4,
        activities=['childcare'],
        probability=0.6,  # 60% in childcare
        priority=1
    ))

    # School age (5-18)
    assigner.add_rule(ActivityRule(
        name="School age",
        condition=lambda p: 5 <= p.age <= 18,
        activities=['education'],
        probability=0.95,
        priority=1
    ))

    # University age (18-24)
    assigner.add_rule(ActivityRule(
        name="University age",
        condition=lambda p: 18 <= p.age <= 24,
        activities=['higher_education'],
        probability=0.40,  # 40% attend university
        priority=2
    ))

    # Working age (19-64)
    assigner.add_rule(ActivityRule(
        name="Working age",
        condition=lambda p: 19 <= p.age <= 64,
        activities=['work', 'leisure'],
        probability=0.80,  # 80% employment
        priority=3
    ))

    # Elderly (65+)
    assigner.add_rule(ActivityRule(
        name="Retirement age",
        condition=lambda p: p.age >= 65,
        activities=['leisure'],
        probability=1.0,
        priority=1
    ))

    # Care home residents (very elderly or disabled)
    assigner.add_rule(ActivityRule(
        name="Care home eligibility",
        condition=lambda p: p.age >= 85,
        activities=['care_home_resident'],
        probability=0.15,  # 15% of 85+ in care homes
        priority=10  # Applied last
    ))

    return assigner
```

#### Medieval World Activity Assigner

```python
def create_medieval_activity_assigner():
    """Create activity assigner for medieval/historical world."""
    assigner = ActivityAssigner()

    # Universal home
    assigner.add_rule(ActivityRule(
        name="Universal home",
        condition=lambda p: True,
        activities=['home'],
        probability=1.0,
        priority=0
    ))

    # Children (all help with work from young age)
    assigner.add_rule(ActivityRule(
        name="Working children",
        condition=lambda p: 7 <= p.age <= 15,
        activities=['domestic_work'],
        probability=0.80,
        priority=1
    ))

    # Adult males - most work outside home
    assigner.add_rule(ActivityRule(
        name="Adult males - labor",
        condition=lambda p: 16 <= p.age <= 60 and p.sex == 'male',
        activities=['work', 'church'],
        probability=0.90,
        priority=2
    ))

    # Adult females - domestic work and some trades
    assigner.add_rule(ActivityRule(
        name="Adult females - domestic",
        condition=lambda p: 16 <= p.age <= 50 and p.sex == 'female',
        activities=['domestic_work', 'church'],
        probability=0.95,
        priority=2
    ))

    # Nobility (based on properties)
    assigner.add_rule(ActivityRule(
        name="Nobility",
        condition=lambda p: p.properties.get('social_class') == 'noble',
        activities=['court', 'hunting', 'church'],
        probability=1.0,
        priority=5
    ))

    # Clergy
    assigner.add_rule(ActivityRule(
        name="Clergy",
        condition=lambda p: p.properties.get('occupation') == 'clergy',
        activities=['religious_service'],
        probability=1.0,
        priority=5
    ))

    return assigner
```

### 4. Geo-spatial Variation

Add geographical context to activity assignment:

```python
def assign_activities_with_geo_context(self, person: 'Person') -> List[str]:
    """Assign activities considering geographical context."""
    activities = set()

    # Classify geo_unit
    geo_type = self._classify_geo_unit(person.geographical_unit)

    for rule in self.rules:
        # Check if rule has geo requirements
        if hasattr(rule, 'geo_requirement'):
            if geo_type != rule.geo_requirement:
                continue

        if rule.applies_to(person):
            activities.update(rule.activities)

    return list(activities)

def _classify_geo_unit(self, geo_unit: 'GeographicalUnit') -> str:
    """Classify geographical unit as urban/rural/suburban."""
    # Option 1: Based on properties
    if hasattr(geo_unit, 'properties'):
        if 'urban_rural_classification' in geo_unit.properties:
            return geo_unit.properties['urban_rural_classification']

    # Option 2: Based on population density
    if hasattr(geo_unit, 'population_density'):
        if geo_unit.population_density > 4000:
            return 'urban'
        elif geo_unit.population_density > 1000:
            return 'suburban'
        else:
            return 'rural'

    # Option 3: Based on lookup table
    if geo_unit.name in self.urban_codes:
        return 'urban'
    elif geo_unit.name in self.rural_codes:
        return 'rural'

    return 'unknown'
```

### 5. Usage Examples

#### Example 1: Modern UK Population

```python
# In create_world.py or similar script

# Load activity configuration
with open('configs/activities_modern_uk.yaml') as f:
    activity_config = yaml.safe_load(f)

# Create population manager with activity config
population = PopulationManager(
    geography=geo,
    data_dir="data/population",
    activity_config=activity_config
)

# Load demographics
population.load_demographics_from_csv('demographics_male.csv',
                                     'demographics_female.csv')

# Generate population - activities assigned automatically
population.generate_population()
```

#### Example 2: Medieval England

```python
# Create custom activity assigner
activity_assigner = create_medieval_activity_assigner()

# Create population manager
population = PopulationManager(
    geography=geo,
    data_dir="data/population"
)
population.activity_assigner = activity_assigner

# Generate with additional properties
population.generate_population(
    properties={'world_type': 'medieval'}
)
```

#### Example 3: Dynamic Assignment with Properties

```python
# Assign social classes before activity assignment
def assign_social_classes(person):
    """Assign social class based on age and random chance."""
    if random.random() < 0.02:  # 2% nobility
        person.properties['social_class'] = 'noble'
    elif random.random() < 0.05:  # 5% clergy
        person.properties['occupation'] = 'clergy'
    elif random.random() < 0.30:  # 30% artisans
        person.properties['social_class'] = 'artisan'
    else:
        person.properties['social_class'] = 'peasant'

# In PopulationManager.generate_population()
for age, sex, unit, count in all_age_sex_geo:
    for _ in range(count):
        person = Person(age=age, sex=sex, geographical_unit=unit)

        # Assign properties first
        assign_social_classes(person)

        # Then assign activities based on properties
        activities = self.activity_assigner.assign_activities(person)
        for activity in activities:
            person.add_activity(activity)
```

## Implementation Plan

### Phase 1: Core Framework (Week 1)
1. Create `ActivityRule` and `ActivityAssigner` classes
2. Update `PopulationManager.__init__()` to accept activity configuration
3. Modify `generate_population()` to use activity assigner
4. Write unit tests for activity assignment

### Phase 2: Configuration Support (Week 2)
1. Implement YAML configuration loading
2. Create example configuration files (modern UK, medieval England)
3. Add validation for configuration files
4. Document configuration format

### Phase 3: Geo-spatial Features (Week 3)
1. Implement geo_unit classification
2. Add urban/rural activity variations
3. Create lookup tables for geo classifications
4. Test with real geographical data

### Phase 4: Advanced Features (Week 4)
1. Add probabilistic activity pools (random selection from options)
2. Implement activity dependencies (if X then Y)
3. Add time-of-day activity patterns
4. Create activity validation tools

## Testing Strategy

### Unit Tests
```python
def test_activity_rule_application():
    """Test that rules are applied correctly."""
    person = Person(age=25, sex='male')
    rule = ActivityRule(
        name="Test",
        condition=lambda p: p.age >= 18,
        activities=['work'],
        probability=1.0
    )
    assert rule.applies_to(person) == True

def test_activity_assignment_priority():
    """Test that rules are applied in priority order."""
    assigner = ActivityAssigner()
    # Add rules with different priorities
    # Verify correct order of application

def test_geo_spatial_variation():
    """Test that activities vary by geography."""
    # Create people in urban vs rural areas
    # Verify different activity assignments
```

### Integration Tests
```python
def test_full_population_generation():
    """Test complete population generation with activities."""
    pop_manager = PopulationManager(geography, activity_config=config)
    pop_manager.generate_population()

    # Verify all people have activities
    assert all(len(p.activities) > 0 for p in pop_manager.people)

    # Verify activity distributions match expectations
    stats = pop_manager.get_statistics()
    assert stats['activity_counts']['home'] == len(pop_manager.people)
```

## Benefits of This Framework

1. **Flexibility**: Easy to create different activity patterns for different worlds
2. **Maintainability**: Configuration separate from code
3. **Testability**: Rules can be unit tested independently
4. **Extensibility**: Easy to add new rules or conditions
5. **Reusability**: Same framework works for modern, historical, and fantasy worlds
6. **Transparency**: Activity assignment logic is explicit and documented
7. **Performance**: Rules evaluated efficiently with early termination

## Future Enhancements

1. **Activity Scheduling**: Add time-of-day patterns
2. **Activity Networks**: Model relationships between activities
3. **Dynamic Activities**: Activities change over time (aging, life events)
4. **Activity Constraints**: Some activities mutually exclusive
5. **Machine Learning**: Learn activity patterns from real data
6. **Validation Tools**: Verify activity assignments match expected distributions
7. **Visualization**: Plot activity distributions by demographics

## References

- Current code: `may/population/population.py:207-236`
- Related code: `may/distributor/distributor_pop_to_venue.py`
- Example usage: `create_world_medieval.py:112`
