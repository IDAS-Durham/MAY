# Custom Background Maps - Implementation Summary

## Overview

The world_map visualization now supports **arbitrary background images** in addition to OpenStreetMap tiles. This enables visualization of historical worlds, fantasy settings, or any scenario where modern maps don't apply.

## What Was Implemented

### 1. Backend Changes (app.py)

**Added:**
- Global `_map_config` dictionary to store map configuration
- Updated `initialize_app(world, map_config=None)` to accept optional map configuration
- New API endpoint: `GET /api/map/config` to serve configuration to frontend
- Created `static/map_images/` directory for storing local images

**Configuration Structure:**
```python
_map_config = {
    'background_type': 'osm',  # 'osm' or 'image'
    'image_url': None,         # URL or path to image
    'bounds': None,            # [[south, west], [north, east]]
    'attribution': None        # Attribution text
}
```

### 2. Frontend Changes (app.js)

**Updated State:**
```javascript
const state = {
    map: null,
    baseLayer: null,      // NEW: Track base layer
    imageBounds: null,    // NEW: Bounds for image overlay
    mapConfig: null,      // NEW: Store configuration
    // ... existing state
};
```

**New Functions:**
- `loadMapConfiguration()` - Fetches config from backend API
- Rewrote `initializeMap()` - Supports both OSM tiles and image overlays

**Image Overlay Logic:**
- Uses Leaflet's `L.imageOverlay()` with geographic bounds
- Employs standard Web Mercator projection (EPSG:3857)
- Centers map on image and fits bounds automatically

### 3. Launcher Changes (launch_world_map.py)

**New Command-Line Arguments:**
- `--map-background` (osm|image) - Choose background type
- `--map-image` (path/URL) - Path to custom image
- `--map-bounds` (string) - Geographic bounds "south,west,north,east"
- `--map-attribution` (string) - Attribution text

**Features:**
- Validates bounds format and values
- Checks if local image files exist
- Automatically copies local images to `static/map_images/`
- Converts local paths to URL paths
- Supports remote image URLs (HTTP/HTTPS)

### 4. Documentation (README.md)

**Added Comprehensive Section:**
- Why use custom backgrounds
- How to use them (examples)
- How to determine geographic bounds (3 methods)
- Image requirements and recommendations
- Troubleshooting guide
- Multiple real-world examples

## Usage Examples

### Example 1: Medieval England Map

```bash
python launch_world_map.py \
    --world-file medieval_england.joblib \
    --map-background image \
    --map-image /path/to/medieval_england_1200.png \
    --map-bounds "50.0,-6.0,56.0,2.0" \
    --map-attribution "Medieval England 1200 AD"
```

### Example 2: Fantasy World

```bash
python launch_world_map.py \
    --world-file fantasy_world.joblib \
    --map-background image \
    --map-image "https://cdn.example.com/fantasy_map.jpg" \
    --map-bounds "-45.0,-180.0,45.0,180.0" \
    --map-attribution "Fantasy Realm © 2025"
```

### Example 3: Default OpenStreetMap (No Change)

```bash
python launch_world_map.py --world-file world.joblib
# Uses OSM by default - backward compatible!
```

## How It Works

### Geographic Referencing

1. User provides image and four corner coordinates (south, west, north, east)
2. Backend stores this configuration
3. Frontend fetches configuration via `/api/map/config`
4. Leaflet creates an `imageOverlay` with the specified bounds
5. World markers (geography, venues) are plotted using their lat/long coordinates
6. The image is stretched/projected to fit the geographic bounds

### Coordinate Alignment

The key is that:
- **Your World's coordinates** (lat/long from geographical units and venues) remain unchanged
- **The image** is stretched to fit the specified geographic bounds
- **Markers** are placed using standard lat/long, which Leaflet maps onto the image

This means your World instance must have coordinates that align with the image's geography.

## File Structure

```
world_map/
├── static/
│   ├── map_images/          # NEW: Directory for custom images
│   ├── js/
│   │   └── app.js          # MODIFIED: Added image overlay support
│   └── css/
│       └── style.css       # Unchanged
├── templates/
│   └── index.html          # Unchanged
├── app.py                  # MODIFIED: Added map config support
├── launch_world_map.py     # MODIFIED: Added CLI arguments
└── README.md               # MODIFIED: Added documentation
```

## Backward Compatibility

✅ **Fully backward compatible**

- Default behavior unchanged: Uses OpenStreetMap tiles
- Existing scripts continue to work without modification
- Custom backgrounds are opt-in via command-line arguments

## Technical Details

### Image Overlay Implementation

Uses Leaflet's `L.imageOverlay()`:

```javascript
L.imageOverlay(imageUrl, bounds, {
    attribution: 'Custom Map Image',
    opacity: 0.9,
    interactive: false
}).addTo(map);
```

### Bounds Format

- **Input**: `"south,west,north,east"` (comma-separated string)
- **Parsed**: `[[south, west], [north, east]]` (nested array)
- **Leaflet**: `L.latLngBounds(L.latLng(south, west), L.latLng(north, east))`

### Coordinate System

- Uses WGS84 geographic coordinates (EPSG:4326)
- Leaflet displays in Web Mercator projection (EPSG:3857)
- Automatic transformation handled by Leaflet

## Limitations and Considerations

### Distortion

Latitude/longitude spacing is not uniform due to Earth's curvature. Images may appear distorted, especially:
- Near poles
- Over large areas
- For maps using different projections

**Solution**: Use images that match or are close to Web Mercator projection.

### Performance

Large images (>10MB) may:
- Take time to load
- Consume memory
- Slow down zooming/panning

**Solution**: Optimize images before use (compress, resize, tile).

### Accuracy

The accuracy of marker placement depends on:
- Correctness of the specified bounds
- Alignment between image geography and World coordinates
- Projection differences

**Solution**: Use GIS tools for precise georeferencing.

## Future Enhancements

Potential improvements:

1. **Interactive Georeferencing**: Web UI to adjust bounds visually
2. **Multiple Layers**: Support for base map + overlays
3. **Opacity Control**: Slider to adjust image transparency
4. **Tile Generation**: Pre-generate tiles from large images
5. **CRS Support**: Support for other coordinate reference systems
6. **Rotation**: Allow rotated images
7. **Warping**: Non-rectangular image warping for better projection matching

## Testing Checklist

Tested scenarios:
- ✅ OpenStreetMap default (backward compatibility)
- ✅ Local PNG image with geographic bounds
- ✅ Local JPG image with geographic bounds
- ✅ Remote image URL (HTTP/HTTPS)
- ✅ Invalid bounds (proper error messages)
- ✅ Missing image file (proper error messages)
- ✅ Image transparency (PNG alpha)
- ✅ Multiple geographic levels (SGU, MGU, LGU)
- ✅ Venue markers on custom background
- ✅ Popup interactions on custom background

## Support

For issues:
- Check the README's "Troubleshooting Custom Backgrounds" section
- Verify your bounds are correct (south < north, west < east)
- Test with OpenStreetMap first to verify your World data is correct
- Check browser console for JavaScript errors

## Credits

- **Leaflet.js**: Map rendering and image overlays
- **OpenStreetMap**: Default tile layer
- **Flask**: Backend framework
- **Python argparse**: Command-line interface
