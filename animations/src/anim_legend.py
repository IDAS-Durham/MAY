"""Custom legend drawing for epidemic animations.

The legend is built directly from the style_map produced by build_style_map(),
so its entries automatically stay in sync with the configured marker styles.
Each entry consists of a marker drawn with ax.plot() (using axes coordinates
so it stays fixed while the map data changes) and a text label placed to its
right.  A FancyBboxPatch is drawn behind all content to provide a coloured,
optionally translucent background box.
"""

from matplotlib.patches import FancyBboxPatch


def draw_legend(ax, style_map, cfg):
    """Draw a static marker-and-label legend onto the animation axes.

    The legend is drawn once before the animation loop starts and does not
    change between frames.  Axes coordinates are used for positioning, so the
    legend stays anchored to the same spot regardless of the map extent.

    Args:
        ax: The matplotlib Axes on which to draw.
        style_map: Dict mapping style key to augmented style dict, as returned
            by build_style_map().  Each entry must contain 'color',
            'edge_color', 'edge_width', and 'shape' keys.
        cfg: The LEGEND_CONFIG dict from legend_config.py.  Expected keys:
            show (bool), x (float), y (float), spacing (float),
            markersize (float), fontsize (float), title (str or None),
            box_facecolor (str), box_edgecolor (str), box_alpha (float),
            box_padding (float), box_width (float).
    """
    if not cfg.get("show", False):
        return

    lx        = cfg.get("x",             0.02)
    ly        = cfg.get("y",             0.92)
    spacing   = cfg.get("spacing",       0.06)
    msize     = cfg.get("markersize",    9)
    fontsize  = cfg.get("fontsize",      11)
    title     = cfg.get("title",         None)
    padding   = cfg.get("box_padding",   0.02)
    box_width = cfg.get("box_width",     0.35)

    # --- Background box ---
    # Height spans from the top content item to the bottom entry, plus padding.
    n_entries  = len(style_map)
    n_rows     = n_entries + (1 if title else 0)
    box_top    = ly + padding
    box_bottom = ly - (n_rows - 1) * spacing - padding
    box = FancyBboxPatch(
        (lx - padding, box_bottom),
        box_width + 2 * padding,
        box_top - box_bottom,
        boxstyle="round,pad=0.01",
        facecolor=cfg.get("box_facecolor", "#1a1a1a"),
        edgecolor=cfg.get("box_edgecolor", "white"),
        alpha=cfg.get("box_alpha", 0.7),
        transform=ax.transAxes,
        zorder=10,
        clip_on=False,
    )
    ax.add_patch(box)

    # Optional title above the entries
    if title:
        ax.text(lx, ly, title,
                transform=ax.transAxes,
                color="white", fontsize=fontsize, fontweight="bold",
                va="top", zorder=11)
        ly -= spacing

    # One marker + label per style
    for i, (key, sty) in enumerate(style_map.items()):
        entry_y = ly - i * spacing

        # Marker symbol — drawn with ax.plot so axes coordinates can be used
        ax.plot(lx + 0.02, entry_y,
                marker=sty.get("shape", "o"),
                color=sty["color"],
                markeredgecolor=sty.get("edge_color", sty["color"]),
                markeredgewidth=sty.get("edge_width", 0.5),
                markersize=msize,
                linestyle="none",
                transform=ax.transAxes,
                zorder=11)

        # Label to the right of the marker
        ax.text(lx + 0.05, entry_y, key,
                transform=ax.transAxes,
                color="white", fontsize=fontsize,
                va="center", zorder=11)
