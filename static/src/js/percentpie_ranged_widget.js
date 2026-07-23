/**
 * APS SIS - Percent Pie (Ranged Colors) — Field Wrapper
 *
 * Thin Odoo field wrapper around the reusable PercentPie component.
 * For direct use in dashboards, import PercentPie from:
 *   @aps_sis/components/percent_pie/percent_pie
 */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";

export class PercentPieRangedField extends Component {
    static template = "aps_sis.PercentPieRangedField";
    static components = { PercentPie };
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
}

export const percentPieRangedField = {
    component: PercentPieRangedField,
    displayName: _t("PercentPie Ranged"),
    supportedTypes: ["float", "integer"],
    additionalClasses: ["o_field_percent_pie"],
    extractProps: ({ string }) => ({ string }),
};

registry.category("fields").add("percentpie_ranged", percentPieRangedField);
