// Extra screenshot states, injected by scripts/check_vibrancy_page.py. {{SHOT}} names the state to show.
const shotName = '{{SHOT}}';

// Keep only the map section, so the screenshot shows the part of the page being looked at.
function keepOnlyMapSection() {
    const keep = document.getElementById('what-if').closest('section');
    document.querySelectorAll('.hero, main > section, main > details, footer').forEach(item => {
        if (item !== keep) {
            item.style.display = 'none';
        }
    });
}

// Open the What if drawer after the Diversity counts double preset.
function showWhatIf() {
    document.getElementById('what-if').open = true;
    const presets = [...document.querySelectorAll('.preset')];
    presets.find(button => button.textContent === 'Diversity counts double').click();
}

// Show the Hot spots layer, so its legend is visible above the map.
// Show one requested map layer.
function showLayer(name) {
    window.vibrancy.setLayer(name);
    keepOnlyMapSection();
}

// Show the four place cards with Darlinghurst's profile beside them.
function showCards() {
    const feature = auditData.geo.features.find(item => item.properties.name === 'Darlinghurst');
    window.vibrancy.select(feature.properties.id);
    const grid = document.querySelector('.four');
    const keep = grid.closest('section');
    document.querySelectorAll('.hero, main > section, main > details, footer').forEach(item => {
        item.style.display = item === keep ? '' : 'none';
    });
    const profile = document.getElementById('profile');
    profile.style.position = 'static';
    profile.style.width = '100%';
    profile.style.maxHeight = 'none';
    profile.style.marginBottom = '14px';
    keep.insertBefore(profile, grid);
}

function showHotspots() {
    window.vibrancy.setLayer('hotspots');
}

// Show one categorical map layer with a category focused through its legend control.
function showFocus(layerName, category) {
    window.vibrancy.setLayer(layerName);
    const button = [...document.querySelectorAll('#legend .legend-choice')].find(item => {
        return item.dataset.focusCategory === category;
    });
    button.click();
    keepOnlyMapSection();
}

// Focus one quintile on one chart through its own chip buttons, then keep only that chart's card.
function showChartQuintileFocus(chartId, quintile) {
    const button = document.querySelector('.quintile-focus-button.quintile-' + quintile + '[data-chart="' + chartId + '"]');
    button.click();
    keepOnlyChartCard(chartId);
}

// Keep only one chart's card, so the screenshot shows it alone at its full width.
function keepOnlyChartCard(chartId) {
    const chart = document.getElementById(chartId);
    const keep = chart.closest('.chart-card') || chart;
    const section = chart.closest('section');
    document.querySelectorAll('.hero, main > section, main > details, footer').forEach(item => {
        item.style.display = section === item ? '' : 'none';
    });
    section.querySelectorAll(':scope > *').forEach(item => {
        item.style.display = item === keep ? '' : 'none';
    });
}

// Keep one complete story panel, including its heading, explanation, and charts.
function keepOnlySection(sectionId) {
    const keep = document.getElementById(sectionId);
    document.querySelectorAll('.hero, main > section, main > details, footer').forEach(item => {
        if (item !== keep) {
            item.style.display = 'none';
        }
    });
}

// Open the profile card of Holsworthy Military Area, an SA2 with no Diversity pillar.
function showHolsworthy() {
    const feature = auditData.geo.features.find(item => item.properties.name === 'Holsworthy Military Area');
    window.vibrancy.select(feature.properties.id);
}

// Switch the page to dark theme, the same way the theme control does.
function switchToDark() {
    const themeControl = document.getElementById('theme');
    themeControl.value = 'dark';
    themeControl.dispatchEvent(new Event('change', { bubbles: true }));
}

// Select a known scored SA2, so its chosen-ring styling is visible on the map.
function showSelected() {
    const feature = auditData.geo.features.find(item => item.properties.name === 'Darlinghurst');
    window.vibrancy.select(feature.properties.id);
    keepOnlyMapSection();
}

// Select Centennial Park (not scored, hollow), so the chosen ring is visible with no fill behind it.
function showCentennial() {
    const feature = auditData.geo.features.find(item => item.properties.name === 'Centennial Park');
    window.vibrancy.select(feature.properties.id);
    keepOnlyMapSection();
}

const auditData = JSON.parse(document.getElementById('story-data').textContent);
if (['intensity', 'diversity', 'placetypes'].includes(shotName)) {
    showLayer(shotName === 'placetypes' ? 'place_types' : shotName);
} else if (shotName === 'cards') {
    showCards();
} else if (shotName === 'whatif') {
    showWhatIf();
    keepOnlyMapSection();
} else if (shotName === 'hotspots') {
    showHotspots();
    keepOnlyMapSection();
} else if (shotName === 'typefocus') {
    showFocus('place_types', 'dense and diverse');
} else if (shotName === 'hotspotfocus') {
    showFocus('hotspots', 'high-high');
} else if (shotName === 'moran') {
    keepOnlyChartCard('moran-chart');
} else if (shotName === 'distance') {
    keepOnlyChartCard('distance-chart');
} else if (shotName === 'distancedark') {
    switchToDark();
    keepOnlyChartCard('distance-chart');
} else if (shotName === 'distancequintile') {
    showChartQuintileFocus('distance-chart', 4);
} else if (shotName === 'overallquintile') {
    showFocus('overall', '4');
} else if (shotName === 'histogram') {
    keepOnlyChartCard('histogram-chart');
} else if (shotName === 'intensitydesign') {
    keepOnlyChartCard('intensity-design-chart');
} else if (shotName === 'densitydiversity') {
    keepOnlyChartCard('density-diversity-chart');
} else if (shotName === 'stability') {
    keepOnlyChartCard('stability-chart');
} else if (shotName === 'footpanel') {
    keepOnlySection('foot-traffic-check');
} else if (shotName === 'weekdayscatter') {
    keepOnlyChartCard('weekday-chart');
} else if (shotName === 'weekendscatter') {
    keepOnlyChartCard('weekend-chart');
} else if (shotName === 'selected') {
    showSelected();
} else if (shotName === 'selecteddark') {
    switchToDark();
    showSelected();
} else if (shotName === 'centennial') {
    showCentennial();
} else {
    showHolsworthy();
    keepOnlyMapSection();
}
