/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ImageField } from "@web/views/fields/image/image_field";
import { onMounted, useRef } from "@odoo/owl";

export class ImageResultField extends ImageField {
    static template = "aps_sis.ImageResultField";

    setup() {
        super.setup();
        this.containerRef = useRef("svgContainer");
        onMounted(() => this.mountSvg());
    }

    mountSvg() {
        const container = this.containerRef.el;
        if (container) {
            container.innerHTML = '';
            const url = this.getUrl(this.props.name);
            const size = this.props.width || 120;
            const svg = updateProgressCircle(50, ['#2ecc71', '#e74c3c'], size, '#0264f7', url);
            container.appendChild(svg);
        }
    }

    get sizeStyle() {
        let style = "";
        if (this.props.width) {
            style += `width: ${this.props.width}px;`;
        }
        if (this.props.height) {
            style += `height: ${this.props.height}px;`;
        }
        return style;
    }

    get imgClass() {
        return "img";
    }
}

export const imageResultField = {
    component: ImageResultField,
    extractProps({ options }) {
        const props = {};
        if (options.size && Array.isArray(options.size)) {
            props.width = options.size[0];
            props.height = options.size[1];
        }
        return props;
    },
};

registry.category("fields").add("image_result", imageResultField);

function updateProgressCircle(
    outerPercent = 50,               // 0–100
    segments = ['#2ecc71', '#e74c3c'],  // array of segment colors (max 10)
    size = 120,                      // overall size of the circle
    outerColor = '#0062d3',           // color of the outer circle
    imageHref = ''                   // URL of the image to use
  ) {
    const processedSegments = segments.slice(0, 10);
    const numSegments = processedSegments.length;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const center = size / 2;
    const scale = size / 120;
    const outerR = 47 * scale;
    const innerR = 36 * scale;
    const iconR = 30 * scale;
    const outerStroke = 10 * scale;
    const innerStroke = 8 * scale;
    const circumference = 2 * Math.PI * outerR;

    // Set SVG attributes
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);

    // Create defs and clipPath
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const clipPath = document.createElementNS('http://www.w3.org/2000/svg', 'clipPath');
    clipPath.setAttribute('id', 'circleClip' + Date.now()); // unique id
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

    // Create outer circle (progress)
    const outerCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    outerCircle.setAttribute('cx', center);
    outerCircle.setAttribute('cy', center);
    outerCircle.setAttribute('r', outerR);
    outerCircle.setAttribute('fill', 'none');
    outerCircle.setAttribute('stroke', outerColor);
    outerCircle.setAttribute('stroke-width', outerStroke);
    outerCircle.setAttribute('stroke-linecap', 'round');
    outerCircle.style.strokeDasharray = circumference;
    outerCircle.style.strokeDashoffset = circumference;
    outerCircle.style.transition = 'stroke-dashoffset 1s ease';
    outerCircle.style.transform = 'rotate(-90deg)';
    outerCircle.style.transformOrigin = `${center}px ${center}px`;
    svg.appendChild(outerCircle);

    // Animate outer circle
    setTimeout(() => {
      outerCircle.style.strokeDashoffset = circumference * (1 - outerPercent / 100);
    }, 0);

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
    image.setAttribute('clip-path', `url(#${clipPath.getAttribute('id')})`);
    svg.appendChild(image);
  
    // ── Inner segments ───────────────────────────────────────
    const segAngle = (2 * Math.PI) / 10;     // 36° in radians (fixed size)
    const gapAngle = (2 * Math.PI) / 180; // 2 degrees in radians
    const visibleAngle = segAngle - 2 * gapAngle;
    const segmentCircumference = visibleAngle * innerR;

    for (let i = 0; i < numSegments; i++) {
      const startAngle = -Math.PI / 2 + i * segAngle + gapAngle; // Add gap at the start
      const endAngle = -Math.PI / 2 + (i + 1) * segAngle - gapAngle; // Subtract gap at the end

      const x1 = center + innerR * Math.cos(startAngle);
      const y1 = center + innerR * Math.sin(startAngle);
      const x2 = center + innerR * Math.cos(endAngle);
      const y2 = center + innerR * Math.sin(endAngle);
      const large = segAngle > Math.PI ? 1 : 0; // always 0 for 36°

      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute('d', `M ${x1} ${y1} A ${innerR} ${innerR} 0 0 1 ${x2} ${y2}`);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke-width', innerStroke);
        path.setAttribute('stroke-linecap', 'butt');

      path.setAttribute('stroke', processedSegments[i]);
      path.style.strokeDasharray = segmentCircumference;
      path.style.strokeDashoffset = segmentCircumference;
      path.style.transition = 'stroke-dashoffset 0.5s ease';
      segmentsGroup.appendChild(path);
    }

    // Animate segments one by one after outer ring
    for (let i = 0; i < numSegments; i++) {
      setTimeout(() => {
        const path = segmentsGroup.children[i];
        path.style.strokeDashoffset = '0';
      }, 1000 + i * (1000 / numSegments));
    }

    // Rotate icon once after segments finish
    // setTimeout(() => {
    //   image.style.transition = 'transform 1s ease';
    //   image.style.transform = 'rotate(360deg)';
    // }, 1000 + (numSegments - 1) * (1000 / numSegments) + 500);

    return svg;
  }
  
//   Usage example:
  document.addEventListener('DOMContentLoaded', () => {
  const outerPercent = 59;
//   const segments = ['#2ecc71', '#e74c3c', '#3498db', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e'];
  const segments = ['#2ecc71', '#2ecc71', '#3498db'];
  const size = 150;
  const outerColor = '#00cf3e';
  const svg = updateProgressCircle(outerPercent, segments, size, outerColor);
  document.body.appendChild(svg);

});