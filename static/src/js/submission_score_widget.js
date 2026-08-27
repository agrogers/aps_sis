/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";
import { PercentPie } from "@aps_sis/components/percent_pie/percent_pie";

export class SubmissionScoreField extends Component {
    static template = "aps_sis.SubmissionScoreField";
    static components = { PercentPie };
    static props = { ...standardFieldProps };

    get score() {
        return this.formatNumber(this.props.record.data.score);
    }

    get outOfMarks() {
        return this.formatNumber(this.props.record.data.out_of_marks);
    }

    get percent() {
        const value = Number(this.props.record.data.result_percent || 0);
        return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
    }

    get isGraded() {
        const score = Number(this.props.record.data.score);
        const outOfMarks = Number(this.props.record.data.out_of_marks);
        return Number.isFinite(score) && score !== -0.01 && outOfMarks > 0;
    }

    formatNumber(value) {
        if (value === false || value === null || value === undefined || Number(value) === -0.01) {
            return "–";
        }
        return Number(value).toString();
    }

}

registry.category("fields").add("submission_score", {
    component: SubmissionScoreField,
    displayName: _t("Submission Score"),
    supportedTypes: ["float", "integer"],
});
