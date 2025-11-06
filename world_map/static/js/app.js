// World Map Visualization - Main JavaScript

// Global state
const state = {
    map: null,
    layers: {
        geography: null,
        venues: {}
    },
    selectedLevel: null,
    selectedVenueType: null,
    showPopulation: true,
    showVenues: false
};

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    console.log('Initializing World Map Visualization...');
    initializeMap();
    loadWorldStatistics();
    loadGeographyLevels();
    loadVenueTypes();
    setupEventListeners();
});

// Initialize Leaflet map
function initializeMap() {
    state.map = L.map('map').setView([51.5074, -0.1278], 6); // Default to London

    // Add OpenStreetMap tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(state.map);

    console.log('Map initialized');
}

// Setup event listeners
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
            // Clear venue layers
            Object.values(state.layers.venues).forEach(layer => {
                if (layer) state.map.removeLayer(layer);
            });
        }
    });
}

// Load world statistics
async function loadWorldStatistics() {
    try {
        const response = await fetch('/api/world/statistics');
        const stats = await response.json();

        // Update stats summary in header
        const summaryEl = document.getElementById('stats-summary');
        if (stats.population && stats.geography) {
            summaryEl.innerHTML = `
                📍 ${stats.geography.total_units.toLocaleString()} units |
                👥 ${stats.population.total_population.toLocaleString()} people
            `;
        }

        // Update detailed stats in sidebar
        displayWorldStats(stats);
    } catch (error) {
        console.error('Error loading world statistics:', error);
    }
}

// Display world statistics
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

// Load geography levels
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

        // Auto-select first level
        if (data.levels.length > 0) {
            selectGeographyLevel(data.levels[0]);
        }
    } catch (error) {
        console.error('Error loading geography levels:', error);
    }
}

// Select a geography level
async function selectGeographyLevel(level) {
    state.selectedLevel = level;

    // Update active button
    document.querySelectorAll('.level-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.level === level);
    });

    await loadGeographyLevel(level);
}

// Load geography level data
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

        // Create marker cluster or regular markers
        state.layers.geography = L.geoJSON(geojson, {
            pointToLayer: (feature, latlng) => {
                const props = feature.properties;
                const population = props.population;

                // Size marker based on population
                const radius = Math.max(5, Math.min(15, Math.sqrt(population) / 2));

                return L.circleMarker(latlng, {
                    radius: radius,
                    fillColor: getPopulationColor(population),
                    color: '#fff',
                    weight: 1,
                    opacity: 1,
                    fillOpacity: 0.7
                });
            },
            onEachFeature: (feature, layer) => {
                const props = feature.properties;

                // Create popup
                const popupContent = `
                    <div class="popup-title">${props.name}</div>
                    <div class="popup-info"><strong>Level:</strong> ${props.level}</div>
                    <div class="popup-info"><strong>Population:</strong> ${props.population.toLocaleString()}</div>
                    <div class="popup-info"><strong>Venues:</strong> ${props.venues_count}</div>
                    <button class="popup-button" onclick="showUnitDetails('${props.name}')">
                        View Details
                    </button>
                `;

                layer.bindPopup(popupContent);

                // Click handler
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

// Get color based on population
function getPopulationColor(population) {
    return population > 10000 ? '#800026' :
           population > 5000  ? '#BD0026' :
           population > 2000  ? '#E31A1C' :
           population > 1000  ? '#FC4E2A' :
           population > 500   ? '#FD8D3C' :
           population > 200   ? '#FEB24C' :
           population > 100   ? '#FED976' :
                                '#FFEDA0';
}

// Show unit details
async function showUnitDetails(unitName) {
    try {
        const response = await fetch(`/api/geography/unit/${encodeURIComponent(unitName)}`);
        const unit = await response.json();

        const panel = document.getElementById('info-panel');
        const content = document.getElementById('info-content');

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

        content.innerHTML = html;
        panel.classList.remove('hidden');
    } catch (error) {
        console.error('Error loading unit details:', error);
    }
}

// Load venue types
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

// Select venue type
function selectVenueType(venueType) {
    state.selectedVenueType = venueType;

    // Update active button
    document.querySelectorAll('.venue-type-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === venueType);
    });

    // Enable venues checkbox
    document.getElementById('show-venues').checked = true;
    state.showVenues = true;

    loadVenues(venueType);
}

// Load venues
async function loadVenues(venueType) {
    try {
        // Remove existing venue layer
        if (state.layers.venues[venueType]) {
            state.map.removeLayer(state.layers.venues[venueType]);
        }

        if (!state.showVenues) {
            return;
        }

        const response = await fetch(`/api/venues/${venueType}`);
        const geojson = await response.json();

        state.layers.venues[venueType] = L.geoJSON(geojson, {
            pointToLayer: (feature, latlng) => {
                return L.circleMarker(latlng, {
                    radius: 6,
                    fillColor: getVenueColor(feature.properties.type),
                    color: '#fff',
                    weight: 1,
                    opacity: 1,
                    fillOpacity: 0.8
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

// Get color based on venue type
function getVenueColor(type) {
    const colors = {
        'school': '#e74c3c',
        'hospital': '#3498db',
        'university': '#9b59b6',
        'company': '#f39c12',
        'household': '#2ecc71',
        'default': '#95a5a6'
    };
    return colors[type] || colors['default'];
}

// Show venue details
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
