#!/usr/bin/env python3
"""
World Map - Interactive visualization for World instances.

This Flask application provides an interactive map interface for exploring
World instances containing geography, population, venues, and households.
"""

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import logging
from collections import defaultdict
import json
import yaml
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global world instance - set via initialize_app()
_world_instance = None

# Global map configuration
_map_config = {
    'background_type': 'osm',  # 'osm' or 'image'
    'image_url': None,
    'bounds': None,  # [[south, west], [north, east]]
    'attribution': None
}

# Global info panel configuration
_panel_config = None


def load_panel_config(config_path=None):
    """Load info panel configuration from YAML file."""
    global _panel_config

    if config_path is None:
        config_path = Path(__file__).parent / 'yaml' / 'info_panel_config.yaml'

    try:
        with open(config_path, 'r') as f:
            _panel_config = yaml.safe_load(f)
        logger.info(f"Loaded panel config from {config_path}")
    except FileNotFoundError:
        logger.warning(f"Panel config not found at {config_path}, using defaults")
        _panel_config = _get_default_panel_config()
    except Exception as e:
        logger.error(f"Error loading panel config: {e}")
        _panel_config = _get_default_panel_config()

    return _panel_config


def _convert_numpy_types(obj):
    """Recursively convert numpy types to Python native types for JSON serialization."""
    import numpy as np

    if obj is None:
        return None
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.str_):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _convert_numpy_types(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_numpy_types(item) for item in obj]
    return obj


def _get_default_panel_config():
    """Return default panel configuration.

    Uses same nested structure as info_panel_config.yaml for consistency with event_visualisation.yaml.
    """
    return {
        'geo_unit_panel': {
            'title_field': 'name',
            'popup': {'enabled': True},
            'detail_sections': []
        },
        'venue_panel': {
            'title_field': 'name',
            'popup': {'enabled': True},
            'detail_sections': []
        },
        'marker_styles': {
            'geo_unit': {
                'size': {'method': 'sqrt', 'min_radius': 5, 'max_radius': 15, 'scale': 0.5},
                'border': {'color': '#808080', 'width': 1, 'opacity': 1},
                'fill_opacity': 0.7,
                'zoom_scaling': {'enabled': True, 'base_zoom': 6, 'scale_exponent': 0.5, 'min_scale': 0.3, 'max_scale': 3.0}
            },
            'venue': {
                'size': {'radius': 6},
                'border': {'color': '#ffffff', 'width': 1, 'opacity': 1},
                'fill_opacity': 0.8,
                'zoom_scaling': {'enabled': True, 'base_zoom': 6, 'scale_exponent': 0.5, 'min_scale': 0.3, 'max_scale': 3.0}
            }
        }
    }


def initialize_app(world, map_config=None, panel_config_path=None):
    """
    Initialize the Flask app with a World instance and optional map configuration.

    Args:
        world: World instance to visualize
        map_config: Dict with optional keys:
            - background_type: 'osm' (default) or 'image'
            - image_url: URL or path to background image (required if background_type='image')
            - bounds: [[south, west], [north, east]] geographic bounds (required if background_type='image')
            - attribution: Attribution text for the image
        panel_config_path: Path to info panel YAML config (optional)

    Returns:
        Flask app instance
    """
    global _world_instance, _map_config
    _world_instance = world

    if map_config:
        _map_config.update(map_config)

    # Load panel configuration
    load_panel_config(panel_config_path)

    logger.info(f"Initialized world map with: {world}")
    logger.info(f"Map configuration: {_map_config}")
    return app


def get_world():
    """Get the current World instance."""
    if _world_instance is None:
        raise RuntimeError("World instance not initialized. Call initialize_app() first.")
    return _world_instance


# Create Flask app
app = Flask(__name__)
CORS(app)


# ============================================================================
# Web Routes
# ============================================================================

@app.route('/')
def index():
    """Serve the main interactive map page."""
    return render_template('index.html')


@app.route('/api/map/config')
def get_map_config():
    """Get map configuration including background type and bounds."""
    return jsonify(_map_config)


@app.route('/api/panel/config')
def get_panel_config():
    """Get info panel configuration for customizing displayed attributes."""
    global _panel_config
    if _panel_config is None:
        load_panel_config()
    return jsonify(_panel_config)


# ============================================================================
# API: Geography
# ============================================================================

@app.route('/api/geography/levels')
def get_geography_levels():
    """Get available geography levels."""
    try:
        world = get_world()
        if not world.geography:
            return jsonify({'levels': []})

        return jsonify({
            'levels': world.geography.levels,
            'units_per_level': {
                level: len(world.geography.get_units_by_level(level))
                for level in world.geography.levels
            }
        })
    except Exception as e:
        logger.error(f"Error getting geography levels: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/geography/<level>')
def get_geography_level(level):
    """
    Get all geographical units at a specific level as GeoJSON.

    Returns point features with coordinates and metadata.
    For units with children, aggregates population and venue counts from all descendants.
    """
    try:
        world = get_world()
        if not world.geography:
            return jsonify({'type': 'FeatureCollection', 'features': []})

        units = world.geography.get_units_by_level(level)
        if not units:
            return jsonify({'type': 'FeatureCollection', 'features': []})

        features = []
        for unit_name, unit in units.items():
            if not unit.coordinates:
                continue

            lat, lon = unit.coordinates

            # Use get_people() to recursively get all people from unit and descendants
            all_people = unit.get_people()
            population = len(all_people) if all_people else 0

            # Aggregate venues from unit and all descendants
            all_venues = list(unit.venues) if unit.venues else []
            if unit.children:
                for descendant in unit.get_descendants():
                    if descendant.venues:
                        all_venues.extend(descendant.venues)
            venues_count = len(all_venues)

            # Get venue breakdown from all aggregated venues
            venue_types = defaultdict(int)
            for venue in all_venues:
                venue_types[str(venue.type)] += 1

            feature = {
                'type': 'Feature',
                'properties': {
                    'id': int(unit.id) if hasattr(unit.id, 'item') else unit.id,
                    'name': str(unit.name),
                    'level': str(unit.level),
                    'population': int(population),
                    'venues_count': int(venues_count),
                    'venue_types': dict(venue_types),
                    'has_parent': unit.parent is not None,
                    'children_count': int(len(unit.children)) if unit.children else 0
                },
                'geometry': {
                    'type': 'Point',
                    # Convert numpy floats to Python floats for JSON serialization
                    'coordinates': [float(lon), float(lat)]
                }
            }
            features.append(feature)

        geojson = {
            'type': 'FeatureCollection',
            'features': features
        }

        logger.info(f"Returned {len(features)} features for level {level}")
        return jsonify(geojson)

    except Exception as e:
        logger.error(f"Error getting geography level {level}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/geography/unit/<unit_name>')
def get_unit_details(unit_name):
    """Get detailed information about a specific geographical unit.

    For units with children, aggregates statistics from all descendants.
    """
    try:
        world = get_world()
        if not world.geography:
            return jsonify({'error': 'No geography data'}), 404

        unit = world.geography.get_unit(unit_name)
        if not unit:
            return jsonify({'error': f'Unit {unit_name} not found'}), 404

        # Use get_people() to recursively get all people from unit and descendants
        all_people = unit.get_people()

        # Collect detailed statistics from all people
        age_groups = {
            '0-15': 0, '16-24': 0, '25-34': 0,
            '35-49': 0, '50-64': 0, '65+': 0
        }

        sex_distribution = defaultdict(int)

        for person in all_people:
            # Age groups
            if person.age <= 15:
                age_groups['0-15'] += 1
            elif person.age <= 24:
                age_groups['16-24'] += 1
            elif person.age <= 34:
                age_groups['25-34'] += 1
            elif person.age <= 49:
                age_groups['35-49'] += 1
            elif person.age <= 64:
                age_groups['50-64'] += 1
            else:
                age_groups['65+'] += 1

            # Sex distribution
            sex_distribution[person.sex] += 1

        # Aggregate venues from unit and all descendants
        all_venues = list(unit.venues) if unit.venues else []
        if unit.children:
            for descendant in unit.get_descendants():
                if descendant.venues:
                    all_venues.extend(descendant.venues)

        # Venue breakdown from all aggregated venues
        venue_details = []
        venue_types = defaultdict(int)
        for venue in all_venues:
            venue_types[venue.type] += 1
            # Only include details for first 50 venues
            if len(venue_details) < 50:
                venue_details.append({
                    'id': venue.id,
                    'name': venue.name,
                    'type': venue.type,
                    'coordinates': venue.coordinates,
                    'properties': venue.properties
                })

        # Parent and children info
        parent_info = None
        if unit.parent:
            parent_info = {
                'id': unit.parent.id,
                'name': unit.parent.name,
                'level': unit.parent.level
            }

        children_info = []
        if unit.children:
            for child in unit.children:
                # Use get_people() for children too to show aggregated population
                child_population = len(child.get_people())
                children_info.append({
                    'id': child.id,
                    'name': child.name,
                    'level': child.level,
                    'population': child_population
                })

        return jsonify({
            'id': unit.id,
            'name': unit.name,
            'level': unit.level,
            'coordinates': unit.coordinates,
            'population': len(all_people),
            'age_distribution': age_groups,
            'sex_distribution': dict(sex_distribution),
            'venues_count': len(all_venues),
            'venue_types': dict(venue_types),
            'venue_details': venue_details,
            'parent': parent_info,
            'children': children_info,
            'properties': unit.properties
        })

    except Exception as e:
        logger.error(f"Error getting unit details for {unit_name}: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# API: Population
# ============================================================================

@app.route('/api/population/statistics')
def get_population_statistics():
    """Get overall population statistics."""
    try:
        world = get_world()
        if not world.population:
            return jsonify({'error': 'No population data'}), 404

        stats = world.population.get_statistics()

        # Add geographical distribution
        geo_distribution = defaultdict(int)
        if world.geography:
            for level in world.geography.levels:
                units = world.geography.get_units_by_level(level)
                for unit in units.values():
                    if unit.people:
                        geo_distribution[level] += len(unit.people)

        stats['geographical_distribution'] = dict(geo_distribution)

        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting population statistics: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/population/person/<int:person_id>')
def get_person_details(person_id):
    """Get detailed information about a specific person including activity_map."""
    try:
        world = get_world()
        if not world.population:
            return jsonify({'error': 'No population data'}), 404

        person = world.population.get_person(person_id)
        if not person:
            return jsonify({'error': f'Person {person_id} not found'}), 404

        # Get geographical unit info
        geo_info = None
        if person.geographical_unit:
            geo_info = {
                'id': person.geographical_unit.id,
                'name': person.geographical_unit.name,
                'level': person.geographical_unit.level,
                'coordinates': person.geographical_unit.coordinates
            }

        # Build activity_map representation
        activity_map_data = {}
        if hasattr(person, 'activity_map') and person.activity_map:
            for activity_type, venues_by_type in person.activity_map.items():
                activity_map_data[activity_type] = {}
                if isinstance(venues_by_type, dict):
                    for venue_type, subsets in venues_by_type.items():
                        subset_list = []
                        if subsets:
                            for subset in (subsets if isinstance(subsets, list) else [subsets]):
                                if subset:
                                    subset_info = {
                                        'subset_name': getattr(subset, 'name', 'unknown'),
                                        'venue_id': getattr(subset.venue, 'id', None) if hasattr(subset, 'venue') else None,
                                        'venue_name': getattr(subset.venue, 'name', 'unknown') if hasattr(subset, 'venue') else 'unknown',
                                        'venue_type': getattr(subset.venue, 'type', venue_type) if hasattr(subset, 'venue') else venue_type
                                    }
                                    subset_list.append(subset_info)
                        activity_map_data[activity_type][venue_type] = subset_list

        return jsonify({
            'id': person.id,
            'age': person.age,
            'sex': person.sex,
            'activities': person.activities,
            'activity_map': activity_map_data,
            'properties': person.properties,
            'geographical_unit': geo_info
        })

    except Exception as e:
        logger.error(f"Error getting person details for {person_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/geography/unit/<unit_name>/people')
def get_unit_people(unit_name):
    """Get list of people in a geographical unit with pagination."""
    try:
        world = get_world()
        if not world.geography:
            return jsonify({'error': 'No geography data'}), 404

        unit = world.geography.get_unit(unit_name)
        if not unit:
            return jsonify({'error': f'Unit {unit_name} not found'}), 404

        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)  # Cap at 200 per page

        # Get all people from unit (and optionally descendants)
        include_descendants = request.args.get('include_descendants', 'false').lower() == 'true'

        if include_descendants:
            all_people = unit.get_people()
        else:
            all_people = list(unit.people) if unit.people else []

        total_count = len(all_people)

        # Apply pagination
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_people = all_people[start_idx:end_idx]

        # Build person summaries
        people_data = []
        for person in paginated_people:
            # Get primary activity info
            primary_activity = None
            if hasattr(person, 'activity_map') and person.activity_map:
                if 'primary_activity' in person.activity_map:
                    for venue_type, subsets in person.activity_map['primary_activity'].items():
                        if subsets:
                            subset = subsets[0] if isinstance(subsets, list) else subsets
                            if subset and hasattr(subset, 'venue'):
                                primary_activity = {
                                    'type': venue_type,
                                    'venue_name': getattr(subset.venue, 'name', 'unknown')
                                }
                                break

            people_data.append({
                'id': person.id,
                'age': person.age,
                'sex': person.sex,
                'activities': person.activities,
                'primary_activity': primary_activity
            })

        return jsonify({
            'unit_name': unit_name,
            'total_count': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page,
            'people': people_data
        })

    except Exception as e:
        logger.error(f"Error getting people for unit {unit_name}: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# API: Venues
# ============================================================================

@app.route('/api/venues/types')
def get_venue_types():
    """Get all available venue types and their counts."""
    try:
        world = get_world()
        if not world.venues:
            return jsonify({'types': []})

        venue_types = {}
        for venue_type in world.venues.get_venue_types():
            venues = world.venues.get_venues_by_type(venue_type)
            venue_types[venue_type] = len(venues)

        return jsonify({'types': venue_types})

    except Exception as e:
        logger.error(f"Error getting venue types: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/venues/<venue_type>')
def get_venues_by_type(venue_type):
    """Get all venues of a specific type as GeoJSON."""
    try:
        world = get_world()
        if not world.venues:
            return jsonify({'type': 'FeatureCollection', 'features': []})

        venues = world.venues.get_venues_by_type(venue_type)

        features = []
        for venue in venues:
            if not venue.coordinates:
                continue

            lat, lon = venue.coordinates

            # Count members across all subsets
            total_members = 0
            if hasattr(venue, 'subsets') and venue.subsets:
                for subset in venue.subsets.values():
                    if hasattr(subset, 'num_members'):
                        total_members += subset.num_members

            feature = {
                'type': 'Feature',
                'properties': {
                    'id': int(venue.id) if hasattr(venue.id, 'item') else venue.id,
                    'name': str(venue.name),
                    'type': str(venue.type),
                    'geographical_unit': str(venue.geographical_unit.name) if venue.geographical_unit else None,
                    'num_members': int(total_members),
                    'properties': _convert_numpy_types(venue.properties) if venue.properties else {}
                },
                'geometry': {
                    'type': 'Point',
                    # Convert numpy floats to Python floats for JSON serialization
                    'coordinates': [float(lon), float(lat)]
                }
            }
            features.append(feature)

        geojson = {
            'type': 'FeatureCollection',
            'features': features
        }

        logger.info(f"Returned {len(features)} venues of type {venue_type}")
        return jsonify(geojson)

    except Exception as e:
        logger.error(f"Error getting venues of type {venue_type}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/venues/venue/<int:venue_id>')
def get_venue_details(venue_id):
    """Get detailed information about a specific venue."""
    try:
        world = get_world()
        if not world.venues:
            return jsonify({'error': 'No venues data'}), 404

        venue = world.venues.get_venue_by_id(venue_id)
        if not venue:
            return jsonify({'error': f'Venue {venue_id} not found'}), 404

        # Get geographical unit info
        geo_info = None
        if venue.geographical_unit:
            geo_info = {
                'id': venue.geographical_unit.id,
                'name': venue.geographical_unit.name,
                'level': venue.geographical_unit.level,
                'coordinates': venue.geographical_unit.coordinates
            }

        # Get subset information
        subsets_info = []
        if hasattr(venue, 'subsets') and venue.subsets:
            for subset_name, subset in venue.subsets.items():
                subset_info = {
                    'name': subset_name,
                }
                if hasattr(subset, 'num_members'):
                    subset_info['num_members'] = subset.num_members
                if hasattr(subset, 'capacity'):
                    subset_info['capacity'] = subset.capacity
                subsets_info.append(subset_info)

        return jsonify({
            'id': venue.id,
            'name': venue.name,
            'type': venue.type,
            'coordinates': venue.coordinates,
            'geographical_unit': geo_info,
            'properties': venue.properties,
            'subsets': subsets_info
        })

    except Exception as e:
        logger.error(f"Error getting venue details for {venue_id}: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# API: Households
# ============================================================================

@app.route('/api/households/statistics')
def get_household_statistics():
    """Get household statistics."""
    try:
        world = get_world()
        if not world.households:
            return jsonify({'error': 'No household data'}), 404

        # Calculate statistics
        total_households = len(world.households.households)

        size_distribution = defaultdict(int)
        for household in world.households.households:
            size = household.size() if hasattr(household, 'size') else len(household.residents)
            size_distribution[size] += 1

        return jsonify({
            'total_households': total_households,
            'size_distribution': dict(size_distribution),
            'average_size': sum(k * v for k, v in size_distribution.items()) / total_households if total_households > 0 else 0
        })

    except Exception as e:
        logger.error(f"Error getting household statistics: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# API: World Statistics
# ============================================================================

@app.route('/api/world/statistics')
def get_world_statistics():
    """Get comprehensive statistics about the world."""
    try:
        world = get_world()
        stats = world.get_statistics()
        # Convert numpy types to Python native types for JSON serialization
        stats = _convert_numpy_types(stats)
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting world statistics: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# API: Events (Simulation Event Visualization)
# ============================================================================

# Global event loader instance
_event_loader = None
_event_config = None


def load_event_config(config_path=None):
    """Load event visualization configuration from YAML file."""
    global _event_config

    if config_path is None:
        config_path = Path(__file__).parent / 'yaml' / 'event_visualisation.yaml'

    try:
        with open(config_path, 'r') as f:
            _event_config = yaml.safe_load(f)
        logger.info(f"Loaded event config from {config_path}")
    except FileNotFoundError:
        logger.warning(f"Event config not found at {config_path}, using defaults")
        _event_config = _get_default_event_config()
    except Exception as e:
        logger.error(f"Error loading event config: {e}")
        _event_config = _get_default_event_config()

    return _event_config


def _get_default_event_config():
    """Return default event configuration.

    Uses same nested structure as YAML config files for consistency with info_panel_config.yaml.
    """
    return {
        'event_types': {
            'infections': {
                'label': 'Infections',
                'default_visible': True,
                'marker': {
                    'color': '#e74c3c',
                    'border': {'color': '#ffffff', 'width': 2, 'opacity': 0.8},
                    'fill_opacity': 0.8,
                    'size_scale': 1.0
                },
                'color_thresholds': [
                    {'max_count': 5, 'color': '#fee5d9', 'label': 'Very Low'},
                    {'max_count': 20, 'color': '#fcae91', 'label': 'Low'},
                    {'max_count': 50, 'color': '#fb6a4a', 'label': 'Medium'},
                    {'max_count': 100, 'color': '#de2d26', 'label': 'High'},
                    {'max_count': None, 'color': '#a50f15', 'label': 'Very High'}
                ],
                'use_relative_scaling': False,
                'gradient': {'low': '#fee5d9', 'medium': '#fcae91', 'high': '#fb6a4a', 'very_high': '#cb181d'}
            },
            'deaths': {
                'label': 'Deaths',
                'default_visible': True,
                'marker': {
                    'color': '#2c3e50',
                    'border': {'color': '#ffffff', 'width': 2, 'opacity': 0.9},
                    'fill_opacity': 0.9,
                    'size_scale': 1.2
                },
                'color_thresholds': [
                    {'max_count': 1, 'color': '#d9d9d9', 'label': 'Very Low'},
                    {'max_count': 5, 'color': '#969696', 'label': 'Low'},
                    {'max_count': 15, 'color': '#525252', 'label': 'Medium'},
                    {'max_count': 30, 'color': '#252525', 'label': 'High'},
                    {'max_count': None, 'color': '#000000', 'label': 'Very High'}
                ],
                'use_relative_scaling': False,
                'gradient': {'low': '#d9d9d9', 'medium': '#969696', 'high': '#525252', 'very_high': '#252525'}
            }
        },
        'time': {
            'aggregation_window': 1.0,
            'playback_interval_ms': 500,
            'rolling_window_days': 1
        },
        'display': {
            'default_mode': 'choropleth',
            'choropleth': {
                'size': {'method': 'sqrt', 'min_radius': 6, 'max_radius': 35, 'scale': 2.0},
                'border': {'color': '#333333', 'width': 1, 'opacity': 0.8},
                'fill_opacity': 0.7
            },
            'markers': {
                'size': {'method': 'sqrt', 'min_radius': 5, 'max_radius': 40, 'scale': 1.5},
                'border': {'color': '#ffffff', 'width': 2, 'opacity': 1},
                'fill_opacity': 0.6
            },
            'zoom_scaling': {'enabled': True, 'base_zoom': 6, 'scale_exponent': 0.5, 'min_scale': 0.3, 'max_scale': 3.0}
        },
        'aggregation': {'method': 'count', 'cumulative': False},
        'legend': {'position': 'bottomright', 'show_threshold_labels': True, 'show_totals': True, 'title': 'Event Counts'},
        'popup': {'show_count': True, 'show_rate': True, 'show_geo_unit_name': True}
    }


def initialize_events(events_path, world=None):
    """Initialize event loader with optional world instance for geo coordinates."""
    global _event_loader

    try:
        from event_loader import load_events_with_world
        _event_loader = load_events_with_world(events_path, world)
        logger.info(f"Event loader initialized from {events_path}")
    except Exception as e:
        logger.error(f"Failed to initialize event loader: {e}")
        _event_loader = None


def get_event_loader():
    """Get the event loader instance."""
    return _event_loader


@app.route('/api/events/config')
def get_event_config():
    """Get event visualization configuration."""
    global _event_config
    if _event_config is None:
        load_event_config()
    return jsonify(_event_config)


@app.route('/api/events/summary')
def get_events_summary():
    """Get summary of available events."""
    loader = get_event_loader()
    if loader is None:
        return jsonify({'error': 'Events not loaded'}), 404

    return jsonify({
        'available_types': loader.get_available_event_types(),
        'counts': loader.get_event_summary(),
        'time_range': loader.get_time_range()
    })


@app.route('/api/events/geojson/<event_type>')
def get_events_geojson(event_type):
    """Get events as GeoJSON for map display."""
    loader = get_event_loader()
    if loader is None:
        return jsonify({'error': 'Events not loaded'}), 404

    # Parse query parameters
    time_start = request.args.get('time_start', type=float, default=0.0)
    time_end = request.args.get('time_end', type=float, default=loader.time_max)
    method = request.args.get('method', default='count')
    cumulative = request.args.get('cumulative', default='false').lower() == 'true'

    try:
        geojson = loader.get_events_geojson(
            event_type=event_type,
            time_start=time_start,
            time_end=time_end,
            method=method,
            cumulative=cumulative
        )
        return jsonify(geojson)
    except Exception as e:
        logger.error(f"Error getting events geojson: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/events/timeseries/<event_type>')
def get_events_timeseries(event_type):
    """Get daily event counts as timeseries."""
    loader = get_event_loader()
    if loader is None:
        return jsonify({'error': 'Events not loaded'}), 404

    try:
        df = loader.get_daily_events_timeseries(event_type)
        return jsonify({
            'event_type': event_type,
            'data': df.to_dict(orient='records')
        })
    except Exception as e:
        logger.error(f"Error getting events timeseries: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/events/aggregated/<event_type>')
def get_events_aggregated(event_type):
    """Get aggregated events by geo_unit."""
    loader = get_event_loader()
    if loader is None:
        return jsonify({'error': 'Events not loaded'}), 404

    time_start = request.args.get('time_start', type=float, default=0.0)
    time_end = request.args.get('time_end', type=float, default=loader.time_max)
    method = request.args.get('method', default='count')

    try:
        aggregated = loader.aggregate_events_by_geo_unit(
            event_type=event_type,
            time_start=time_start,
            time_end=time_end,
            method=method
        )

        # Convert to serializable format
        result = {}
        for geo_unit_id, data in aggregated.items():
            result[str(geo_unit_id)] = _convert_numpy_types(data)

        return jsonify({
            'event_type': event_type,
            'time_start': time_start,
            'time_end': time_end,
            'method': method,
            'data': result
        })
    except Exception as e:
        logger.error(f"Error getting aggregated events: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/events')
def events_page():
    """Serve the events visualization page."""
    return render_template('events_map.html')


# ============================================================================
# Error Handlers
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    logger.warning("Run this app using the launcher script, not directly!")
    logger.warning("Example: python launch_world_map.py")
