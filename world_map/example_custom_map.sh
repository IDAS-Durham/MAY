#!/bin/bash
# Example: Launching world_map with a custom background image
#
# This example script demonstrates how to use a custom map background
# for visualizing historical or fictional worlds.

# ==============================================================================
# Configuration
# ==============================================================================

# Path to your World instance file
WORLD_FILE="../my_world.joblib"

# Path to your custom map image (local file or URL)
# Examples:
#   Local: "/path/to/medieval_england.png"
#   URL:   "https://example.com/maps/england_1200.jpg"
MAP_IMAGE="/path/to/your_custom_map.png"

# Geographic bounds of your map image
# Format: "south,west,north,east"
#
# These coordinates define the corners of your image:
#   south = southern latitude (bottom edge)
#   west  = western longitude (left edge)
#   north = northern latitude (top edge)
#   east  = eastern longitude (right edge)
#
# Example for England: "50.0,-6.0,56.0,2.0"
MAP_BOUNDS="50.0,-6.0,56.0,2.0"

# Attribution text for your map
MAP_ATTRIBUTION="Custom Map - Your Attribution Here"

# Server configuration
HOST="127.0.0.1"
PORT="5000"

# ==============================================================================
# Launch Command
# ==============================================================================

echo "============================================================"
echo "Launching World Map with Custom Background"
echo "============================================================"
echo ""
echo "World File: $WORLD_FILE"
echo "Map Image:  $MAP_IMAGE"
echo "Bounds:     $MAP_BOUNDS"
echo "Server:     http://$HOST:$PORT"
echo ""
echo "============================================================"
echo ""

python launch_world_map.py \
    --world-file "$WORLD_FILE" \
    --map-background image \
    --map-image "$MAP_IMAGE" \
    --map-bounds "$MAP_BOUNDS" \
    --map-attribution "$MAP_ATTRIBUTION" \
    --host "$HOST" \
    --port "$PORT"

# ==============================================================================
# Notes
# ==============================================================================
#
# To use this script:
# 1. Edit the configuration variables above
# 2. Make the script executable: chmod +x example_custom_map.sh
# 3. Run it: ./example_custom_map.sh
#
# To switch back to OpenStreetMap:
# python launch_world_map.py --world-file "$WORLD_FILE"
#
# For more examples, see README.md
