import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class SchoolCalendarReport extends Component {
    static template = "aps_sis.SchoolCalendarReport";
    static props = {
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        updateActionState: { type: Function, optional: true },
        className: { type: String, optional: true },
        globalState: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        // Restore remembered year from the action context (persists across navigation)
        const rememberedId = this.props.action?.context?.selected_year_id;

        this.state = useState({
            years: [],
            yearId: null,
            yearName: "",
            months: [],
            schoolName: "",
            logoUrl: "",
        });

        onWillStart(async () => {
            await this._loadYears(rememberedId || null);
        });
    }

    async _loadYears(selectedId = null) {
        const years = await this.orm.searchRead(
            "aps.academic.year",
            [["active", "=", true]],
            ["name", "short_name", "start_date", "end_date", "is_current"],
            { order: "start_date desc" }
        );
        this.state.years = years;
        let year = null;
        if (selectedId) {
            year = years.find((y) => y.id === selectedId);
        }
        if (!year) {
            year = years.find((y) => y.is_current) || years[0] || null;
        }
        if (year) {
            this.state.yearId = year.id;
            await this._loadCalendar(year);
        } else {
            this.state.months = [];
        }
    }

    async _loadCalendar(year) {
        this.state.yearName = year.short_name || year.name;
        const company = await this.orm.searchRead(
            "res.company",
            [],
            ["name", "logo"]
        );
        if (company.length) {
            this.state.schoolName = company[0].name;
            this.state.logoUrl =
                company[0].logo &&
                `/web/image/res.company/${company[0].id}/logo`;
        }
        // Server expects plain 'YYYY-MM-DD' strings
        this.state.months = await this.orm.call(
            "aps.school.calendar",
            "get_calendar_report_data",
            [year.start_date, year.end_date]
        );
    }

    async onYearChange(ev) {
        const yearId = Number(ev.target.value);
        // Remember the selection in the action context so it survives navigation
        if (this.props.action) {
            this.props.action.context = {
                ...this.props.action.context,
                selected_year_id: yearId,
            };
        }
        await this._loadYears(yearId);
    }

    printPdf() {
        this.actionService.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "aps_sis.report_school_calendar_template",
            data: { academic_year_id: this.state.yearId },
            context: {
                academic_year_id: this.state.yearId,
            },
        });
    }

    /** Split months into rows of two for the 2-column layout. */
    get monthRows() {
        const rows = [];
        const m = this.state.months;
        for (let i = 0; i < m.length; i += 2) {
            rows.push([m[i], m[i + 1] || null]);
        }
        return rows;
    }
}

registry.category("actions").add("school_calendar_report", SchoolCalendarReport);
