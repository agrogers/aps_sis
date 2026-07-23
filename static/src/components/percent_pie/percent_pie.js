/**
 * APS SIS - Pure PercentPie Component (reusable, no Odoo record dependency)
 *
 * Use directly in dashboards or any OWL template:
 *   <PercentPie value="75" string="'Average'"/>
 */
import { Component } from "@odoo/owl";
import { formatFloat } from "@web/views/fields/formatters";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";

export class PercentPie extends Component {
    static template = "aps_sis.PercentPie";
    static props = {
        value: { type: [Number, String] },
        string: { type: String, optional: true },
    };

    get displayValue() {
        const num = typeof this.props.value === "number"
            ? this.props.value
            : parseFloat(this.props.value || 0);
        if (Number.isNaN(num)) return 0;
        return Math.max(0, Math.min(100, num));
    }

    get formattedValue() {
        return formatFloat(this.displayValue, { digits: [16, 0] }) + "%";
    }

    get color() {
        return getColorForPercent(this.displayValue);
    }
}
