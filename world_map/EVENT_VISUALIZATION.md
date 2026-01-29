# Event Visualization Add-on

This add-on allows you to visualize simulation events from `simulation_events.h5` files on the interactive world map. Events are aggregated by geographical unit and displayed with time-based controls.

## Features

- **Time-based playback**: Slider and play/pause controls to move through simulation time
- **Multiple event types**: Infections, deaths, hospital admissions, ICU admissions, discharges, symptom changes
- **Aggregation by geo_unit**: Events are aggregated at the smallest geographical unit level
- **Configurable display**: YAML configuration for colors, symbols, and display options
- **Two display modes**: Choropleth (colored circles) or graduated markers
- **Cumulative or rolling window**: Show cumulative totals or events in a rolling time window

## Usage

### Basic Usage

Launch the world map with an events file:

```bash
python launch_world_map.py --world-file world_state.h5 --events-file simulation_events.h5
```

### With Custom Map Background

```bash
python launch_world_map.py \
    --world-file world_state.h5 \
    --events-file simulation_events.h5 \
    --map-background image \
    --map-image /path/to/map.png \
    --map-bounds "55.0,2.0,50.0,-5.0"
```

## Configuration

The event visualization is configured via `yaml/event_visualisation.yaml`:

### Event Types

```yaml
event_types:
  infections:
    label: "Infections"
    color: "#e74c3c"
    gradient:
      low: "#fee5d9"
      medium: "#fcae91"
      high: "#fb6a4a"
      very_high: "#cb181d"
    default_visible: true

  deaths:
    label: "Deaths"
    color: "#2c3e50"
    default_visible: true
```

### Time Settings

```yaml
time:
  aggregation_window: 1.0    # Aggregate per day
  playback_interval_ms: 500  # Playback speed
  rolling_window_days: 1     # Show events from last N days
```

### Display Options

```yaml
display:
  default_mode: "choropleth"  # or "markers"

aggregation:
  method: "count"    # or "rate" (per 100k population)
  cumulative: false  # true for cumulative totals
```

## HDF5 File Requirements

The events file (`simulation_events.h5`) should have the following structure:

```
/events/
  - infections: (person_id, infector_id, venue_id, time)
  - deaths: (person_id, venue_id, time)
  - hospital_admissions: (person_id, hospital_id, time, reason)
  - icu_admissions: (person_id, hospital_id, time)
  - hospital_discharges: (person_id, hospital_id, time, outcome)
  - symptom_changes: (person_id, venue_id, time, old_symptom, new_symptom)

/lookups/
  - venues: (venue_id, name, type, geo_unit_id, n_subsets)
  - people: (person_id, age, sex, geo_unit_id, ...)
```

The lookups are used to map events to geographical units for aggregation.

## API Endpoints

The add-on provides several API endpoints:

- `GET /api/events/config` - Get visualization configuration
- `GET /api/events/summary` - Get summary of available events
- `GET /api/events/geojson/<event_type>` - Get events as GeoJSON for map display
  - Query params: `time_start`, `time_end`, `method`, `cumulative`
- `GET /api/events/timeseries/<event_type>` - Get daily event counts
- `GET /api/events/aggregated/<event_type>` - Get aggregated counts by geo_unit
- `GET /events` - Dedicated events visualization page

## UI Controls

When events are loaded, a new "Simulation Events" section appears in the sidebar:

1. **Enable Events**: Master toggle to show/hide all event layers
2. **Event Type Toggles**: Show/hide individual event types (infections, deaths, etc.)
3. **Time Slider**: Drag to select a point in time
4. **Playback Controls**:
   - Play/Pause: Animate through time
   - Step backward/forward: Move one time step
   - Reset: Return to start time
5. **Aggregation Options**:
   - Cumulative: Toggle cumulative vs rolling window
   - Display Mode: Switch between choropleth and markers
6. **Event Stats**: Shows current counts for visible event types

## Color Scheme

Events use color gradients to indicate intensity:

- **Low count**: Light color (e.g., light pink for infections)
- **Medium count**: Medium intensity
- **High count**: Darker color
- **Very high count**: Darkest color (e.g., dark red for infections)

The size of markers also scales with event count.

## Performance Notes

- Events are aggregated server-side to avoid overwhelming the map with individual markers
- The geo_unit-level aggregation provides a balance between detail and performance
- For very large simulation files (millions of events), initial loading may take a few seconds
