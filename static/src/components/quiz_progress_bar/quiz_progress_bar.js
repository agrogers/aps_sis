import { Component } from "@odoo/owl";

export class QuizProgressBar extends Component {
    static template = "aps_sis.QuizProgressBar";
    static props = {
        summary: { type: Object, optional: true },
        progressFilter: { optional: true },
        onFilter: { type: Function, optional: true },
    };

    getWidth(key) {
        const summary = this.props.summary;
        if (!summary || !summary.total_possible_questions) {
            return 0;
        }
        return ((summary[key] || 0) / summary.total_possible_questions) * 100;
    }

    getSegmentTitle(key, label) {
        const summary = this.props.summary;
        const count = summary?.[key] || 0;
        const total = summary?.total_possible_questions || 0;
        const percentage = total ? Math.round((count / total) * 100) : 0;
        return `${label}: ${count} question${count === 1 ? "" : "s"} (${percentage}%)`;
    }
}