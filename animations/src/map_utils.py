"""Map background loading utilities for epidemic animations."""

import io
import os

import numpy as np
import requests
from PIL import Image


def fetch_esri_map(bbox, resolution):
    """Download a shaded-relief tile from ESRI ArcGIS Online.

    No API key is required.  The downloaded image is returned as a PIL Image
    in RGB mode.

    Args:
        bbox: Dict with keys ``west``, ``east``, ``south``, ``north``
            in WGS-84 decimal degrees.
        resolution: ``(width_px, height_px)`` tuple for the requested tile size.

    Returns:
        A PIL Image in RGB mode.

    Raises:
        requests.HTTPError: If the tile server returns an error response.
    """
    w, e, s, n = bbox["west"], bbox["east"], bbox["south"], bbox["north"]
    url = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Shaded_Relief/MapServer/export"
        f"?bbox={w},{s},{e},{n}"
        f"&bboxSR=4326&imageSR=4326"
        f"&size={resolution[0]},{resolution[1]}"
        "&format=png32&transparent=false&f=image"
    )
    print("  Downloading elevation map from ESRI...", end="", flush=True)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    print(" done.")
    return img


def get_map(cfg):
    """Load or download the map background image.

    If ``cfg['map_image']`` is set, loads that file directly.  Otherwise
    downloads a shaded-relief tile from ESRI and caches it locally as
    ``esri_map_cache.png``.

    Args:
        cfg: The CONFIG dict.  Relevant keys: ``map_image``, ``image_corners``,
            ``map_bbox``, ``map_resolution``.

    Returns:
        A ``(img, corners)`` tuple where ``img`` is a PIL Image in RGB mode and
        ``corners`` is a dict with keys ``west``, ``east``, ``south``, ``north``
        describing the geographic extents of the image.
    """
    cache_path = "esri_map_cache.png"

    if cfg["map_image"]:
        img     = Image.open(cfg["map_image"]).convert("RGB")
        corners = cfg["image_corners"] or cfg["map_bbox"]
        print(f"  Using custom map image: {cfg['map_image']}")
        return img, corners

    if os.path.exists(cache_path):
        print(f"  Using cached map: {cache_path}")
        img = Image.open(cache_path).convert("RGB")
    else:
        resolution = cfg.get("map_resolution", (900, 1100))
        img = fetch_esri_map(cfg["map_bbox"], resolution)
        img.save(cache_path)
        print(f"  Map cached to: {cache_path}")

    return img, cfg["map_bbox"]


def set_gif_play_once(filepath):
    """Strip the Netscape loop extension from a GIF so it plays only once.

    Matplotlib's Pillow writer hardcodes infinite looping (``loop=0``).
    Removing the 19-byte Netscape Application Block causes viewers to default
    to playing the GIF once and stopping.

    Args:
        filepath: Path to the GIF file to modify in-place.
    """
    with open(filepath, "rb") as f:
        data = bytearray(f.read())

    marker = b"\x21\xff\x0b" + b"NETSCAPE2.0"
    idx = data.find(marker)
    if idx != -1:
        del data[idx: idx + 19]
        with open(filepath, "wb") as f:
            f.write(data)
