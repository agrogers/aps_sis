/**
 * APS SIS - Percent Pie (Ranged Colors)
 */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";
import { getColorForPercent } from "@aps_sis/js/utils/color_utils";

export class PercentPieRangedField extends Component {
    static template = "aps_sis.PercentPieRangedField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
    };

    get value() {
        const raw = this.props.record.data[this.props.name];
        const num = typeof raw === "number" ? raw : parseFloat(raw || 0);
        if (Number.isNaN(num)) return 0;
        return Math.max(0, Math.min(100, num));
    }

    get formattedValue() {
        return formatFloat(this.value, { trailingZeros: false }) + "%";
    }

    get color() {
        return getColorForPercent(this.value);
    }
}

export const percentPieRangedField = {
    component: PercentPieRangedField,
    displayName: _t("PercentPie Ranged"),
    supportedTypes: ["float", "integer"],
    additionalClasses: ["o_field_percent_pie"],
    extractProps: ({ string }) => ({ string }),
};

registry.category("fields").add("percentpie_ranged", percentPieRangedField);
