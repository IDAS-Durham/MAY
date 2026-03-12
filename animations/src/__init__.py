"""Epidemic animation support library."""

from .sim_data_loader import load_simulation_events
from .map_utils import get_map, set_gif_play_once, fetch_esri_map
from .anim_styles import build_style_map, get_visibility_window
from .anim_legend import draw_legend

__all__ = [
    "load_simulation_events",
    "get_map",
    "set_gif_play_once",
    "fetch_esri_map",
    "build_style_map",
    "get_visibility_window",
    "draw_legend",
]
