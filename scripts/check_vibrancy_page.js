// Browser checks injected by scripts/check_vibrancy_page.py.
// Each result becomes one field in #check-results for the Python runner.
const themeControl = document.getElementById('theme');
const auditData = JSON.parse(document.getElementById('story-data').textContent);
const auditExpected = {{EXPECTED}};
const auditResults = {};
const mapElement = document.getElementById('map');
const profile = document.getElementById('profile');
const darlinghurst = auditData.geo.features.find(
    feature => feature.properties.name === 'Darlinghurst'
);
const centennialPark = auditData.geo.features.find(
    feature => feature.properties.name === 'Centennial Park'
);

// Apply the requested theme through the page control.
function applyTheme() {
    if (!themeControl || '{{THEME}}' !== 'dark') {
        return;
    }
    themeControl.value = 'dark';
    themeControl.dispatchEvent(new Event('change', { bubbles: true }));
}

// Return the builder-derived map colour for the known SA2 in one layer.
function expectedColour(layerName, themeName) {
    const theme = themeName || currentThemeName();
    if (layerName === "overall") {
        return auditExpected.colours.themes[theme].overall_fill;
    }
    return auditExpected.colours.themes[theme].pillar[layerName].known_fill;
}

// Check the map legend against each embedded layer definition.
function legendsMatch() {
    return Object.keys(auditData.layers).every(layerName => {
        window.vibrancy.setLayer(layerName);
        const layer = auditData.layers[layerName];
        const text = document.getElementById('legend').textContent;
        return layer.labels.every((label, index) => {
            return text.includes(label + ' (' + layer.counts[index] + ')');
        });
    });
}

// Confirm equal weights reproduce all baseline ranks and classes, and the page then shows the baseline.
function equalWeightsMatch() {
    const ranking = window.vibrancy.weightedRanking([100, 100, 100]);
    const sameRanking = auditData.geo.features
        .filter(feature => feature.properties.scored)
        .every(feature => {
            const properties = feature.properties;
            return ranking.ranks[String(properties.id)] === properties.rank &&
                ranking.classes[String(properties.id)] === properties.rank_class;
        });
    window.vibrancy.setWeights([100, 100, 100]);
    return sameRanking && window.vibrancy.state().mode === 'baseline';
}

// Confirm intensity-only weights produce the saved leading places.
function intensityOnlyMatch() {
    window.vibrancy.setWeights([100, 0, 0]);
    const names = auditData.geo.features
        .filter(feature => feature.properties.scored)
        .sort((first, second) => {
            return window.vibrancy.shownRank(first.properties.id) -
                window.vibrancy.shownRank(second.properties.id);
        })
        .slice(0, 5)
        .map(feature => feature.properties.name);
    return JSON.stringify(names) === JSON.stringify(auditExpected.intensity_top);
}

// Confirm a named sensitivity variant uses every saved rank.
function variantRanksMatch() {
    window.vibrancy.setVariant('Equal per indicator');
    const names = auditData.geo.features
        .filter(feature => feature.properties.scored)
        .sort((first, second) => {
            return window.vibrancy.shownRank(first.properties.id) -
                window.vibrancy.shownRank(second.properties.id);
        })
        .slice(0, 10)
        .map(feature => feature.properties.name);
    const allRanksMatch = auditData.geo.features
        .filter(feature => feature.properties.scored)
        .every(feature => {
            return window.vibrancy.shownRank(feature.properties.id) ===
                auditExpected.equal_ranks[String(feature.properties.id)];
        });
    return JSON.stringify(names) === JSON.stringify(auditExpected.equal_top) && allRanksMatch;
}

// Measure whether labels sit inside their chart and do not overlap one another.
function chartGeometry() {
    return [...document.querySelectorAll('.chart svg')].map(chart => {
        const chartBox = chart.getBoundingClientRect();
        const labels = [...chart.querySelectorAll('text')].map(label => ({
            label: label.textContent.trim(),
            box: label.getBoundingClientRect(),
        }));
        const outside = labels.filter(item => {
            const box = item.box;
            return box.left < chartBox.left - 1 || box.top < chartBox.top - 1 ||
                box.right > chartBox.right + 1 || box.bottom > chartBox.bottom + 1;
        });
        const overlaps = [];
        labels.forEach((first, index) => {
            labels.slice(index + 1).forEach(second => {
                const firstBox = first.box;
                const secondBox = second.box;
                const intersects = firstBox.left < secondBox.right &&
                    firstBox.right > secondBox.left &&
                    firstBox.top < secondBox.bottom &&
                    firstBox.bottom > secondBox.top;
                if (intersects) {
                    overlaps.push(first.label + ' / ' + second.label);
                }
            });
        });
        return {
            id: chart.parentElement.id,
            inside: outside.length === 0,
            noOverlaps: overlaps.length === 0,
            outside: outside.map(item => item.label),
            overlapsWith: overlaps,
        };
    });
}

// Calculate the contrast ratio for two hexadecimal colours.
function contrastRatio(first, second) {
    const colourValues = colour => {
        if (colour.startsWith("#")) {
            return colour.match(/\w\w/g).map(value => parseInt(value, 16) / 255);
        }
        return colour.match(/[\d.]+/g).slice(0, 3).map(value => Number(value) / 255);
    };
    const luminance = colour => colourValues(colour)
        .map(value => value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
        .reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    const values = [luminance(first), luminance(second)].sort(
        (firstValue, secondValue) => firstValue - secondValue
    );
    return (values[1] + 0.05) / (values[0] + 0.05);
}

// The x and y axis titles every chart must show, exactly.
const requiredAxisTitles = {
    'distance-chart': ['Distance from the CBD (km)', 'Vibrancy score'],
    'histogram-chart': ['Vibrancy score', 'SA2s in the bin'],
    'intensity-design-chart': ['Intensity score', 'Design score'],
    'density-diversity-chart': ['Density score (mean of Intensity and Design)', 'Diversity score'],
    'equity-chart': ['Median income group', "Share of the group's residents (%)"],
    'stability-chart': ['Median range of ranks across the 22 checks (places)', 'Baseline rank quintile'],
    'weekday-chart': ['Vibrancy score', 'Daily count, weekdays'],
    'weekend-chart': ['Vibrancy score', 'Daily count, weekends'],
    'moran-chart': ['Vibrancy score', 'Average score of neighbouring SA2s'],
};

// Read the axis lines, tick labels, and axis titles that one chart draws.
function readAxes(chartId) {
    const chart = document.getElementById(chartId);
    const axisLines = [...chart.querySelectorAll('line.axis')].map(line => ({
        x1: Number(line.getAttribute('x1')),
        x2: Number(line.getAttribute('x2')),
        y1: Number(line.getAttribute('y1')),
        y2: Number(line.getAttribute('y2')),
        box: line.getBoundingClientRect(),
    }));
    const titleTexts = selector => [...chart.querySelectorAll(selector)].map(item => item.textContent.trim());
    return {
        horizontal: axisLines.filter(line => line.y1 === line.y2 && line.x2 - line.x1 > 100),
        vertical: axisLines.filter(line => line.x1 === line.x2 && line.y2 - line.y1 > 100),
        xTicks: [...chart.querySelectorAll('text.tick-x')],
        yTicks: [...chart.querySelectorAll('text.tick-y')],
        xTitles: titleTexts('text.axis-title-x'),
        yTitles: titleTexts('text.axis-title-y'),
        allTitles: titleTexts('text.axis-title'),
    };
}

// Check one chart has both axis lines, three or more labels on each axis, and exactly the required titles.
// The labels of each axis must lie on the outer side of its line.
function axesAreComplete(chartId, details) {
    const axes = readAxes(chartId);
    const expected = requiredAxisTitles[chartId];
    const hasLines = axes.horizontal.length === 1 && axes.vertical.length === 1;
    const xBelowAxis = hasLines && axes.xTicks.every(label => {
        return label.getBoundingClientRect().top >= axes.horizontal[0].box.top - 1;
    });
    const yLeftOfAxis = hasLines && axes.yTicks.every(label => {
        return label.getBoundingClientRect().right <= axes.vertical[0].box.left + 1;
    });
    details[chartId] = {
        xTitle: axes.xTitles.join(' | '),
        yTitle: axes.yTitles.join(' | '),
        xTicks: axes.xTicks.length,
        yTicks: axes.yTicks.length,
        horizontalAxis: axes.horizontal.length,
        verticalAxis: axes.vertical.length,
    };
    return hasLines && xBelowAxis && yLeftOfAxis && axes.xTicks.length >= 3 && axes.yTicks.length >= 3 &&
        JSON.stringify(axes.xTitles) === JSON.stringify([expected[0]]) &&
        JSON.stringify(axes.yTitles) === JSON.stringify([expected[1]]) &&
        axes.allTitles.length === 2;
}

// Check the axes of all eight charts, one result per chart, and keep the details for the report.
function checkAllAxes() {
    const details = {};
    Object.keys(requiredAxisTitles).forEach(chartId => {
        auditResults['axes-' + chartId] = axesAreComplete(chartId, details);
    });
    auditResults.axisDetails = details;
}

// Return the smallest and largest text size drawn in the charts, in rendered pixels.
function chartTextSizes() {
    const sizes = [...document.querySelectorAll('.chart text')].map(label => {
        return parseFloat(getComputedStyle(label).fontSize) * label.getScreenCTM().a;
    });
    return {smallest: Math.min(...sizes), largest: Math.max(...sizes)};
}

// Check chart text is large enough and neutral axis titles use the shared ink colour.
function checkChartTextAndColours() {
    const sizes = chartTextSizes();
    const smallestAllowed = innerWidth < 700 ? 11 : 12;
    auditResults.chartTextSize = sizes.smallest >= smallestAllowed - 0.05 && sizes.largest <= 13.5;
    auditResults.textSizeDetails = {smallest: sizes.smallest.toFixed(1), largest: sizes.largest.toFixed(1)};
    const axisStrokes = Object.keys(requiredAxisTitles).map(chartId => {
        return getComputedStyle(document.querySelector('#' + chartId + ' line.axis')).stroke;
    });
    const ink = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim();
    const neutralTitles = [...document.querySelectorAll('text.axis-title')].filter(label => {
        return !label.matches('.intensity-title, .diversity-title, .design-title');
    });
    auditResults.axisColours = axisStrokes.every(stroke => stroke === axisStrokes[0]) &&
        neutralTitles.every(label => colourMatches(getComputedStyle(label).fill, ink));
}

// Check numeric tick labels are whole numbers.
function wholeTicks() {
    return [...document.querySelectorAll('.chart text')]
        .map(text => text.textContent.trim())
        .filter(text => /^-?[\d,]+(?:\.\d+)?$/.test(text))
        .every(text => !text.includes('.'));
}

// Check the named outer exceptions remain visible at each viewport width.
function distanceLabelsVisible() {
    const count = innerWidth < 700 ? 2 : 3;
    const names = auditData.geo.features
        .filter(feature => feature.properties.scored && feature.properties.distance_km > 10)
        .sort((first, second) => second.properties.score - first.properties.score)
        .slice(0, count)
        .map(feature => feature.properties.name);
    const text = document.getElementById('distance-chart').textContent;
    return names.every(name => text.includes(name));
}

// Check the three highest walking-count labels remain near their dots.
function footLabelsFit(day) {
    const chart = document.getElementById(day + '-chart');
    const sites = auditData.foot_sites
        .filter(site => site[day + '_average'] !== null)
        .sort((first, second) => second[day + '_average'] - first[day + '_average'])
        .slice(0, 3);
    return sites.every(site => {
        const feature = auditData.geo.features.find(item => {
            return String(item.properties.id) === String(site.sa2_code);
        });
        const label = [...chart.querySelectorAll('text')].find(text => {
            return text.textContent.trim() === feature.properties.name;
        });
        const dot = chart.querySelector('circle[data-code="' + feature.properties.id + '"]');
        if (!label || !dot) {
            return false;
        }
        const labelBox = label.getBoundingClientRect();
        const dotBox = dot.getBoundingClientRect();
        const dotX = dotBox.left + dotBox.width / 2;
        const dotY = dotBox.top + dotBox.height / 2;
        const horizontal = Math.max(labelBox.left - dotX, dotX - labelBox.right, 0);
        const vertical = Math.max(labelBox.top - dotY, dotY - labelBox.bottom, 0);
        return Math.hypot(horizontal, vertical) <= 60;
    });
}

// Check map labels remain within the phone map frame.
function mapLabelsFit() {
    if (innerWidth >= 700) {
        return true;
    }
    const mapBox = mapElement.getBoundingClientRect();
    return [...document.querySelectorAll('.map-label')].every(label => {
        const box = label.getBoundingClientRect();
        return box.left >= mapBox.left && box.right <= mapBox.right &&
            box.top >= mapBox.top && box.bottom <= mapBox.bottom;
    });
}

// Check histogram bars and labels remain inside the plot area.
function histogramFits() {
    const chart = document.getElementById('histogram-chart');
    const axisBoxes = [...chart.querySelectorAll('line.axis')].map(line => line.getBoundingClientRect());
    const plotTop = Math.min(...axisBoxes.map(box => box.top));
    const bars = [...chart.querySelectorAll('rect.chart-bar')].map(bar => bar.getBoundingClientRect());
    const labels = [...chart.querySelectorAll('text')].map(label => label.getBoundingClientRect());
    const barsFit = bars.every(box => box.top >= plotTop - 1);
    const labelsClear = labels.every(label => bars.every(bar => {
        return !(label.left < bar.right && label.right > bar.left &&
            label.top < bar.bottom && label.bottom > bar.top);
    }));
    return barsFit && labelsClear;
}

// Check visible card descendants remain within their right card edge.
function cardsFit() {
    const cards = [...document.querySelectorAll('.place-card, #profile:not([hidden])')];
    const offenders = [];
    cards.forEach(card => {
        const cardBox = card.getBoundingClientRect();
        [...card.querySelectorAll('*')].forEach(element => {
            const box = element.getBoundingClientRect();
            if (box.right > cardBox.right + 1) {
                offenders.push(card.className + ':' + element.tagName + ':' + element.textContent.trim());
            }
        });
    });
    auditResults.cardBoundOffenders = offenders;
    return offenders.length === 0;
}

// Check that the five Limits bullets stay inside their enclosing panel.
function limitsFit() {
    const list = document.getElementById('limits-list');
    const card = list ? list.closest('.card') : null;
    if (!list || !card || list.children.length !== 5) {
        return false;
    }
    const cardBox = card.getBoundingClientRect();
    return [...list.children].every(item => {
        const box = item.getBoundingClientRect();
        return box.left >= cardBox.left - 1 && box.right <= cardBox.right + 1 &&
            box.top >= cardBox.top - 1 && box.bottom <= cardBox.bottom + 1;
    });
}

// Count how many times a phrase appears in a text.
function countPhrase(text, phrase) {
    return text.split(phrase).length - 1;
}

// Return the tooltip lines for one SA2 in the current state.
function tooltipText(code) {
    return window.vibrancy.tooltipLines(code).join('\n');
}

// Return the class fifth shown under the current weights or check.
function classChanged(properties) {
    return window.vibrancy.shownClass(properties.id) !== properties.rank_class;
}

// Check the tooltip and profile card text of one SA2 in the baseline, weights and check states.
// Each outcome becomes its own result named with the prefix.
function checkTextStates(name, prefix) {
    const properties = auditData.geo.features.find(feature => feature.properties.name === name).properties;
    const code = properties.id;
    const baselineScore = properties.score.toFixed(1);
    const baselineLine = 'Vibrancy score ' + baselineScore + ', rank ' + properties.rank + ' of 372';

    document.getElementById('baseline').click();
    const baselineTooltip = tooltipText(code);
    window.vibrancy.select(code);
    const baselineCard = profile.innerText;
    auditResults[prefix + 'BaselineTooltip'] = countPhrase(baselineTooltip, 'Vibrancy score') === 1 &&
        baselineTooltip.includes('Vibrancy score ' + baselineScore) &&
        baselineTooltip.includes('Rank ' + properties.rank + ' of 372') &&
        !baselineTooltip.includes('Your weights') && !baselineTooltip.includes('Rank in this check');
    auditResults[prefix + 'BaselineCard'] = countPhrase(baselineCard, 'Score ' + baselineScore) === 1 &&
        !baselineCard.includes('With your weights') && !baselineCard.includes('Rank in this check');

    window.vibrancy.setWeights([100, 0, 0]);
    const weightScore = window.vibrancy.state().custom.scores[code].toFixed(1);
    const weightRank = window.vibrancy.shownRank(code);
    const weightsLine = 'score ' + weightScore + ', rank ' + weightRank + ' of 372';
    const weightsTooltip = tooltipText(code);
    const weightsCard = profile.innerText;
    auditResults[prefix + 'WeightsTooltip'] = countPhrase(weightsTooltip, 'Your weights') === 1 &&
        weightsTooltip.includes('Your weights: ' + weightsLine) &&
        weightsTooltip.includes('Baseline: score ' + baselineScore + ', rank ' + properties.rank + ' of 372') &&
        !weightsTooltip.includes('Vibrancy score') && !weightsTooltip.includes('Rank in this check');
    auditResults[prefix + 'WeightsRank'] = !classChanged(properties) || weightRank !== properties.rank;
    auditResults[prefix + 'WeightsCard'] = countPhrase(weightsCard, 'With your weights') === 1 &&
        weightsCard.includes('With your weights: ' + weightsLine) &&
        countPhrase(weightsCard, 'Score ' + baselineScore) === 1;

    window.vibrancy.setVariant('Equal per indicator');
    const checkLine = 'Rank in this check: ' + auditExpected.equal_ranks[String(code)] +
        ' (baseline: ' + properties.rank + ')';
    const checkTooltip = tooltipText(code);
    const checkCard = profile.innerText;
    auditResults[prefix + 'VariantTooltip'] = countPhrase(checkTooltip, 'Rank in this check') === 1 &&
        checkTooltip.includes(checkLine) && checkTooltip.includes(baselineLine) &&
        !checkTooltip.includes('Your weights');
    auditResults[prefix + 'VariantCard'] = countPhrase(checkCard, 'Rank in this check') === 1 &&
        checkCard.includes(checkLine) && !checkCard.includes('With your weights');

    document.getElementById('baseline').click();
    auditResults[prefix + 'BackToBaseline'] = tooltipText(code) === baselineTooltip &&
        profile.innerText === baselineCard;
}

// Confirm that a place whose map class changes under the weights also shows a different rank.
function changedClassShowsNewRank() {
    window.vibrancy.setWeights([100, 0, 0]);
    const changed = auditData.geo.features.find(feature => {
        return feature.properties.scored && classChanged(feature.properties);
    });
    if (!changed) {
        return false;
    }
    const properties = changed.properties;
    const line = 'Your weights: score ' + window.vibrancy.state().custom.scores[properties.id].toFixed(1) +
        ', rank ' + window.vibrancy.shownRank(properties.id) + ' of 372';
    const differs = window.vibrancy.shownRank(properties.id) !== properties.rank;
    const shown = tooltipText(properties.id).includes(line);
    window.vibrancy.setBaseline();
    return differs && shown;
}

// Check the pillar and place-type tooltips show each fact once, in every state.
function otherLayersMatch() {
    const properties = auditData.geo.features.find(feature => {
        return feature.properties.name === 'Parramatta - North';
    }).properties;
    const baselineLine = 'Vibrancy score ' + properties.score.toFixed(1) + ', rank ' + properties.rank + ' of 372';
    const states = [
        () => document.getElementById('baseline').click(),
        () => window.vibrancy.setWeights([100, 0, 0]),
        () => window.vibrancy.setVariant('Equal per indicator'),
    ];
    const matches = states.map(applyState => {
        applyState();
        window.vibrancy.setLayer('intensity');
        const pillar = tooltipText(properties.id);
        window.vibrancy.setLayer('place_types');
        const placeType = tooltipText(properties.id);
        return pillar.includes('Intensity ' + properties.intensity.toFixed(1)) &&
            pillar.includes(baselineLine) && countPhrase(pillar, properties.place_type) === 1 &&
            !pillar.includes('Your weights') && !pillar.includes('Rank in this check') &&
            placeType.split('\n')[1] === properties.place_type && placeType.includes(baselineLine) &&
            countPhrase(placeType, properties.place_type) === 1 &&
            !placeType.includes('Your weights') && !placeType.includes('Rank in this check');
    });
    window.vibrancy.setBaseline();
    return matches.every(Boolean);
}

// Return the text drawn inside the SVG charts.
function chartText() {
    return [...document.querySelectorAll('.chart svg')].map(chart => chart.textContent).join('\n');
}

// Count the source-date and middle-share phrases in the rendered page text.
// The histogram draws its own "75% of SA2s" bracket label, so that count is kept apart.
function checkRepeatedFacts() {
    const shareText = Math.round(auditData.score_middle_share * 100) + '% of SA2s';
    const pageText = document.body.innerText;
    const counts = {
        sourceDates: countPhrase(pageText, 'Source dates'),
        middleShareSentence: countPhrase(pageText, shareText + ' score between 90 and 110'),
        middleShareInCharts: countPhrase(chartText(), shareText),
        middleShareAll: countPhrase(pageText, shareText),
    };
    auditResults.sourceDatesOnce = counts.sourceDates === 1;
    auditResults.middleShareSentenceOnce = counts.middleShareSentence === 1;
    auditResults.middleShareOutsideChartsOnce = counts.middleShareAll - counts.middleShareInCharts === 1;
    auditResults.renderedCounts = counts;
}

// Return the last child of an element that is a block box with some height, or null.
function lastBlockChild(element) {
    const children = [...element.children].filter(child => {
        return child.getBoundingClientRect().height > 0 && getComputedStyle(child).display !== 'inline';
    });
    return children.length > 0 ? children[children.length - 1] : null;
}

// Return the last block element inside a card, going down through last children.
// A bordered box, such as a chart frame, counts as one element: it is where the eye stops.
function lastContentElement(card) {
    let element = card;
    let child = lastBlockChild(element);
    while (child) {
        element = child;
        if (getComputedStyle(element).borderBottomWidth !== '0px') {
            break;
        }
        child = lastBlockChild(element);
    }
    return element;
}

// Measure the space under the last content of each panel card and under each "How to read it" line.
// The bottom gap must be 16 to 40 px, and the space under a "How to read it" line at least 8 px.
function checkPanelSpacing() {
    const bottomGaps = [...document.querySelectorAll('main > section.card')].map(card => {
        const last = lastContentElement(card);
        return Math.round((card.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom) * 10) / 10;
    });
    const howGaps = [...document.querySelectorAll('.how')].map(line => {
        const next = line.nextElementSibling;
        return Math.round((next.getBoundingClientRect().top - line.getBoundingClientRect().bottom) * 10) / 10;
    });
    auditResults.cardBottomGaps = bottomGaps.length === 8 && bottomGaps.every(gap => gap >= 16 && gap <= 40);
    auditResults.howLineGaps = howGaps.length === 8 && howGaps.every(gap => gap >= 8);
    auditResults.spacingDetails = {
        cardBottomGaps: bottomGaps,
        howLineGaps: howGaps,
        smallestCardGap: Math.min(...bottomGaps),
        largestCardGap: Math.max(...bottomGaps),
        smallestHowGap: Math.min(...howGaps),
    };
}

// The what-if cases: the audit name, the preset button that sets them (if any), and two SA2s to read.
const whatIfCases = [
    {name: 'intensityOnly', preset: 'Intensity only'},
    {name: 'dropDiversity', preset: 'Drop Diversity'},
    {name: 'double', preset: 'Diversity counts double'},
    {name: 'diversityOnly', preset: null},
    {name: 'designOnly', preset: null},
];
const parramattaNorth = auditData.geo.features.find(feature => feature.properties.name === 'Parramatta - North');
const holsworthy = auditData.geo.features.find(feature => feature.properties.name === 'Holsworthy Military Area');
const noScoreText = 'No score with these weights';
const allZeroMessage = 'Give at least one pillar a weight above zero.';

// Return the sliders of the What if drawer in the order Intensity, Diversity, Design.
function weightSliders() {
    return [...document.querySelectorAll('.drawer input[type=range]')];
}

// Return the preset button with this label, or undefined.
function presetButton(label) {
    return [...document.querySelectorAll('.preset')].find(button => button.textContent === label);
}

// Put one what-if case on the page: click its preset button, or set its weights directly.
function applyWhatIfCase(whatIfCase) {
    const expected = auditExpected.what_if[whatIfCase.name];
    if (whatIfCase.preset) {
        presetButton(whatIfCase.preset).click();
    } else {
        window.vibrancy.setWeights(expected.weights);
    }
}

// Return the text of the state line, summary line, movers, legend, one tooltip and one open card.
function readWhatIfState(feature) {
    window.vibrancy.select(feature.properties.id);
    return [
        document.getElementById('state-line').textContent,
        document.getElementById('weight-summary').textContent,
        document.getElementById('rank-moves').textContent,
        document.getElementById('legend').textContent,
        tooltipText(feature.properties.id),
        profile.innerText,
    ];
}

// Record whether the current what-if state shows any NaN, undefined or Infinity text.
function scanWhatIfState(label) {
    const texts = [...readWhatIfState(parramattaNorth), ...readWhatIfState(holsworthy)];
    auditResults['cleanText' + label] = texts.every(text => !/NaN|undefined|Infinity/.test(text));
}

// Read the number in brackets at the end of each legend item.
function legendCounts() {
    return [...document.querySelectorAll('#legend .legend-item')].map(item => {
        const match = item.textContent.match(/\((\d+)\)$/);
        return match ? Number(match[1]) : null;
    });
}

// Read the full text of every legend item, in order.
function legendTexts() {
    return [...document.querySelectorAll('#legend .legend-item')].map(item => item.textContent);
}

// Check the sliders, shares, summary line, scores, ranks, fifths and legend of one what-if case.
function checkWhatIfCase(whatIfCase) {
    const name = whatIfCase.name;
    const expected = auditExpected.what_if[name];
    applyWhatIfCase(whatIfCase);
    auditResults[name + 'Sliders'] = weightSliders().every((slider, index) => {
        const value = Number(slider.value);
        return value >= Number(slider.min) && value <= Number(slider.max) && value === expected.weights[index];
    });
    const shown = ['intensity', 'diversity', 'design'].map(pillar => {
        return document.getElementById(pillar + '-pct').textContent;
    });
    auditResults[name + 'Shares'] = shown.join('/') === expected.shares.map(share => share + '%').join('/') &&
        document.getElementById('state-line').textContent === 'Showing: your weights (Intensity ' +
        expected.shares[0] + '%, Diversity ' + expected.shares[1] + '%, Design ' + expected.shares[2] + '%)';
    auditResults[name + 'Summary'] = document.getElementById('weight-summary').textContent === expected.summary;
    const ranking = window.vibrancy.state().custom;
    if (ranking === null) {
        auditResults[name + 'Ranking'] = false;
        auditResults[name + 'Legend'] = false;
        return;
    }
    const codes = Object.keys(expected.ranks);
    auditResults[name + 'Ranking'] = Object.keys(ranking.ranks).length === expected.count &&
        codes.every(code => ranking.ranks[code] === expected.ranks[code]) &&
        codes.every(code => ranking.classes[code] === expected.fifths[code]) &&
        codes.every(code => Math.abs(ranking.scores[code] - expected.scores[code]) < 0.000001);
    const counts = legendCounts();
    const fifthCounts = counts.slice(0, 5);
    const hasNoScoreEntry = document.getElementById('legend').textContent.includes(noScoreText);
    auditResults[name + 'Legend'] = JSON.stringify(fifthCounts) === JSON.stringify(expected.fifth_counts) &&
        fifthCounts.reduce((sum, value) => sum + value, 0) === expected.count &&
        hasNoScoreEntry === (expected.no_score > 0) &&
        (expected.no_score === 0 || counts[5] === expected.no_score);
    scanWhatIfState(name);
}

// Return the movers list as text lines such as "Wyong: 228 → 123".
function moverLines() {
    return [...document.querySelectorAll('#rank-moves li')].map(item => item.textContent);
}

// Check the ten biggest movers of one case against the ranks worked out from the scores file.
function checkMoverLines(whatIfCase) {
    const expected = auditExpected.what_if[whatIfCase.name];
    applyWhatIfCase(whatIfCase);
    const lines = moverLines();
    const expectedLines = expected.movers.map(mover => mover[0] + ': ' + mover[1] + ' → ' + mover[2]);
    auditResults[whatIfCase.name + 'Movers'] = lines.length === 10 && lines.every((line, index) => {
        const tied = expectedLines.filter((other, otherIndex) => {
            return expected.move_gaps[otherIndex] === expected.move_gaps[index];
        });
        return tied.includes(line);
    });
}

// Check the SA2s that have no score when only Diversity counts.
function checkNoScoreSa2s() {
    const expected = auditExpected.what_if.diversityOnly;
    window.vibrancy.setWeights(expected.weights);
    const unscored = expected.no_score_names.map(name => {
        return auditData.geo.features.find(feature => feature.properties.name === name);
    });
    auditResults.noScoreList = unscored.length === 4 && unscored.every(Boolean);
    auditResults.noScoreTooltip = unscored.every(feature => {
        const lines = tooltipText(feature.properties.id);
        return lines.includes(noScoreText) && !lines.includes('Your weights') && lines.includes('Baseline: score');
    });
    auditResults.noScoreCard = unscored.every(feature => {
        window.vibrancy.select(feature.properties.id);
        return profile.innerText.includes('With your weights: no score');
    });
    auditResults.noScoreFill = unscored.every(feature => {
        return window.vibrancy.mapFill(feature.properties.id) === '#d7d7d3';
    });
    const scoredCode = parramattaNorth.properties.id;
    const line = 'Your weights: score ' + expected.scores[scoredCode].toFixed(1) +
        ', rank ' + expected.ranks[scoredCode] + ' of ' + expected.count;
    window.vibrancy.select(scoredCode);
    auditResults.rankOutOfScored = tooltipText(scoredCode).includes(line) &&
        profile.innerText.includes('With your weights: score ' + expected.scores[scoredCode].toFixed(1) +
        ', rank ' + expected.ranks[scoredCode] + ' of ' + expected.count);
}

// Check that all-zero weights keep the last valid state and show the message, from a weights state and from baseline.
function checkAllZeroWeights() {
    window.vibrancy.setWeights([100, 0, 100]);
    const before = [document.getElementById('state-line').textContent, document.getElementById('legend').textContent];
    const beforeRanking = window.vibrancy.state().custom;
    const beforeFill = window.vibrancy.mapFill(darlinghurst.properties.id);
    window.vibrancy.setWeights([0, 0, 0]);
    auditResults.allZeroMessage = document.getElementById('weight-summary').textContent === allZeroMessage;
    auditResults.allZeroKeepsState = document.getElementById('state-line').textContent === before[0] &&
        document.getElementById('legend').textContent === before[1] &&
        window.vibrancy.state().custom === beforeRanking && window.vibrancy.state().mode === 'weights' &&
        window.vibrancy.mapFill(darlinghurst.properties.id) === beforeFill;
    scanWhatIfState('AllZero');
    window.vibrancy.setBaseline();
    window.vibrancy.setWeights([0, 0, 0]);
    auditResults.allZeroFromBaseline = document.getElementById('weight-summary').textContent === allZeroMessage &&
        document.getElementById('state-line').textContent === 'Showing: baseline' &&
        window.vibrancy.state().mode === 'baseline' && window.vibrancy.state().custom === null;
}

// Check that equal weights, set by hand or through setWeights, give exactly the baseline state.
function checkEqualWeightsAreBaseline() {
    window.vibrancy.setBaseline();
    const baselineTexts = readWhatIfState(parramattaNorth);
    const setByHand = () => {
        weightSliders().forEach(slider => {
            slider.value = 40;
        });
        window.vibrancy.calculateWeights();
    };
    const setThroughFunction = () => window.vibrancy.setWeights([100, 100, 100]);
    const setAtMiddle = () => window.vibrancy.setWeights([50, 50, 50]);
    const results = [setByHand, setThroughFunction, setAtMiddle].map(setEqual => {
        window.vibrancy.setWeights([100, 0, 0]);
        setEqual();
        return readWhatIfState(parramattaNorth).join('|') === baselineTexts.join('|') &&
            window.vibrancy.state().mode === 'baseline' && window.vibrancy.state().custom === null;
    });
    auditResults.equalByHandIsBaseline = results[0];
    auditResults.equalThroughFunctionIsBaseline = results[1];
    auditResults.equalAtFiftyIsBaseline = results[2];
    auditResults.baselineHasNoWhatIfText = baselineTexts[0] === 'Showing: baseline' &&
        baselineTexts[1] === '' && baselineTexts[2] === '' &&
        !baselineTexts[4].includes('Your weights') && !baselineTexts[5].includes('With your');
    window.vibrancy.setWeights([100, 0, 0]);
    weightSliders().forEach(slider => {
        slider.value = 40;
    });
    window.vibrancy.calculateWeights();
    auditResults.equalByHandKeepsSliders = weightSliders().every(slider => Number(slider.value) === 40);
    scanWhatIfState('EqualByHand');
}

// Check the sentence about SA2s that change fifth reads correctly for none, one, two and many.
function checkFifthChangeSentences() {
    const sentences = auditExpected.moves_sentences;
    auditResults.fifthChangeSentences = Object.keys(sentences).length === 4 &&
        Object.keys(sentences).every(count => window.vibrancy.fifthChangeSentence(Number(count)) === sentences[count]);
}

// Check the drawer has three presets and one Back to baseline button, and Back to baseline clears the what-if text.
function checkDrawerButtons() {
    const labels = [...document.querySelectorAll('.preset')].map(button => button.textContent);
    auditResults.presetButtons = JSON.stringify(labels) ===
        JSON.stringify(['Intensity only', 'Drop Diversity', 'Diversity counts double']);
    const chipButtons = [...document.querySelectorAll('#what-if .chips button')];
    auditResults.oneBaselineButton = chipButtons.length === 4 && chipButtons[3].id === 'baseline' &&
        chipButtons.filter(button => button.textContent === 'Back to baseline').length === 1;
    presetButton('Intensity only').click();
    document.getElementById('baseline').click();
    auditResults.backToBaselineClears = document.getElementById('weight-summary').textContent === '' &&
        document.getElementById('rank-moves').textContent === '' &&
        document.getElementById('state-line').textContent === 'Showing: baseline' &&
        weightSliders().every(slider => Number(slider.value) === 50);
    scanWhatIfState('BackToBaseline');
}

// Check the biggest movers are focusable buttons that highlight the SA2, and a click opens its card.
function checkMoverButtons() {
    document.getElementById('what-if').open = true;
    presetButton('Diversity counts double').click();
    const buttons = [...document.querySelectorAll('#rank-moves button')];
    auditResults.moverButtons = buttons.length === 10 && buttons.every(button => {
        return button.tagName === 'BUTTON' && button.type === 'button' && button.tabIndex >= 0 && !button.disabled;
    });
    if (!auditResults.moverButtons) {
        auditResults.moverHighlight = false;
        auditResults.moverClickOpensCard = false;
        auditResults.moverFirstIsRichmond = false;
        return;
    }
    const first = buttons[0];
    const feature = auditData.geo.features.find(item => item.properties.name === first.textContent);
    const code = feature.properties.id;
    first.dispatchEvent(new MouseEvent('mouseenter'));
    const hoverWeight = window.vibrancy.outlineWeight(code);
    first.dispatchEvent(new MouseEvent('mouseleave'));
    const leaveWeight = window.vibrancy.outlineWeight(code);
    first.focus();
    const focusWeight = window.vibrancy.outlineWeight(code);
    const focusedButton = document.activeElement === first;
    first.blur();
    auditResults.moverHighlight = hoverWeight >= 2 && leaveWeight < 2 && focusWeight >= 2 && focusedButton &&
        window.vibrancy.outlineWeight(code) < 2;
    first.click();
    auditResults.moverClickOpensCard = !profile.hidden && profile.textContent.includes(first.textContent) &&
        profile.contains(document.activeElement);
    auditResults.moverFirstIsRichmond = first.textContent === 'Richmond - Clarendon' &&
        moverLines()[0] === 'Richmond - Clarendon: 276 → 122';
}

// Check the sliders start in the middle, before anything on the page has been used.
function checkInitialSliders() {
    auditResults.initialSlidersAtFifty = weightSliders().every(slider => Number(slider.value) === 50);
    auditResults.initialStateIsBaseline = document.getElementById('state-line').textContent === 'Showing: baseline';
}

// Check the presets carry the weights the drawer promises, and Back to baseline returns the sliders to 50.
function checkSliderPositions() {
    const presetWeights = [...document.querySelectorAll('.preset')].map(button => button.dataset.weights);
    auditResults.presetWeights = JSON.stringify(presetWeights) === JSON.stringify(['100,0,0', '50,0,50', '50,100,50']);
    window.vibrancy.setWeights([0, 100, 0]);
    document.getElementById('baseline').click();
    auditResults.backToBaselineAtFifty = weightSliders().every(slider => Number(slider.value) === 50);
}

// Check D27: selecting "Intensity only" also moves the sliders to 100/0/0, the one visual match for
// the one sensitivity check a weight setting can reproduce exactly (verified independently in
// Python); every other check still resets the sliders to neutral, and a manual slider move
// afterward still resets the picker to Baseline as normal.
function checkIntensityOnlySliderSync() {
    window.vibrancy.setVariant('Intensity only');
    const slidersAtIntensityOnly = weightSliders().every((slider, index) => {
        return Number(slider.value) === [100, 0, 0][index];
    });
    const stateLineDuringSync = document.getElementById('state-line').textContent;
    window.vibrancy.setVariant('Equal per indicator');
    const slidersStayNeutralForOtherCheck = weightSliders().every(slider => Number(slider.value) === 50);
    window.vibrancy.setVariant('Intensity only');
    weightSliders()[1].value = 40;
    window.vibrancy.calculateWeights();
    auditResults.intensityOnlySyncsSliders = slidersAtIntensityOnly &&
        stateLineDuringSync === 'Showing: check: Intensity only';
    auditResults.otherChecksKeepNeutralSliders = slidersStayNeutralForOtherCheck;
    auditResults.sliderMoveAfterSyncResetsToBaseline =
        document.getElementById('variant-picker').value === 'Baseline' &&
        window.vibrancy.state().mode === 'weights';
    window.vibrancy.setBaseline();
}

// Check that a sensitivity check picked from the dropdown also lists its ten biggest movers,
// reusing the same #rank-moves list the weight presets already populate (values verified
// independently from output/vibrancy_scores.csv and output/vibrancy_variant_ranks.csv).
function checkVariantMovers() {
    window.vibrancy.setVariant('Equal per indicator');
    const firstButtons = [...document.querySelectorAll('#rank-moves button')];
    auditResults.variantMoverButtons = firstButtons.length === 10;
    auditResults.variantMoverFirstIsWileyPark = firstButtons.length === 10 &&
        moverLines()[0] === 'Wiley Park: 292 → 119';
    window.vibrancy.setVariant('Intensity only');
    const secondButtons = [...document.querySelectorAll('#rank-moves button')];
    auditResults.variantMoversChangeWithVariant = secondButtons.length === 10 &&
        moverLines()[0] !== 'Wiley Park: 292 → 119';
    window.vibrancy.setBaseline();
    auditResults.baselineHasNoVariantMovers = document.getElementById('rank-moves').textContent === '';
}

// Check the profile cards and the place cards: missing pillars, real off-scale values, and fact lines.
function checkCards() {
    window.vibrancy.setBaseline();
    checkMissingPillarCards('');
    checkRealOffScaleCard();
    window.vibrancy.setWeights([0, 100, 0]);
    checkMissingPillarCards('InWeightsState');
    window.vibrancy.setBaseline();
    checkPlaceCardMissingPillars();
    checkFactLines();
    checkPlaceCardFacts();
    checkSingularCases();
    checkPlaceAndProfileCardsAgree();
    checkFactTotals();
    checkHotspots();
}

// Prove D25-3: the weight-mode and sensitivity-variant-mode what-if legends and summaries read as
// the same shape for the case that shares an identical ranking (Intensity-only weights and the
// "Intensity only" variant, verified independently in Python), matching the owner's own check.
function checkWeightsVariantWordingParity() {
    const expected = auditExpected.intensity_only_parity;
    window.vibrancy.setWeights([100, 0, 0]);
    const weightsLegend = legendTexts().slice(0, 5);
    const weightsSummaryText = document.getElementById('weight-summary').textContent;
    window.vibrancy.setBaseline();
    window.vibrancy.setVariant('Intensity only');
    const variantLegend = legendTexts().slice(0, 5);
    const variantSummaryText = document.getElementById('variant-summary').textContent;
    const legendLabelsMatch = expected.legend_labels.every((label, index) => {
        return weightsLegend[index].startsWith(label) && variantLegend[index].startsWith(label);
    });
    auditResults.weightsVariantLegendParity =
        JSON.stringify(weightsLegend) === JSON.stringify(variantLegend) && legendLabelsMatch;
    auditResults.weightsVariantSummaryParity =
        weightsSummaryText === expected.summary && variantSummaryText === expected.summary;
    window.vibrancy.setBaseline();
}

// Run all the checks of the What if drawer.
function checkWhatIfDrawer() {
    whatIfCases.forEach(checkWhatIfCase);
    whatIfCases.forEach(checkMoverLines);
    checkNoScoreSa2s();
    checkAllZeroWeights();
    checkEqualWeightsAreBaseline();
    checkFifthChangeSentences();
    checkWeightsVariantWordingParity();
    checkDrawerButtons();
    checkMoverButtons();
    checkSliderPositions();
    checkIntensityOnlySliderSync();
    checkVariantMovers();
    document.getElementById('what-if').open = false;
    window.vibrancy.setBaseline();
}

// Check the equity and stability axes reach one tick above the tallest bar, and the two duplicate sentences are gone.
function checkEquityAndStabilityAxes() {
    const tickTexts = (chartId, selector) => {
        return [...document.querySelectorAll('#' + chartId + ' ' + selector)].map(label => label.textContent.trim());
    };
    const equityTicks = tickTexts('equity-chart', 'text.tick-y');
    const tallestShare = Math.max(...auditData.equity.flatMap(row => {
        return [row.top_quintile_share * 100, row.bottom_quintile_share * 100];
    }));
    const equityValues = equityTicks.map(label => Number(label.replace('%', '')));
    auditResults.equityPercentTicks = equityTicks.every(label => /^\d+%$/.test(label)) &&
        equityValues[0] === 0 && equityValues[equityValues.length - 1] > tallestShare &&
        equityValues[equityValues.length - 2] <= tallestShare;
    const stabilityTicks = tickTexts('stability-chart', 'text.tick-x');
    const tallestRange = Math.max(...auditData.rank_bands.map(band => band.maximum));
    const stabilityValues = stabilityTicks.map(label => Number(label));
    auditResults.stabilityWholeTicks = stabilityTicks.every(label => /^\d+$/.test(label)) &&
        stabilityValues[0] === 0 && stabilityValues[stabilityValues.length - 1] >= tallestRange;
    const pageText = document.body.innerText;
    auditResults.duplicateSentencesGone = !pageText.includes("Share of the group's residents.") &&
        !pageText.includes('Median range of ranks across the 22 checks, by baseline rank band.');
}

// Check the five rendered stability rows against summaries computed from the saved scores.
function checkStabilityQuintiles() {
    const expected = auditExpected.rank_bands;
    const rows = auditData.rank_bands;
    const dataMatch = rows.length === expected.length && rows.every((row, index) => {
        const wanted = expected[index];
        return row.label === wanted.label && row.sa2s === wanted.sa2s &&
            row.median === wanted.median && row.maximum === wanted.maximum &&
            row.mover_name === wanted.mover_name &&
            row.mover_rank_min === wanted.mover_rank_min && row.mover_rank_max === wanted.mover_rank_max;
    });
    const chart = document.getElementById('stability-chart');
    const medianLabels = [...chart.querySelectorAll('.median-label')].map(item => item.textContent.trim());
    const moverLabels = [...chart.querySelectorAll('.mover-label')].map(item => {
        return [...item.querySelectorAll('tspan')]
            .map(part => part.textContent.trim())
            .join(' ');
    });
    const extensions = [...chart.querySelectorAll('rect.range-extension')];
    const renderedMatch = expected.every((row, index) => {
        const median = Math.round(row.median).toFixed(0);
        const extension = extensions[index];
        return medianLabels[index] === 'median ' + median + ' places' &&
            moverLabels[index] === row.mover_name + ' swings ' + row.mover_rank_min + ' to ' + row.mover_rank_max &&
            extension.dataset.moverName === row.mover_name &&
            Number(extension.dataset.median) === row.median &&
            Number(extension.dataset.maximum) === row.maximum && Number(extension.getAttribute('width')) > 0;
    });
    auditResults.stabilityQuintiles = dataMatch && renderedMatch;
}

// Check each stability-chart bar and its lighter extension are the true colour of their own
// quintile (the map's own ramp step, computed independently from the builder's colour roles,
// not the page), and that no label text overlaps a bar or its extension, in either theme.
function checkStabilityBarColours() {
    const theme = currentThemeName();
    const expectedRamp = auditExpected.quintile_ramp[theme];
    const bars = [...document.querySelectorAll('#stability-chart .chart-bar')];
    const extensions = [...document.querySelectorAll('#stability-chart .range-extension')];
    const medianLabels = [...document.querySelectorAll('#stability-chart .median-label')];
    const moverLabels = [...document.querySelectorAll('#stability-chart .mover-label')];
    const barColoursOk = bars.length === 5 && bars.every((bar, index) => {
        return colourMatches(bar.getAttribute('fill'), expectedRamp[4 - index]);
    });
    const extensionsTinted = extensions.length === 5 && extensions.every(extension => {
        return !expectedRamp.includes(extension.getAttribute('fill'));
    });
    // The median label is the one label drawn over its own row's extension (the mover label sits
    // clear below the row); check its fill keeps 4.5:1 against every one of the five extensions.
    const medianLabelsReadable = medianLabels.length === 5 && medianLabels.every((label, index) => {
        const textFill = getComputedStyle(label).fill;
        return contrastRatio(textFill, extensions[index].getAttribute('fill')) >= 4.5;
    });
    // A narrow chart can clamp the mover label onto its own bar or extension; wherever that
    // happens the label must switch to a fill that keeps 4.5:1 against the shape it now covers.
    const moverLabelsReadable = moverLabels.every((label, index) => {
        const box = label.getBBox();
        const textFill = getComputedStyle(label).fill;
        if (boxesOverlap(box, bars[index].getBBox())) {
            return contrastRatio(textFill, bars[index].getAttribute('fill')) >= 4.5;
        }
        if (boxesOverlap(box, extensions[index].getBBox())) {
            return contrastRatio(textFill, extensions[index].getAttribute('fill')) >= 4.5;
        }
        return true;
    });
    auditResults['stabilityBarColours-' + theme] =
        barColoursOk && extensionsTinted && medianLabelsReadable && moverLabelsReadable;
}

// Read the rows of the pillar bars in the open profile card.
function pillarRows() {
    return [...profile.querySelectorAll('.pillar')].map(row => ({
        label: row.querySelector('span').textContent,
        value: row.querySelector('b span').textContent,
        offScale: row.querySelector('b small') !== null,
        marker: row.querySelector('.bar i') !== null,
    }));
}

// Return whether a pillar score is present and outside the 70 to 130 bar scale.
function reallyOffScale(value) {
    return value !== null && (value < 70 || value > 130);
}

// Check the four SA2s with no Diversity pillar: n/a alone in that row, and "off scale" only for a real value.
function checkMissingPillarCards(suffix) {
    const names = ['Holsworthy Military Area', 'Rookwood Cemetery', 'Badgerys Creek', 'Royal National Park'];
    auditResults['missingPillarCards' + suffix] = names.every(name => {
        const properties = auditData.geo.features.find(feature => feature.properties.name === name).properties;
        window.vibrancy.select(properties.id);
        const rows = pillarRows();
        const diversity = rows.find(row => row.label === 'Diversity');
        const presentOffScale = ['intensity', 'design'].some(key => reallyOffScale(properties[key]));
        return properties.diversity === null && diversity.value === 'n/a' && !diversity.offScale &&
            !diversity.marker && rows.some(row => row.offScale) === presentOffScale &&
            profile.innerText.includes('off scale') === presentOffScale;
    });
}

// Check a present pillar that is really off the scale keeps its tag (Sydney Airport, Diversity -27.9).
function checkRealOffScaleCard() {
    const airport = auditData.geo.features.find(feature => feature.properties.name === 'Sydney Airport').properties;
    window.vibrancy.select(airport.id);
    const diversity = pillarRows().find(row => row.label === 'Diversity');
    auditResults.offScaleKeptForRealValue = reallyOffScale(airport.diversity) && diversity.offScale &&
        diversity.value === formatAuditScore(airport.diversity) && diversity.marker;
}

// Format a score to one decimal, as the page does.
function formatAuditScore(value) {
    return (Math.abs(value) < 0.05 ? 0 : value).toFixed(1);
}

// Check the place cards written into the page treat a missing pillar the same way.
function checkPlaceCardMissingPillars() {
    const rows = [...document.querySelectorAll('.place-card .pillar')];
    auditResults.placeCardMissingPillars = rows.every(row => {
        return row.querySelector('b span').textContent !== 'n/a' ||
            (row.querySelector('b small') === null && row.querySelector('.bar i') === null);
    });
}

// Check the four fact lines of a profile card against the lines worked out from the scores file.
function checkFactLines() {
    Object.keys(auditExpected.fact_lines).forEach(name => {
        const properties = auditData.geo.features.find(feature => feature.properties.name === name).properties;
        window.vibrancy.select(properties.id);
        const lines = [...profile.querySelectorAll('.facts li')].map(item => [
            item.querySelector('strong').textContent,
            item.querySelector('span').textContent,
        ]);
        auditResults['factLines-' + name] = JSON.stringify(lines) === JSON.stringify(auditExpected.fact_lines[name]);
    });
}

// Check the four fact lines of each place card written into the page, against the lines worked out from the scores.
function checkPlaceCardFacts() {
    Object.keys(auditExpected.place_card_facts).forEach(name => {
        const cards = [...document.querySelectorAll('.place-card')];
        const card = cards.find(item => item.querySelector('h3').textContent === name);
        const lines = [...card.querySelectorAll('.facts li')].map(item => [
            item.querySelector('strong').textContent,
            item.querySelector('span').textContent,
        ]);
        auditResults['placeCardFacts-' + name] = JSON.stringify(lines) ===
            JSON.stringify(auditExpected.place_card_facts[name]);
    });
}

// Check each SA2 whose displayed density is exactly 1 says so in the singular, on its profile card.
function checkSingularCases() {
    Object.keys(auditExpected.singular_cases).forEach(name => {
        const index = auditExpected.singular_cases[name];
        window.vibrancy.select(auditData.geo.features.find(feature => feature.properties.name === name).properties.id);
        const shown = profile.querySelectorAll('.facts li strong')[index].textContent;
        auditResults['singularCase-' + name] = shown === auditExpected.fact_lines[name][index][0] &&
            shown.startsWith('1 ');
    });
}

// Check the profile card and the place card of one SA2 give the same second line for each fact.
// A place card that says "the highest of N SA2s" is left out, because the profile card never says that.
function checkPlaceAndProfileCardsAgree() {
    Object.keys(auditExpected.place_card_facts).forEach(name => {
        const cards = [...document.querySelectorAll('.place-card')];
        const card = cards.find(item => item.querySelector('h3').textContent === name);
        const placeSeconds = [...card.querySelectorAll('.facts li span')].map(item => item.textContent);
        window.vibrancy.select(auditData.geo.features.find(feature => feature.properties.name === name).properties.id);
        const profileSeconds = [...profile.querySelectorAll('.facts li span')].map(item => item.textContent);
        auditResults['cardsAgree-' + name] = placeSeconds.length === 4 && placeSeconds.every((second, index) => {
            return second.startsWith('the highest of') || second === profileSeconds[index];
        });
    });
}

// Check every scored SA2 carries the whole-number totals the card facts need (an SA2 without a density has null).
function checkFactTotals() {
    const keys = ['businesses', 'stops', 'intersections'];
    auditResults.factTotalsAreWhole = auditData.geo.features.every(feature => {
        const properties = feature.properties;
        return keys.every(key => Number.isInteger(properties[key]) || (!properties.scored && properties[key] === null));
    });
}

// Check the note under the distance chart, and that it is the only place that says it.
function checkDistanceAxisNote() {
    const note = document.getElementById('distance-axis-note');
    const expected = auditExpected.below_axis_note;
    auditResults.distanceAxisNote = note.textContent === expected && note.hidden === (expected === '');
    auditResults.distanceNoteNotRepeated = countPhrase(document.body.innerText, expected) === 1;
}

// Check each of the four scatter charts has a semibold title in the main ink colour above a lighter y title.
function checkChartTitleStyle() {
    const bodyColour = getComputedStyle(document.body).color;
    const ids = ['intensity-design-chart', 'density-diversity-chart', 'weekday-chart', 'weekend-chart'];
    auditResults.chartTitleStyle = ids.every(chartId => {
        const title = document.querySelector('#' + chartId + ' text.chart-title');
        const yTitle = document.querySelector('#' + chartId + ' text.axis-title-y');
        const titleStyle = getComputedStyle(title);
        const gap = yTitle.getBoundingClientRect().top - title.getBoundingClientRect().bottom;
        const titleWeight = Number(titleStyle.fontWeight);
        return titleWeight >= 600 && titleWeight > Number(getComputedStyle(yTitle).fontWeight) &&
            titleStyle.fill === bodyColour && gap >= 3;
    });
}

// Return the median score of the SA2s in one distance group, taken from the embedded data.
function groupMedian(lower, upper) {
    const scores = auditData.geo.features
        .filter(feature => feature.properties.scored && feature.properties.distance_km >= lower &&
            feature.properties.distance_km < upper)
        .map(feature => feature.properties.score)
        .sort((first, second) => first - second);
    return scores[Math.floor(scores.length / 2)];
}

// Check every distance group label is exactly three lines, none of them wider than its column.
// A column is the distance to the next label in the same row, so staggered labels get two columns.
function checkDistanceGroupLabels() {
    const chart = document.getElementById('distance-chart');
    const labels = [...chart.querySelectorAll('text.tick-x')].map(label => ({
        x: Number(label.getAttribute('x')),
        y: Number(label.getAttribute('y')),
        lines: [...label.querySelectorAll('tspan')].map(part => ({
            text: part.textContent,
            width: part.getComputedTextLength(),
        })),
    }));
    const slot = (Number(chart.querySelector('line.axis').getAttribute('x2')) -
        Number(chart.querySelector('line.axis').getAttribute('x1'))) / 5;
    const columnWidth = label => {
        const spacings = labels.filter(other => other !== label && other.y === label.y)
            .map(other => Math.abs(other.x - label.x));
        return spacings.length > 0 ? Math.min(...spacings) : slot;
    };
    const medians = [[0, 5], [5, 10], [10, 20], [20, 40], [40, 1e6]].map(band => groupMedian(band[0], band[1]));
    auditResults.distanceGroupLabels = labels.length === 5 && labels.every((label, index) => {
        const medianText = label.lines.length === 3 ? label.lines[1].text : '';
        return label.lines.length === 3 && label.lines.every(line => line.width <= columnWidth(label)) &&
            /^(median|med\.) /.test(medianText) && medianText.endsWith(formatAuditScore(medians[index])) &&
            /^n = \d+$/.test(label.lines[2].text);
    });
    auditResults.distanceLabelDetails = labels.map(label => label.lines.map(line => line.text).join(' / '));
}

// Check the distance card is a full-width row and its found title states the median contrast, from embedded data.
// Return the width of the Moran card: a chart-card that has always been full width, the reference
// every other full-width layout check compares against, at whatever viewport is current.
function fullWidthReference() {
    return document.querySelector('.moran-card').getBoundingClientRect().width;
}

// Check one chart-card's rendered width matches the full-width reference (within rounding).
function isFullWidth(card) {
    return Math.abs(card.getBoundingClientRect().width - fullWidthReference()) <= 2;
}

function checkDistanceTitle() {
    const card = document.getElementById('distance-chart').closest('.chart-card');
    auditResults.distanceFullWidth = isFullWidth(card);
    const title = card.querySelector('.found-title');
    const text = title ? title.textContent : '';
    const near = formatAuditScore(groupMedian(0, 5));
    const far = formatAuditScore(groupMedian(40, 1e6));
    const topOuter = auditData.geo.features
        .filter(feature => feature.properties.scored && feature.properties.distance_km > 10)
        .sort((first, second) => second.properties.score - first.properties.score)[0];
    const expected = 'The median score falls from ' + near + ' near the centre to ' + far +
        ' beyond 40 km, but a few centres such as ' + topOuter.properties.name + ' buck the trend';
    auditResults.distanceTitleResolved = Boolean(title) && !text.includes('{{') && text === expected;
    auditResults.distanceTitleNotRepeated = countPhrase(document.body.innerText, text) === 1;
    auditResults.distanceCaptionRemoved = document.getElementById('distance-caption') === null;
}

// Check the histogram card is full width (matching the distance card) and its found title is right.
function checkHistogramTitle() {
    const card = document.getElementById('histogram-chart').closest('.chart-card');
    auditResults.histogramFullWidth = isFullWidth(card);
    const title = card.querySelector('.found-title');
    const text = title ? title.textContent : '';
    const share = Math.round(auditData.score_middle_share * 100) + '%';
    const below = auditData.geo.features
        .filter(feature => feature.properties.scored && feature.properties.score < 70);
    let expected = 'Most SA2s sit close to the average: ' + share + ' score within 10 points of 100';
    if (below.length) {
        const lowest = below.sort((first, second) => first.properties.score - second.properties.score)[0];
        expected += ', but ' + below.length + ' score below 70, as low as ' + lowest.properties.name +
            ' at ' + formatAuditScore(lowest.properties.score);
    }
    auditResults.histogramTitleResolved = Boolean(title) && !text.includes('{{') && text === expected;
    auditResults.histogramTitleNotRepeated = countPhrase(document.body.innerText, text) === 1;
    auditResults.histogramCaptionRemoved = document.getElementById('histogram-caption') === null;
}

// Check both panel-2 scatters: full width, and only the four card-example SA2s carry true colour.
function checkPanelTwoScatters() {
    const chartIds = ['intensity-design-chart', 'density-diversity-chart'];
    const theme = currentThemeName();
    const fade = auditExpected.map_focus.themes[theme].fade;
    const colours = auditExpected.distance.colours;
    const exampleNames = auditExpected.place_card_names;
    chartIds.forEach(chartId => {
        const chart = document.getElementById(chartId);
        const card = chart.closest('.chart-card');
        const dots = [...chart.querySelectorAll('circle.mark')];
        const fadeMatches = dots.every(dot => {
            const feature = auditData.geo.features.find(item => String(item.properties.id) === dot.dataset.code);
            const isExample = exampleNames.includes(feature.properties.name);
            const expectedFill = isExample ? colours[feature.properties.name][theme] : fade;
            return colourMatches(dot.getAttribute('fill'), expectedFill);
        });
        const text = chart.textContent;
        auditResults[chartId + 'FullWidth'] = isFullWidth(card);
        auditResults[chartId + 'Fade'] = fadeMatches;
        auditResults[chartId + 'ExampleNamesShown'] = exampleNames.every(name => text.includes(name));
    });
}

// Check both walking-count scatters: full width, found title text, and its repeat status.
function checkWalkingTitles() {
    ['weekday', 'weekend'].forEach(day => {
        const chart = document.getElementById(day + '-chart');
        const card = chart.closest('.chart-card');
        const title = card.querySelector('.found-title');
        const text = title ? title.textContent : '';
        const label = day === 'weekday' ? 'weekdays' : 'weekends';
        const expected = 'Busier ' + label + ' track a higher score too (Spearman ' +
            auditExpected.foot_correlations[day] + ')';
        auditResults[day + 'FullWidth'] = isFullWidth(card);
        auditResults[day + 'TitleResolved'] = Boolean(title) && !text.includes('{{') && text === expected;
        auditResults[day + 'TitleNotRepeated'] = countPhrase(document.body.innerText, text) === 1;
    });
}

// Check the independent-measure panel's copy, order, and chart ownership.
function checkFootTrafficPanel() {
    const equityPanel = document.getElementById('equity-chart').closest('section');
    const footPanel = document.getElementById('foot-traffic-check');
    const stabilityPanel = document.getElementById('stability-chart').closest('section');
    const panels = [...document.querySelectorAll('main > section')];
    const expectedTitle = 'Measured walking counts align weakly with the score: Spearman ' +
        auditExpected.foot_correlations.weekday + ' on weekdays and ' +
        auditExpected.foot_correlations.weekend + ' on weekends';
    const howText = footPanel.querySelector('.how').textContent.replace(/\s+/g, ' ').trim();
    const panelTwoCards = [
        document.getElementById('intensity-design-chart').closest('.chart-card'),
        document.getElementById('density-diversity-chart').closest('.chart-card'),
    ];
    auditResults.footPanelOrder = panels.indexOf(equityPanel) < panels.indexOf(footPanel) &&
        panels.indexOf(footPanel) < panels.indexOf(stabilityPanel);
    auditResults.footPanelTitle = document.getElementById('foot-traffic-title').textContent === expectedTitle;
    auditResults.walkingPanelPlacement =
        document.getElementById('weekday-chart').closest('section') === footPanel &&
        document.getElementById('weekend-chart').closest('section') === footPanel &&
        document.getElementById('limits-list').closest('section') === stabilityPanel &&
        document.getElementById('try-what-if').closest('section') === stabilityPanel;
    auditResults.footPanelCaveat = howText.includes(
        'The City of Sydney only counts pedestrians at 16 inner-city sites (ranked 1 to 29, all in the top ' +
        'quintile), so a quintile button below is only offered for the quintile that has data, and this ' +
        'check tests ordering among the busiest places only.'
    );
    auditResults.panelTwoKickersGone = panelTwoCards.every(card => card.querySelector(':scope > .kicker') === null);
}

// Check both walking-count scatters: only the top three by count keep their true colour and a label.
function checkWalkingFade() {
    const theme = currentThemeName();
    const fade = auditExpected.map_focus.themes[theme].fade;
    const colours = auditExpected.distance.colours;
    ['weekday', 'weekend'].forEach(day => {
        const chart = document.getElementById(day + '-chart');
        const topNames = auditExpected.foot_top_names[day];
        const dots = [...chart.querySelectorAll('circle.mark')];
        const flaggedNames = [];
        const fadeMatches = dots.every(dot => {
            const feature = auditData.geo.features.find(item => String(item.properties.id) === dot.dataset.code);
            const isFlagged = dot.dataset.labelled === 'true';
            if (isFlagged) {
                flaggedNames.push(feature.properties.name);
            }
            const expectedFill = isFlagged ? colours[feature.properties.name][theme] : fade;
            return colourMatches(dot.getAttribute('fill'), expectedFill);
        });
        const namesMatch = JSON.stringify(flaggedNames.slice().sort()) === JSON.stringify([...topNames].sort());
        const text = chart.textContent;
        auditResults[day + 'Fade'] = fadeMatches && namesMatch;
        auditResults[day + 'TopNamesShown'] = topNames.every(name => text.includes(name));
    });
}

// Check every distance-chart dot is faded except the ones the chart actually labelled with a name.
function checkDistanceFade() {
    const chart = document.getElementById('distance-chart');
    const theme = currentThemeName();
    const fade = auditExpected.map_focus.themes[theme].fade;
    const colours = auditExpected.distance.colours;
    const dots = [...chart.querySelectorAll('circle.mark')];
    let labelledCount = 0;
    const fadeMatches = dots.every(dot => {
        const feature = auditData.geo.features.find(item => String(item.properties.id) === dot.dataset.code);
        const fill = dot.getAttribute('fill');
        if (dot.dataset.labelled === 'true') {
            labelledCount += 1;
            return colourMatches(fill, colours[feature.properties.name][theme]);
        }
        return colourMatches(fill, fade);
    });
    auditResults.distanceDotCount = dots.length === 372;
    auditResults.distanceFade = fadeMatches && labelledCount >= 2 && labelledCount <= 3;
}

// The independent expectation for the short label a chart's quintile-focus state line shows: a
// fixed design choice (matching the stability chart's own wording), not derived from any data.
const auditQuintileFocusLabels = [
    'Bottom quintile', 'Fourth quintile', 'Middle quintile', 'Second quintile', 'Top quintile',
];

// Return the fill one dot must show while a quintile is focused on its chart: its true colour if
// its own SA2 is in the focused quintile (the SA2's saved quintile, not the page's), else the fade.
function expectedChartFocusFill(dot, focusedQuintile, theme) {
    const feature = auditData.geo.features.find(item => String(item.properties.id) === dot.dataset.code);
    const ownQuintile = auditExpected.quintiles[feature.properties.name];
    return ownQuintile === focusedQuintile
        ? auditExpected.quintile_ramp[theme][focusedQuintile]
        : auditExpected.map_focus.themes[theme].fade;
}

// Check the shared quintile-focus mechanism on one chart: each of its five buttons colours
// exactly the SA2s of that quintile (computed independently from the saved scores, never the
// page) and fades every other dot; "Show all" restores the chart's original rendering exactly;
// this chart's focus never changes any of the other charts' own focus state.
function quintileButton(chartId, level) {
    return document.querySelector('.quintile-focus-button.quintile-' + level + '[data-chart="' + chartId + '"]');
}

function quintileClearButton(chartId) {
    return document.querySelector('.quintile-focus-clear[data-chart="' + chartId + '"]');
}

function checkChartQuintileFocus(chartId, otherChartIds) {
    const theme = currentThemeName();
    const chart = document.getElementById(chartId);
    const dots = () => [...chart.querySelectorAll('circle.dot[data-code]')];
    const originalFills = new Map(dots().map(dot => [dot.dataset.code, dot.getAttribute('fill')]));
    const otherStatesBefore = otherChartIds.map(id => document.getElementById(id + '-focus-state').textContent);
    // Some charts (the walking-count scatters) only have data in one quintile, so they show only
    // that quintile's button; test whichever buttons the chart actually has, not a fixed five.
    const levels = [...document.querySelectorAll('.quintile-focus-button[data-chart="' + chartId + '"]')]
        .map(button => Number(button.dataset.quintile));
    let everyQuintileOk = true;
    levels.forEach(quintile => {
        quintileButton(chartId, quintile).click();
        const coloursOk = dots().every(dot => {
            return colourMatches(dot.getAttribute('fill'), expectedChartFocusFill(dot, quintile, theme));
        });
        const pressedOk = levels.every(level => {
            return quintileButton(chartId, level).getAttribute('aria-pressed') === String(level === quintile);
        });
        const clearNotPressed = quintileClearButton(chartId).getAttribute('aria-pressed') === 'false';
        const stateOk = document.getElementById(chartId + '-focus-state').textContent ===
            'Showing: ' + auditQuintileFocusLabels[quintile];
        everyQuintileOk = everyQuintileOk && coloursOk && pressedOk && clearNotPressed && stateOk;
    });
    quintileClearButton(chartId).click();
    const restoredFills = dots().every(dot => dot.getAttribute('fill') === originalFills.get(dot.dataset.code));
    const restoredState = document.getElementById(chartId + '-focus-state').textContent === 'Showing: baseline';
    const clearPressed = quintileClearButton(chartId).getAttribute('aria-pressed') === 'true';
    const otherStatesAfter = otherChartIds.map(id => document.getElementById(id + '-focus-state').textContent);
    const othersUnaffected = otherStatesBefore.every((text, index) => text === otherStatesAfter[index]);
    auditResults[chartId + 'QuintileFocus'] =
        everyQuintileOk && restoredFills && restoredState && clearPressed && othersUnaffected;
}

// Run the quintile-focus check on each of the five charts against the other four, in turn.
function checkAllChartQuintileFocus() {
    const chartIds = [
        'distance-chart', 'intensity-design-chart', 'density-diversity-chart', 'weekday-chart', 'weekend-chart',
    ];
    chartIds.forEach(chartId => {
        checkChartQuintileFocus(chartId, chartIds.filter(id => id !== chartId));
    });
}

// The Hot spots layer, its tooltips and cards, and the Moran scatterplot, checked against the CSV-based expectations.
const hotspotExpected = auditExpected.hotspots;
const hotspotKeys = ['high-high', 'low-low', 'high-low', 'low-high', 'not significant'];

// Return the feature of the SA2 with this name.
function featureNamed(name) {
    return auditData.geo.features.find(feature => feature.properties.name === name);
}

// Return the colour the page must use for a cluster class in a theme.
function expectedClusterColour(themeName, className) {
    return auditExpected.hotspot_colours[themeName][hotspotKeys.indexOf(className)].toLowerCase();
}

// Return whether the known SA2s are filled with their cluster colour for a theme (the Hot spots layer is shown).
function hotspotFillsMatch(themeName) {
    return Object.keys(auditExpected.hotspot_sa2s).every(name => {
        const fill = window.vibrancy.mapFill(featureNamed(name).properties.id).toLowerCase();
        return fill === expectedClusterColour(themeName, auditExpected.hotspot_sa2s[name]);
    });
}

// Switch the page theme through its control.
function switchTheme(themeName) {
    themeControl.value = themeName;
    themeControl.dispatchEvent(new Event('change', { bubbles: true }));
}

// Return the button for one category in the current map legend.
function categoryLegendButton(category) {
    return [...document.querySelectorAll('#legend .legend-choice')].find(button => {
        return button.dataset.focusCategory === category;
    });
}

// Return the independently expected true colour of one category.
function expectedCategoryColour(layerName, themeName, category) {
    if (layerName === 'place_types') {
        return auditExpected.colours.themes[themeName].place[category];
    }
    return expectedClusterColour(themeName, category);
}

// Return one representative feature for each category of a categorical map layer.
function categoryRepresentatives(layerName) {
    if (layerName === 'place_types') {
        return Object.entries(auditExpected.colours.place_representatives).map(([category, name]) => ({
            category,
            feature: featureNamed(name),
        }));
    }
    return Object.entries(auditExpected.hotspot_sa2s).map(([name, category]) => ({
        category,
        feature: featureNamed(name),
    }));
}

// Check rendered category fills against builder-derived true colours and the audit's fixed fade settings.
function categoryStylesMatch(layerName, themeName, focusedCategory) {
    const expected = auditExpected.map_focus;
    return categoryRepresentatives(layerName).every(item => {
        const style = window.vibrancy.mapStyle(item.feature.properties.id);
        const faded = focusedCategory !== null && item.category !== focusedCategory;
        const expectedColourValue = faded
            ? expected.themes[themeName].fade
            : expectedCategoryColour(layerName, themeName, item.category);
        const expectedOpacity = faded ? expected.fade_opacity : expected.full_opacity;
        return colourMatches(style.fillColor, expectedColourValue) &&
            Math.abs(style.fillOpacity - expectedOpacity) < 1e-9;
    });
}

// Check that the legend dims every category except the active focus.
function legendDimMatches(focusedCategory, categoryCount) {
    const buttons = [...document.querySelectorAll('#legend .legend-choice')];
    return buttons.length === categoryCount && buttons.every(button => {
        const focused = button.dataset.focusCategory === focusedCategory;
        const dimmed = button.classList.contains('dimmed');
        const opacity = Number(getComputedStyle(button).opacity);
        return focused ? !dimmed && opacity === 1 : dimmed && Math.abs(opacity - 0.38) < 1e-9;
    });
}

// Check one theme's legend, table-row, keyboard, override, independence, and border behavior.
function checkMapFocusTheme(themeName) {
    const placeFocus = 'dense and diverse';
    const hotspotFocus = 'high-high';
    const focusExpected = auditExpected.map_focus;
    window.vibrancy.clearCategoryFocus();
    window.vibrancy.setLayer('place_types');

    const placeButton = categoryLegendButton(placeFocus);
    placeButton.click();
    auditResults['placeLegendFocus-' + themeName] =
        categoryStylesMatch('place_types', themeName, placeFocus);
    const placeNote = document.getElementById('focus-line');
    const placeNoteMatches = !placeNote.hidden &&
        placeNote.textContent === 'Showing: dense and diverse only. Click again to show all four.';
    const placeDimMatches = legendDimMatches(placeFocus, 4);
    categoryLegendButton(placeFocus).click();
    auditResults['placeLegendRestore-' + themeName] =
        categoryStylesMatch('place_types', themeName, null);

    const placeRow = [...document.querySelectorAll('.type-row')].find(row => {
        return row.dataset.placeType === placeFocus;
    });
    placeRow.click();
    auditResults['placeTableFocus-' + themeName] =
        categoryStylesMatch('place_types', themeName, placeFocus) &&
        placeRow.getAttribute('aria-pressed') === 'true';
    placeRow.click();
    auditResults['placeTableRestore-' + themeName] =
        categoryStylesMatch('place_types', themeName, null);

    window.vibrancy.setLayer('hotspots');
    categoryLegendButton(hotspotFocus).click();
    auditResults['hotspotLegendFocus-' + themeName] =
        categoryStylesMatch('hotspots', themeName, hotspotFocus);
    const hotspotNote = document.getElementById('focus-line');
    const hotspotNoteMatches = !hotspotNote.hidden &&
        hotspotNote.textContent === 'Showing: High-high only. Click again to show all five.';
    const hotspotDimMatches = legendDimMatches(hotspotFocus, 5);
    categoryLegendButton(hotspotFocus).click();
    auditResults['hotspotLegendRestore-' + themeName] =
        categoryStylesMatch('hotspots', themeName, null);
    auditResults['focusLegendDim-' + themeName] = placeDimMatches && hotspotDimMatches;
    auditResults['focusNote-' + themeName] = placeNoteMatches && hotspotNoteMatches;

    window.vibrancy.setLayer('place_types');
    const keyboardPlaceButton = categoryLegendButton(placeFocus);
    const placeButtonsReachable = [...document.querySelectorAll('#legend .legend-choice')].every(button => {
        return button.tagName === 'BUTTON' && button.tabIndex === 0;
    });
    keyboardPlaceButton.focus();
    keyboardPlaceButton.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    const enterWorked = window.vibrancy.focusState().placeType === placeFocus;
    window.vibrancy.clearCategoryFocus();

    window.vibrancy.setLayer('hotspots');
    const keyboardHotspotButton = categoryLegendButton(hotspotFocus);
    const hotspotButtonsReachable = [...document.querySelectorAll('#legend .legend-choice')].every(button => {
        return button.tagName === 'BUTTON' && button.tabIndex === 0;
    });
    keyboardHotspotButton.focus();
    keyboardHotspotButton.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true}));
    const spaceWorked = window.vibrancy.focusState().hotspot === hotspotFocus;
    auditResults['focusLegendKeyboard-' + themeName] =
        placeButtonsReachable && hotspotButtonsReachable && enterWorked && spaceWorked;
    window.vibrancy.clearCategoryFocus();

    window.vibrancy.setLayer('place_types');
    const keyboardRow = [...document.querySelectorAll('.type-row')].find(row => {
        return row.dataset.placeType === placeFocus;
    });
    keyboardRow.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    const rowEnterWorked = window.vibrancy.focusState().placeType === placeFocus;
    keyboardRow.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', bubbles: true}));
    const rowSpaceWorked = window.vibrancy.focusState().placeType === null;
    auditResults['typeRowKeyboard-' + themeName] =
        keyboardRow.tabIndex === 0 && keyboardRow.getAttribute('role') === 'button' &&
        rowEnterWorked && rowSpaceWorked;

    window.vibrancy.toggleCategoryFocus('place_types', placeFocus);
    window.vibrancy.toggleCategoryFocus('hotspots', hotspotFocus);
    const pending = window.vibrancy.focusState();
    const otherLayersStayFull = ['overall', 'intensity', 'diversity', 'design'].every(layerName => {
        window.vibrancy.setLayer(layerName);
        return auditData.geo.features.filter(feature => feature.properties.scored).every(feature => {
            const style = window.vibrancy.mapStyle(feature.properties.id);
            return Math.abs(style.fillOpacity - focusExpected.full_opacity) < 1e-9 &&
                !colourMatches(style.fillColor, focusExpected.themes[themeName].fade);
        });
    });
    window.vibrancy.setLayer('place_types');
    const placeFocusWaited = categoryStylesMatch('place_types', themeName, placeFocus);
    window.vibrancy.setLayer('hotspots');
    const hotspotFocusWaited = categoryStylesMatch('hotspots', themeName, hotspotFocus);
    auditResults['independentFocus-' + themeName] =
        pending.placeType === placeFocus && pending.hotspot === hotspotFocus &&
        placeFocusWaited && hotspotFocusWaited && otherLayersStayFull;
    window.vibrancy.clearCategoryFocus();

    window.vibrancy.toggleCategoryFocus('place_types', placeFocus);
    const placeTarget = categoryRepresentatives('place_types').find(item => item.category !== placeFocus);
    window.vibrancy.select(placeTarget.feature.properties.id);
    let targetStyle = window.vibrancy.mapStyle(placeTarget.feature.properties.id);
    const chosenPlace = colourMatches(
        targetStyle.fillColor,
        expectedCategoryColour('place_types', themeName, placeTarget.category)
    ) && targetStyle.fillOpacity === focusExpected.full_opacity &&
        targetStyle.weight === 3 &&
        colourMatches(targetStyle.color, focusExpected.themes[themeName].chosen);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    window.vibrancy.highlight(placeTarget.feature.properties.id, true);
    targetStyle = window.vibrancy.mapStyle(placeTarget.feature.properties.id);
    const highlightedPlace = colourMatches(
        targetStyle.fillColor,
        expectedCategoryColour('place_types', themeName, placeTarget.category)
    ) && targetStyle.fillOpacity === focusExpected.full_opacity &&
        targetStyle.weight === 2 &&
        colourMatches(targetStyle.color, expectedCategoryColour('place_types', themeName, placeTarget.category));
    window.vibrancy.highlight(placeTarget.feature.properties.id, false);
    window.vibrancy.clearCategoryFocus();

    window.vibrancy.toggleCategoryFocus('hotspots', hotspotFocus);
    const hotspotTarget = categoryRepresentatives('hotspots').find(item => item.category !== hotspotFocus);
    window.vibrancy.select(hotspotTarget.feature.properties.id);
    targetStyle = window.vibrancy.mapStyle(hotspotTarget.feature.properties.id);
    const chosenHotspot = colourMatches(
        targetStyle.fillColor,
        expectedCategoryColour('hotspots', themeName, hotspotTarget.category)
    ) && targetStyle.fillOpacity === focusExpected.full_opacity &&
        targetStyle.weight === 3 &&
        colourMatches(targetStyle.color, focusExpected.themes[themeName].chosen);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    window.vibrancy.highlight(hotspotTarget.feature.properties.id, true);
    targetStyle = window.vibrancy.mapStyle(hotspotTarget.feature.properties.id);
    const highlightedHotspot = colourMatches(
        targetStyle.fillColor,
        expectedCategoryColour('hotspots', themeName, hotspotTarget.category)
    ) && targetStyle.fillOpacity === focusExpected.full_opacity &&
        targetStyle.weight === 2 &&
        colourMatches(
            targetStyle.color,
            auditExpected.colours.themes[themeName].place[hotspotTarget.feature.properties.place_type]
        );
    window.vibrancy.highlight(hotspotTarget.feature.properties.id, false);
    window.vibrancy.clearCategoryFocus();
    auditResults['focusOverrides-' + themeName] =
        chosenPlace && highlightedPlace && chosenHotspot && highlightedHotspot;

    window.vibrancy.setLayer('overall');
    const borderStyles = auditData.geo.features.map(feature => {
        return window.vibrancy.mapStyle(feature.properties.id);
    });
    auditResults['mapBorders-' + themeName] = borderStyles.every(style => {
        return style.weight === focusExpected.border_weight &&
            colourMatches(style.color, focusExpected.themes[themeName].border) &&
            !colourMatches(style.color, focusExpected.themes[themeName].surface) &&
            !style.dashArray;
    });
}

// Check the chosen SA2's ring colour and halo, including the hollow not-scored case (Centennial Park).
function checkChosenRing(themeName) {
    const focusExpected = auditExpected.map_focus;
    window.vibrancy.setLayer('overall');
    const known = featureNamed(auditExpected.colours.known_name);
    window.vibrancy.select(known.properties.id);
    const knownStyle = window.vibrancy.mapStyle(known.properties.id);
    const knownHalo = document.querySelector('.chosen-halo');
    auditResults['chosenRingColour-' + themeName] =
        colourMatches(knownStyle.color, focusExpected.themes[themeName].chosen) && knownStyle.weight === 3;
    auditResults['chosenRingHalo-' + themeName] =
        knownHalo !== null && getComputedStyle(knownHalo).filter !== 'none';
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));

    window.vibrancy.select(centennialPark.properties.id);
    const centennialStyle = window.vibrancy.mapStyle(centennialPark.properties.id);
    const centennialHalo = document.querySelector('.chosen-halo');
    auditResults['chosenRingCentennialPark-' + themeName] =
        colourMatches(centennialStyle.color, focusExpected.themes[themeName].chosen) &&
        centennialStyle.weight === 3 && centennialStyle.fillOpacity === 0 &&
        centennialHalo !== null && getComputedStyle(centennialHalo).filter !== 'none';
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
}

// Return the legend swatch button for one quintile of the score layer currently shown.
function quintileLegendButton(quintile) {
    return [...document.querySelectorAll('#legend .legend-choice')].find(button => {
        return Number(button.dataset.focusCategory) === quintile;
    });
}

// Return the independently expected true colour of one quintile on a score layer: the Overall
// layer's own ramp, or the given pillar's own ramp (both already builder-derived, not the page's).
function expectedQuintileColour(layerName, themeName, quintile) {
    if (layerName === 'overall') {
        return auditExpected.quintile_ramp[themeName][quintile];
    }
    return auditExpected.colours.themes[themeName].pillar[layerName].ramp[quintile];
}

// Return one SA2's quintile on a score layer, independently: the Overall layer uses the SA2's
// own saved quintile, a pillar layer uses that pillar's own saved ranking.
function expectedLayerQuintile(layerName, name) {
    return layerName === 'overall' ? auditExpected.quintiles[name] : auditExpected.pillar_quintiles[layerName][name];
}

// Return one representative feature for each quintile of a score layer, for checking legend fills.
function quintileRepresentatives(layerName) {
    const seen = {};
    auditData.geo.features.filter(feature => feature.properties.scored).forEach(feature => {
        const quintile = expectedLayerQuintile(layerName, feature.properties.name);
        if (quintile === undefined || quintile in seen) {
            return;
        }
        seen[quintile] = feature;
    });
    return Object.entries(seen).map(([quintile, feature]) => ({quintile: Number(quintile), feature}));
}

// Check rendered quintile fills on a score layer against independently computed true colours and
// the audit's fixed fade settings: the categoryStylesMatch counterpart for a numeric quintile
// category instead of a place-type or hot-spot name.
function quintileStylesMatch(layerName, themeName, focusedQuintile) {
    const expected = auditExpected.map_focus;
    return quintileRepresentatives(layerName).every(item => {
        const style = window.vibrancy.mapStyle(item.feature.properties.id);
        const faded = focusedQuintile !== null && item.quintile !== focusedQuintile;
        const expectedColourValue = faded
            ? expected.themes[themeName].fade
            : expectedQuintileColour(layerName, themeName, item.quintile);
        const expectedOpacity = faded ? expected.fade_opacity : expected.full_opacity;
        return colourMatches(style.fillColor, expectedColourValue) &&
            Math.abs(style.fillOpacity - expectedOpacity) < 1e-9;
    });
}

// Check the click-to-focus mechanism on the Overall layer and each pillar layer: each legend
// swatch colours exactly its own quintile (computed independently, as above) and fades the rest;
// switching layers clears the focus; a chosen or highlighted SA2 still shows true colour and its
// ring even while its own quintile is not the one focused.
function checkScoreLayerQuintileFocus(themeName) {
    ['overall', 'intensity', 'diversity', 'design'].forEach(layerName => {
        window.vibrancy.setLayer(layerName);
        let everyQuintileOk = true;
        for (let quintile = 0; quintile < 5; quintile += 1) {
            quintileLegendButton(quintile).click();
            everyQuintileOk = everyQuintileOk && quintileStylesMatch(layerName, themeName, quintile);
            quintileLegendButton(quintile).click();
        }
        auditResults[layerName + 'QuintileFocus-' + themeName] =
            everyQuintileOk && quintileStylesMatch(layerName, themeName, null);
    });

    window.vibrancy.setLayer('overall');
    quintileLegendButton(4).click();
    const switchedAway = window.vibrancy.focusState().quintile === 4;
    window.vibrancy.setLayer('intensity');
    auditResults['quintileFocusClearsOnLayerSwitch-' + themeName] =
        switchedAway && window.vibrancy.focusState().quintile === null;

    window.vibrancy.setLayer('overall');
    quintileLegendButton(4).click();
    const target = quintileRepresentatives('overall').find(item => item.quintile !== 4);
    window.vibrancy.select(target.feature.properties.id);
    let targetStyle = window.vibrancy.mapStyle(target.feature.properties.id);
    const targetColour = expectedQuintileColour('overall', themeName, target.quintile);
    const chosenOk = colourMatches(targetStyle.fillColor, targetColour) &&
        targetStyle.fillOpacity === auditExpected.map_focus.full_opacity && targetStyle.weight === 3 &&
        colourMatches(targetStyle.color, auditExpected.map_focus.themes[themeName].chosen);
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    window.vibrancy.highlight(target.feature.properties.id, true);
    targetStyle = window.vibrancy.mapStyle(target.feature.properties.id);
    const highlightedOk = colourMatches(targetStyle.fillColor, targetColour) &&
        targetStyle.fillOpacity === auditExpected.map_focus.full_opacity && targetStyle.weight === 2;
    window.vibrancy.highlight(target.feature.properties.id, false);
    auditResults['quintileFocusOverrides-' + themeName] = chosenOk && highlightedOk;
    window.vibrancy.clearCategoryFocus();
}

// Check focus behavior in both themes and leave the map in a clean copy of its starting state.
function checkMapFocus() {
    const startingTheme = currentThemeName();
    ['light', 'dark'].forEach(themeName => {
        switchTheme(themeName);
        checkMapFocusTheme(themeName);
        checkChosenRing(themeName);
        checkScoreLayerQuintileFocus(themeName);
    });
    auditResults.outlinesRemoved = document.getElementById('outlines') === null;
    window.vibrancy.clearCategoryFocus();
    switchTheme(startingTheme);
    window.vibrancy.setLayer('overall');
}

// Check the layer button, the legend, and the fills in both themes.
function checkHotspotLayer() {
    const buttons = [...document.querySelectorAll('.layer')].map(button => button.textContent);
    auditResults.hotspotButton = buttons.length === 6 && buttons[4] === 'Place types' && buttons[5] === 'Hot spots' &&
        document.querySelector('.layer[data-layer=hotspots]') !== null;
    window.vibrancy.setLayer('hotspots');
    const legendItems = [...document.querySelectorAll('#legend .legend-item')].map(item => item.textContent);
    auditResults.hotspotLegend = JSON.stringify(legendItems) === JSON.stringify(hotspotExpected.legend);
    const startTheme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    const otherTheme = startTheme === 'dark' ? 'light' : 'dark';
    auditResults.hotspotFills = hotspotFillsMatch(startTheme);
    switchTheme(otherTheme);
    window.vibrancy.setLayer('hotspots');
    auditResults.hotspotFillsAfterThemeSwitch = hotspotFillsMatch(otherTheme);
    switchTheme(startTheme);
    window.vibrancy.setLayer('overall');
}

// Check the tooltip and the profile card of two SA2s on the Hot spots layer, and scan for broken text.
function checkHotspotTooltipsAndCards() {
    window.vibrancy.setLayer('hotspots');
    const scanned = [document.getElementById('legend').textContent];
    Object.keys(hotspotExpected.tooltips).forEach(name => {
        const id = featureNamed(name).properties.id;
        const lines = window.vibrancy.tooltipLines(id);
        const expectedLines = hotspotExpected.tooltips[name];
        auditResults['hotspotTooltip-' + name] = JSON.stringify(lines) === JSON.stringify(expectedLines);
        window.vibrancy.select(id);
        const cardLines = profile.innerText.split('\n').map(line => line.trim());
        auditResults['hotspotCard-' + name] = hotspotExpected.card_lines[name].every(line => cardLines.includes(line));
        scanned.push(lines.join('\n'), profile.innerText);
    });
    auditResults.cleanTextHotspots = scanned.every(text => !/NaN|undefined|Infinity/.test(text));
    window.vibrancy.setLayer('overall');
}

// Return a function that turns a pixel position into a value, from the first and last tick labels of one axis.
function scaleFromTicks(labels, pixelOf) {
    const first = labels[0];
    const last = labels[labels.length - 1];
    const slope = (Number(last.textContent) - Number(first.textContent)) / (pixelOf(last) - pixelOf(first));
    return pixel => Number(first.textContent) + (pixel - pixelOf(first)) * slope;
}

// Check the Moran scatterplot's dots, colours, quadrants, note, and the slope of its line.
function checkMoranChart() {
    const chart = document.getElementById('moran-chart');
    const dots = [...chart.querySelectorAll('circle.mark')];
    const themeName = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    const quadrantLines = [...chart.querySelectorAll('line.quadrant')].map(line => ({
        x1: Number(line.getAttribute('x1')), x2: Number(line.getAttribute('x2')),
        y1: Number(line.getAttribute('y1')), y2: Number(line.getAttribute('y2')),
    }));
    const verticalX = quadrantLines.find(line => line.x1 === line.x2).x1;
    const horizontalY = quadrantLines.find(line => line.y1 === line.y2).y1;
    auditResults.moranDotCount = dots.length === hotspotExpected.dots;
    auditResults.moranColours = dots.every(dot => {
        const className = hotspotExpected.class_by_code[dot.dataset.code];
        return dot.getAttribute('fill').toLowerCase() === expectedClusterColour(themeName, className);
    });
    const rightOfLine = dot => Number(dot.getAttribute('cx')) >= verticalX;
    const aboveLine = dot => Number(dot.getAttribute('cy')) < horizontalY;
    const quadrants = {
        'high-high': dot => rightOfLine(dot) && aboveLine(dot), 'low-low': dot => !rightOfLine(dot) && !aboveLine(dot),
        'high-low': dot => rightOfLine(dot) && !aboveLine(dot), 'low-high': dot => !rightOfLine(dot) && aboveLine(dot),
    };
    auditResults.moranQuadrants = dots.every(dot => {
        const className = hotspotExpected.class_by_code[dot.dataset.code];
        return className === 'not significant' || quadrants[className](dot);
    });
    const note = document.getElementById('moran-axis-note');
    auditResults.moranAxisNote = note.textContent === hotspotExpected.axis_note &&
        note.hidden === (hotspotExpected.axis_note === '');
    const line = chart.querySelector('line.ref');
    const toX = scaleFromTicks([...chart.querySelectorAll('text.tick-x')], label => Number(label.getAttribute('x')));
    const yLabels = [...chart.querySelectorAll('text.tick-y')];
    const toY = scaleFromTicks(yLabels, label => Number(label.getAttribute('y')) - 4);
    const drawnSlope = (toY(Number(line.getAttribute('y2'))) - toY(Number(line.getAttribute('y1')))) /
        (toX(Number(line.getAttribute('x2'))) - toX(Number(line.getAttribute('x1'))));
    auditResults.moranSlope = drawnSlope.toFixed(3) === hotspotExpected.global_i.toFixed(3) &&
        hotspotExpected.global_i.toFixed(3) === '0.548' &&
        Math.abs(hotspotExpected.recomputed_slope - hotspotExpected.global_i) < 1e-9;
    auditResults.moranSlopeLabel = [...chart.querySelectorAll('text')].some(label => {
        return label.textContent === 'slope ' + hotspotExpected.global_i.toFixed(2) + " (Moran's I)";
    });
    auditResults.moranSlopeDetails = drawnSlope.toFixed(4);
}

// Check hovering a dot highlights its SA2 on the map without changing the layer, and a click opens its card.
function checkMoranInteraction() {
    const chart = document.getElementById('moran-chart');
    const darlinghurst = featureNamed('Darlinghurst').properties;
    const dot = chart.querySelector('circle.mark[data-code="' + darlinghurst.id + '"]');
    const layerBefore = document.querySelector('.layer[aria-pressed=true]').dataset.layer;
    dot.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    const highlighted = window.vibrancy.outlineWeight(darlinghurst.id) >= 2;
    dot.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
    dot.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    const layerAfter = document.querySelector('.layer[aria-pressed=true]').dataset.layer;
    auditResults.moranHoverAndClick = highlighted && layerBefore === layerAfter && !profile.hidden &&
        profile.textContent.includes('Darlinghurst');
}

// Check the card's question, title, and text, the drawer note, and that the card stacks on a phone.
function checkMoranCard() {
    const card = document.querySelector('.moran-card');
    const text = hotspotExpected.text;
    auditResults.moranCardText = card.querySelector('.kicker').textContent === 'Do neighbouring SA2s score alike?' &&
        card.querySelector('.moran-title').textContent === text.title &&
        JSON.stringify([...card.querySelectorAll('.moran-text p')].map(item => item.textContent)) ===
        JSON.stringify(text.paragraphs);
    const columns = getComputedStyle(card.querySelector('.moran-body')).gridTemplateColumns.split(' ').length;
    auditResults.moranCardLayout = columns === (innerWidth <= 900 ? 1 : 2);
    const drawerNote = document.querySelector('#what-if .source').textContent;
    auditResults.drawerNoteMentionsHotSpots = drawerNote ===
        'Weights affect Overall score only. Pillar layers, place types and hot spots remain based on the baseline.';
    auditResults.cleanTextMoran = !/NaN|undefined|Infinity/.test(card.innerText);
}

// Run all the checks of the hot-spot layer and the Moran card.
function checkHotspots() {
    checkHotspotLayer();
    checkHotspotTooltipsAndCards();
    checkMoranChart();
    checkMoranInteraction();
    checkMoranCard();
    window.vibrancy.setBaseline();
}


// Return the active theme name and a browser-normalised colour.
function currentThemeName() {
    return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

function rgbColour(hexColour) {
    const channels = [1, 3, 5].map(start => parseInt(hexColour.slice(start, start + 2), 16));
    return 'rgb(' + channels.join(', ') + ')';
}

// Compare a computed/browser colour with a builder hexadecimal value.
function colourMatches(actual, expected) {
    return actual.toLowerCase() === expected.toLowerCase() || actual === rgbColour(expected);
}

// Check all three rows in one place or profile card.
function pillarRowsMatch(container, themeName) {
    const expected = auditExpected.colours.themes[themeName].pillar;
    return pillarNames.every(name => {
        const row = container.querySelector('.pillar[data-pillar="' + name + '"]');
        if (!row) {
            return false;
        }
        const label = row.querySelector(':scope > span');
        const value = row.querySelector(':scope > b');
        const marker = row.querySelector('.bar i');
        const textMatches = colourMatches(getComputedStyle(label).color, expected[name].text) &&
            colourMatches(getComputedStyle(value).color, expected[name].text);
        return textMatches && (!marker ||
            colourMatches(getComputedStyle(marker).backgroundColor, expected[name].bar));
    });
}

// Check known fills on every pillar layer and one representative of every place type.
function colourMapFillsMatch(themeName) {
    const known = featureNamed(auditExpected.colours.known_name);
    const pillarLayers = ['intensity', 'diversity', 'design'];
    const pillarsMatch = pillarLayers.every(name => {
        window.vibrancy.setLayer(name);
        return colourMatches(window.vibrancy.mapFill(known.properties.id), expectedColour(name, themeName));
    });
    window.vibrancy.setLayer('place_types');
    const placeMatches = Object.entries(auditExpected.colours.place_representatives).every(([placeType, name]) => {
        const feature = featureNamed(name);
        const fill = window.vibrancy.mapFill(feature.properties.id);
        return colourMatches(fill, auditExpected.colours.themes[themeName].place[placeType]);
    });
    window.vibrancy.setLayer('overall');
    const overallMatches = colourMatches(
        window.vibrancy.mapFill(known.properties.id),
        expectedColour('overall', themeName)
    );
    return {pillarsMatch, placeMatches, overallMatches};
}

// Check place-type chips and table swatches against builder-derived values.
function placeComponentsMatch(themeName) {
    const expectedBackground = auditExpected.colours.themes[themeName].place;
    const expectedText = auditExpected.colours.themes[themeName].place_text;
    const cards = [...document.querySelectorAll('.place-card[data-place-type]')];
    const cardChips = cards.every(card => {
        const colour = getComputedStyle(card.querySelector('.type-chip')).backgroundColor;
        return colourMatches(colour, expectedBackground[card.dataset.placeType]);
    });
    const rows = [...document.querySelectorAll('.type-row[data-place-type]')];
    const rowSwatches = rows.every(row => {
        const colour = getComputedStyle(row.querySelector('.type-swatch')).backgroundColor;
        return colourMatches(colour, expectedBackground[row.dataset.placeType]);
    });
    const profiles = Object.entries(auditExpected.colours.place_representatives).every(([placeType, name]) => {
        const feature = featureNamed(name);
        window.vibrancy.select(feature.properties.id);
        const wrapper = profile.querySelector('.type-' + placeClass(placeType));
        const chip = wrapper ? wrapper.querySelector(':scope > .type-chip') : null;
        if (!chip) {
            return false;
        }
        const style = getComputedStyle(chip);
        return colourMatches(style.backgroundColor, expectedBackground[placeType]) &&
            colourMatches(style.color, expectedText[placeType]);
    });
    window.vibrancy.select(centennialPark.properties.id);
    const notScoredHasNoChip = profile.querySelector('.type-chip') === null;
    return {
        cardsAndRows: cardChips && rowSwatches,
        profiles: profiles && notScoredHasNoChip,
    };
}

// Check the four fixed cards, the selected profile, and a rendered tooltip.
function pillarCardsAndTooltipMatch(themeName) {
    const cards = [...document.querySelectorAll('.place-card')];
    const cardsMatch = cards.length === 4 && cards.every(card => pillarRowsMatch(card, themeName));
    const known = featureNamed(auditExpected.colours.known_name);
    window.vibrancy.select(known.properties.id);
    const profileMatches = !profile.hidden && pillarRowsMatch(profile, themeName);
    const tooltipBox = document.createElement('div');
    tooltipBox.innerHTML = window.vibrancyTooltip(known.properties);
    document.body.append(tooltipBox);
    const expected = auditExpected.colours.themes[themeName].pillar;
    const tooltipMatches = pillarNames.every(name => {
        const item = tooltipBox.querySelector('.' + name + '-text');
        return item && colourMatches(getComputedStyle(item).color, expected[name].text);
    });
    tooltipBox.remove();
    return {cardsMatch, profileMatches, tooltipMatches};
}

// Check sliders, layer dots, panel-two buttons, Methods names, and chart axis words.
function pillarControlsAndTextMatch(themeName) {
    const expected = auditExpected.colours.themes[themeName].pillar;
    const sliders = pillarNames.every(name => {
        const label = document.querySelector('.drawer label[data-pillar="' + name + '"]');
        const input = label.querySelector('input');
        return colourMatches(getComputedStyle(label).color, expected[name].text) &&
            colourMatches(getComputedStyle(input).accentColor, expected[name].bar);
    });
    const dots = pillarNames.every(name => {
        const dot = document.querySelector('.layer.pillar-button.' + name + ' .layer-dot');
        return colourMatches(getComputedStyle(dot).backgroundColor, expected[name].bar);
    });
    const jumpButtons = pillarNames.every(name => {
        const button = document.querySelector('.jump-layer.' + name);
        return colourMatches(getComputedStyle(button).color, expected[name].text);
    });
    const methods = pillarNames.every(name => {
        const text = document.querySelector('#methods-detail .' + name + '-text');
        return text && colourMatches(getComputedStyle(text).color, expected[name].text);
    });
    const axisWords = pillarNames.every(name => {
        const words = [...document.querySelectorAll('.chart .' + name + '-title')];
        return words.length > 0 &&
            words.every(word => colourMatches(getComputedStyle(word).fill, expected[name].text));
    });
    return {sliders, dots, jumpButtons, methods, axisWords};
}

// Return whether an element is one of the approved consumers of a pillar colour.
function allowedPillarConsumer(element) {
    return Boolean(
        element.closest('.pillar[data-pillar], .drawer [data-pillar], [class*="type-"], [class*="place-"], ' +
            '.intensity-title, .diversity-title, .design-title') ||
        element.matches('.pillar-text, .layer-dot, .jump-layer, .intensity-title, .diversity-title, .design-title')
    );
}

// Scan computed chart marks, buttons, and text for pillar colours outside the approved elements.
function unexpectedPillarColours(themeName) {
    const pillar = auditExpected.colours.themes[themeName].pillar;
    const expected = new Set();
    Object.values(pillar).forEach(palette => {
        [...palette.ramp, palette.text, palette.bar].forEach(colour => expected.add(rgbColour(colour)));
    });
    const selector = '.chart *, button, p, h1, h2, h3, th, td, label, span, b, i, input';
    const properties = ['color', 'backgroundColor', 'fill', 'stroke', 'accentColor'];
    const offenders = [];
    document.querySelectorAll(selector).forEach(element => {
        properties.forEach(property => {
            const value = getComputedStyle(element)[property];
            if (expected.has(value) && !allowedPillarConsumer(element)) {
                offenders.push(element.tagName + '.' + element.className + ':' + property + ':' + value);
            }
        });
    });
    return [...new Set(offenders)];
}

// Check the contrast of every element whose text deliberately carries a pillar role.
function pillarTextContrast(themeName) {
    const surface = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();
    const selector = [
        '.pillar[data-pillar] > span',
        '.pillar[data-pillar] > b',
        '.pillar-text',
        '.drawer label[data-pillar]',
        '.jump-layer',
        '.chart .intensity-title',
        '.chart .diversity-title',
        '.chart .design-title',
    ].join(',');
    return [...document.querySelectorAll(selector)].every(element => {
        const style = getComputedStyle(element);
        const colour = element instanceof SVGElement ? style.fill : style.color;
        return contrastRatio(colour, surface) >= 4.5;
    });
}

// Scan chip- and swatch-like descendant selectors and prove that each one has a rendered matching structure.
function descendantChipStructures() {
    const pattern = /\.([A-Za-z0-9_-]+)\s+\.((?:pillar-text|[A-Za-z0-9_-]+-(?:chip|swatch)))\b/g;
    const selectors = new Set();
    function readRules(rules) {
        [...rules].forEach(rule => {
            if (rule.selectorText) {
                [...rule.selectorText.matchAll(pattern)].forEach(match => {
                    selectors.add('.' + match[1] + ' .' + match[2]);
                });
            }
            if (rule.cssRules) {
                readRules(rule.cssRules);
            }
        });
    }
    [...document.styleSheets].forEach(sheet => {
        try {
            readRules(sheet.cssRules);
        } catch (error) {
            if (error.name !== 'SecurityError') {
                throw error;
            }
        }
    });
    const details = [...selectors].sort().map(selector => ({
        selector,
        rendered: document.querySelector(selector) !== null,
    }));
    return {details, matches: details.length > 0 && details.every(item => item.rendered)};
}

// Run the complete colour audit in both themes and restore the starting theme.
function checkColourSystem() {
    const startingTheme = currentThemeName();
    const scan = {};
    ['light', 'dark'].forEach(themeName => {
        switchTheme(themeName);
        const fills = colourMapFillsMatch(themeName);
        const cards = pillarCardsAndTooltipMatch(themeName);
        const controls = pillarControlsAndTextMatch(themeName);
        const placeComponents = placeComponentsMatch(themeName);
        const offenders = unexpectedPillarColours(themeName);
        auditResults['pillarLayerColours-' + themeName] = fills.pillarsMatch && fills.overallMatches;
        auditResults['placeTypeColours-' + themeName] = fills.placeMatches && placeComponents.cardsAndRows;
        auditResults['profilePlaceTypeColours-' + themeName] = placeComponents.profiles;
        auditResults['pillarCardColours-' + themeName] =
            cards.cardsMatch && cards.profileMatches && cards.tooltipMatches;
        auditResults['pillarSliderColours-' + themeName] = controls.sliders;
        auditResults['pillarButtonColours-' + themeName] = controls.dots && controls.jumpButtons;
        auditResults['pillarTextColours-' + themeName] = controls.methods && controls.axisWords;
        auditResults['pillarTextContrast-' + themeName] = pillarTextContrast(themeName);
        auditResults['pillarColourScope-' + themeName] = offenders.length === 0;
        scan[themeName] = offenders;
    });
    auditResults.pillarColourScan = scan;
    const structures = descendantChipStructures();
    auditResults.descendantChipStructures = structures.matches;
    auditResults.descendantChipSelectors = structures.details;
    switchTheme(startingTheme);
    window.vibrancy.setLayer('overall');
}
// Run every browser check and put concise Boolean values in the result object.
function runAudit() {
    checkInitialSliders();
    checkColourSystem();
    checkMapFocus();
    auditResults.rows = document.querySelectorAll('#rows tr').length === 372;
    auditResults.kpis = document.querySelectorAll('.kpi').length === 4;
    const mapHeight = mapElement.getBoundingClientRect().height;
    auditResults.mapHeight = innerWidth >= 1000 ? mapHeight >= 600 : mapHeight >= 400;
    auditResults.legends = legendsMatch();
    window.vibrancy.setLayer('overall');
    const overallFill = window.vibrancy.mapFill(darlinghurst.properties.id);
    window.vibrancy.setLayer('intensity');
    const intensityFill = window.vibrancy.mapFill(darlinghurst.properties.id);
    auditResults.layerFill = overallFill === expectedColour('overall') &&
        intensityFill === expectedColour('intensity');
    window.vibrancy.select(darlinghurst.properties.id);
    auditResults.darlingProfile = !profile.hidden && profile.textContent.includes('Score 124.9') &&
        profile.textContent.includes('Rank 1 of 372');
    window.vibrancy.select(centennialPark.properties.id);
    auditResults.centennialProfile = !profile.hidden && profile.textContent.includes('Not scored');
    window.vibrancy.search('Darlinghurst');
    auditResults.search = !profile.hidden && profile.textContent.includes('Darlinghurst');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    auditResults.escape = profile.hidden;
    window.vibrancy.sortTable('score', 'desc');
    const descending = document.querySelector('#rows tr').cells[2].textContent;
    window.vibrancy.sortTable('score', 'asc');
    const ascending = document.querySelector('#rows tr').cells[2].textContent;
    auditResults.sorting = descending === 'Darlinghurst' && ascending === 'Sydney Airport';
    window.vibrancy.sortTable('score', 'desc');
    const csvLines = window.vibrancy.csv().split('\n');
    auditResults.csv = csvLines.length === 373 && csvLines[1].includes('Darlinghurst');
    const filter = document.getElementById('filter');
    filter.value = 'Darling';
    filter.dispatchEvent(new Event('input', { bubbles: true }));
    auditResults.tableSearch = document.querySelectorAll('#rows tr').length === 3;
    filter.value = '';
    filter.dispatchEvent(new Event('input', { bubbles: true }));
    const cards = [...document.querySelectorAll('.place-card')];
    const rows = new Set(cards.map(card => Math.round(card.getBoundingClientRect().top))).size;
    auditResults.wideCards = innerWidth < 1000 || rows === 1;
    auditResults.phoneCards = innerWidth >= 1000 || rows === cards.length;
    const band = document.querySelector('[data-band-order]');
    auditResults.bandOrder = Boolean(band) && band.dataset.bandOrder ===
        'Top quintile (75 SA2s)|Second quintile (74 SA2s)|Middle quintile (75 SA2s)|' +
        'Fourth quintile (74 SA2s)|Bottom quintile (74 SA2s)';
    const counts = window.vibrancy.chartCounts();
    auditResults.charts = counts.beeswarm === 372 && counts.histogram === 30 &&
        counts.intensityDesign === 372 && counts.densityDiversity === 367 && counts.equity === 6 &&
        counts.stability === 5 && counts.weekday === 16 && counts.weekend === 16;
    const firstMark = document.querySelector('#distance-chart circle.mark');
    firstMark.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    auditResults.chartHighlight = window.vibrancy.outlineWeight(darlinghurst.properties.id) >= 2;
    firstMark.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    auditResults.chartClick = !profile.hidden;
    auditResults.equalWeights = equalWeightsMatch();
    auditResults.intensityOnly = intensityOnlyMatch();
    auditResults.variantRanks = variantRanksMatch();
    const sensitivity = auditData.sensitivity.find(row => row.variant === 'Equal per indicator');
    const summary = document.getElementById('variant-summary').textContent;
    auditResults.variantSummary = summary.includes(
        Number(sensitivity.spearman_rank_correlation).toFixed(2)
    ) && summary.includes(String(sensitivity.top_25_overlap));
    auditResults.variantState = document.getElementById('state-line').textContent ===
        'Showing: check: Equal per indicator';
    window.vibrancy.setWeights([40, 20, 40]);
    auditResults.weightState = document.getElementById('state-line').textContent ===
        'Showing: your weights (Intensity 40%, Diversity 20%, Design 40%)';
    window.vibrancy.setBaseline();
    auditResults.baselineState = document.getElementById('state-line').textContent === 'Showing: baseline';
    checkTextStates('Parramatta - North', 'parramatta');
    checkTextStates('Sydney Airport', 'airport');
    auditResults.changedClassRank = changedClassShowsNewRank();
    auditResults.otherLayerTooltips = otherLayersMatch();
    checkWhatIfDrawer();
    checkCards();
    auditResults.horizontalScroll = innerWidth >= 1000 ||
        document.documentElement.scrollWidth <= innerWidth;
    const geometry = chartGeometry();
    auditResults.chartGeometry = geometry.every(result => result.inside && result.noOverlaps);
    auditResults.chartGeometryDetails = geometry;
    checkAllAxes();
    checkChartTextAndColours();
    checkEquityAndStabilityAxes();
    checkStabilityQuintiles();
    checkStabilityBarColours();
    checkChartTitleStyle();
    checkDistanceAxisNote();
    checkDistanceGroupLabels();
    checkDistanceTitle();
    checkDistanceFade();
    checkHistogramTitle();
    checkPanelTwoScatters();
    checkWalkingTitles();
    checkFootTrafficPanel();
    checkWalkingFade();
    checkAllChartQuintileFocus();
    auditResults.axisQuality = wholeTicks();
    auditResults.distanceLabels = distanceLabelsVisible();
    auditResults.footLabels = footLabelsFit('weekday') && footLabelsFit('weekend');
    const isDark = document.documentElement.dataset.theme === 'dark';
    const ramp = [0, 1, 2, 3, 4].map(index => {
        return getComputedStyle(document.documentElement).getPropertyValue('--c' + index).trim();
    });
    const neutrals = ['--chart-secondary'].map(name => {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    });
    const tints = ramp.map(colour => tint(colour, 0.5));
    const clusterColours = ['high-high', 'low-low', 'high-low', 'low-high', 'not-significant'].map(name => {
        return getComputedStyle(document.documentElement).getPropertyValue('--cluster-' + name).trim();
    });
    const fade = getComputedStyle(document.documentElement).getPropertyValue('--map-fade').trim();
    const fills = [...document.querySelectorAll('.chart circle, .chart rect')]
        .map(mark => mark.getAttribute('fill'))
        .filter(Boolean);
    const allowed = [...ramp, ...tints, ...neutrals, ...clusterColours, fade];
    auditResults.chartTheme = !isDark || fills.every(fill => allowed.includes(fill));
    if (isDark) {
        const surface = '#1a1a19';
        const contrasts = ramp.map(colour => contrastRatio(colour, surface));
        const neutralContrast = neutrals.map(colour => contrastRatio(colour, surface));
        auditResults.darkContrast = contrasts[2] >= 3 && contrasts[3] >= 3 && contrasts[4] >= 3 &&
            contrasts[0] >= 1.8 && contrasts[1] >= 1.8 && neutralContrast.every(value => value >= 3);
    } else {
        auditResults.darkContrast = true;
    }
    auditResults.histogramLayout = histogramFits();
    auditResults.cardBounds = cardsFit();
    auditResults.limits = limitsFit();
    checkRepeatedFacts();
    checkPanelSpacing();
    auditResults.darkBody = getComputedStyle(document.body).backgroundColor;
}

applyTheme();
runAudit();
const output = document.createElement('pre');
output.id = 'check-results';
output.textContent = JSON.stringify(auditResults);
document.body.appendChild(output);
