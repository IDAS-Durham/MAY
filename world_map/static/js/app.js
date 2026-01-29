// World Map Visualization - Main JavaScript
// ==========================================
// Modular, configurable map visualization

// Global state
const state = {
    map: null,
    baseLayer: null,
    imageBounds: null,
    layers: {
        geography: null,
        venues: {}
    },
    selectedLevel: null,
    selectedVenueType: null,
    showPopulation: true,
    showVenues: false,
    mapConfig: null,
    panelConfig: null,  // Info panel configuration
    // Zoom scaling state
    zoomListenerAdded: false,
    baseZoom: 6
};

// =============================================================================
// INITIALIZATION
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Initializing World Map Visualization...');

    // Load configurations
    await Promise.all([
        loadMapConfiguration(),
        loadPanelConfiguration()
    ]);

    // Initialize map
    initializeMap();

    // Load data
    loadWorldStatistics();
    loadGeographyLevels();
    loadVenueTypes();
    setupEventListeners();
});

// Load map configuration from backend
async function loadMapConfiguration() {
    try {
        const response = await fetch('/api/map/config');
        state.mapConfig = await response.json();
        console.log('Map configuration loaded:', state.mapConfig);
    } catch (error) {
        console.error('Error loading map configuration:', error);
        state.mapConfig = {
            background_type: 'osm',
            image_url: null,
            bounds: null,
            attribution: null
        };
    }
}

// Load panel configuration from backend
async function loadPanelConfiguration() {
    try {
        const response = await fetch('/api/panel/config');
        state.panelConfig = await response.json();
        console.log('Panel configuration loaded:', state.panelConfig);
    } catch (error) {
        console.error('Error loading panel configuration:', error);
        state.panelConfig = getDefaultPanelConfig();
    }
}

// Default panel configuration fallback
// Uses same nested structure as info_panel_config.yaml for consistency
function getDefaultPanelConfig() {
    return {
        geo_unit_panel: {
            title_field: 'name',
            popup: { enabled: true },
            detail_sections: []
        },
        marker_styles: {
            geo_unit: {
                size: { method: 'sqrt', min_radius: 5, max_radius: 15, scale: 0.5 },
                border: { color: '#808080', width: 1, opacity: 1 },
                fill_opacity: 0.7,
                zoom_scaling: { enabled: true, base_zoom: 6, scale_exponent: 0.5, min_scale: 0.3, max_scale: 3.0 }
            },
            venue: {
                size: { radius: 6 },
                border: { color: '#ffffff', width: 1, opacity: 1 },
                fill_opacity: 0.8,
                zoom_scaling: { enabled: true, base_zoom: 6, scale_exponent: 0.5, min_scale: 0.3, max_scale: 3.0 }
            }
        }
    };
}

// =============================================================================
// MAP INITIALIZATION
// =============================================================================

function initializeMap() {
    const config = state.mapConfig;

    if (config.background_type === 'image' && config.image_url && config.bounds) {
        // IMAGE-BASED MAP WITH GEOGRAPHIC PROJECTION
        const [[south, west], [north, east]] = config.bounds;
        const centerLat = (south + north) / 2;
        const centerLon = (west + east) / 2;

        state.map = L.map('map', {
            crs: L.CRS.EPSG3857,
            minZoom: 1,
            maxZoom: 18,
            attributionControl: true
        }).setView([centerLat, centerLon], 6);

        const bounds = L.latLngBounds(
            L.latLng(south, west),
            L.latLng(north, east)
        );

        state.baseLayer = L.imageOverlay(config.image_url, bounds, {
            attribution: config.attribution || 'Custom Map Image',
            opacity: 0.9,
            interactive: false
        }).addTo(state.map);

        state.imageBounds = bounds;
        state.map.fitBounds(bounds);

        console.log('Map initialized with georeferenced image');
    } else {
        // OPENSTREETMAP TILES (DEFAULT)
        state.map = L.map('map').setView([51.5074, -0.1278], 6);

        state.baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(state.map);

        console.log('Map initialized with OpenStreetMap tiles');
    }

    // Setup zoom listener for marker scaling
    setupGeoUnitZoomListener();
}

// =============================================================================
// ZOOM SCALING FOR GEO UNIT MARKERS
// =============================================================================

// Setup zoom listener to scale geo unit markers with zoom level
function setupGeoUnitZoomListener() {
    if (state.zoomListenerAdded || !state.map) return;

    const zoomConfig = state.panelConfig?.marker_styles?.geo_unit?.zoom_scaling || {};

    // Check if zoom scaling is enabled (default: true)
    if (zoomConfig.enabled === false) {
        console.log('Geo unit zoom scaling disabled in config');
        return;
    }

    // Get base zoom from config or current map zoom
    state.baseZoom = zoomConfig.base_zoom || state.map.getZoom() || 6;

    state.map.on('zoomend', () => {
        updateGeoUnitMarkerRadii();
    });

    state.zoomListenerAdded = true;
    console.log('Zoom listener added for geo unit markers, base zoom:', state.baseZoom);
}

// Calculate zoom scale factor for geo unit markers
function getGeoUnitZoomScaleFactor() {
    if (!state.map) return 1;

    const zoomConfig = state.panelConfig?.marker_styles?.geo_unit?.zoom_scaling || {};

    // Check if zoom scaling is enabled
    if (zoomConfig.enabled === false) return 1;

    const currentZoom = state.map.getZoom();
    const baseZoom = zoomConfig.base_zoom || state.baseZoom || 6;
    const scaleExponent = zoomConfig.scale_exponent || 0.5;
    const minScale = zoomConfig.min_scale || 0.3;
    const maxScale = zoomConfig.max_scale || 3.0;

    // Scale factor increases as you zoom in, decreases as you zoom out
    const rawScale = Math.pow(2, (currentZoom - baseZoom) * scaleExponent);

    // Clamp to min/max bounds
    return Math.max(minScale, Math.min(maxScale, rawScale));
}

// Update all geo unit marker radii based on current zoom
function updateGeoUnitMarkerRadii() {
    const zoomConfig = state.panelConfig?.marker_styles?.geo_unit?.zoom_scaling || {};

    // Check if zoom scaling is enabled
    if (zoomConfig.enabled === false) return;

    if (!state.layers.geography) return;

    const scaleFactor = getGeoUnitZoomScaleFactor();

    state.layers.geography.eachLayer((marker) => {
        if (marker.options && marker.options.baseRadius) {
            const newRadius = marker.options.baseRadius * scaleFactor;
            marker.setRadius(newRadius);
        }
    });
}

// =============================================================================
// EVENT LISTENERS
// =============================================================================

function setupEventListeners() {
    // Close panel button
    document.getElementById('close-panel').addEventListener('click', () => {
        document.getElementById('info-panel').classList.add('hidden');
    });

    // Layer controls
    document.getElementById('show-population').addEventListener('change', (e) => {
        state.showPopulation = e.target.checked;
        if (state.selectedLevel) {
            loadGeographyLevel(state.selectedLevel);
        }
    });

    document.getElementById('show-venues').addEventListener('change', (e) => {
        state.showVenues = e.target.checked;
        if (state.showVenues && state.selectedVenueType) {
            loadVenues(state.selectedVenueType);
        } else {
            Object.values(state.layers.venues).forEach(layer => {
                if (layer) state.map.removeLayer(layer);
            });
        }
    });
}

// =============================================================================
// STATISTICS
// =============================================================================

async function loadWorldStatistics() {
    try {
        const response = await fetch('/api/world/statistics');
        const stats = await response.json();

        const summaryEl = document.getElementById('stats-summary');
        if (stats.population && stats.geography) {
            summaryEl.innerHTML = `
                📍 ${stats.geography.total_units.toLocaleString()} units |
                👥 ${stats.population.total_population.toLocaleString()} people
            `;
        }

        displayWorldStats(stats);
    } catch (error) {
        console.error('Error loading world statistics:', error);
    }
}

function displayWorldStats(stats) {
    const statsEl = document.getElementById('world-stats');
    let html = '';

    if (stats.population) {
        html += `
            <div class="stat-item">
                <span class="stat-label">Total Population</span>
                <span class="stat-value">${stats.population.total_population.toLocaleString()}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Mean Age</span>
                <span class="stat-value">${stats.population.mean_age.toFixed(1)}</span>
            </div>
        `;
    }

    if (stats.geography) {
        html += `
            <div class="stat-item">
                <span class="stat-label">Geographic Units</span>
                <span class="stat-value">${stats.geography.total_units.toLocaleString()}</span>
            </div>
        `;
    }

    if (stats.venues) {
        html += `
            <div class="stat-item">
                <span class="stat-label">Venues</span>
                <span class="stat-value">${stats.venues.total_venues.toLocaleString()}</span>
            </div>
        `;
    }

    if (stats.households) {
        html += `
            <div class="stat-item">
                <span class="stat-label">Households</span>
                <span class="stat-value">${stats.households.total_households.toLocaleString()}</span>
            </div>
        `;
    }

    statsEl.innerHTML = html;
}

// =============================================================================
// GEOGRAPHY LEVELS
// =============================================================================

async function loadGeographyLevels() {
    try {
        const response = await fetch('/api/geography/levels');
        const data = await response.json();

        const container = document.getElementById('geography-levels');
        container.innerHTML = data.levels.map((level, index) => `
            <button class="level-button ${index === 0 ? 'active' : ''}"
                    data-level="${level}"
                    onclick="selectGeographyLevel('${level}')">
                ${level} (${data.units_per_level[level].toLocaleString()} units)
            </button>
        `).join('');

        // Auto-select first (smallest) level
        if (data.levels.length > 0) {
            selectGeographyLevel(data.levels[0]);
        }
    } catch (error) {
        console.error('Error loading geography levels:', error);
    }
}

async function selectGeographyLevel(level) {
    state.selectedLevel = level;

    document.querySelectorAll('.level-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.level === level);
    });

    await loadGeographyLevel(level);
}

// =============================================================================
// GEOGRAPHY LAYER - Circle Markers
// =============================================================================

async function loadGeographyLevel(level) {
    try {
        // Remove existing geography layer
        if (state.layers.geography) {
            state.map.removeLayer(state.layers.geography);
        }

        if (!state.showPopulation) {
            return;
        }

        const response = await fetch(`/api/geography/${level}`);
        const geojson = await response.json();

        console.log(`Received ${geojson.features.length} features for level ${level}`);

        if (geojson.features.length === 0) {
            console.warn('No features returned - check if coordinates exist in HDF5');
            return;
        }

        // Get marker style config
        const styleConfig = state.panelConfig?.marker_styles?.geo_unit || {};

        // Get current zoom scale factor
        const zoomScale = getGeoUnitZoomScaleFactor();

        state.layers.geography = L.geoJSON(geojson, {
            pointToLayer: (feature, latlng) => {
                const props = feature.properties;
                const population = props.population || 0;

                // Calculate base radius (before zoom scaling)
                const baseRadius = calculateMarkerRadius(population, styleConfig.size);

                // Apply zoom scale factor
                const scaledRadius = baseRadius * zoomScale;

                // Get color based on config
                const fillColor = getPopulationColor(population, styleConfig.color);

                const borderConfig = styleConfig.border || {};

                return L.circleMarker(latlng, {
                    radius: scaledRadius,
                    baseRadius: baseRadius,  // Store for zoom updates
                    fillColor: fillColor,
                    color: borderConfig.color || '#fff',
                    weight: borderConfig.width || 1,  // Use 'width' for consistency with YAML
                    opacity: borderConfig.opacity || 1,
                    fillOpacity: styleConfig.fill_opacity || 0.7
                });
            },
            onEachFeature: (feature, layer) => {
                const props = feature.properties;

                // Create popup based on config
                const popupContent = createGeoUnitPopup(props);
                layer.bindPopup(popupContent);

                // Click handler for detail panel
                layer.on('click', () => {
                    showUnitDetails(props.name);
                });
            }
        }).addTo(state.map);

        // Fit map to bounds
        if (geojson.features.length > 0) {
            state.map.fitBounds(state.layers.geography.getBounds());
        }

        console.log(`Loaded ${geojson.features.length} features for level ${level}`);
    } catch (error) {
        console.error('Error loading geography level:', error);
    }
}

// Calculate marker radius based on config
// Uses same keywords as event_visualisation.yaml for consistency
function calculateMarkerRadius(population, sizeConfig) {
    if (!sizeConfig) {
        return Math.max(5, Math.min(15, Math.sqrt(population) / 2));
    }

    const method = sizeConfig.method || 'sqrt';
    const minRadius = sizeConfig.min_radius || 5;
    const maxRadius = sizeConfig.max_radius || 15;
    // Support both 'scale' (new) and 'scale_factor' (legacy) for backwards compatibility
    const scaleFactor = sizeConfig.scale || sizeConfig.scale_factor || 0.5;

    let rawRadius;
    switch (method) {
        case 'sqrt':
            rawRadius = Math.sqrt(population) * scaleFactor;
            break;
        case 'log':
            rawRadius = Math.log10(population + 1) * scaleFactor * 3;
            break;
        case 'linear':
            rawRadius = population * scaleFactor / 100;
            break;
        default:
            rawRadius = Math.sqrt(population) * scaleFactor;
    }

    return Math.max(minRadius, Math.min(maxRadius, rawRadius));
}

// Get color based on population thresholds from config
function getPopulationColor(population, colorConfig) {
    if (!colorConfig || !colorConfig.thresholds) {
        // Default color scheme
        return population > 10000 ? '#800026' :
               population > 5000  ? '#BD0026' :
               population > 2000  ? '#E31A1C' :
               population > 1000  ? '#FC4E2A' :
               population > 500   ? '#FD8D3C' :
               population > 200   ? '#FEB24C' :
               population > 100   ? '#FED976' :
                                    '#FFEDA0';
    }

    const thresholds = colorConfig.thresholds;
    for (let i = thresholds.length - 1; i >= 0; i--) {
        const threshold = thresholds[i];
        if (threshold.value === null || population > threshold.value) {
            return threshold.color;
        }
    }

    return thresholds[0]?.color || '#FFEDA0';
}

// Create popup content for geo unit
function createGeoUnitPopup(props) {
    const popupConfig = state.panelConfig?.geo_unit_panel?.popup;

    if (!popupConfig || !popupConfig.enabled) {
        // Default popup
        return `
            <div class="popup-title">${props.name}</div>
            <div class="popup-info"><strong>Level:</strong> ${props.level}</div>
            <div class="popup-info"><strong>Population:</strong> ${props.population.toLocaleString()}</div>
            <div class="popup-info"><strong>Venues:</strong> ${props.venues_count}</div>
            <button class="popup-button" onclick="showUnitDetails('${props.name}')">
                View Details
            </button>
        `;
    }

    // Build popup from config
    let html = '';
    const fields = popupConfig.fields || [];

    for (const field of fields) {
        const value = getFieldValue(props, field.name);
        const formattedValue = formatValue(value, field.format);

        if (field.name === 'name') {
            html += `<div class="popup-title">${formattedValue}</div>`;
        } else {
            html += `<div class="popup-info"><strong>${field.label}:</strong> ${formattedValue}</div>`;
        }
    }

    html += `
        <button class="popup-button" onclick="showUnitDetails('${props.name}')">
            View Details
        </button>
    `;

    return html;
}

// =============================================================================
// DETAIL PANEL - Configurable
// =============================================================================

async function showUnitDetails(unitName) {
    try {
        const response = await fetch(`/api/geography/unit/${encodeURIComponent(unitName)}`);
        const unit = await response.json();

        const panel = document.getElementById('info-panel');
        const content = document.getElementById('info-content');

        // Build panel from config
        const html = buildDetailPanel(unit, 'geo_unit_panel');

        content.innerHTML = html;
        panel.classList.remove('hidden');
    } catch (error) {
        console.error('Error loading unit details:', error);
    }
}

// Build detail panel based on configuration
function buildDetailPanel(data, panelType) {
    const panelConfig = state.panelConfig?.[panelType];

    if (!panelConfig) {
        // Fallback to default rendering
        return buildDefaultGeoUnitPanel(data);
    }

    let html = '';

    // Title
    const titleField = panelConfig.title_field || 'name';
    const title = getFieldValue(data, titleField);
    html += `<h2>${title}</h2>`;

    // Sections
    const sections = panelConfig.detail_sections || [];

    for (const section of sections) {
        if (!section.enabled) continue;

        html += buildPanelSection(section, data);
    }

    return html;
}

// Build individual panel section
function buildPanelSection(section, data) {
    let html = '';

    // Section title
    if (section.title) {
        html += `<h3>${section.title}</h3>`;
    }

    switch (section.type) {
        case 'grid':
            html += buildGridSection(section, data);
            break;
        case 'distribution':
            html += buildDistributionSection(section, data);
            break;
        case 'breakdown':
            html += buildBreakdownSection(section, data);
            break;
        case 'list':
            html += buildListSection(section, data);
            break;
        case 'properties':
            html += buildPropertiesSection(section, data);
            break;
        default:
            console.warn(`Unknown section type: ${section.type}`);
    }

    return html;
}

// Build grid section (basic info)
function buildGridSection(section, data) {
    const fields = section.fields || [];
    let html = '<div class="info-grid">';

    for (const field of fields) {
        const value = getFieldValue(data, field.source || field.name);
        const formattedValue = formatValue(value, field.format);

        html += `
            <div class="info-item">
                <div class="info-item-label">${field.label}</div>
                <div class="info-item-value">${formattedValue}</div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

// Build distribution section (bar chart)
function buildDistributionSection(section, data) {
    const source = section.source;
    const distribution = getFieldValue(data, source);

    if (!distribution || typeof distribution !== 'object') {
        return '';
    }

    const total = Object.values(distribution).reduce((a, b) => a + b, 0);
    if (total === 0) return '';

    let html = '<div class="bar-chart">';

    for (const [group, count] of Object.entries(distribution)) {
        const percentage = (count / total * 100).toFixed(1);

        html += `
            <div class="bar-item">
                <div class="bar-label">${group}</div>
                <div class="bar-wrapper">
                    <div class="bar-fill" style="width: ${percentage}%"></div>
                </div>
                <div class="bar-value">${count.toLocaleString()}</div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

// Build breakdown section (venue types, etc.)
function buildBreakdownSection(section, data) {
    const source = section.source;
    const breakdown = getFieldValue(data, source);

    if (!breakdown || typeof breakdown !== 'object' || Object.keys(breakdown).length === 0) {
        return '<p><em>No data available</em></p>';
    }

    // Sort entries
    let entries = Object.entries(breakdown);
    if (section.sort_by === 'count') {
        entries.sort((a, b) => section.sort_order === 'desc' ? b[1] - a[1] : a[1] - b[1]);
    } else if (section.sort_by === 'name') {
        entries.sort((a, b) => section.sort_order === 'desc' ? b[0].localeCompare(a[0]) : a[0].localeCompare(b[0]));
    }

    // Limit items
    if (section.max_items) {
        entries = entries.slice(0, section.max_items);
    }

    const maxValue = Math.max(...entries.map(([_, v]) => v));

    let html = '<div class="bar-chart">';

    for (const [type, count] of entries) {
        const width = (count / maxValue * 100).toFixed(1);

        html += `
            <div class="bar-item">
                <div class="bar-label">${type}</div>
                <div class="bar-wrapper">
                    <div class="bar-fill" style="width: ${width}%"></div>
                </div>
                <div class="bar-value">${count.toLocaleString()}</div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

// Build list section (venues, children, etc.)
function buildListSection(section, data) {
    const source = section.source;
    let items = getFieldValue(data, source);

    if (!items || !Array.isArray(items) || items.length === 0) {
        return '<p><em>No items</em></p>';
    }

    // Limit items
    if (section.max_items) {
        items = items.slice(0, section.max_items);
    }

    const fields = section.fields || [];

    let html = '<div class="list-section">';

    for (const item of items) {
        let itemText = fields.map(f => {
            const value = getFieldValue(item, f.name);
            return value !== undefined ? value : '';
        }).filter(v => v).join(' - ');

        html += `<div class="list-item">${itemText}</div>`;
    }

    if (data[source] && data[source].length > items.length) {
        html += `<div class="list-item list-more">... and ${data[source].length - items.length} more</div>`;
    }

    html += '</div>';
    return html;
}

// Build properties section (JSON display)
function buildPropertiesSection(section, data) {
    const props = data.properties;

    if (!props || Object.keys(props).length === 0) {
        return '';
    }

    // Filter out excluded properties
    const exclude = section.exclude || [];
    const filtered = Object.fromEntries(
        Object.entries(props).filter(([k]) => !exclude.includes(k))
    );

    if (Object.keys(filtered).length === 0) {
        return '';
    }

    return `
        <pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; font-size: 0.85rem; overflow-x: auto;">
${JSON.stringify(filtered, null, 2)}
        </pre>
    `;
}

// Default geo unit panel (fallback)
function buildDefaultGeoUnitPanel(unit) {
    let html = `
        <h2>${unit.name}</h2>

        <div class="info-grid">
            <div class="info-item">
                <div class="info-item-label">Level</div>
                <div class="info-item-value">${unit.level}</div>
            </div>
            <div class="info-item">
                <div class="info-item-label">Population</div>
                <div class="info-item-value">${unit.population.toLocaleString()}</div>
            </div>
            <div class="info-item">
                <div class="info-item-label">Venues</div>
                <div class="info-item-value">${unit.venues_count}</div>
            </div>
            <div class="info-item">
                <div class="info-item-label">Children Units</div>
                <div class="info-item-value">${unit.children.length}</div>
            </div>
        </div>
    `;

    // Age distribution
    if (unit.age_distribution) {
        html += `
            <h3>Age Distribution</h3>
            <div class="bar-chart">
                ${Object.entries(unit.age_distribution)
                    .map(([group, count]) => {
                        const percentage = (count / unit.population * 100).toFixed(1);
                        return `
                            <div class="bar-item">
                                <div class="bar-label">${group}</div>
                                <div class="bar-wrapper">
                                    <div class="bar-fill" style="width: ${percentage}%"></div>
                                </div>
                                <div class="bar-value">${count}</div>
                            </div>
                        `;
                    }).join('')}
            </div>
        `;
    }

    // Sex distribution
    if (unit.sex_distribution) {
        html += `
            <h3>Sex Distribution</h3>
            <div class="bar-chart">
                ${Object.entries(unit.sex_distribution)
                    .map(([sex, count]) => {
                        const percentage = (count / unit.population * 100).toFixed(1);
                        return `
                            <div class="bar-item">
                                <div class="bar-label">${sex}</div>
                                <div class="bar-wrapper">
                                    <div class="bar-fill" style="width: ${percentage}%"></div>
                                </div>
                                <div class="bar-value">${count}</div>
                            </div>
                        `;
                    }).join('')}
            </div>
        `;
    }

    // Venue types
    if (unit.venue_types && Object.keys(unit.venue_types).length > 0) {
        html += `
            <h3>Venue Types</h3>
            <div class="bar-chart">
                ${Object.entries(unit.venue_types)
                    .sort((a, b) => b[1] - a[1])
                    .map(([type, count]) => `
                        <div class="bar-item">
                            <div class="bar-label">${type}</div>
                            <div class="bar-wrapper">
                                <div class="bar-fill" style="width: ${count / Math.max(...Object.values(unit.venue_types)) * 100}%"></div>
                            </div>
                            <div class="bar-value">${count}</div>
                        </div>
                    `).join('')}
            </div>
        `;
    }

    // People section with "View People" button
    if (unit.population > 0) {
        html += `
            <h3>People</h3>
            <p>${unit.population.toLocaleString()} people in this area</p>
            <button class="action-button" onclick="showUnitPeople('${unit.name}')">
                View People List
            </button>
        `;
    }

    return html;
}

// =============================================================================
// PEOPLE LIST AND PERSON DETAILS
// =============================================================================

// State for people pagination
const peopleState = {
    currentUnit: null,
    currentPage: 1,
    perPage: 50,
    totalCount: 0,
    totalPages: 0
};

// Show list of people in a geographical unit
async function showUnitPeople(unitName, page = 1) {
    try {
        peopleState.currentUnit = unitName;
        peopleState.currentPage = page;

        const response = await fetch(
            `/api/geography/unit/${encodeURIComponent(unitName)}/people?page=${page}&per_page=${peopleState.perPage}`
        );
        const data = await response.json();

        if (data.error) {
            console.error('Error loading people:', data.error);
            return;
        }

        peopleState.totalCount = data.total_count;
        peopleState.totalPages = data.total_pages;

        const panel = document.getElementById('info-panel');
        const content = document.getElementById('info-content');

        let html = `
            <h2>People in ${unitName}</h2>
            <p class="people-count">${data.total_count.toLocaleString()} people total</p>

            <button class="back-button" onclick="showUnitDetails('${unitName}')">
                &larr; Back to Unit Details
            </button>

            <div class="people-list">
                <table class="people-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Age</th>
                            <th>Sex</th>
                            <th>Primary Activity</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        for (const person of data.people) {
            const primaryActivity = person.primary_activity
                ? `${person.primary_activity.type}: ${person.primary_activity.venue_name}`
                : '-';

            html += `
                <tr class="person-row" onclick="showPersonDetails(${person.id})">
                    <td>${person.id}</td>
                    <td>${person.age}</td>
                    <td>${person.sex}</td>
                    <td>${primaryActivity}</td>
                    <td><span class="view-link">View &rarr;</span></td>
                </tr>
            `;
        }

        html += `
                    </tbody>
                </table>
            </div>
        `;

        // Pagination controls
        if (data.total_pages > 1) {
            html += `
                <div class="pagination">
                    <button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="showUnitPeople('${unitName}', ${page - 1})">
                        &larr; Prev
                    </button>
                    <span class="pagination-info">Page ${page} of ${data.total_pages}</span>
                    <button class="pagination-btn" ${page >= data.total_pages ? 'disabled' : ''} onclick="showUnitPeople('${unitName}', ${page + 1})">
                        Next &rarr;
                    </button>
                </div>
            `;
        }

        content.innerHTML = html;
        panel.classList.remove('hidden');

    } catch (error) {
        console.error('Error loading people list:', error);
    }
}

// Show detailed information about a specific person
async function showPersonDetails(personId) {
    try {
        const response = await fetch(`/api/population/person/${personId}`);
        const person = await response.json();

        if (person.error) {
            console.error('Error loading person:', person.error);
            return;
        }

        const panel = document.getElementById('info-panel');
        const content = document.getElementById('info-content');

        let html = `
            <h2>Person #${person.id}</h2>

            <button class="back-button" onclick="showUnitPeople('${peopleState.currentUnit}', ${peopleState.currentPage})">
                &larr; Back to People List
            </button>

            <div class="info-grid">
                <div class="info-item">
                    <div class="info-item-label">Age</div>
                    <div class="info-item-value">${person.age}</div>
                </div>
                <div class="info-item">
                    <div class="info-item-label">Sex</div>
                    <div class="info-item-value">${person.sex}</div>
                </div>
            </div>
        `;

        // Geographical Unit
        if (person.geographical_unit) {
            html += `
                <h3>Location</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-item-label">Area</div>
                        <div class="info-item-value">${person.geographical_unit.name}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-item-label">Level</div>
                        <div class="info-item-value">${person.geographical_unit.level}</div>
                    </div>
                </div>
            `;
        }

        // Activities list
        if (person.activities && person.activities.length > 0) {
            html += `
                <h3>Activities</h3>
                <div class="activities-list">
                    ${person.activities.map(activity => `
                        <span class="activity-tag">${activity}</span>
                    `).join('')}
                </div>
            `;
        }

        // Activity Map
        if (person.activity_map && Object.keys(person.activity_map).length > 0) {
            html += `<h3>Activity Map</h3>`;

            for (const [activityType, venuesByType] of Object.entries(person.activity_map)) {
                if (Object.keys(venuesByType).length === 0) continue;

                html += `
                    <div class="activity-map-section">
                        <h4>${formatActivityType(activityType)}</h4>
                        <div class="activity-venues">
                `;

                for (const [venueType, subsets] of Object.entries(venuesByType)) {
                    if (!subsets || subsets.length === 0) continue;

                    for (const subset of subsets) {
                        html += `
                            <div class="activity-venue-item">
                                <span class="venue-type-badge">${venueType}</span>
                                <span class="venue-name">${subset.venue_name}</span>
                                ${subset.subset_name !== 'default' ? `<span class="subset-name">(${subset.subset_name})</span>` : ''}
                            </div>
                        `;
                    }
                }

                html += `
                        </div>
                    </div>
                `;
            }
        }

        // Additional Properties
        if (person.properties && Object.keys(person.properties).length > 0) {
            html += `
                <h3>Additional Properties</h3>
                <div class="properties-grid">
            `;

            for (const [key, value] of Object.entries(person.properties)) {
                const displayValue = typeof value === 'object' ? JSON.stringify(value) : value;
                html += `
                    <div class="property-item">
                        <span class="property-key">${key}:</span>
                        <span class="property-value">${displayValue}</span>
                    </div>
                `;
            }

            html += `</div>`;
        }

        content.innerHTML = html;
        panel.classList.remove('hidden');

    } catch (error) {
        console.error('Error loading person details:', error);
    }
}

// Format activity type for display
function formatActivityType(activityType) {
    return activityType
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

// Get nested field value from object (supports 'parent.child' paths)
function getFieldValue(obj, path) {
    if (!path) return undefined;

    const parts = path.split('.');
    let value = obj;

    for (const part of parts) {
        if (value === null || value === undefined) return undefined;
        value = value[part];
    }

    return value;
}

// Format value based on format type
function formatValue(value, format) {
    if (value === undefined || value === null) return '-';

    switch (format) {
        case 'number':
            return typeof value === 'number' ? value.toLocaleString() : value;
        case 'percentage':
            return typeof value === 'number' ? `${value.toFixed(1)}%` : value;
        case 'decimal':
            return typeof value === 'number' ? value.toFixed(2) : value;
        default:
            if (typeof value === 'number') {
                return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
            }
            return value;
    }
}

// =============================================================================
// VENUE TYPES
// =============================================================================

async function loadVenueTypes() {
    try {
        const response = await fetch('/api/venues/types');
        const data = await response.json();

        const container = document.getElementById('venue-types');
        container.innerHTML = Object.entries(data.types)
            .map(([type, count]) => `
                <button class="venue-type-button"
                        data-type="${type}"
                        onclick="selectVenueType('${type}')">
                    ${type} (${count.toLocaleString()})
                </button>
            `).join('');
    } catch (error) {
        console.error('Error loading venue types:', error);
    }
}

function selectVenueType(venueType) {
    state.selectedVenueType = venueType;

    document.querySelectorAll('.venue-type-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === venueType);
    });

    document.getElementById('show-venues').checked = true;
    state.showVenues = true;

    loadVenues(venueType);
}

// =============================================================================
// VENUE LAYER
// =============================================================================

async function loadVenues(venueType) {
    try {
        if (state.layers.venues[venueType]) {
            state.map.removeLayer(state.layers.venues[venueType]);
        }

        if (!state.showVenues) {
            return;
        }

        const response = await fetch(`/api/venues/${venueType}`);
        const geojson = await response.json();

        const styleConfig = state.panelConfig?.marker_styles?.venue || {};

        state.layers.venues[venueType] = L.geoJSON(geojson, {
            pointToLayer: (feature, latlng) => {
                const venueColors = styleConfig.colors || {};
                const fillColor = venueColors[feature.properties.type] || venueColors.default || '#95a5a6';

                return L.circleMarker(latlng, {
                    radius: styleConfig.radius || 6,
                    fillColor: fillColor,
                    color: styleConfig.border?.color || '#fff',
                    weight: styleConfig.border?.weight || 1,
                    opacity: styleConfig.border?.opacity || 1,
                    fillOpacity: styleConfig.fill_opacity || 0.8
                });
            },
            onEachFeature: (feature, layer) => {
                const props = feature.properties;

                const popupContent = `
                    <div class="popup-title">${props.name}</div>
                    <div class="popup-info"><strong>Type:</strong> ${props.type}</div>
                    <div class="popup-info"><strong>Area:</strong> ${props.geographical_unit || 'Unknown'}</div>
                    <div class="popup-info"><strong>Members:</strong> ${props.num_members}</div>
                    <button class="popup-button" onclick="showVenueDetails(${props.id})">
                        View Details
                    </button>
                `;

                layer.bindPopup(popupContent);
            }
        }).addTo(state.map);

        console.log(`Loaded ${geojson.features.length} venues of type ${venueType}`);
    } catch (error) {
        console.error('Error loading venues:', error);
    }
}

// =============================================================================
// VENUE DETAILS
// =============================================================================

async function showVenueDetails(venueId) {
    try {
        const response = await fetch(`/api/venues/venue/${venueId}`);
        const venue = await response.json();

        const panel = document.getElementById('info-panel');
        const content = document.getElementById('info-content');

        let html = `
            <h2>${venue.name}</h2>

            <div class="info-grid">
                <div class="info-item">
                    <div class="info-item-label">Type</div>
                    <div class="info-item-value">${venue.type}</div>
                </div>
                <div class="info-item">
                    <div class="info-item-label">Area</div>
                    <div class="info-item-value">${venue.geographical_unit ? venue.geographical_unit.name : 'Unknown'}</div>
                </div>
            </div>
        `;

        // Subsets
        if (venue.subsets && venue.subsets.length > 0) {
            html += `<h3>Subsets</h3>`;
            venue.subsets.forEach(subset => {
                html += `
                    <div class="info-item">
                        <strong>${subset.name}:</strong>
                        ${subset.num_members || 0} members
                        ${subset.capacity ? `/ ${subset.capacity} capacity` : ''}
                    </div>
                `;
            });
        }

        // Properties
        if (venue.properties && Object.keys(venue.properties).length > 0) {
            html += `
                <h3>Properties</h3>
                <pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; font-size: 0.85rem; overflow-x: auto;">
${JSON.stringify(venue.properties, null, 2)}
                </pre>
            `;
        }

        content.innerHTML = html;
        panel.classList.remove('hidden');
    } catch (error) {
        console.error('Error loading venue details:', error);
    }
}
