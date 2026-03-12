"""Legend configuration for the epidemic spread animation.

Edit the values in LEGEND_CONFIG to control the appearance and placement of
the static intensity legend drawn on the animation axes.
"""

LEGEND_CONFIG = {
    # Set to False to hide the legend entirely.
    "show": True,

    # Position of the first legend entry in axes coordinates (0-1).
    # (0, 0) is the bottom-left corner; (1, 1) is top-right.
    "x": 0.02,
    "y": 0.88,

    # Vertical gap between legend entries in axes coordinates.
    "spacing": 0.05,

    # Marker diameter in points.
    "markersize": 9,

    # Font size for entry labels and the optional title.
    "fontsize": 9,

    # Optional title drawn above the entries.  Set to None for no title.
    "title": "Intensity",

    # --- Background box ---
    "box_facecolor":  "#1a1a1a",  # fill colour
    "box_edgecolor":  "white",    # outline colour
    "box_alpha":      0.7,        # opacity (0 = transparent, 1 = opaque)
    "box_padding":    0.02,       # gap between content and box edge (axes coords)
    "box_width":      0.28,       # total width of the box (axes coords)
}
