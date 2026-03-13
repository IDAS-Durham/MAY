"""Legend configuration for the epidemic spread animation.

Edit the values in LEGEND_CONFIG to control the appearance of the legend panel
displayed to the left of the map.
"""

LEGEND_CONFIG = {
    # Set to False to hide the legend panel entirely.
    "show": True,

    # Position of the first legend entry within the legend axes (axes coords 0-1).
    # x=0.15 leaves a small left margin; y=0.95 starts near the top.
    "x": 0.15,
    "y": 0.95,

    # Vertical gap between legend entries in axes coordinates.
    "spacing": 0.055,

    # Marker diameter in points.
    "markersize": 10,

    # Font size for entry labels and the optional title.
    "fontsize": 12,

    # Optional title drawn above the entries.  Set to None for no title.
    "title": "Intensity",

    # --- Legend panel background and border ---
    "box_facecolor": "#FFFFFF", #"#1a1a1a",   # panel background colour
    "box_edgecolor": None, #"#888888",   # panel border colour
}
