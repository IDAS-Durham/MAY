"""Marker style configuration and distribution window utilities.

Each style dict in CONFIG['styles'] is augmented here with five private keys
used at render time:

    _dist        – the resolved scipy.stats distribution
    _alpha_floor – the resolved minimum visible alpha
    _pdf_max     – peak value of the distribution's PDF
    _t_low       – earliest day offset (relative to death date) where alpha >= floor
    _t_high      – latest  day offset (relative to death date) where alpha >= floor
"""

import numpy as np


def get_visibility_window(dist, threshold=0.05, search_days=1000):
    """Find the day-offset range over which a distribution's PDF exceeds a threshold.

    The distribution is evaluated in reversed-time convention (``dist.pdf(-t)``)
    so that distributions defined over positive support appear *before* the
    death date.  The window is found by dense sampling rather than root-finding
    to remain robust across all scipy.stats distribution shapes.

    Args:
        dist: A frozen ``scipy.stats`` distribution.
        threshold: Minimum normalised PDF value (pdf / pdf_max) required for a
            marker to be visible.  Defaults to 0.05.
        search_days: Half-width of the sampling range in days.  Defaults to
            1000, which covers any realistic mortality signal.

    Returns:
        A ``(t_low, t_high, pdf_max)`` tuple where ``t_low`` and ``t_high`` are
        float day offsets from the death date and ``pdf_max`` is the peak PDF
        value used for alpha normalisation.
    """
    t_samples = np.linspace(-search_days, search_days, search_days * 20 + 1)
    pdf_vals  = dist.pdf(-t_samples)
    pdf_max   = float(pdf_vals.max())

    above = (pdf_vals / pdf_max) >= threshold
    if not above.any():
        return 0.0, 0.0, pdf_max

    return float(t_samples[above][0]), float(t_samples[above][-1]), pdf_max


def build_style_map(cfg):
    """Construct the style lookup dict with precomputed distribution parameters.

    Each entry extends the user-supplied style dict with private keys
    (``_dist``, ``_alpha_floor``, ``_pdf_max``, ``_t_low``, ``_t_high``)
    consumed by the animation's ``update`` function.  Per-style ``distribution``
    and ``alpha_floor`` values override the top-level config defaults.

    Args:
        cfg: The CONFIG dict.  Must contain ``styles``, ``distribution``, and
            ``alpha_floor``.  Optionally contains ``style_column``.

    Returns:
        A dict mapping style key to augmented style dict.  The key is the
        ``label`` string when ``style_column`` is set, or ``'_default'``
        otherwise.
    """
    style_column = cfg.get("style_column")

    if style_column is None:
        style_map = {"_default": dict(cfg["styles"][0])}
    else:
        style_map = {s["label"]: dict(s) for s in cfg["styles"]}

    for key, sty in style_map.items():
        dist_s        = sty.get("distribution", cfg["distribution"])
        alpha_floor_s = sty.get("alpha_floor",  cfg["alpha_floor"])
        t_low, t_high, pdf_max = get_visibility_window(dist_s, threshold=alpha_floor_s)
        sty.update({
            "_dist":        dist_s,
            "_alpha_floor": alpha_floor_s,
            "_alpha_max":   sty.get("alpha_max", 1.0),
            "_pdf_max":     pdf_max,
            "_t_low":       t_low,
            "_t_high":      t_high,
        })
        print(f"  Style '{key}': visibility [{t_low:.1f}, {t_high:.1f}] days"
              f"  (pdf_max={pdf_max:.6g})")

    return style_map
