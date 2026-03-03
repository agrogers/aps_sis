/** @odoo-module **/

/**
 * Creates an SVG progress circle with segments and a center image.
 * 
 * @param {number} outerPercent - 0-100, the percentage for the outer ring
 * @param {string[]} segments - Array of hex color strings for inner segments (max 10)
 * @param {number} size - Overall size of the SVG
 * @param {string} outerColor - Hex color of the outer ring
 * @param {string} imageHref - URL of the center image
 * @returns {SVGElement} The constructed SVG element
 */
export function createProgressCircleSvg(
    outerPercent = 50,
    segments = [],
    size = 120,
    outerColor = '#0062d3',
    imageHref = ''
) {
    const processedSegments = segments.slice(0, 10);
    const numSegments = processedSegments.length;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const center = size / 2;
    const scale = size / 120;
    const outerR = 47 * scale;
    const innerR = 36 * scale;
    const iconR = 30 * scale;
    const outerStroke = 9 * scale;
    const innerStroke = 8 * scale;
    const circumference = 2 * Math.PI * outerR;

    // Set SVG attributes
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);

    // Create defs and clipPath
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const clipPath = document.createElementNS('http://www.w3.org/2000/svg', 'clipPath');
    const clipId = 'circleClip' + Date.now() + Math.random().toString(36).substr(2, 9);
    clipPath.setAttribute('id', clipId);
    const clipCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    clipCircle.setAttribute('cx', center);
    clipCircle.setAttribute('cy', center);
    clipCircle.setAttribute('r', iconR);
    clipPath.appendChild(clipCircle);
    defs.appendChild(clipPath);
    svg.appendChild(defs);

    // Create background circle
    const backgroundCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    backgroundCircle.setAttribute('cx', center);
    backgroundCircle.setAttribute('cy', center);
    backgroundCircle.setAttribute('r', outerR);
    backgroundCircle.setAttribute('fill', 'none');
    backgroundCircle.setAttribute('stroke', '#e6e6e6');
    backgroundCircle.setAttribute('stroke-width', outerStroke);
    svg.appendChild(backgroundCircle);

    // Create outer circle (progress) with CSS animation
    const targetOffset = circumference * (1 - outerPercent / 100);
    const outerCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    outerCircle.setAttribute('cx', center);
    outerCircle.setAttribute('cy', center);
    outerCircle.setAttribute('r', outerR);
    outerCircle.setAttribute('fill', 'none');
    outerCircle.setAttribute('stroke', outerColor);
    outerCircle.setAttribute('stroke-width', outerStroke);
    outerCircle.setAttribute('stroke-linecap', 'round');
    outerCircle.setAttribute('class', 'progress-circle-outer');
    outerCircle.style.setProperty('--circumference', circumference);
    outerCircle.style.setProperty('--target-offset', targetOffset);
    outerCircle.style.strokeDasharray = circumference;
    outerCircle.style.strokeDashoffset = circumference;
    outerCircle.style.transform = 'rotate(-90deg)';
    outerCircle.style.transformOrigin = `${center}px ${center}px`;
    svg.appendChild(outerCircle);

    // Create segments group
    const segmentsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    segmentsGroup.setAttribute('id', 'inner-segments');
    svg.appendChild(segmentsGroup);

    // Create image
    const image = document.createElementNS('http://www.w3.org/2000/svg', 'image');
    const imageSize = 60 * scale;
    image.setAttribute('x', center - imageSize / 2);
    image.setAttribute('y', center - imageSize / 2);
    image.setAttribute('width', imageSize);
    image.setAttribute('height', imageSize);
    image.setAttribute('href', imageHref);
    image.setAttribute('clip-path', `url(#${clipId})`);
    svg.appendChild(image);

    // ── Inner segments with CSS animations ───────────────────────────────────────
    const segAngle = (2 * Math.PI) / 10;     // 36° in radians (fixed size)
    const gapAngle = (2 * Math.PI) / 180; // 2 degrees in radians
    const visibleAngle = segAngle - 2 * gapAngle;
    const segmentCircumference = visibleAngle * innerR;

    for (let i = 0; i < numSegments; i++) {
        const startAngle = -Math.PI / 2 + i * segAngle + gapAngle;
        const endAngle = -Math.PI / 2 + (i + 1) * segAngle - gapAngle;

        const x1 = center + innerR * Math.cos(startAngle);
        const y1 = center + innerR * Math.sin(startAngle);
        const x2 = center + innerR * Math.cos(endAngle);
        const y2 = center + innerR * Math.sin(endAngle);

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute('d', `M ${x1} ${y1} A ${innerR} ${innerR} 0 0 1 ${x2} ${y2}`);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke-width', innerStroke);
        path.setAttribute('stroke-linecap', 'butt');
        path.setAttribute('stroke', processedSegments[i]);
        path.setAttribute('class', `progress-segment progress-segment-${i}`);
        path.style.setProperty('--segment-circumference', segmentCircumference);
        path.style.strokeDasharray = segmentCircumference;
        path.style.strokeDashoffset = segmentCircumference;
        segmentsGroup.appendChild(path);
    }

    return svg;
}
