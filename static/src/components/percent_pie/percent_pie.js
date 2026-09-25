/**
 * APS SIS - Pure PercentPie Component (reusable, no Odoo record dependency)
 *
 * Use directly in dashboards or any OWL template:
 *   <PercentPie value="75" string="'Average'"/>
 */
import { Component } from "@odoo/owl";
import { formatFloat } from "@web/views/fields/formatters";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";

export const PERCENT_PIE_SENTINEL = -0.01;

export class PercentPie extends Component {
    static template = "aps_sis.PercentPie";
    static props = {
        value: { type: [Number, String] },
        string: { type: String, optional: true },
        showValue: { type: Boolean, optional: true },
        showText: { type: Boolean, optional: true },
        showTooltip: { type: Boolean, optional: true },
        isSentinel: { type: Boolean, optional: true },
    };

    get showValue() {
        return this.props.showValue !== false;
    }

    get showText() {
        return this.props.showText !== false && Boolean(this.props.string);
    }

    get isSentinel() {
        if (this.props.isSentinel === true) {
            return true;
        }
        const value = typeof this.props.value === "number"
            ? this.props.value
            : parseFloat(this.props.value || 0);
        return Number.isFinite(value) && Math.abs(value - PERCENT_PIE_SENTINEL) < 0.000001;
    }

    get tooltip() {
        return `${this.formattedValue}${this.props.string ? ` - ${this.props.string}` : ""}`;
    }

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

    get pieBackground() {
        if (this.displayValue === 0) {
            return this.color;
        }
        return `conic-gradient(
            ${this.color} 0% ${this.displayValue}%,
            rgba(0, 0, 0, 0.15) 0% 100%
        )`;
    }
}
