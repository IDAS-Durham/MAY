// Event Visualization Module for World Map
// ==========================================
// Displays simulation events aggregated by geo_unit with time controls

// Event visualization state
const eventState = {
    enabled: false,
    loader: null,
    config: null,
    currentTime: 0,
    timeMin: 0,
    timeMax: 0,
    playing: false,
    playInterval: null,
    visibleEventTypes: {},
    layers: {},            // {event_type: L.layerGroup} — persisted between ticks
    markerCache: {},       // {event_type: {geo_unit_id: L.circleMarker}} — reused in-place
    isUpdating: false,     // guard against overlapping async updates
    mode: 'choropleth',  // 'choropleth' or 'markers'
    cumulativeByType: {},  // {event_type: bool} — per-type cumulative flag
    // Zoom scaling state
    baseZoom: 6,           // Reference zoom level for base radius
    zoomListenerAdded: false
};

// =============================================================================
// INITIALIZATION
// =============================================================================

async function initializeEventVisualization() {
    console.log('Initializing event visualization...');

    // Load event configuration
    await loadEventConfig();

    // Check if events are available
    await checkEventsAvailable();

    if (!eventState.enabled) {
        console.log('Events not available - visualization disabled');
        return;
    }

    // Setup UI controls
    setupEventControls();

    // Setup zoom listener for marker scaling
    setupZoomListener();

    console.log('Event visualization initialized');
}

// Setup zoom listener to scale markers with zoom level
function setupZoomListener() {
    if (eventState.zoomListenerAdded || !state.map) return;

    const zoomConfig = eventState.config?.display?.zoom_scaling || {};

    // Check if zoom scaling is enabled (default: true)
    if (zoomConfig.enabled === false) {
        console.log('Zoom scaling disabled in config');
        return;
    }

    // Get base zoom from config or current map zoom
    eventState.baseZoom = zoomConfig.base_zoom || state.map.getZoom() || 6;

    state.map.on('zoomend', () => {
        updateEventMarkerRadii();
    });

    eventState.zoomListenerAdded = true;
    console.log('Zoom listener added for event markers, base zoom:', eventState.baseZoom);
}

// Calculate zoom scale factor relative to base zoom
function getZoomScaleFactor() {
    if (!state.map) return 1;

    const zoomConfig = eventState.config?.display?.zoom_scaling || {};

    // Check if zoom scaling is enabled
    if (zoomConfig.enabled === false) return 1;

    const currentZoom = state.map.getZoom();
    const baseZoom = zoomConfig.base_zoom || eventState.baseZoom || 6;
    const scaleExponent = zoomConfig.scale_exponent || 0.5;
    const minScale = zoomConfig.min_scale || 0.3;
    const maxScale = zoomConfig.max_scale || 3.0;

    // Scale factor increases as you zoom in, decreases as you zoom out
    const rawScale = Math.pow(2, (currentZoom - baseZoom) * scaleExponent);

    // Clamp to min/max bounds
    return Math.max(minScale, Math.min(maxScale, rawScale));
}

// Update all event marker radii based on current zoom
function updateEventMarkerRadii() {
    const zoomConfig = eventState.config?.display?.zoom_scaling || {};

    // Check if zoom scaling is enabled
    if (zoomConfig.enabled === false) return;

    const scaleFactor = getZoomScaleFactor();

    // Iterate the marker cache directly — covers all cached markers regardless of
    // whether they are currently visible, so zoom stays consistent.
    for (const cache of Object.values(eventState.markerCache)) {
        for (const marker of Object.values(cache)) {
            if (marker.options?.baseRadius !== undefined) {
                marker.setRadius(marker.options.baseRadius * scaleFactor);
            }
        }
    }
}

async function loadEventConfig() {
    try {
        const response = await fetch('/api/events/config');
        eventState.config = await response.json();
        console.log('Event config loaded:', eventState.config);
    } catch (error) {
        console.error('Error loading event config:', error);
        eventState.config = getDefaultEventConfig();
    }
}

async function checkEventsAvailable() {
    try {
        const response = await fetch('/api/events/summary');
        const summary = await response.json();

        if (summary.error) {
            eventState.enabled = false;
            return;
        }

        eventState.enabled = true;
        eventState.timeMin = summary.time_range[0];
        eventState.timeMax = summary.time_range[1];
        eventState.currentTime = eventState.timeMin;

        // Initialize visibility and cumulative from config defaults
        const eventTypes = eventState.config?.event_types || {};
        for (const [type, config] of Object.entries(eventTypes)) {
            eventState.visibleEventTypes[type] = config.default_visible || false;
            eventState.cumulativeByType[type] = false;
        }

        console.log('Events available:', summary);
    } catch (error) {
        console.error('Error checking events:', error);
        eventState.enabled = false;
    }
}

function getDefaultEventConfig() {
    // Uses same nested structure as YAML config files for consistency
    return {
        event_types: {
            infections: {
                label: 'Infections',
                default_visible: true,
                marker: {
                    color: '#e74c3c',
                    border: { color: '#ffffff', width: 2, opacity: 0.8 },
                    fill_opacity: 0.8,
                    size_scale: 1.0
                },
                color_thresholds: [
                    { max_count: 5, color: '#fee5d9', label: 'Very Low' },
                    { max_count: 20, color: '#fcae91', label: 'Low' },
                    { max_count: 50, color: '#fb6a4a', label: 'Medium' },
                    { max_count: 100, color: '#de2d26', label: 'High' },
                    { max_count: null, color: '#a50f15', label: 'Very High' }
                ],
                use_relative_scaling: false,
                gradient: { low: '#fee5d9', medium: '#fcae91', high: '#fb6a4a', very_high: '#cb181d' }
            },
            deaths: {
                label: 'Deaths',
                default_visible: true,
                marker: {
                    color: '#2c3e50',
                    border: { color: '#ffffff', width: 2, opacity: 0.9 },
                    fill_opacity: 0.9,
                    size_scale: 1.2
                },
                color_thresholds: [
                    { max_count: 1, color: '#d9d9d9', label: 'Very Low' },
                    { max_count: 5, color: '#969696', label: 'Low' },
                    { max_count: 15, color: '#525252', label: 'Medium' },
                    { max_count: 30, color: '#252525', label: 'High' },
                    { max_count: null, color: '#000000', label: 'Very High' }
                ],
                use_relative_scaling: false,
                gradient: { low: '#d9d9d9', medium: '#969696', high: '#525252', very_high: '#252525' }
            },
            hospital_admissions: {
                label: 'Hospital Admissions',
                default_visible: false,
                marker: {
                    color: '#3498db',
                    border: { color: '#ffffff', width: 2, opacity: 0.8 },
                    fill_opacity: 0.8,
                    size_scale: 0.9
                },
                color_thresholds: [
                    { max_count: 2, color: '#deebf7', label: 'Very Low' },
                    { max_count: 10, color: '#9ecae1', label: 'Low' },
                    { max_count: 25, color: '#4292c6', label: 'Medium' },
                    { max_count: 50, color: '#2171b5', label: 'High' },
                    { max_count: null, color: '#084594', label: 'Very High' }
                ],
                use_relative_scaling: false,
                gradient: { low: '#deebf7', medium: '#9ecae1', high: '#4292c6', very_high: '#084594' }
            }
        },
        time: {
            aggregation_window: 1.0,
            playback_interval_ms: 500,
            rolling_window_days: 1
        },
        display: {
            default_mode: 'choropleth',
            choropleth: {
                size: { method: 'sqrt', min_radius: 6, max_radius: 35, scale: 2.0 },
                border: { color: '#333333', width: 1, opacity: 0.8 },
                fill_opacity: 0.7
            },
            markers: {
                size: { method: 'sqrt', min_radius: 5, max_radius: 40, scale: 1.5 },
                border: { color: '#ffffff', width: 2, opacity: 1 },
                fill_opacity: 0.6
            },
            zoom_scaling: { enabled: true, base_zoom: 6, scale_exponent: 0.5, min_scale: 0.3, max_scale: 3.0 }
        },
        aggregation: {
            method: 'count',
            cumulative: false
        },
        legend: {
            position: 'bottomright',
            show_threshold_labels: true,
            show_totals: true,
            title: 'Event Counts'
        },
        popup: {
            show_count: true,
            show_rate: true,
            show_geo_unit_name: true
        }
    };
}

// =============================================================================
// UI CONTROLS
// =============================================================================

function setupEventControls() {
    const sidebar = document.getElementById('sidebar');

    // Create events section
    const eventsSection = document.createElement('div');
    eventsSection.className = 'sidebar-section';
    eventsSection.id = 'events-section';
    eventsSection.innerHTML = `
        <h3>Simulation Events</h3>
        <div id="events-toggle-container">
            <label>
                <input type="checkbox" id="enable-events" ${eventState.enabled ? '' : 'disabled'}>
                Show Events
            </label>
        </div>
        <div id="events-controls" class="hidden">
            <div id="event-type-toggles"></div>
            <div id="time-controls">
                <div class="time-display">
                    <span>Day: </span>
                    <span id="current-time-display">${eventState.currentTime.toFixed(1)}</span>
                    <span> / ${eventState.timeMax.toFixed(1)}</span>
                </div>
                <input type="range" id="time-slider"
                       min="${eventState.timeMin}"
                       max="${eventState.timeMax}"
                       step="1"
                       value="${eventState.currentTime}">
                <div class="playback-controls">
                    <button id="play-pause-btn" class="control-btn">
                        <span id="play-icon">&#9658;</span>
                    </button>
                    <button id="step-back-btn" class="control-btn">&lt;</button>
                    <button id="step-forward-btn" class="control-btn">&gt;</button>
                    <button id="reset-btn" class="control-btn">Reset</button>
                </div>
            </div>
            <div id="aggregation-options">
                <select id="display-mode">
                    <option value="choropleth">Choropleth</option>
                    <option value="markers">Markers</option>
                </select>
            </div>
            <div id="event-stats"></div>
        </div>
    `;

    // Insert after statistics section
    const statsSection = sidebar.querySelector('.sidebar-section:last-child');
    if (statsSection) {
        statsSection.after(eventsSection);
    } else {
        sidebar.appendChild(eventsSection);
    }

    // Populate event type toggles
    populateEventTypeToggles();

    // Setup event listeners
    setupEventListeners();
}

function populateEventTypeToggles() {
    const container = document.getElementById('event-type-toggles');
    if (!container) return;

    const eventTypes = eventState.config?.event_types || {};
    let html = '';

    for (const [type, config] of Object.entries(eventTypes)) {
        const checked = eventState.visibleEventTypes[type] ? 'checked' : '';
        const cumulChecked = eventState.cumulativeByType[type] ? 'checked' : '';
        const color = config.color || '#666';

        html += `
            <div class="event-type-row">
                <label class="event-type-toggle">
                    <input type="checkbox" data-event-type="${type}" ${checked}>
                    <span class="event-color-dot" style="background-color: ${color}"></span>
                    ${config.label || type}
                </label>
                <label class="event-cumul-label" title="Show cumulative total from start">
                    <input type="checkbox" class="event-cumul-toggle" data-event-type="${type}" ${cumulChecked}>
                    Cumul.
                </label>
            </div>
        `;
    }

    container.innerHTML = html;
}

function setupEventListeners() {
    // Enable/disable events
    const enableToggle = document.getElementById('enable-events');
    if (enableToggle) {
        enableToggle.addEventListener('change', (e) => {
            const controls = document.getElementById('events-controls');
            if (e.target.checked) {
                controls.classList.remove('hidden');
                updateEventLayers();
            } else {
                controls.classList.add('hidden');
                clearEventLayers();
                // Clear the legend when events are disabled
                const existingLegend = document.querySelector('.event-legend');
                if (existingLegend) existingLegend.remove();
            }
        });
    }

    // Event type toggles
    document.querySelectorAll('#event-type-toggles input').forEach(input => {
        input.addEventListener('change', (e) => {
            const type = e.target.dataset.eventType;
            eventState.visibleEventTypes[type] = e.target.checked;
            updateEventLayers();
        });
    });

    // Time slider
    const slider = document.getElementById('time-slider');
    if (slider) {
        slider.addEventListener('input', (e) => {
            eventState.currentTime = parseFloat(e.target.value);
            document.getElementById('current-time-display').textContent =
                eventState.currentTime.toFixed(1);
            updateEventLayers();
        });
    }

    // Play/pause button
    const playBtn = document.getElementById('play-pause-btn');
    if (playBtn) {
        playBtn.addEventListener('click', togglePlayback);
    }

    // Step buttons
    document.getElementById('step-back-btn')?.addEventListener('click', () => stepTime(-1));
    document.getElementById('step-forward-btn')?.addEventListener('click', () => stepTime(1));
    document.getElementById('reset-btn')?.addEventListener('click', resetTime);

    // Per-type cumulative toggles
    document.querySelectorAll('.event-cumul-toggle').forEach(input => {
        input.addEventListener('change', (e) => {
            const type = e.target.dataset.eventType;
            eventState.cumulativeByType[type] = e.target.checked;
            updateEventLayers();
        });
    });

    // Display mode
    document.getElementById('display-mode')?.addEventListener('change', (e) => {
        eventState.mode = e.target.value;
        updateEventLayers();
    });
}

// =============================================================================
// PLAYBACK CONTROLS
// =============================================================================

function togglePlayback() {
    if (eventState.playing) {
        stopPlayback();
    } else {
        startPlayback();
    }
}

function startPlayback() {
    eventState.playing = true;
    document.getElementById('play-icon').innerHTML = '&#10074;&#10074;'; // Pause icon

    const interval = eventState.config?.time?.playback_interval_ms || 500;

    eventState.playInterval = setInterval(() => {
        if (eventState.currentTime >= eventState.timeMax) {
            stopPlayback();
            return;
        }

        stepTime(1);
    }, interval);
}

function stopPlayback() {
    eventState.playing = false;
    document.getElementById('play-icon').innerHTML = '&#9658;'; // Play icon

    if (eventState.playInterval) {
        clearInterval(eventState.playInterval);
        eventState.playInterval = null;
    }
}

function stepTime(delta) {
    const step = eventState.config?.time?.aggregation_window || 1;
    eventState.currentTime = Math.max(
        eventState.timeMin,
        Math.min(eventState.timeMax, eventState.currentTime + (delta * step))
    );

    document.getElementById('time-slider').value = eventState.currentTime;
    document.getElementById('current-time-display').textContent =
        eventState.currentTime.toFixed(1);

    updateEventLayers();
}

function resetTime() {
    stopPlayback();
    eventState.currentTime = eventState.timeMin;
    document.getElementById('time-slider').value = eventState.currentTime;
    document.getElementById('current-time-display').textContent =
        eventState.currentTime.toFixed(1);
    updateEventLayers();
}

// =============================================================================
// EVENT LAYERS
// =============================================================================

async function updateEventLayers() {
    // Guard: skip this tick if a previous update is still in flight.
    // This prevents queued-up overlapping requests during fast playback.
    if (eventState.isUpdating) return;
    eventState.isUpdating = true;

    try {
        // Get visible event types
        const visibleTypes = Object.entries(eventState.visibleEventTypes)
            .filter(([_, visible]) => visible)
            .map(([type, _]) => type);

        if (visibleTypes.length === 0) {
            _hideAllMarkers();
            updateEventStats({});
            updateEventLegend();
            return;
        }

        // Calculate time window
        const rollingWindow = eventState.config?.time?.rolling_window_days || 1;
        const timeEnd = eventState.currentTime;

        // Group visible types by their per-type cumulative setting
        const cumulTypes  = visibleTypes.filter(t =>  eventState.cumulativeByType[t]);
        const rollingTypes = visibleTypes.filter(t => !eventState.cumulativeByType[t]);

        const allGeojson = {};

        // Fetch cumulative types (time_start = timeMin)
        if (cumulTypes.length > 0) {
            const params = new URLSearchParams({
                time_start: eventState.timeMin,
                time_end:   timeEnd,
                cumulative: 'true'
            });
            cumulTypes.forEach(t => params.append('types', t));
            const resp = await fetch(`/api/events/geojson/batch?${params}`);
            Object.assign(allGeojson, await resp.json());
        }

        // Fetch rolling (non-cumulative) types (time_start = timeEnd - rollingWindow)
        if (rollingTypes.length > 0) {
            const params = new URLSearchParams({
                time_start: timeEnd - rollingWindow,
                time_end:   timeEnd,
                cumulative: 'false'
            });
            rollingTypes.forEach(t => params.append('types', t));
            const resp = await fetch(`/api/events/geojson/batch?${params}`);
            Object.assign(allGeojson, await resp.json());
        }

        // Hide all existing markers so that geo_units absent from this
        // frame's data are invisible (they are not removed — just transparent).
        _hideAllMarkers();

        const allStats = {};
        for (const [eventType, geojson] of Object.entries(allGeojson)) {
            const typeConfig = eventState.config?.event_types?.[eventType] || {};
            if (geojson.features && geojson.features.length > 0) {
                _updateOrCreateLayer(eventType, geojson, typeConfig);
            }
            allStats[eventType] = geojson.properties?.total_count || 0;
        }

        updateEventStats(allStats);
        updateEventLegend();

    } catch (error) {
        console.error('Error updating event layers:', error);
    } finally {
        eventState.isUpdating = false;
    }
}

// Hide all cached markers by setting opacity to 0 (keeps DOM nodes alive for reuse).
function _hideAllMarkers() {
    for (const cache of Object.values(eventState.markerCache)) {
        for (const marker of Object.values(cache)) {
            marker.setStyle({ opacity: 0, fillOpacity: 0 });
        }
    }
}

// Update existing circleMarkers in-place or create new ones for unseen geo_units.
// Only operates in choropleth mode; marker mode falls back to displayEventLayer().
function _updateOrCreateLayer(eventType, geojson, typeConfig) {
    if (eventState.mode !== 'choropleth') {
        // For marker mode, fall back to the original full-recreate approach.
        displayEventLayer(eventType, geojson);
        return;
    }

    const displayConfig    = eventState.config?.display?.choropleth || {};
    const sizeConfig       = displayConfig.size || {};
    const minRadius        = sizeConfig.min_radius || 6;
    const maxRadius        = sizeConfig.max_radius || 35;
    const radiusMethod     = sizeConfig.method || 'sqrt';
    const radiusScale      = sizeConfig.scale || 2.0;
    const borderConfig     = displayConfig.border || {};
    const borderColor      = borderConfig.color || '#333';
    const borderWidth      = borderConfig.width || 1;
    const borderOpacity    = borderConfig.opacity || 0.8;
    const fillOpacity      = displayConfig.fill_opacity || 0.7;
    const colorThresholds  = typeConfig.color_thresholds || [];
    const gradient         = typeConfig.gradient || {};
    const useRelativeScaling = typeConfig.use_relative_scaling || false;
    const popupConfig      = eventState.config?.popup || {};

    const counts   = geojson.features.map(f => f.properties.count);
    const maxCount = Math.max(...counts, 1);
    const zoomScale = getZoomScaleFactor();

    // Ensure a persistent L.layerGroup exists for this event type
    if (!eventState.layers[eventType]) {
        eventState.layers[eventType] = L.layerGroup();
        if (state.map) eventState.layers[eventType].addTo(state.map);
    }
    if (!eventState.markerCache[eventType]) {
        eventState.markerCache[eventType] = {};
    }

    const cache      = eventState.markerCache[eventType];
    const layerGroup = eventState.layers[eventType];

    for (const feature of geojson.features) {
        const geoId    = feature.properties.geo_unit_id;
        const count    = feature.properties.count;
        const [lon, lat] = feature.geometry.coordinates;

        const fillColor  = getColorForCount(count, maxCount, colorThresholds, gradient, useRelativeScaling);
        const baseRadius = calculateEventRadius(count, maxCount, minRadius, maxRadius, radiusMethod, radiusScale);
        const scaledRadius = baseRadius * zoomScale;

        if (cache[geoId]) {
            // Marker already exists — update its style and radius in-place.
            // This avoids DOM node creation/destruction on every tick.
            cache[geoId].setStyle({
                fillColor:   fillColor,
                color:       borderColor,
                weight:      borderWidth,
                opacity:     borderOpacity,
                fillOpacity: fillOpacity
            });
            cache[geoId].setRadius(scaledRadius);
            cache[geoId].options.baseRadius = baseRadius;
        } else {
            // First time we see this geo_unit — create a non-interactive marker.
            // interactive: false lets clicks pass through to the geo_unit marker below.
            const marker = L.circleMarker([lat, lon], {
                radius:      scaledRadius,
                baseRadius:  baseRadius,
                fillColor:   fillColor,
                color:       borderColor,
                weight:      borderWidth,
                opacity:     borderOpacity,
                fillOpacity: fillOpacity,
                interactive: false
            });
            cache[geoId] = marker;
            layerGroup.addLayer(marker);
        }
    }
}

function displayEventLayer(eventType, geojson) {
    const typeConfig = eventState.config?.event_types?.[eventType] || {};
    const displayConfig = eventState.config?.display || {};

    if (eventState.mode === 'choropleth') {
        eventState.layers[eventType] = createChoroplethLayer(geojson, typeConfig);
    } else {
        eventState.layers[eventType] = createMarkerLayer(geojson, typeConfig);
    }

    if (eventState.layers[eventType] && state.map) {
        eventState.layers[eventType].addTo(state.map);
    }
}

function createChoroplethLayer(geojson, typeConfig) {
    const displayConfig = eventState.config?.display?.choropleth || {};
    const useRelativeScaling = typeConfig.use_relative_scaling || false;
    const colorThresholds = typeConfig.color_thresholds || [];
    const gradient = typeConfig.gradient || {
        low: '#fee5d9',
        medium: '#fcae91',
        high: '#fb6a4a',
        very_high: '#cb181d'
    };

    // Calculate max count for relative scaling and radius
    const counts = geojson.features.map(f => f.properties.count);
    const maxCount = Math.max(...counts, 1);

    // Size settings (uses nested structure matching info_panel_config.yaml)
    const sizeConfig = displayConfig.size || {};
    const minRadius = sizeConfig.min_radius || 6;
    const maxRadius = sizeConfig.max_radius || 35;
    const radiusMethod = sizeConfig.method || 'sqrt';
    const radiusScale = sizeConfig.scale || 2.0;

    // Border settings (uses nested structure)
    const borderConfig = displayConfig.border || {};
    const borderColor = borderConfig.color || '#333';
    const borderWidth = borderConfig.width || 1;
    const borderOpacity = borderConfig.opacity || 0.8;

    // Fill opacity
    const fillOpacity = displayConfig.fill_opacity || 0.7;

    // Get current zoom scale factor
    const zoomScale = getZoomScaleFactor();

    return L.geoJSON(geojson, {
        pointToLayer: (feature, latlng) => {
            const count = feature.properties.count;

            // Get color based on count thresholds or relative scaling
            const fillColor = getColorForCount(count, maxCount, colorThresholds, gradient, useRelativeScaling);

            // Calculate base radius (before zoom scaling)
            const baseRadius = calculateEventRadius(count, maxCount, minRadius, maxRadius, radiusMethod, radiusScale);

            // Apply zoom scale factor
            const scaledRadius = baseRadius * zoomScale;

            return L.circleMarker(latlng, {
                radius: scaledRadius,
                baseRadius: baseRadius,  // Store for zoom updates
                fillColor: fillColor,
                color: borderColor,
                weight: borderWidth,
                opacity: 0.8,
                fillOpacity: fillOpacity,
                interactive: false  // clicks pass through to geo_unit marker
            });
        }
    });
}

// Get color for a count value based on thresholds or relative scaling
function getColorForCount(count, maxCount, thresholds, gradient, useRelativeScaling) {
    // Use absolute thresholds if available and not using relative scaling
    if (!useRelativeScaling && thresholds && thresholds.length > 0) {
        for (const threshold of thresholds) {
            // null max_count means "everything above previous threshold"
            if (threshold.max_count === null || count <= threshold.max_count) {
                return threshold.color;
            }
        }
        // Fallback to last threshold color
        return thresholds[thresholds.length - 1].color;
    }

    // Relative scaling based on current max value
    const intensity = maxCount > 0 ? count / maxCount : 0;

    if (intensity < 0.25) {
        return gradient.low;
    } else if (intensity < 0.5) {
        return gradient.medium;
    } else if (intensity < 0.75) {
        return gradient.high;
    } else {
        return gradient.very_high;
    }
}

// Calculate radius based on configured method
function calculateEventRadius(count, maxCount, minRadius, maxRadius, method, scale) {
    let normalizedValue;

    switch (method) {
        case 'sqrt':
            normalizedValue = Math.sqrt(count) / Math.sqrt(maxCount || 1);
            break;
        case 'log':
            normalizedValue = Math.log10(count + 1) / Math.log10(maxCount + 1 || 1);
            break;
        case 'linear':
            normalizedValue = count / (maxCount || 1);
            break;
        default:
            normalizedValue = Math.sqrt(count) / Math.sqrt(maxCount || 1);
    }

    return Math.max(minRadius, Math.min(maxRadius, minRadius + normalizedValue * (maxRadius - minRadius) * scale));
}

function createMarkerLayer(geojson, typeConfig) {
    const markerTypeConfig = typeConfig.marker || {};
    const displayConfig = eventState.config?.display?.markers || {};

    // Get color from marker config (uses nested structure matching info_panel_config.yaml)
    const baseColor = markerTypeConfig.color || '#e74c3c';

    // Border settings - check nested structure first, fallback to flat
    const markerBorder = markerTypeConfig.border || {};
    const displayBorder = displayConfig.border || {};
    const borderColor = markerBorder.color || displayBorder.color || '#fff';
    const borderWidth = markerBorder.width || displayBorder.width || 2;
    const borderOpacity = markerBorder.opacity || displayBorder.opacity || 1;

    // Fill opacity
    const fillOpacity = markerTypeConfig.fill_opacity || displayConfig.fill_opacity || 0.6;

    // Size scale multiplier for this event type
    const sizeScale = markerTypeConfig.size_scale || 1.0;

    // Size settings (uses nested structure)
    const sizeConfig = displayConfig.size || {};
    const minRadius = sizeConfig.min_radius || 5;
    const maxRadius = sizeConfig.max_radius || 40;
    const radiusMethod = sizeConfig.method || 'sqrt';
    const radiusScale = sizeConfig.scale || 1.5;

    // Calculate max count for scaling
    const counts = geojson.features.map(f => f.properties.count);
    const maxCount = Math.max(...counts, 1);

    // Get current zoom scale factor
    const zoomScale = getZoomScaleFactor();

    return L.geoJSON(geojson, {
        pointToLayer: (feature, latlng) => {
            const count = feature.properties.count;

            // Calculate base radius with size scale applied (before zoom scaling)
            const baseRadius = calculateEventRadius(count, maxCount, minRadius, maxRadius, radiusMethod, radiusScale) * sizeScale;

            // Apply zoom scale factor
            const scaledRadius = baseRadius * zoomScale;

            return L.circleMarker(latlng, {
                radius: scaledRadius,
                baseRadius: baseRadius,  // Store for zoom updates
                fillColor: baseColor,
                color: borderColor,
                weight: borderWidth,
                opacity: borderOpacity,
                fillOpacity: fillOpacity,
                interactive: false  // clicks pass through to geo_unit marker
            });
        }
    });
}

function clearEventLayers() {
    for (const [type, layer] of Object.entries(eventState.layers)) {
        if (layer && state.map) {
            state.map.removeLayer(layer);
        }
    }
    eventState.layers = {};
    // Discard cached markers so they are recreated fresh on next enable
    eventState.markerCache = {};
}

function updateEventStats(stats) {
    const container = document.getElementById('event-stats');
    if (!container) return;

    const eventTypes = eventState.config?.event_types || {};
    let html = '<div class="event-stats-grid">';

    for (const [type, config] of Object.entries(eventTypes)) {
        if (eventState.visibleEventTypes[type]) {
            const count = stats[type] || 0;
            html += `
                <div class="event-stat-item">
                    <span class="event-color-dot" style="background-color: ${config.color}"></span>
                    <span class="event-stat-label">${config.label}:</span>
                    <span class="event-stat-value">${count.toLocaleString()}</span>
                </div>
            `;
        }
    }

    html += '</div>';
    container.innerHTML = html;
}

// =============================================================================
// LEGEND
// =============================================================================

function updateEventLegend() {
    // Remove existing legend
    const existingLegend = document.querySelector('.event-legend');
    if (existingLegend) {
        existingLegend.remove();
    }

    // Create new legend if events are visible
    const visibleTypes = Object.entries(eventState.visibleEventTypes)
        .filter(([_, visible]) => visible);

    if (visibleTypes.length === 0) return;

    const legendConfig = eventState.config?.legend || {};
    const position = legendConfig.position || 'bottomright';
    const showThresholdLabels = legendConfig.show_threshold_labels !== false;
    const title = legendConfig.title || 'Event Counts';

    const legend = L.control({ position: position });

    legend.onAdd = function(map) {
        const div = L.DomUtil.create('div', 'info legend event-legend');
        const eventTypes = eventState.config?.event_types || {};

        let html = `<h4>${title}</h4>`;

        for (const [type, _] of visibleTypes) {
            const config = eventTypes[type] || {};
            const useRelativeScaling = config.use_relative_scaling || false;
            const thresholds = config.color_thresholds || [];
            const gradient = config.gradient || {};

            html += `<div class="legend-item"><strong>${config.label || type}</strong>`;

            // Use threshold-based legend if available and not using relative scaling
            if (!useRelativeScaling && thresholds.length > 0 && showThresholdLabels) {
                html += '<div class="legend-thresholds">';
                for (const threshold of thresholds) {
                    const label = threshold.label || (threshold.max_count === null ? '>' : `≤${threshold.max_count}`);
                    html += `
                        <div class="legend-threshold-item">
                            <span class="legend-color-box" style="background: ${threshold.color}"></span>
                            <span class="legend-threshold-label">${label}</span>
                        </div>
                    `;
                }
                html += '</div>';
            } else {
                // Gradient-based legend for relative scaling
                html += `
                    <div class="legend-gradient">
                        <span style="background: ${gradient.low || '#fee5d9'}"></span>
                        <span style="background: ${gradient.medium || '#fcae91'}"></span>
                        <span style="background: ${gradient.high || '#fb6a4a'}"></span>
                        <span style="background: ${gradient.very_high || '#cb181d'}"></span>
                    </div>
                    <div class="legend-labels">
                        <span>Low</span>
                        <span>High</span>
                    </div>
                `;
            }

            html += '</div>';
        }

        div.innerHTML = html;
        return div;
    };

    legend.addTo(state.map);
}

// =============================================================================
// EVENT STATS FOR A SPECIFIC GEO UNIT
// =============================================================================

/**
 * Returns an HTML card showing rolling and cumulative event counts for a given
 * geo_unit_id, or '' if events are not active / no visible types.
 * Called by app.js when the user clicks a geo unit marker.
 */
async function getEventStatsHtmlForUnit(geoUnitId) {
    // Guard: only show when events are enabled and the checkbox is checked
    if (!eventState.enabled) return '';
    const enableToggle = document.getElementById('enable-events');
    if (!enableToggle?.checked) return '';

    const visibleTypes = Object.entries(eventState.visibleEventTypes)
        .filter(([_, visible]) => visible)
        .map(([type]) => type);
    if (visibleTypes.length === 0) return '';

    const timeEnd = eventState.currentTime;
    const rollingWindow = eventState.config?.time?.rolling_window_days || 1;
    const windowLabel = rollingWindow === 1 ? 'day' : `${rollingWindow} days`;

    try {
        // Two concurrent batch requests: rolling window and cumulative total
        const rollingParams = new URLSearchParams({
            time_start: timeEnd - rollingWindow,
            time_end:   timeEnd,
            cumulative: 'false'
        });
        visibleTypes.forEach(t => rollingParams.append('types', t));

        const cumulParams = new URLSearchParams({
            time_start: eventState.timeMin,
            time_end:   timeEnd,
            cumulative: 'true'
        });
        visibleTypes.forEach(t => cumulParams.append('types', t));

        const [rollingResp, cumulResp] = await Promise.all([
            fetch(`/api/events/geojson/batch?${rollingParams}`),
            fetch(`/api/events/geojson/batch?${cumulParams}`)
        ]);

        const rollingData = await rollingResp.json();
        const cumulData   = await cumulResp.json();
        const geoIdInt    = parseInt(geoUnitId);

        let rows = '';
        for (const type of visibleTypes) {
            const typeConfig   = eventState.config?.event_types?.[type] || {};
            const label        = typeConfig.label || type;
            const color        = typeConfig.color || typeConfig.marker?.color || '#666';

            const rollingCount = rollingData[type]?.features
                ?.find(f => f.properties.geo_unit_id === geoIdInt)
                ?.properties?.count ?? 0;

            const cumulCount = cumulData[type]?.features
                ?.find(f => f.properties.geo_unit_id === geoIdInt)
                ?.properties?.count ?? 0;

            rows += `
                <div class="evt-stat-row">
                    <span class="event-color-dot" style="background-color:${color}"></span>
                    <span class="evt-stat-label">${label}</span>
                    <span class="evt-stat-val" title="Events in current ${windowLabel} window">${rollingCount.toLocaleString()}<span class="evt-stat-unit">/${windowLabel}</span></span>
                    <span class="evt-stat-val evt-stat-cumul" title="Cumulative total from simulation start">${cumulCount.toLocaleString()}<span class="evt-stat-unit"> total</span></span>
                </div>`;
        }

        return `
            <div class="evt-stats-panel">
                <div class="evt-stats-header">
                    <span>Events</span>
                    <span class="evt-stats-day">Day ${timeEnd.toFixed(1)}</span>
                </div>
                <div class="evt-stats-col-labels">
                    <span></span><span></span>
                    <span title="Current ${windowLabel} window">/${windowLabel}</span>
                    <span title="From simulation start">total</span>
                </div>
                ${rows}
            </div>`;

    } catch (err) {
        console.error('Error fetching event stats for unit:', err);
        return '';
    }
}

// =============================================================================
// EXPORTS / INTEGRATION
// =============================================================================

// Call initialization after main app loads
document.addEventListener('DOMContentLoaded', () => {
    // Wait for main app to initialize first
    setTimeout(() => {
        initializeEventVisualization();
    }, 1000);
});
