# World Map - Interactive Visualization for World Instances

An interactive web-based visualization tool for exploring `World` class instances from the MAY framework. This application provides a rich, map-based interface for visualizing geography, population, venues, and households.

![World Map Visualization](screenshot.png)

## Features

- 🗺️ **Interactive Map**: Explore geographical units with Leaflet.js
- 🖼️ **Custom Backgrounds**: Use arbitrary images as map backgrounds (historical maps, fantasy worlds, etc.)
- 👥 **Population Visualization**: View population distribution across geographic levels
- 🏢 **Venue Mapping**: Visualize schools, hospitals, universities, and other venues
- 📊 **Rich Statistics**: Age distribution, sex distribution, and demographic breakdowns
- 🔍 **Detailed Views**: Click on any unit or venue for comprehensive information
- 📱 **Responsive Design**: Works on desktop and mobile devices

## Architecture

### Backend (Flask)
- **app.py**: Flask server with REST API endpoints
- Serves data directly from World instance (no HDF5 files needed)
- API endpoints for geography, population, venues, and households

### Frontend
- **templates/index.html**: Main HTML interface
- **static/css/style.css**: Responsive styling
- **static/js/app.js**: Interactive map logic with Leaflet.js

## Installation

### Requirements

```bash
pip install flask flask-cors
```

### Optional (for development)
- Python 3.8+
- Modern web browser (Chrome, Firefox, Safari, Edge)

## Usage

### Method 1: Launch with Example World

```bash
cd world_map
python launch_world_map.py --example
```

This creates a minimal example world and launches the visualization.

### Method 2: Launch with Saved World

```bash
python launch_world_map.py --world-file ../world_state.joblib
```

**Note**: You need to implement the `load_world_from_file()` function in `launch_world_map.py` to load your specific world format.

### Method 3: Custom Script

```python
from may.world import World
from world_map.app import initialize_app

# Create or load your world
world = World(geography=geography, population=population, venues=venues)

# Initialize and run the app
app = initialize_app(world)
app.run(host='0.0.0.0', port=5000, debug=True)
```

### Command Line Options

```bash
python launch_world_map.py --help

Options:
  --example              Create and use an example world
  --world-file PATH      Path to saved World instance file
  --host HOST            Host to run the server on (default: 127.0.0.1)
  --port PORT            Port to run the server on (default: 5000)
  --debug                Run in debug mode
  --map-background       Background map type: osm or image (default: osm)
  --map-image PATH       Path or URL to custom map background image
  --map-bounds BOUNDS    Geographic bounds: "south,west,north,east"
  --map-attribution TEXT Attribution text for custom map
```

## Custom Background Maps

The world map visualization supports **arbitrary background images** in addition to the default OpenStreetMap tiles. This is essential for historical worlds, fantasy settings, or any scenario where modern maps don't apply.

### Why Custom Backgrounds?

- **Historical Worlds**: Use period-accurate maps (e.g., Medieval England, Ancient Rome)
- **Fantasy Worlds**: Display fictional world maps
- **Alternate Geographies**: Show custom or imagined territories
- **Artistic Maps**: Use hand-drawn or stylized cartography

### Using a Custom Background Image

#### Basic Usage

```bash
python launch_world_map.py \
    --world-file world_state.joblib \
    --map-background image \
    --map-image /path/to/your_map.png \
    --map-bounds "50.0,-5.0,55.0,2.0" \
    --map-attribution "Custom Map - Your Attribution"
```

#### Parameters Explained

- `--map-background image`: Switch from OSM to custom image mode
- `--map-image`: Path to local file or URL to remote image
- `--map-bounds`: Geographic coordinates defining the image corners
  - Format: `"south,west,north,east"`
  - Example: `"50.0,-5.0,55.0,2.0"` (southern England)
- `--map-attribution`: Optional credit/attribution text

### Determining Geographic Bounds

The bounds define how your image maps to latitude/longitude coordinates. You need four values:

- **South**: Southern latitude (bottom edge)
- **West**: Western longitude (left edge)
- **North**: Northern latitude (top edge)
- **East**: Eastern longitude (right edge)

#### Method 1: Known Landmarks

If your map shows recognizable locations:
1. Identify 2-4 known points (cities, rivers, coastlines)
2. Look up their lat/long coordinates
3. Use corner or edge points to establish bounds

#### Method 2: Map Scale/Legend

If your map has a scale bar:
1. Measure the map dimensions
2. Use the scale to calculate geographic extent
3. Estimate corner coordinates

#### Method 3: GIS Software

For precise georeferencing:
1. Load image in QGIS (free GIS software)
2. Use the Georeferencer tool
3. Export corner coordinates

### Examples

#### Example 1: Medieval England Map

```bash
python launch_world_map.py \
    --world-file medieval_england.joblib \
    --map-background image \
    --map-image /data/maps/england_1200ad.jpg \
    --map-bounds "50.0,-6.0,56.0,2.0" \
    --map-attribution "Medieval England 1200 AD - Historical Atlas"
```

#### Example 2: Fantasy World

```bash
python launch_world_map.py \
    --world-file fantasy_realm.joblib \
    --map-background image \
    --map-image https://mycdn.com/fantasy_world_map.png \
    --map-bounds "-45.0,-180.0,45.0,180.0" \
    --map-attribution "Fantasy Realm © 2025"
```

#### Example 3: City Map (High Detail)

```bash
python launch_world_map.py \
    --world-file london_1800.joblib \
    --map-background image \
    --map-image /maps/london_1800_detailed.png \
    --map-bounds "51.45,-0.25,51.58,0.05" \
    --map-attribution "London 1800 - City Archives"
```

### Image Requirements

**Supported Formats:**
- PNG (recommended - supports transparency)
- JPG/JPEG
- GIF

**Recommended Specifications:**
- Resolution: 4000x4000 pixels or higher
- File size: Keep under 50MB for web performance
- Transparency: PNG with alpha channel supported
- Color depth: 24-bit or higher

**Coordinate System:**
- Use WGS84 lat/long (EPSG:4326)
- Latitude range: -90 (South Pole) to +90 (North Pole)
- Longitude range: -180 (West) to +180 (East)

### How It Works

The visualization uses Leaflet's `imageOverlay` feature to:
1. Display your image as a georeferenced layer
2. Align it with the specified geographic bounds
3. Allow markers and features to be placed using lat/long coordinates
4. Support standard map interactions (pan, zoom)

Your World instance's coordinates (from geographical units and venues) are plotted on top of the image using their latitude/longitude values.

### Switching Back to OpenStreetMap

To return to the default OpenStreetMap background:

```bash
python launch_world_map.py --world-file world.joblib
# --map-background defaults to 'osm'
```

Or explicitly:

```bash
python launch_world_map.py --world-file world.joblib --map-background osm
```

### Troubleshooting Custom Backgrounds

**Image doesn't display:**
- Check that the image file exists and path is correct
- Verify the image format is supported (PNG, JPG, GIF)
- For URLs, ensure the image is publicly accessible

**Markers appear in wrong locations:**
- Verify your bounds are correct (south < north, west < east)
- Check that coordinates match the geographic projection
- Ensure your World coordinates align with the map image

**Image is stretched or distorted:**
- Use an image with the correct aspect ratio for your bounds
- Lat/long spacing is not uniform (due to Earth's curvature)
- Consider using a map projection that matches your region

## API Endpoints

### Geography

- `GET /api/geography/levels` - Get available geography levels
- `GET /api/geography/<level>` - Get all units at a specific level (GeoJSON)
- `GET /api/geography/unit/<unit_name>` - Get detailed unit information

### Population

- `GET /api/population/statistics` - Get overall population statistics
- `GET /api/population/person/<person_id>` - Get detailed person information

### Venues

- `GET /api/venues/types` - Get all venue types and counts
- `GET /api/venues/<venue_type>` - Get all venues of a type (GeoJSON)
- `GET /api/venues/venue/<venue_id>` - Get detailed venue information

### Households

- `GET /api/households/statistics` - Get household statistics

### World

- `GET /api/world/statistics` - Get comprehensive world statistics

## Customization

### Adding New Visualizations

Edit `static/js/app.js` to add new map layers or visualization types:

```javascript
// Example: Add a heatmap layer
function addHeatmapLayer(data) {
    const heatLayer = L.heatLayer(data, {
        radius: 25,
        blur: 15,
        maxZoom: 17
    }).addTo(state.map);
}
```

### Styling

Modify `static/css/style.css` to customize colors, fonts, and layout:

```css
/* Example: Change primary color */
header {
    background: linear-gradient(135deg, #your-color 0%, #your-color-dark 100%);
}
```

### API Extensions

Add new endpoints in `app.py`:

```python
@app.route('/api/custom/endpoint')
def custom_endpoint():
    world = get_world()
    # Your custom logic here
    return jsonify(result)
```

## World Requirements

For the visualization to work properly, your `World` instance should have:

### Required:
- **Geography**: At least one geographic level with coordinates
- **Population**: People distributed across geographical units

### Optional but Recommended:
- **Venues**: Venues with types and coordinates
- **Households**: Household data for additional statistics

### Example World Structure

```python
from may.world import World
from may.geography import Geography
from may.population import PopulationManager
from may.geography import VenueManager

# Load geography with coordinates
geography = Geography(data_dir="data/geography", levels=["SGU", "MGU", "LGU"])
geography.load_from_csv()

# Load population
population = PopulationManager(geography, data_dir="data/population")
population.load_demographics_from_csv()
population.generate_population()

# Load venues (optional)
venues = VenueManager(geography, data_dir="data/venues")
venues.load_from_csv()

# Create world
world = World(geography=geography, population=population, venues=venues)
```

## Troubleshooting

### No data appears on the map

**Problem**: Map loads but no markers appear.

**Solutions**:
- Check that geographical units have coordinates
- Verify geography levels exist in your world
- Open browser console (F12) to check for JavaScript errors
- Check Flask terminal for API errors

### Port already in use

**Problem**: `Address already in use` error.

**Solution**:
```bash
python launch_world_map.py --example --port 5001
```

### World has no coordinates

**Problem**: Geographical units don't have latitude/longitude.

**Solution**: Ensure your geography CSV files include coordinate data:
```csv
# coord_sgu.csv
geo_unit,latitude,longitude
E00000001,51.5074,-0.1278
E00000002,51.5155,-0.1426
```

### Import errors

**Problem**: `ModuleNotFoundError: No module named 'may'`

**Solution**: Make sure you're running from the correct directory and the MAY framework is in the parent directory.

## Performance Tips

### Large Datasets

For worlds with many geographical units or venues:

1. **Enable clustering**: Modify `app.js` to use Leaflet.markercluster
2. **Implement pagination**: Load data in chunks based on viewport
3. **Cache API responses**: Add caching headers in Flask
4. **Use simpler geometries**: Reduce coordinate precision

### Example: Adding Marker Clustering

```html
<!-- Add to index.html -->
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
```

```javascript
// Modify app.js
const markers = L.markerClusterGroup();
// Add markers to cluster group
state.map.addLayer(markers);
```

## Development

### Project Structure

```
world_map/
├── app.py                  # Flask backend
├── launch_world_map.py     # Launcher script
├── README.md               # This file
├── templates/
│   └── index.html         # Main HTML page
└── static/
    ├── css/
    │   └── style.css      # Styles
    └── js/
        └── app.js         # Frontend logic
```

### Running in Development Mode

```bash
python launch_world_map.py --example --debug
```

This enables:
- Auto-reload on code changes
- Detailed error messages
- Flask debug toolbar

## License

This visualization tool is part of the MAY framework.

## Credits

Built with:
- [Flask](https://flask.palletsprojects.com/) - Python web framework
- [Leaflet.js](https://leafletjs.com/) - Interactive map library
- [OpenStreetMap](https://www.openstreetmap.org/) - Map tiles
