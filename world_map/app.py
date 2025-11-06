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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global world instance - set via initialize_app()
_world_instance = None


def initialize_app(world):
    """
    Initialize the Flask app with a World instance.

    Args:
        world: World instance to visualize

    Returns:
        Flask app instance
    """
    global _world_instance
    _world_instance = world

    logger.info(f"Initialized world map with: {world}")
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

            # Count population and venues
            population = len(unit.people) if unit.people else 0
            venues_count = len(unit.venues) if unit.venues else 0

            # Get venue breakdown
            venue_types = defaultdict(int)
            if unit.venues:
                for venue in unit.venues:
                    venue_types[venue.type] += 1

            feature = {
                'type': 'Feature',
                'properties': {
                    'id': unit.id,
                    'name': unit.name,
                    'level': unit.level,
                    'population': population,
                    'venues_count': venues_count,
                    'venue_types': dict(venue_types),
                    'has_parent': unit.parent is not None,
                    'children_count': len(unit.children) if unit.children else 0
                },
                'geometry': {
                    'type': 'Point',
                    'coordinates': [lon, lat]  # GeoJSON: [longitude, latitude]
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
    """Get detailed information about a specific geographical unit."""
    try:
        world = get_world()
        if not world.geography:
            return jsonify({'error': 'No geography data'}), 404

        unit = world.geography.get_unit(unit_name)
        if not unit:
            return jsonify({'error': f'Unit {unit_name} not found'}), 404

        # Collect detailed statistics
        age_groups = {
            '0-15': 0, '16-24': 0, '25-34': 0,
            '35-49': 0, '50-64': 0, '65+': 0
        }

        sex_distribution = defaultdict(int)

        for person in unit.people:
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

        # Venue breakdown
        venue_details = []
        venue_types = defaultdict(int)
        if unit.venues:
            for venue in unit.venues:
                venue_types[venue.type] += 1
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
                children_info.append({
                    'id': child.id,
                    'name': child.name,
                    'level': child.level,
                    'population': len(child.people)
                })

        return jsonify({
            'id': unit.id,
            'name': unit.name,
            'level': unit.level,
            'coordinates': unit.coordinates,
            'population': len(unit.people),
            'age_distribution': age_groups,
            'sex_distribution': dict(sex_distribution),
            'venues_count': len(unit.venues),
            'venue_types': dict(venue_types),
            'venue_details': venue_details[:50],  # Limit to first 50
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
    """Get detailed information about a specific person."""
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

        return jsonify({
            'id': person.id,
            'age': person.age,
            'sex': person.sex,
            'activities': person.activities,
            'properties': person.properties,
            'geographical_unit': geo_info
        })

    except Exception as e:
        logger.error(f"Error getting person details for {person_id}: {e}")
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
                    'id': venue.id,
                    'name': venue.name,
                    'type': venue.type,
                    'geographical_unit': venue.geographical_unit.name if venue.geographical_unit else None,
                    'num_members': total_members,
                    'properties': venue.properties
                },
                'geometry': {
                    'type': 'Point',
                    'coordinates': [lon, lat]
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
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting world statistics: {e}")
        return jsonify({'error': str(e)}), 500


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
