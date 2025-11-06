# World Map - Interactive Visualization for World Instances

An interactive web-based visualization tool for exploring `World` class instances from the MAY framework. This application provides a rich, map-based interface for visualizing geography, population, venues, and households.

![World Map Visualization](screenshot.png)

## Features

- 🗺️ **Interactive Map**: Explore geographical units with Leaflet.js
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
```

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
