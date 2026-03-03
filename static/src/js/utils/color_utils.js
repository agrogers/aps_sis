/** @odoo-module **/

/**
 * Returns a color based on percent value.
 * Used by percentpie_ranged_widget and image_result_widget.
 * @param {number} p - Percent value (0-100)
 * @returns {string} - Hex color code
 */
export function getColorForPercent(p) {
    if (p < 10) return "#343a40"; // dark gray
    if (p < 50) return "#ff8800"; // orange
    if (p < 60) return "#ffc400"; // light orange
    if (p < 70) return "#ffe600"; // yellow
    if (p < 80) return "#acff2e"; // light green
    if (p < 90) return "#00e974"; // bluey green (teal)
    return "#00beff"; // blue
}
