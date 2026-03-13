#!/usr/bin/env python3
"""Epidemic Spread Animation — simulation_events.h5 → MP4.

Renders a geo-unit choropleth animation of infection and death spread from a
MAY framework ``simulation_events.h5`` file.  Each settlement centroid is drawn
as a circle whose colour and opacity reflect the local event intensity in a
sliding time window.  An epidemic-curve subplot below the map tracks cumulative
and daily event counts.

Run (smoke test — small time range)::

    python animations/animate_epidemic.py \\
        --events world_map/data/simulation_events_5_mar_whole_world.h5 \\
        --world  world_map/data/world_state_medieval_updated.h5 \\
        --time-range 0 30 \\
        --output /tmp/test_epidemic.mp4

Full run (uses CONFIG defaults)::

    python animations/animate_epidemic.py

Edit CONFIG below to customise the animation.
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.colors as mcolors
import numpy as np
from scipy import stats

# Ensure the animations/ directory is on sys.path so src/ is importable
# whether the script is run from the project root or from animations/.
_ANIM_DIR = os.path.dirname(os.path.abspath(__file__))
if _ANIM_DIR not in sys.path:
    sys.path.insert(0, _ANIM_DIR)

from src import load_simulation_events, get_map, get_visibility_window  # noqa: E402
from legend_config import LEGEND_CONFIG  # noqa: E402

# ============================================================
# CONFIGURATION  ← edit these values to customise the animation
# ============================================================
CONFIG = {
    # --- Data files ---
    "events_file":      "world_map/data/simulation_events_with_rats.h5",
    "world_state_file": "world_map/data/world_state_medieval_updated_low_contact_high_cluster.h5",

    # --- What to animate ---
    "event_types": ["infections", "deaths"],   # subset or both , "deaths"

    # --- Animation timing ---
    "fps":            10,     # frames per second
    "days_per_frame": 1.0,    # simulation days advanced per frame
    "time_range":  None,   # [start_day, end_day] or None = full simulation

    # --- Geo-unit display ---
    "show_geo_unit_markers":     False,   # dim baseline circles for all units
    "geo_unit_level":            "MBD_Temp_ID",  # geography level to animate
    "geo_unit_marker_base_size": 20,     # scatter size in pt² (before scaling)
    "geo_unit_size_method":      "fixed",  # "fixed" or "population"

    # --- Per-event-type fade distribution and colour ---
    "event_styles": {
        "infections": {
            "color":        "#ff6600",
            "edge_color":   "#aa3300",
            "alpha_max":    1.0,
            "distribution": stats.norm(loc=0, scale=2),   #stats.uniform(loc=0, scale=7),  # visible 7 sim-days
            "alpha_floor":  0.0,
            "size_scale":   1.5,
        },
        "deaths": {
            "color":        "#1a1a2e",
            "edge_color":   "#00000000",
            "alpha_max":    0.7,
            "distribution": stats.uniform(loc=0, scale=1000),
            "alpha_floor":  0.0,
            "size_scale":   1.5,
            "normalize_by_population": True,   # colour ∝ % of geo-unit population dead
        },
    },

    # --- Intensity → colour thresholds (events in window per geo_unit) ---
    # Each list maps to intensity_colors entries; None = catch-all top bucket.
    "intensity_thresholds": {
        "infections": [1,  5,  20, 100, None],
        "deaths":     [0.01, 10.0, 40.0, 70.0, None],  # % of geo-unit population
    },
    "intensity_colors": {
        "infections": ["#ffe0b2", "#ffb74d", "#ff9800", "#e65100", "#b71c1c"],
        "deaths":     ["#cfd8dc", "#90a4ae", "#546e7a", "#263238", "#000000"],
    },

    # --- Epidemic curve subplot ---
    "show_stats":         False,
    "stats_height_ratio": [4, 1],          # map : curve height ratio
    "curve_event_types":  ["infections", "deaths"],

    # --- Map background (same API as tmp/animations) ---
    # Geographic bounding box of the animation window (WGS-84 decimal degrees)
    "map_bbox": {
        "west":  -6.0,
        "east":   2.0,
        "south": 49.0,
        "north": 56.0,
    },

    # Corners of the image file when they differ from map_bbox; None to use map_bbox.
    "image_corners": {"west": -6.05, "east": 2.05, "south": 49.05, "north": 56.21},

    "map_image":  'world_map/data/Topographic_Map_of_the_UK_Blank (Edited).png', # 'world_map/image1.png',#  'world_map/Topographic_Map_of_the_UK_cropped.png',           # None = auto-download ESRI; path = custom image  #
#    "map_bbox":     {"west": -7.0, "east": 2.0, "south": 50.0, "north": 56.0},
#    "image_corners": {"west": -7.0, "east": 2.0, "south": 50.0, "north": 56.0},
    "map_resolution": (900, 1100),  # pixel resolution for ESRI download

    # --- Output ---
    "output_file":   "animations/output/epidemic_infections_only_no_rats.mp4",
    "output_format": "mp4",         # "mp4" or "gif"
    "figure_size":   (8, 8),
    "dpi":           120,
    "title":         "Medieval Epidemic Spread",
}
# ============================================================
# Legend appearance is configured separately in legend_config.py


def _precompute_event_styles(cfg: dict) -> dict:
    """Augment each event_style dict with precomputed distribution parameters.

    Args:
        cfg: The CONFIG dict.

    Returns:
        Dict mapping event_type → augmented style dict with ``_dist``,
        ``_pdf_max``, ``_t_low``, ``_t_high``, ``_alpha_floor`` keys added.
    """
    result = {}
    for et in cfg["event_types"]:
        sty         = dict(cfg["event_styles"].get(et, {}))
        dist        = sty.get("distribution", stats.uniform(loc=0, scale=7))
        alpha_floor = sty.get("alpha_floor", 0.05)
        t_low, t_high, pdf_max = get_visibility_window(dist, threshold=alpha_floor)
        sty.update({
            "_dist":        dist,
            "_pdf_max":     pdf_max,
            "_t_low":       t_low,
            "_t_high":      t_high,
            "_alpha_floor": alpha_floor,
        })
        print(f"  {et}: visibility window [{t_low:.1f}, {t_high:.1f}] days"
              f"  (pdf_max={pdf_max:.6g})")
        result[et] = sty
    return result


def _build_color_tables(cfg: dict) -> dict:
    """Pre-convert intensity colour strings to (N, 4) RGBA float arrays.

    Args:
        cfg: The CONFIG dict.

    Returns:
        Dict mapping event_type → ndarray shape (N_buckets, 4) float32.
    """
    tables = {}
    for et in cfg["event_types"]:
        colors = cfg["intensity_colors"].get(et, [])
        tables[et] = np.array([mcolors.to_rgba(c) for c in colors], dtype=np.float32)
    return tables


def _draw_intensity_legend(ax, cfg: dict, legend_cfg: dict):
    """Draw an intensity colour-scale legend into a dedicated legend axes.

    The axes background and border are styled by the caller; this function only
    draws the text and marker content.

    Args:
        ax: Dedicated legend Axes (not the map axes).
        cfg: The CONFIG dict.
        legend_cfg: The LEGEND_CONFIG dict.
    """
    if not legend_cfg.get("show", False):
        return

    lx      = legend_cfg.get("x",       0.15)
    ly      = legend_cfg.get("y",       0.95)
    spacing = legend_cfg.get("spacing", 0.05)
    msize   = legend_cfg.get("markersize", 10)
    fsize   = legend_cfg.get("fontsize",   16)
    title   = legend_cfg.get("title",   None)

    cur_y = ly
    if title:
        ax.text(lx, cur_y, title,
                transform=ax.transAxes, color="black",
                fontsize=fsize, fontweight="bold", va="top")
        cur_y -= spacing

    for et in cfg["event_types"]:
        colors     = cfg["intensity_colors"].get(et, [])
        thresholds = cfg["intensity_thresholds"].get(et, [])

        # Event type header
        sty_color = cfg["event_styles"].get(et, {}).get("color", "white")
        ax.text(lx, cur_y, et.capitalize(),
                transform=ax.transAxes, color=sty_color,
                fontsize=fsize, fontweight="bold", va="center")
        cur_y -= spacing

        for i, color in enumerate(colors):
            ax.plot(lx + 0.12, cur_y,
                    marker="o", color=color,
                    markeredgecolor="#555555", markeredgewidth=0.3,
                    markersize=msize, linestyle="none",
                    transform=ax.transAxes)

            thr_lo = thresholds[i - 1] if i > 0 else 0
            thr_hi = thresholds[i] if i < len(thresholds) else None
            label  = f"≥{thr_lo}" if thr_hi is None else f"{thr_lo}–{thr_hi}"

            ax.text(lx + 0.25, cur_y, label,
                    transform=ax.transAxes, color="black",
                    fontsize=fsize - 2, va="center")
            cur_y -= spacing


def build_animation(cfg: dict):
    """Construct and save the epidemic spread animation.

    Args:
        cfg: The CONFIG dict defined at the top of this module.
    """
    # --- 1. Load and aggregate simulation data ---
    print("Loading simulation events...")
    sim = load_simulation_events(cfg)

    geo_units = sim["geo_units"]
    U         = len(geo_units)
    lons      = np.array([u["lon"] for u in geo_units], dtype=np.float64)
    lats      = np.array([u["lat"] for u in geo_units], dtype=np.float64)
    pops      = np.array([u["pop"] for u in geo_units], dtype=np.float64)

    # --- 2. Pre-compute per-event-type style parameters ---
    print("Pre-computing event styles...")
    event_styles = _precompute_event_styles(cfg)
    color_tables = _build_color_tables(cfg)

    # --- 3. Load map background ---
    print("Preparing map...")
    map_img, img_extent = get_map(cfg)
    bbox = cfg["map_bbox"]

    # --- 4. Build figure ---
    from matplotlib.gridspec import GridSpec

    show_stats = cfg.get("show_stats", True)
    fig = plt.figure(figsize=cfg["figure_size"], dpi=cfg["dpi"])
    fig.patch.set_facecolor("#1a1a1a")

    if show_stats:
        gs = GridSpec(
            2, 2, figure=fig,
            width_ratios=[1, 4],
            height_ratios=cfg["stats_height_ratio"],
            hspace=0.04, wspace=0.05,
        )
        ax_legend = fig.add_subplot(gs[:, 0])
        ax_map    = fig.add_subplot(gs[0, 1])
        ax_curve  = fig.add_subplot(gs[1, 1])
    else:
        gs = GridSpec(1, 2, figure=fig, width_ratios=[1, 4], wspace=0.05)
        ax_legend = fig.add_subplot(gs[0, 0])
        ax_map    = fig.add_subplot(gs[0, 1])
        ax_curve  = None

    # Legend axes styling — dark background, white border, no ticks
    ax_legend.set_facecolor(LEGEND_CONFIG.get("box_facecolor", "#1a1a1a"))
    ax_legend.set_xlim(0, 1)
    ax_legend.set_ylim(0, 1)
    ax_legend.set_xticks([])
    ax_legend.set_yticks([])
    for spine in ax_legend.spines.values():
        spine.set_edgecolor(LEGEND_CONFIG.get("box_edgecolor", "white"))
        spine.set_linewidth(0.8)

    # Map axes
    ax_map.set_facecolor("#1a1a1a")
    ax_map.imshow(
        np.array(map_img),
        extent=[img_extent["west"], img_extent["east"],
                img_extent["south"], img_extent["north"]],
        aspect="auto", origin="upper", zorder=0,
    )
    ax_map.set_xlim(bbox["west"],  bbox["east"])
    ax_map.set_ylim(bbox["south"], bbox["north"])
    ax_map.axis("off")
    ax_map.set_title(cfg["title"], color="white", fontsize=16, pad=6, fontweight="bold")

    # Dim baseline markers for all geo-units
    if cfg.get("show_geo_unit_markers", True):
        base_size = cfg.get("geo_unit_marker_base_size", 20)
        ax_map.scatter(lons, lats, s=base_size, c="#888888",
                       alpha=0.03, linewidths=0, zorder=2)

    # One scatter per event type — updated each frame
    scats = {}
    for et in cfg["event_types"]:
        sty       = event_styles[et]
        base_size = cfg.get("geo_unit_marker_base_size", 20) * sty.get("size_scale", 1.0)
        sc = ax_map.scatter([], [], s=base_size, linewidths=0, zorder=5)
        scats[et] = sc

    # Text overlays
    label_box = dict(boxstyle="round,pad=0.4", facecolor="#1a1a1a", alpha=0.7)
    day_text = ax_map.text(
        0.02, 0.02, "",
        transform=ax_map.transAxes, color="white",
        fontsize=12, ha="left", va="bottom", bbox=label_box, zorder=10,
    )
    stat_text = ax_map.text(
        0.98, 0.02, "",
        transform=ax_map.transAxes, color="white",
        fontsize=12, ha="right", va="bottom", bbox=label_box, zorder=10,
    )

    # Intensity legend — drawn into the dedicated left-hand panel
    _draw_intensity_legend(ax_legend, cfg, LEGEND_CONFIG)

    # --- 5. Epidemic curve subplot ---
    cursor_line = None
    if ax_curve is not None:
        ax_curve.set_facecolor("#1a1a1a")
        days_axis = np.arange(sim["n_days"]) + sim["day_offset"]

        for et in cfg.get("curve_event_types", cfg["event_types"]):
            if et not in sim["daily_global"]:
                continue
            color = cfg["event_styles"].get(et, {}).get("color", "white")
            ax_curve.plot(days_axis, sim["daily_global"][et],
                          color=color, lw=1.0, label=et, alpha=0.85)

        cursor_line = ax_curve.axvline(
            x=sim["time_range"][0], color="white", lw=0.8, alpha=0.5, zorder=5
        )
        ax_curve.set_xlim(sim["time_range"])
        ax_curve.set_xlabel("Simulation day", color="white", fontsize=7)
        ax_curve.set_ylabel("Daily events",   color="white", fontsize=7)
        ax_curve.tick_params(colors="white", labelsize=6)
        for spine in ax_curve.spines.values():
            spine.set_color("#555555")
        ax_curve.legend(fontsize=7, labelcolor="white",
                        facecolor="#1a1a1a", edgecolor="#555555",
                        loc="upper left")

    # --- 6. Animation frame parameters ---
    t_start, t_end = sim["time_range"]
    n_frames = int(np.ceil((t_end - t_start) / cfg["days_per_frame"])) + 1
    print(f"Animation: {n_frames} frames  "
          f"(day {t_start:.1f} → {t_end:.1f}, {cfg['days_per_frame']} day/frame)")

    # --- 7. Per-frame update function ---
    def update(frame_idx):
        t = t_start + frame_idx * cfg["days_per_frame"]

        artists = []

        for et in cfg["event_types"]:
            sty         = event_styles[et]
            dist        = sty["_dist"]
            pdf_max     = sty["_pdf_max"]
            alpha_max   = sty.get("alpha_max", 1.0)
            alpha_floor = sty["_alpha_floor"]
            t_low       = sty["_t_low"]
            t_high      = sty["_t_high"]
            sc          = scats[et]

            if et not in sim["counts"]:
                sc.set_offsets(np.empty((0, 2)))
                artists.append(sc)
                continue

            # Days in the visibility window for the current time t
            d_start = max(0, int(np.floor(t + t_low)))
            d_end   = min(sim["n_days"] - 1, int(np.ceil(t + t_high)))

            if d_start > d_end:
                sc.set_offsets(np.empty((0, 2)))
                artists.append(sc)
                continue

            days_in_window = np.arange(d_start, d_end + 1)
            # Fade weights: pdf(t - d) normalised to [0, alpha_max]
            offsets = t - days_in_window.astype(np.float64)
            weights = dist.pdf(offsets)
            if pdf_max > 0:
                weights = weights / pdf_max * alpha_max

            # intensity_vec: weighted event count per geo_unit  shape (U,)
            counts_window = sim["counts"][et][:, d_start:d_end + 1]  # (U, W)
            intensity_vec = counts_window @ weights                   # (U,)

            # Optionally normalise by geo-unit population → % of population affected
            if sty.get("normalize_by_population", False):
                display_vec = intensity_vec / np.maximum(pops, 1) * 100.0
            else:
                display_vec = intensity_vec

            # Map intensity → colour bucket
            thresholds = [x for x in cfg["intensity_thresholds"][et] if x is not None]
            buckets    = np.searchsorted(thresholds, display_vec)
            buckets    = np.clip(buckets, 0, len(color_tables[et]) - 1)

            rgba = color_tables[et][buckets].copy()  # (U, 4) float32
            max_thresh = float(thresholds[-1]) if thresholds else 1.0
            raw_alpha  = (display_vec / max_thresh).astype(np.float32)
            rgba[:, 3] = np.clip(raw_alpha, 0.0, alpha_max)
            # Hide units with no events in the window
            rgba[intensity_vec < 0.01, 3] = 0.0

            base_size = cfg.get("geo_unit_marker_base_size", 20) * sty.get("size_scale", 1.0)

            sc.set_offsets(np.column_stack([lons, lats]))
            sc.set_facecolor(rgba)
            # Edge colour: slightly darker, same alpha
            edge_rgba = rgba.copy()
            edge_rgba[:, :3] *= 0.6
            sc.set_edgecolor(edge_rgba)
            sc.set_sizes(np.full(U, base_size))
            artists.append(sc)

        # Update cursor line
        if cursor_line is not None:
            cursor_line.set_xdata([t, t])
            artists.append(cursor_line)

        # Update text
        day_int = int(np.clip(np.floor(t) - sim["day_offset"], 0, sim["n_days"] - 1))
        day_text.set_text(f"Day {int(np.floor(t))}")

        lines = []
        for et in cfg["event_types"]:
            if et not in sim["daily_global"]:
                continue
            daily = int(sim["daily_global"][et][day_int])
            cum   = int(sim["cumulative"][et][day_int])
            lines.append(f"New {et}: {daily:,}")
            lines.append(f"Total {et}: {cum:,}")
        stat_text.set_text("\n".join(lines))

        artists.extend([day_text, stat_text])
        return artists

    ani = animation.FuncAnimation(
        fig, update, frames=n_frames,
        interval=1000 / cfg["fps"],
        blit=False, repeat=False,
    )

    # --- 8. Save ---
    out = cfg["output_file"]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    fmt = cfg.get("output_format", "mp4").lower()
    print(f"Rendering {n_frames} frames → {out}  (this may take a while)...")
    if fmt == "mp4":
        writer = animation.FFMpegWriter(
            fps=cfg["fps"], bitrate=2000,
            extra_args=["-pix_fmt", "yuv420p"],
        )
        ani.save(out, writer=writer, dpi=cfg["dpi"])
    else:
        ani.save(out, writer="pillow", fps=cfg["fps"])
        from src import set_gif_play_once
        set_gif_play_once(out)

    plt.close(fig)
    print(f"Done. Saved: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render epidemic spread animation from simulation_events.h5"
    )
    parser.add_argument("--events",     help="Path to simulation_events.h5")
    parser.add_argument("--world",      help="Path to world_state.h5")
    parser.add_argument("--output",     help="Output file path (.mp4 or .gif)")
    parser.add_argument("--time-range", nargs=2, type=float,
                        metavar=("START", "END"),
                        help="Simulation day range to animate")
    args = parser.parse_args()

    if args.events:
        CONFIG["events_file"] = args.events
    if args.world:
        CONFIG["world_state_file"] = args.world
    if args.output:
        CONFIG["output_file"] = args.output
        # Infer format from extension
        if args.output.lower().endswith(".gif"):
            CONFIG["output_format"] = "gif"
        else:
            CONFIG["output_format"] = "mp4"
    if args.time_range:
        CONFIG["time_range"] = args.time_range

    build_animation(CONFIG)
