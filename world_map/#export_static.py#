#!/usr/bin/env python3
"""export_static.py — Export the World Map as a self-contained HTML file.

The output file requires no Python, no server, and (by default) no internet
connection. Open it in any modern browser by double-clicking.

How it works:
  1. Loads the world from a .h5 or .joblib file.
  2. Uses the Flask test client to call every /api/* endpoint and collect the
     JSON responses (reuses all existing app.py logic without reimplementing it).
  3. Reads and inlines the CSS and JS static files.
  4. Downloads Leaflet.js/CSS from unpkg.com and embeds them inline (offline
     mode, the default).  Use --cdn to skip this step.
  5. Writes a single .html file containing:
       - Embedded world data as a JS object (STATIC_WORLD_DATA)
       - A fetch() interceptor that serves /api/* calls from that object
       - All CSS and JS inlined

Usage:
    # Basic export (offline — no internet needed to view)
    python world_map/export_static.py --world-file world.h5 --output map.html

    # Custom medieval background image (local file is base64-embedded)
    python world_map/export_static.py --world-file world.h5 --output map.html \\
        --map-background image --map-image medieval.jpg --map-bounds "55,2,50,-5"

    # CDN mode — Leaflet loaded from unpkg.com at view time (viewer needs internet)
    python world_map/export_static.py --world-file world.h5 --output map.html --cdn

    # Allow a larger file (default max embedded data: 80 MB)
    python world_map/export_static.py --world-file world.h5 --output map.html --max-size-mb 200
"""

import sys
import json
import base64
import argparse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup so we can import from both world_map/ and the project root (may/)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

LEAFLET_VERSION = '1.9.4'
LEAFLET_JS_URL = f'https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js'
LEAFLET_CSS_URL = f'https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css'

DEFAULT_MAX_SIZE_MB = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download(url: str) -> str:
    """Download a URL and return its text content."""
    print(f"    Downloading {url} ...", end='', flush=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'world-map-exporter/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode('utf-8')
    print(f" {len(content) // 1024} KB")
    return content


def _json_size(obj) -> int:
    """Return the serialised byte size of a JSON-serialisable object."""
    return len(json.dumps(obj, ensure_ascii=False).encode('utf-8'))


def _safe_json(data) -> str:
    """Serialise data to JSON that is safe to embed inside a <script> tag.

    The only dangerous sequence is '</script>' — escape the slash so the
    browser's HTML parser does not prematurely close the script block.
    """
    return json.dumps(data, ensure_ascii=False).replace('</', '<\\/')


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_data(flask_app, world, geography_units_all, venue_ids_all,
                  max_size_bytes: int) -> dict:
    """Use the Flask test client to pre-generate all API responses.

    Returns a dict keyed by logical name whose values are the parsed JSON
    responses.  Heavy detail data (per-unit, per-venue) is dropped once the
    running size estimate exceeds *max_size_bytes*.
    """
    client = flask_app.test_client()

    def get_json(path: str):
        resp = client.get(path)
        return resp.get_json()

    data: dict = {}
    total_bytes: int = 0

    # ---- Core configuration (always collected) --------------------------------
    print("  Fetching core configuration ...", flush=True)
    core_endpoints = [
        ('map_config',       '/api/map/config'),
        ('panel_config',     '/api/panel/config'),
        ('world_statistics', '/api/world/statistics'),
        ('geography_levels', '/api/geography/levels'),
        ('venue_types',      '/api/venues/types'),
        ('events_config',    '/api/events/config'),
    ]
    for key, path in core_endpoints:
        val = get_json(path)
        data[key] = val
        total_bytes += _json_size(val)
    data['events_available'] = False  # events require a live server

    # ---- Geography GeoJSON per level -----------------------------------------
    print("  Fetching geography GeoJSON ...")
    geography_by_level: dict = {}
    for level in (data['geography_levels'].get('levels') or []):
        print(f"    Level {level} ...", end='', flush=True)
        geojson = get_json(f'/api/geography/{level}')
        geography_by_level[level] = geojson
        sz = _json_size(geojson)
        total_bytes += sz
        n_feat = len(geojson.get('features', []))
        print(f" {n_feat} features, {sz // 1024} KB")
    data['geography_by_level'] = geography_by_level

    # ---- Venue GeoJSON per type ----------------------------------------------
    print("  Fetching venue GeoJSON ...")
    venues_by_type: dict = {}
    for venue_type in (data['venue_types'].get('types') or {}).keys():
        print(f"    Type {venue_type} ...", end='', flush=True)
        geojson = get_json(f'/api/venues/{venue_type}')
        venues_by_type[venue_type] = geojson
        sz = _json_size(geojson)
        total_bytes += sz
        n_feat = len(geojson.get('features', []))
        print(f" {n_feat} features, {sz // 1024} KB")
    data['venues_by_type'] = venues_by_type

    print(f"\n  Core data collected: {total_bytes / (1024 * 1024):.1f} MB")

    # ---- Per-unit details (click popups) ------------------------------------
    geography_units: dict = {}
    geography_units_people: dict = {}

    if total_bytes < max_size_bytes and geography_units_all:
        n = len(geography_units_all)
        print(f"  Fetching details for {n} geo units ...")
        for i, unit_name in enumerate(geography_units_all):
            detail = get_json(f'/api/geography/unit/{unit_name}')
            if detail and 'error' not in detail:
                geography_units[unit_name] = detail
                total_bytes += _json_size(detail)

            people = get_json(
                f'/api/geography/unit/{unit_name}/people?page=1&per_page=50'
            )
            if people and 'error' not in people:
                geography_units_people[unit_name] = people
                total_bytes += _json_size(people)

            if (i + 1) % 100 == 0 or (i + 1) == n:
                pct = int(100 * (i + 1) / n)
                print(
                    f"    {i + 1}/{n} ({pct}%)"
                    f" — {total_bytes / (1024 * 1024):.1f} MB so far"
                )

            if total_bytes > max_size_bytes:
                remaining = n - (i + 1)
                print(
                    f"  Size limit reached after {i + 1} units. "
                    f"{remaining} units will lack detail popups."
                )
                break

        print(
            f"  Unit details: {len(geography_units)} / {n} units embedded"
        )
    else:
        reason = (
            f"size limit already reached ({total_bytes / (1024 * 1024):.1f} MB)"
            if total_bytes >= max_size_bytes
            else "world has no geography"
        )
        print(f"  Skipping unit details ({reason}).")

    data['geography_units'] = geography_units
    data['geography_units_people'] = geography_units_people

    # ---- Per-venue details (click popups) ------------------------------------
    venue_details: dict = {}

    if total_bytes < max_size_bytes and venue_ids_all:
        n = len(venue_ids_all)
        print(f"  Fetching details for {n} venues ...")
        for i, venue_id in enumerate(venue_ids_all):
            detail = get_json(f'/api/venues/venue/{venue_id}')
            if detail and 'error' not in detail:
                venue_details[str(venue_id)] = detail
                total_bytes += _json_size(detail)

            if (i + 1) % 500 == 0 or (i + 1) == n:
                pct = int(100 * (i + 1) / n)
                print(
                    f"    {i + 1}/{n} ({pct}%)"
                    f" — {total_bytes / (1024 * 1024):.1f} MB so far"
                )

            if total_bytes > max_size_bytes:
                remaining = n - (i + 1)
                print(
                    f"  Size limit reached after {i + 1} venues. "
                    f"{remaining} venues will lack detail popups."
                )
                break

        print(
            f"  Venue details: {len(venue_details)} / {n} venues embedded"
        )
    else:
        reason = (
            f"size limit already reached ({total_bytes / (1024 * 1024):.1f} MB)"
            if total_bytes >= max_size_bytes
            else "world has no venues"
        )
        print(f"  Skipping venue details ({reason}).")

    data['venue_details'] = venue_details

    print(f"\n  Total embedded data: {total_bytes / (1024 * 1024):.1f} MB")
    return data


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

# JavaScript fetch interceptor — inlined as a string so the f-string below
# doesn't need to escape any braces inside the JS.
_FETCH_INTERCEPTOR = r"""(function () {
    'use strict';

    var _orig = window.fetch;

    function okResponse(data) {
        return Promise.resolve({
            ok: true,
            status: 200,
            headers: { get: function () { return 'application/json'; } },
            json: function () { return Promise.resolve(data); },
            text: function () { return Promise.resolve(JSON.stringify(data)); }
        });
    }

    function notFound(msg) {
        var payload = { error: msg || 'Not available in static export' };
        return Promise.resolve({
            ok: false,
            status: 404,
            headers: { get: function () { return 'application/json'; } },
            json: function () { return Promise.resolve(payload); },
            text: function () { return Promise.resolve(JSON.stringify(payload)); }
        });
    }

    function dec(s) {
        try { return decodeURIComponent(s); } catch (e) { return s; }
    }

    window.fetch = function (resource, opts) {
        var url = (typeof resource === 'string') ? resource : resource.url;
        var d = window.STATIC_WORLD_DATA;
        var m;

        // Strip query string for path matching
        var qi = url.indexOf('?');
        var pu = (qi === -1) ? url : url.slice(0, qi);

        // ---- Exact static routes ----------------------------------------
        if (pu === '/api/map/config')           return okResponse(d.map_config);
        if (pu === '/api/panel/config')         return okResponse(d.panel_config);
        if (pu === '/api/world/statistics')     return okResponse(d.world_statistics);
        if (pu === '/api/geography/levels')     return okResponse(d.geography_levels);
        if (pu === '/api/venues/types')         return okResponse(d.venue_types);
        if (pu === '/api/events/config')        return okResponse(d.events_config);
        if (pu === '/api/events/summary')       return notFound('Events not available in static export.');
        if (pu === '/api/events/geojson/batch') return notFound('Events not available in static export.');

        // ---- /api/geography/<level>  (not /api/geography/levels) -----------
        m = pu.match(/^\/api\/geography\/([^\/]+)$/);
        if (m && m[1] !== 'levels') {
            var level = dec(m[1]);
            var gbl = d.geography_by_level[level];
            return gbl ? okResponse(gbl) : notFound('Level "' + level + '" not found.');
        }

        // ---- /api/geography/unit/<name>/people  (must check before unit detail)
        m = pu.match(/^\/api\/geography\/unit\/(.+)\/people$/);
        if (m) {
            var uname = dec(m[1]);
            var ppl = d.geography_units_people[uname];
            return ppl
                ? okResponse(ppl)
                : notFound('People list for "' + uname + '" not available in static export.');
        }

        // ---- /api/geography/unit/<name> ------------------------------------
        m = pu.match(/^\/api\/geography\/unit\/(.+)$/);
        if (m) {
            var uname2 = dec(m[1]);
            var ud = d.geography_units[uname2];
            return ud ? okResponse(ud) : notFound('Unit "' + uname2 + '" not found.');
        }

        // ---- /api/venues/venue/<id>  (must check before venue type) --------
        m = pu.match(/^\/api\/venues\/venue\/(\d+)$/);
        if (m) {
            var vid = m[1];
            var vd = d.venue_details[vid];
            return vd ? okResponse(vd) : notFound('Venue detail not available in static export.');
        }

        // ---- /api/venues/<type>  (not /api/venues/types) -------------------
        m = pu.match(/^\/api\/venues\/([^\/]+)$/);
        if (m && m[1] !== 'types') {
            var vtype = dec(m[1]);
            var vbt = d.venues_by_type[vtype];
            return vbt ? okResponse(vbt) : notFound('Venue type "' + vtype + '" not found.');
        }

        // ---- Individual person detail (too large to embed) -----------------
        if (pu.match(/^\/api\/population\/person\/\d+$/)) {
            return notFound('Individual person details are not available in static export.');
        }

        // ---- Event endpoints (require live server) -------------------------
        if (pu.startsWith('/api/events/')) {
            return notFound('Event data requires a live server. Not available in static export.');
        }

        // ---- Fall through to real fetch (e.g. CDN resources) ---------------
        return _orig(resource, opts);
    };
}());
"""


def _build_html(
    data: dict,
    css_style: str,
    css_events: str,
    js_app: str,
    js_events: str,
    leaflet_js: str | None,
    leaflet_css: str | None,
    title: str = "World Map Visualization",
) -> str:
    """Assemble the final self-contained HTML string."""

    data_json = _safe_json(data)

    if leaflet_css and leaflet_js:
        # Offline mode — embed Leaflet bytes directly
        leaflet_css_block = f'<style>\n{leaflet_css}\n</style>'
        leaflet_js_block = f'<script>\n{leaflet_js}\n</script>'
    else:
        # CDN mode
        cdn_base = f'https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet'
        leaflet_css_block = f'<link rel="stylesheet" href="{cdn_base}.css" />'
        leaflet_js_block = f'<script src="{cdn_base}.js"></script>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {leaflet_css_block}
    <style>
{css_style}
    </style>
    <style>
{css_events}
    </style>
</head>
<body>
    <div id="app">
        <!-- Header -->
        <header>
            <h1>&#x1F5FA;&#xFE0F; World Map Visualization</h1>
            <div id="stats-summary"></div>
        </header>

        <!-- Sidebar -->
        <div id="sidebar">
            <div class="sidebar-section">
                <h3>Geography Levels</h3>
                <div id="geography-levels"></div>
            </div>
            <div class="sidebar-section">
                <h3>Venue Types</h3>
                <div id="venue-types"></div>
            </div>
            <div class="sidebar-section">
                <h3>Layers</h3>
                <div id="layer-controls">
                    <label>
                        <input type="checkbox" id="show-population" checked>
                        Population Markers
                    </label>
                    <label>
                        <input type="checkbox" id="show-venues">
                        Venue Markers
                    </label>
                </div>
            </div>
            <div class="sidebar-section">
                <h3>Statistics</h3>
                <div id="world-stats"></div>
            </div>
        </div>

        <!-- Map Container -->
        <div id="map"></div>

        <!-- Info Panel -->
        <div id="info-panel" class="hidden">
            <button id="close-panel" class="close-btn">&times;</button>
            <div id="info-content"></div>
        </div>
    </div>

    <!-- ============================================================
         Embedded world data
         ============================================================ -->
    <script>
window.STATIC_WORLD_DATA = {data_json};
    </script>

    <!-- ============================================================
         Fetch interceptor — must come BEFORE app.js
         Routes /api/* calls to the embedded data above.
         ============================================================ -->
    <script>
{_FETCH_INTERCEPTOR}
    </script>

    {leaflet_js_block}

    <!-- Application JavaScript -->
    <script>
{js_app}
    </script>
    <script>
{js_events}
    </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# World loading (mirrors logic in launch_world_map.py)
# ---------------------------------------------------------------------------

def load_world_from_file(filepath: str):
    """Load a World instance from a .h5 or .joblib file."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"World file not found: {filepath}")

    suffix = path.suffix.lower()
    if suffix == '.joblib':
        import joblib
        return joblib.load(path)
    elif suffix in ('.h5', '.h5py', '.hdf5'):
        from may.serialization.world_loader import load_world_from_hdf5
        return load_world_from_hdf5(str(path))
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. "
            "Expected .h5, .hdf5, or .joblib."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Export the World Map as a self-contained HTML file.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--world-file', required=True,
        help='Path to the world file (.h5, .hdf5, or .joblib)',
    )
    parser.add_argument(
        '--output', required=True,
        help='Output HTML file path (e.g. map.html)',
    )
    parser.add_argument(
        '--cdn', action='store_true',
        help=(
            'Use Leaflet from unpkg.com CDN instead of embedding it. '
            'Produces a smaller file but requires internet to view.'
        ),
    )
    parser.add_argument(
        '--max-size-mb', type=float, default=DEFAULT_MAX_SIZE_MB,
        metavar='MB',
        help=(
            f'Maximum size of embedded JSON data in MB '
            f'(default: {DEFAULT_MAX_SIZE_MB}). '
            'Detail popups are dropped first when the limit is approached.'
        ),
    )
    parser.add_argument(
        '--map-background', choices=['osm', 'image'], default='osm',
        help="Map background: 'osm' (OpenStreetMap) or 'image' (custom image)",
    )
    parser.add_argument(
        '--map-image',
        help=(
            "Path to a local image file or a URL. "
            "Local files are base64-embedded so the HTML stays self-contained. "
            "Required when --map-background=image."
        ),
    )
    parser.add_argument(
        '--map-bounds',
        metavar='N,E,S,W',
        help=(
            "Geographic bounds for the custom image as "
            "'north,east,south,west' (e.g. '55,2,50,-5'). "
            "Required when --map-background=image."
        ),
    )
    parser.add_argument(
        '--map-attribution',
        help='Attribution text shown on the map for a custom image.',
    )
    parser.add_argument(
        '--title', default='World Map Visualization',
        help='HTML page title (default: "World Map Visualization")',
    )

    args = parser.parse_args()

    print('=' * 60)
    print('  World Map Static Exporter')
    print('=' * 60)

    # ---- [1] Load world ------------------------------------------------------
    print(f'\n[1/5] Loading world from {args.world_file} ...')
    world = load_world_from_file(args.world_file)
    print(f'  World loaded: {world}')

    # ---- [2] Build map config ------------------------------------------------
    map_config: dict = {
        'background_type': 'osm',
        'image_url': None,
        'bounds': None,
        'attribution': None,
    }

    if args.map_background == 'image':
        if not args.map_image:
            print('ERROR: --map-image is required when --map-background=image')
            sys.exit(1)
        if not args.map_bounds:
            print('ERROR: --map-bounds is required when --map-background=image')
            sys.exit(1)

        # Parse bounds
        try:
            vals = [float(x.strip()) for x in args.map_bounds.split(',')]
            if len(vals) != 4:
                raise ValueError('Expected 4 values')
            north, east, south, west = vals
            bounds = [[south, west], [north, east]]
        except Exception as exc:
            print(f"ERROR: Invalid --map-bounds '{args.map_bounds}': {exc}")
            print("  Expected format: 'north,east,south,west'  e.g. '55,2,50,-5'")
            sys.exit(1)

        image_src = args.map_image
        if not image_src.startswith(('http://', 'https://')):
            img_path = Path(image_src)
            if not img_path.exists():
                print(f'ERROR: Image file not found: {image_src}')
                sys.exit(1)
            # Embed as a base64 data URI so the HTML is fully self-contained
            suffix = img_path.suffix.lower().lstrip('.')
            mime = 'image/jpeg' if suffix in ('jpg', 'jpeg') else f'image/{suffix}'
            img_bytes = img_path.read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode('ascii')
            image_src = f'data:{mime};base64,{img_b64}'
            print(
                f'  Image embedded as base64 '
                f'({len(img_bytes) / 1024:.0f} KB → '
                f'{len(img_b64) / 1024:.0f} KB base64)'
            )

        map_config = {
            'background_type': 'image',
            'image_url': image_src,
            'bounds': bounds,
            'attribution': args.map_attribution or 'Custom Map Image',
        }

    # ---- [2] Collect API data ------------------------------------------------
    print(f'\n[2/5] Collecting world data (max {args.max_size_mb:.0f} MB) ...')

    from app import initialize_app  # noqa: E402 — must be after sys.path setup

    flask_app = initialize_app(world, map_config=map_config)
    flask_app.config['TESTING'] = True

    # Build the full lists of unit names and venue IDs needed for detail pages
    geography_units_all: list[str] = []
    if world.geography:
        for level in world.geography.levels:
            units = world.geography.get_units_by_level(level)
            geography_units_all.extend(units.keys())

    # Collect venue IDs (deduplicated)
    venue_ids_all: list[int] = []
    if world.venues:
        seen: set[int] = set()
        for vtype in world.venues.get_venue_types():
            for v in world.venues.get_venues_by_type(vtype):
                if v.id not in seen:
                    venue_ids_all.append(v.id)
                    seen.add(v.id)

    print(
        f'  Geography units: {len(geography_units_all)} | '
        f'Venues: {len(venue_ids_all)}'
    )

    max_size_bytes = int(args.max_size_mb * 1024 * 1024)
    data = _collect_data(
        flask_app, world,
        geography_units_all, venue_ids_all,
        max_size_bytes,
    )

    # ---- [3] Read static files -----------------------------------------------
    print('\n[3/5] Reading static files ...')
    static_dir = SCRIPT_DIR / 'static'
    css_style  = (static_dir / 'css' / 'style.css').read_text(encoding='utf-8')
    css_events = (static_dir / 'css' / 'events.css').read_text(encoding='utf-8')
    js_app     = (static_dir / 'js' / 'app.js').read_text(encoding='utf-8')
    js_events  = (static_dir / 'js' / 'events.js').read_text(encoding='utf-8')
    print('  style.css, events.css, app.js, events.js — OK')

    # ---- [4] Leaflet ---------------------------------------------------------
    leaflet_js: str | None = None
    leaflet_css: str | None = None

    if not args.cdn:
        print(f'\n[4/5] Downloading Leaflet {LEAFLET_VERSION} for offline embedding ...')
        leaflet_css = _download(LEAFLET_CSS_URL)
        leaflet_js  = _download(LEAFLET_JS_URL)
    else:
        print(f'\n[4/5] CDN mode — Leaflet will load from unpkg.com at view time.')

    # ---- [5] Build HTML ------------------------------------------------------
    print('\n[5/5] Building HTML ...')
    html = _build_html(
        data=data,
        css_style=css_style,
        css_events=css_events,
        js_app=js_app,
        js_events=js_events,
        leaflet_js=leaflet_js,
        leaflet_css=leaflet_css,
        title=args.title,
    )

    output_path = Path(args.output)
    output_path.write_text(html, encoding='utf-8')
    size_mb = output_path.stat().st_size / (1024 * 1024)

    print(f'\n{"=" * 60}')
    print('  Export complete!')
    print(f'  Output : {output_path.resolve()}')
    print(f'  Size   : {size_mb:.1f} MB')
    if not args.cdn:
        print('  Mode   : offline (no internet required to view)')
    else:
        print('  Mode   : CDN (viewer needs internet access for map tiles/Leaflet)')
    print(f'{"=" * 60}')
    print(f'\nTo view: open {output_path} in any modern browser.')


if __name__ == '__main__':
    main()
